"""Walk the need list, fill it from the plan or by hand, then write it.

A planner can print its layout and write all of it. This is the screen
between those two: a way to take most of a plan and not the rest, and a
way to answer a need the allocator could not place.

The table's shape, because none of it is the obvious design:

    the rows are NEEDS, not bindings   a need with nothing on it is still
                                       a row. Clearing one leaves it
                                       where it was.
    three states, not two              (unset) · proposed · yours
    proposing fills the GAPS only      it never overwrites what you
                                       chose, and that is what makes
                                       "propose all" safe at any moment
    choosing it yourself means yours   you do not confirm a decision you
                                       just made
    `?` is advisory, not a filter      a proposal you never looked at is
                                       still written. The mark says you
                                       did not check it.

The state lives for the length of the session, keyed by the need. A file
per game to hold it instead is five more formats to keep in step.

Rows group by urgency and not by device. Urgency belongs to the need, so
a row keeps its place when you clear it or move it to another control.
Grouped by device, rows jump between sections while you work.

A game supplies what the core cannot know: `describe(placement)`, which
turns its own payload into `[(which part of the control, what it does)]`.

    review.run(layout, 'X4 Foundations', 'VIRPIL',
               describe=..., write=lambda layout: ...)

`write` takes a `Layout` narrowed to the needs that ended up with a
control. That is what `Layout.but()` is for, and it is why a writer
cannot derive its tables inside `build()`.
"""

import collections
import contextlib
import curses
import io
import os
import re
import textwrap
import time

from core import actions as cactions
from core import capture as ccapture
from core import devmap
from core import needs as corneeds
from core import overlay as coverlay
from core import solvers as csolvers
from core import tui as ctui

#: What a row can be. `MINE` covers "I confirmed the proposal" and "I
#: chose this myself". Once you have looked at it, where it came from
#: stops mattering.
#:
#: These are also tone names in `core.tui.Theme`, and that is worth
#: keeping: a state is handed straight to the theme, so the row for a
#: need and the control that need sits on cannot drift apart.
UNSET, PROPOSED, MINE = 'unset', 'proposed', 'mine'

MARK = {UNSET: ' ', PROPOSED: '?', MINE: '+'}

#: Nothing said. One word for an empty field on the form and for a row
#: with nothing on it, so the two read the same way.
NOTHING = '(none)'

#: Drawn on a row whose `suits` field is empty.
#:
#: This is not a fourth placement state. A row carries two marks and they
#: are independent of each other:
#:
#:     MARK[...]   where the row sits.  ' ' nothing, '?' proposed, '+' yours
#:     BARE        what the function is.  drawn while `suits` is empty
#:
#: So a row can carry `+` and `·` at once. The control is settled and the
#: job is not. `J` fills the job and `Z` proposes one. `p`, `P`, `c`, `C`,
#: `↵`, `l` and `x` all work on the control, so none of them takes this
#: mark off, and a row the plan just filled keeps it.
#:
#: `suits` is read by an overlay, which matches on the job. A bare row is
#: therefore a row no `[[want]]` rule can reach, and it is placed on reach
#: and shape alone.
BARE = '·'

#: What each mark means, in words, once. Three screens name them: the
#: help, the map's legend and the detail panel. Three phrasings of the
#: same three states is what they grow otherwise.
#:
#: "proposed, not accepted" rather than "not checked". `+` is reached by
#: accepting with `c`, or by assigning the row yourself, so `?` is the
#: absence of a decision and not of a glance.
#:
#: Neither mark gates anything. `placements()` hands a writer both. So
#: these words say what you have not done. They do not say what will not
#: happen.
MARK_SAID = {
    MINE: 'assigned by you',
    PROPOSED: 'proposed, not accepted',
    UNSET: 'unassigned',
}


class Row:
    """One line of the table. `kind` decides what it answers to."""

    def __init__(self, kind, text, need=None, group=None, held=0):
        self.kind = kind        # 'head', 'need', 'bind' or 'gap'.
        self.text = text
        self.need = need
        #: On a heading, the group's real name. `text` is raised to
        #: capitals for the screen, and `rename` needs what the needs
        #: hold. 'IN A TURN' is not it.
        self.group = group
        #: On a heading, how many rows the group holds under the filter.
        #: Counted where the band was worked out, because that is the
        #: one place it is already known. The screen says it only where
        #: the rows are hidden: open, they are there to be counted.
        self.held = held

    @property
    def selectable(self):
        # A heading is a thing you act on: `R` renames it. Unreachable,
        # it leaves a category renamed by standing on one of its
        # members.
        #
        # A `bind` is the answer to the row above it and not a thing you
        # put anywhere. A `gap` answers nothing. Moving skips both.
        return self.kind in ('need', 'head')


class Review:
    """What the reviewer has decided so far.

    All of this works without a terminal, and every key the screen
    answers to is one call on this object. That is the point of keeping
    the two apart.
    """

    def __init__(self, layout, title, subtitle='', describe=None,
                 paths=(), catalogue=(), source='', save=None,
                 harvest=None, drop=None, rules=None, rebuild=None,
                 game='', offers=(), add=None, guess=None):
        self.title = title
        #: `bind-wizard.py`'s own word for this game. Only the overlay
        #: needs it. A rule that names `what` belongs to one game, and two
        #: games can hold a function of the same name that wants
        #: different things.
        self.game = game
        self.subtitle = subtitle
        self.describe = describe or (lambda p: [])
        #: [(label, path)] the game supplies: where it found the install,
        #: and the file it writes. The core cannot know these, because
        #: every game hides its configuration somewhere else. A screen
        #: that overwrites a file says which file.
        self.paths = list(paths)
        #: Everything the game accepts a binding for. The list below is
        #: what somebody asked for out of it: 147 rows across the family
        #: against 5856 actions. Without this, nothing on this screen
        #: knows the rest is there.
        self.catalogue = list(catalogue)
        #: Which file it was read out of. The vocabulary screen puts this
        #: on its top bar. After `h` reads the game again, or `D` forgets
        #: it, that screen has to say which file is in front of you.
        self.source = source
        #: How the judgements get written down. A game that derives its
        #: needs has none, and the screen copes rather than raises. It
        #: cannot help, and taking the review down over it is worse than
        #: saying so.
        self.save = save
        #: Something has changed and the files do not have it yet. The
        #: frame says `unsaved` while this is true, and `s` clears it.
        #: The capture wizard in sim-device-map works the same way.
        self.unsaved = False
        #: What that something was, for the box that asks about it.
        self.since = ''
        #: Reading the game again, and forgetting what was read. Both run
        #: `bind-wizard.py`'s own verbs as subprocesses. Neither can touch
        #: the judgements: `drop` walks `CACHE`, and the judgements are
        #: not in it.
        self.harvest = harvest
        self.drop = drop
        #: The scoring this game plays by: the core's, with the game's
        #: over the top. The screen that explains the allocator reads the
        #: same set the allocator ran on. Any other set explains somebody
        #: else's run, and DCS tightens a band.
        self.rules = rules or corneeds.RULES
        self.status = ''
        #: What `f` narrowed the action level to. Matched against the
        #: need's own name and not against what it binds. `f` answers
        #: "where is the row for X".
        self.filter = ''
        #: Which rows are showing what sits under them. Empty to start
        #: with. The list of what a game can do is what you come here to
        #: read, and a plan that binds two actions to a button puts two
        #: lines under every row before you have asked.
        #:
        #: A set and not a flag with exceptions hung off it. `h` writes
        #: every row at once and `→` writes one, which is two ways of
        #: saying the same thing about a row. Said twice, the two
        #: disagree the moment you use both.
        self.open_binds = set()
        #: Groups whose rows are hidden. The heading stays: a group you
        #: shut is a thing you can open again, and a list that drops it
        #: has nowhere to put the cursor.
        self.shut = set()
        #: Laying the whole thing out again, for `o`. The argument is
        #: optional, like `save`. A game that cannot do this says so
        #: rather than raising: the screen cannot help, and taking the
        #: review down over it is worse than a sentence.
        self.rebuild = rebuild
        #: How a game puts one of its own actions on its own list. A
        #: promoted need the screen holds and the adapter does not is a
        #: need the next allocation drops. `o` is one such allocation,
        #: and this screen asking for a plan again is another.
        self.add = add
        #: What the program proposes about a function, on `Z`.
        #: `Adapter.guess` fills `device` and `suits`, and it marks both
        #: in `Need.guessed`. So a second run leaves what you corrected
        #: alone.
        self.guess = guess
        #: [(key, word, what it does)] a game puts on this screen itself.
        #: DCS lays out one aircraft module at a time, and `t` changes
        #: which. A game that needs a key of its own asks for one here
        #: rather than keeping a whole screen for it.
        #:
        #: The callable takes this Review and the `tui`. It answers with a
        #: line for the status bar, or with an Adapter to reopen on.
        #: Changing module means a different list of needs, a different
        #: store and a different kneeboard, so that is a new screen and
        #: not a redraw of this one.
        taken = set(''.join(re.findall(r"'([a-zA-Z])'", _loop_keys())))
        for key, word, _do in offers:
            if key in taken:
                # Loudly, at construction. A game's key that the family
                # already holds either shadows the family's key or is
                # dead, and which of the two depends on the order of an
                # elif chain. Neither is a thing to find out at the
                # keyboard.
                raise ValueError(
                    f'{key!r} ({word}) is a key this screen already '
                    f'answers to. Taken: {", ".join(sorted(taken))}')
        self.offers = list(offers)
        self.relay(layout)

    def relay(self, layout):
        """Take a freshly allocated layout and show that instead.

        Four fields and nothing else, which is why a keystroke can call
        this. The `Need` objects are the same objects, so everything you
        decided about them is on them already and comes through
        untouched: what you chose, what you accepted, what you filed them
        under, and what job they do.
        """
        self.layout = layout
        #: What the planner worked out, per need. A need it could not
        #: place has none, and `p` on that row has nothing to offer.
        self.plan = {p.need: p for p in layout.placed}
        #: Every need the planner was asked about, placed or not. The
        #: axes are in the same list, because an axis is a function that
        #: wants an input like every other row here.
        self.needs = ([p.need for p in layout.placed]
                      + list(layout.unplaced))
        #: Where each need sits now, and how it got there.
        self.at = {n: self.plan.get(n) for n in self.needs}
        for n in self.needs:
            self._recorded(n)
        # Who put it there, and not merely that something did. A
        # placement the allocator made from `yours` carries `how ==
        # 'yours'`, so a choice you made last week opens green and the
        # planner's opens purple. That is what the mark is for, and a
        # mark rebuilt from nothing each time cannot do it.
        self.mark = {n: self._came_by(n) for n in self.needs}

    def desk(self):
        """Which desk this layout is for, or '' where nothing says."""
        return corneeds.desk_of(self.layout)

    def overlay(self):
        """The overlay this layout was laid out to, or None."""
        return corneeds.OVERLAY

    def wishes(self):
        """(kept, of how many) for the overlay on, or None where none
        is."""
        got = corneeds.OVERLAY
        if got is None:
            return None
        kept, broken, _lost = got.kept(self.layout)
        return kept, kept + broken

    def lay_over(self, name):
        """Put an overlay on, or take every one off, and plan again.

        Returns a line. The count comes with it. "f-18 is on" and "f-18
        got 19 of its 34 wishes" are different facts, and the second one
        tells you whether to keep it.
        """
        if self.rebuild is None:
            return 'This game cannot make a layout again.'
        try:
            got = None if name is None else coverlay.named(name, self.game)
        except coverlay.Bad as e:
            return str(e)
        corneeds.OVERLAY = got
        if got is None:
            corneeds.forget_wishes(self.needs)
        self.relay(self.rebuild())
        # Which template is on is a decision like any other on this
        # screen, and `s` is what keeps one. Unmarked, the frame says
        # nothing, `q` offers nothing, and the choice lasts until you
        # quit.
        self.touched(f'laid out to {got.called}' if got
                     else 'laid out to no template')
        if got is None:
            return 'No overlay. The reach and the shape decide.'
        kept, of = self.wishes() or (0, 0)
        return (f'{got.name}: {kept} of {of} place wishes kept' if of
                else f'{got.name} asks for no places.')

    def unhonoured(self, need):
        """Why what you chose is not under this need, or '' if it is.

        An empty row reads the same whether the planner had nowhere to
        put it or the control you chose is gone, and those want opposite
        things from you: one is a hardware problem, the other is a
        decision waiting. The allocator says this on stderr, which under
        curses is the inside of the screen it is drawing.
        """
        want = need.assignment or {}
        if want.get('how') != corneeds.CHOSE or self.at[need] is not None:
            return ''
        pool = [(role, c) for role, d in sorted(self.layout.devices.items())
                for c in d.groups(bindable=True)]
        j = corneeds.assigned_at(pool, want)
        if j is None:
            return (f'You put this row on {want.get("control")}. '
                    'The desk does not have this control.')
        return (f'You put this row on {pool[j][1].label}. '
                'A different row has this control.')

    def _recorded(self, need):
        """Write down a placement the PROGRAM made, as `SOLVED`.

        `dump_assignments` writes the rows a need carries an assignment
        for, and nothing else. A proposal carried none, so a save after
        `P` wrote a binds file with no rows in it while the screen held
        42 placed. The file is supposed to answer "what is on my desk
        right now", which is that function's own first line.

        `SOLVED` is the word for it. `read_assignments` drops such a row,
        so the next run scores from scratch rather than from wherever
        this one stopped, and the `yours` pass takes `CHOSE` alone. What
        the row buys is `stayed`, the term worth +20 that keeps a layout
        from reshuffling, and a screen that can say what moved.

        A decision of yours is never overwritten. `CHOSE`, `ACCEPTED` and
        `CLEARED` are answers; this is a note about a proposal.
        """
        at = self.at[need]
        if at is None:
            return
        if (need.assignment or {}).get('how') in (
                corneeds.CHOSE, corneeds.ACCEPTED, corneeds.CLEARED):
            return
        need.assignment = {'role': at.role, 'control': at.ctrl.id,
                           'how': corneeds.SOLVED}
        if need.takes == corneeds.AXIS and at.slots:
            need.assignment['axis'] = at.slots[0][0].index

    def _came_by(self, need):
        """Who put this where it is, as a mark.

        This reads what the placement says about itself. A mark rebuilt
        from nothing on every open makes everything placed `?`, and an
        evening spent walking the list comes back purple and in the
        planner's order.

        `accepted` is checked against WHERE it landed, and not merely
        that it landed. You said yes to a control, not to a row. Where
        the desk or the needs have changed since and the allocator has
        moved it, the row goes back to `?`. That is the one moment the
        mark has something to tell you.
        """
        at = self.at[need]
        if at is None:
            return UNSET
        if at.why.how == 'yours':
            return MINE
        mine = need.assignment or {}
        if (mine.get('how') == corneeds.ACCEPTED
                and mine.get('role') == at.role
                and mine.get('control') == at.ctrl.id):
            return MINE
        return PROPOSED

    # -------------------------------------------------------------- reading

    def counts(self):
        """(yours, proposed, unset), over every row that carries a mark.

        The axes are included, by being rows like any other.
        """
        m = [self.mark[n] for n in self.needs]
        return m.count(MINE), m.count(PROPOSED), m.count(UNSET)

    def binds(self, need):
        """[(part of the control, what it does)] -- the game's own answer.

        `describe` is the adapter's hook and this is its only caller, so
        this is the only place that copes with a need sitting on nothing.
        """
        p = self.at[need]
        return self.describe(p) if p is not None else []

    def where(self, need):
        """The one-line answer to "what is this on?".

        The lever's own label for an axis, and not the control's. Three
        of the stick's axes are `Main stick`, and one of them is pitch.
        """
        p = self.at[need]
        if p is None:
            return '(unset)'
        if need.takes != corneeds.AXIS:
            return f'{p.role} · {p.ctrl.label}'
        return (f'{p.role} · {self.lever(p).label}'
                + (' · inverted' if need.invert else ''))

    def lever(self, p):
        """The axis object a placement sits on."""
        return self.layout.devices[p.role].axis(p.slots[0][0].index)

    def turn_round(self, need):
        """Invert an axis, or stop. Returns a line.

        This is the one thing about an axis you change from a screen.
        Which end is which is a fact about your hardware and your wrist.
        It is not a fact about the game.
        """
        if need.takes != corneeds.AXIS:
            return f'{need.what} is not an axis.'
        need.invert = not need.invert
        self.touched('an axis turned round')
        return (f'{need.what} is inverted.' if need.invert
                else f'{need.what} is not inverted.')

    def occupied(self, besides=None):
        """{(role, button)} carrying something now, ignoring one need."""
        out = set()
        for need, p in self.at.items():
            if p is None or need is besides:
                continue
            for b, _v in p.slots:
                out.add((p.role, b))
        return out

    def free(self):
        """[(role, control)] with every input of it still spare.

        Worked out from what is assigned, and not read off the layout.
        Clearing a need hands its control back, and assigning one takes a
        control the allocator had left over.

        `corneeds.spare_controls` says what free means, so this and the
        allocator answer the same question. Counted on the buttons
        alone, this offered the main stick with pitch, roll and steering
        on it.

        A control a row on this screen claims is not offered, whatever
        its inputs say. Two rows across the four games bind nothing at
        all, and a row with no bindings takes a control and writes
        nothing: Elite's `Head look` and MSFS's `Look around`. The
        screen shows them sitting there, so offering the control is the
        screen contradicting itself.
        """
        claimed = {(p.role, p.ctrl.id)
                   for p in self.at.values() if p is not None}
        return [(role, ctrl) for role, ctrl in corneeds.spare_controls(
                    self.layout.devices, self.occupied())
                if (role, ctrl.id) not in claimed]

    def fits(self, need):
        """Free controls this need could live on.

        The shape and capacity tests `score()` makes, without the reach
        tables. Somebody placing a thing by hand has decided it is worth
        the reach. "Nothing fits" where four controls do is the tool
        arguing with them.
        """
        return [(role, c) for role, c in self.free()
                if c.kind in need.shapes
                and len(c.bindable_buttons) >= need.wanted]

    def who_has(self, role, ctrl):
        """Every need sitting on this control right now, in row order.

        A list, not the first one found. A control carries more than the
        need that took it: the share pass hands a leftover need one spare
        button of a control something else owns, so X4's bottom thumb hat
        holds Weapon group AND three shared needs.

        One name of the four reads as though the other three were
        nowhere, on the screen you open to find out what is still spare.
        Thirteen controls across the five games are like this.
        """
        return [need for need in self.needs
                if (p := self.at[need]) is not None
                and p.role == role and p.ctrl is ctrl]

    def why_not(self, need, role, ctrl):
        """None where this need may go on this control, else the reason.

        The by-hand list offers only what fits, so it never needs this.

        A press can land anywhere: on a lever, on a hat with too few
        positions, or on something another need has. "No" with no reason
        is the worst of the three answers.
        """
        if ctrl is None:
            return 'the device map does not have this button'
        if not ctrl.bindable:
            return f'{ctrl.label} carries no binding'
        if ctrl.kind not in need.shapes:
            return (f'{ctrl.label} is a {ctrl.kind}. This row needs a '
                    f'{need.first_shape}')
        if len(ctrl.bindable_buttons) < need.wanted:
            return (f'{ctrl.label} has '
                    f'{ctui.plural(len(ctrl.bindable_buttons), "bindable "
                                       "button")}. This row needs '
                    f'{need.wanted}')
        others = [n for n in self.who_has(role, ctrl) if n is not need]
        if others:
            return (f'{ctrl.label} carries '
                    + ' · '.join(n.what for n in others)
                    + '. Press x to clear it')
        return None

    def control_at(self, role, button):
        """The map's control owning a raw kernel button number."""
        dev = self.layout.devices.get(role)
        return None if dev is None else dev.group_of(button)

    def touched_at(self, role, kind, index):
        """(control, what to call this part of it) for a touched input.

        A control's buttons and its axes are numbered in different
        namespaces, so `kind` says which one `index` is in. `control_at`
        above answers for a button alone, which is what an assignment
        asks and not what a hand on the desk reports.

        The control is None where the map names nothing there. One walk,
        so the corner box and the list cannot disagree about which
        control a thumb is on.
        """
        dev = self.layout.devices.get(role)
        if dev is None:
            return None, ''
        if kind == 'axis':
            return dev.axis_group(index), f'axis {index}'
        return dev.group_of(index), f'js {index}'

    def on_input(self, role, kind, index):
        """[need] sitting on the INPUT somebody just touched.

        The button, not the control it belongs to. Three rows share the
        stick's top thumb hat, and pressing `up` is one of them: a hat
        lit whole says the press reached a control and leaves the reader
        to work out which function that was.

        So this is narrower than the corner box below, which names what
        the control carries. The box answers "what is this", and the
        rows answer "what did my thumb just do".
        """
        want = corneeds.OnAxis(index) if kind == 'axis' else index
        return [n for n, p in self.at.items()
                if p is not None and p.role == role
                and any(b == want for b, _v in p.slots)]

    def pressed(self, role, kind, index):
        """[(tone, text)] naming what was just touched, for the corner.

        A number is not an answer to "which one did I press": it is the
        same question again. This says which device, what the control is
        called, which part of it this is, and what is on it.

        The device map draws the same box for the same question, out of
        the same map. This is that answer in this screen's own tones.
        """
        if role not in self.layout.devices:
            return []
        ctrl, part = self.touched_at(role, kind, index)
        out = [('subhead', f'{role}  {part}')]
        if ctrl is None:
            # A button the firmware reports with nothing behind it, or an
            # axis nobody has swept. The map is where that gets answered,
            # and saying so beats a blank box.
            out.append(('unset', 'The device map does not name it.'))
            return out
        out.append(('plain', ctrl.label))
        way = ctrl.direction(index) if kind == 'button' else ''
        if way:
            out.append(('meta', way))
        on = self.who_has(role, ctrl)
        if on:
            out.append((self.mark[on[0]],
                        _one_of([n.what for n in on])))
        else:
            out.append(('meta', 'Nothing is on it.'))
        return out

    def took(self, need, role, button):
        """Assign from the input somebody moved, or say why not.

        Everything after `capture.wait_input` returns, in one call with no
        terminal in it. So the only part of pressing a control that a test
        cannot reach is reading the kernel.

        `button` is an axis index where the need wants an axis. The
        capture reads whichever kind the row is for, so one key means one
        thing on every row.
        """
        if need.takes == corneeds.AXIS:
            dev = self.layout.devices.get(role)
            got = dev.axis(button) if dev else None
            if got is None:
                return (f'The desk has no {role} axis {button}, so '
                        f'{need.what} cannot go there.')
            ctrl = dev.axis_group(button)
            if ctrl is None:
                return (f'No control in the map has {role} axis '
                        f'{button}, so {need.what} cannot go there.')
            if (self.mark[need] == MINE and (p := self.at[need]) is not None
                    and p.role == role and p.slots
                    and p.slots[0][0].index == button):
                # Already yours, and already this lever. `unsaved` over a
                # keystroke that changed nothing brings a save box up on
                # the way out, to somebody who has just saved. With a
                # stick on the desk this is the easiest key to press by
                # accident, because the lever you nudge is the one it is
                # on.
                return f'{need.what} is yours, and it is already here.'
            self.assign(need, role, ctrl, axis=button)
            return f'{need.what} -> {role}/{got.label}  (yours)'
        ctrl = self.control_at(role, button)
        no = self.why_not(need, role, ctrl)
        if no:
            # `why_not` answers with a fragment. The control is its
            # subject, and this puts the row's name in front.
            return f'{need.what} cannot go there: {no}.'
        # `why_not` answers 'not in the device map' first, so a control
        # that got past it exists. Saying so here is cheaper than
        # hoisting the check and keeping its sentence in two places.
        assert ctrl is not None
        p = self.assign(need, role, ctrl, button)
        said = f'{need.what} -> {role}/{ctrl.label}'
        if len(need.bindings) == 1 and p.slots:
            landed = p.slots[0][0]
            said += f' · {ctrl.direction(landed) or f"button {landed}"}'
            if landed != button:
                said += (', not where you pressed: that contact carries '
                         'no binding' if button not in ctrl.bindable_buttons
                         else ', its own direction')
        return f'{said}  (yours)'

    def devices(self):
        """[(role, Device)] in a fixed order, for the header and the map."""
        return sorted(self.layout.devices.items())

    def device_line(self):
        """`stick R-VPC Stick WarBRD-D · throttle L-VPC VMAX...`

        A role is not a device. `devmap.by_role` keys on the map's
        `kind`, so a second stick makes you choose between the two with
        SIM_DEVICE_ROLES. After that, a row reading "stick" does not say
        which one you chose. The header carries the answer, so no row has
        to.
        """
        return '   '.join(f'{role} {d.product}' for role, d in self.devices())

    def map_lines(self):
        """The device map as the review sees it, with what sits on each
        control. It answers "is that really a hat, and what is on it".

        `[(tone, text)]`, not bare lines. The tone is the one thing only
        this method knows, and naming it here keeps the two screens
        honest: a control wears the state of the need on it, and that
        state is the word the table draws its row with.

        Every control also carries the table's own `?` or `+` mark. An
        unexplained colour is some of the rows being a different colour.
        So the mark says it in text, the legend says what the mark means,
        and the colour does what colour is good at.

        The map comes first and the paths last. This is the screen you
        open to find a spare control, and nine lines of Proton prefix
        ahead of it make the screen read like a newspaper.
        """
        out = []
        # What this layout is OF, before what is in it. You open this
        # screen to ask what you are working on, and the desk and the
        # overlay both decide where everything landed.
        out.append(('head', 'LAID OUT FOR'))
        said = [('desk', self.desk() or 'nothing says')]
        got = corneeds.OVERLAY
        said.append(('overlay', got.name if got is not None else 'none'))
        count = self.wishes()
        if count and count[1]:
            said.append(('wishes kept', f'{count[0]} of {count[1]}'))
        _fields(lambda tone, text='', lead='': out.append((tone, lead + text)),
                said)
        out.append(('plain', ''))
        out.append(('head', 'MARKS'))
        # The legend is three lines, because a line carries one tone. A
        # legend not drawn in the colours it explains explains nothing.
        for state in (MINE, PROPOSED, UNSET):
            out.append((state, f'  {MARK[state]} {MARK_SAID[state]}'))
        # The number the REACH column prints. One line, because the
        # column is ten characters wide and a phrase is longer.
        out.append(('plain', ''))
        out.append(('head', 'REACH'))
        for n in sorted(corneeds.REACH_MEANS):
            if n != corneeds.UNMEASURED:
                out.append(('meta', f'  {n} {corneeds.REACH_MEANS[n]}'))
        out.append(('meta', '  - nobody has measured it'))
        for role, dev in self.devices():
            ids = f'{dev.slug} · usb {dev.usb or "?"}'
            if dev.serial:
                ids += f' · serial {dev.serial}'
            out.append(('plain', ''))
            out.append(('subhead', f'  {role}  {dev.product}'))
            out.append(('meta', f'    {dev.n_buttons} buttons, '
                                f'{dev.n_axes} axes · {ids}'))
            out.append(('meta', f'    {_tilde(str(dev.path))}'))
            out.append(('plain', ''))
            # Named columns. Five unnamed ones say nothing about which is
            # which: `2,3,4` is a button list, and the only way to learn
            # that is to work it out from the numbers.
            out.append(('meta', f'    {"KIND":10} {"CONTROL":24} '
                                f'{"BUTTONS":16} {"REACH":10} ON IT'))
            for ctrl in dev.groups():
                held = self.who_has(role, ctrl)
                parts = [','.join(str(b) for b in ctrl.buttons)]
                if ctrl.push is not None:
                    parts.append(f'+{ctrl.push}')
                if ctrl.axes:
                    parts.append('ax' + ','.join(str(a) for a in ctrl.axes))
                btns = ' '.join(x for x in parts if x)
                # Carrying something: that need's state, mark and colour
                # alike, which is how the table draws it. Free and
                # bindable: plain, because a spare control is the normal
                # case and colouring the normal case says nothing.
                # Bindable by nothing: as dim as the ids above it.
                # The first one's mark and colour. Two needs on one
                # control can differ, with one accepted and one still
                # proposed, and a row carries one tone. The names say the
                # rest.
                state = self.mark[held[0]] if held else None
                tone = state or ('plain' if ctrl.bindable else 'meta')
                on = (' · '.join(n.what for n in held) if held
                      else '' if ctrl.bindable else '(carries nothing)')
                out.append((tone,
                            f'  {MARK[state] if state else " "} '
                            f'{ctrl.kind:10} {ctrl.label[:24]:24} '
                            f'{(btns or "-")[:16]:16} '
                            f'{_hand(ctrl):10.10} '
                            + on))
        if self.paths:
            out.append(('plain', ''))
            out.append(('head', 'WHERE'))
            # Each path on its own lines. A Proton prefix is 120
            # characters before it says anything, and a truncated path
            # answers nothing. Shortened at the home directory, which is
            # 14 of those characters and the part a reader knows.
            for label, path in self.paths:
                out.append(('subhead', f'  {label}'))
                out.extend(('meta', f'    {ln}')
                           for ln in _fold(_tilde(str(path))))
        return out

    # -------------------------------------------------------------- writing

    def placements(self):
        """Every need that ended up with a control.

        Proposed and yours alike. The `?` says you did not check it. It
        does not say the row is off.
        """
        return [self.at[n] for n in self.needs if self.at[n] is not None]

    def result(self):
        """The layout to hand a writer: the same plan, narrowed."""
        return self.layout.but(self.placements())

    # ---------------------------------------------------------------- doing

    def propose(self, need):
        """Put the planner's suggestion on this need.

        This moves the CONTROL. It does not describe the function: a row
        with no `suits` keeps its `·` after this, because the plan has no
        opinion about what a thing is for. `J` answers that, and `Z`
        proposes an answer.

        A row you cleared has no suggestion to put back. The allocator is
        told to leave a cleared row alone, so the last plan holds nothing
        for it. The clear is therefore forgotten first and the game lays
        itself out again. Without that, `x` on a saved row could only be
        undone by hand, and the key that restores a proposal would answer
        that there is none.
        """
        if (need.assignment or {}).get('how') == corneeds.CLEARED:
            need.assignment = None
            self.touched('a clear undone')
            if self.rebuild is not None:
                self.relay(self.rebuild())
        if self.mark[need] == MINE:
            return f'{need.what} is yours. Press x to clear it first.'
        p = self.plan.get(need)
        if p is None:
            return f'The planner has no control for {need.what}.'
        busy = self.occupied(besides=need)
        if any((p.role, b) in busy for b, _v in p.slots):
            return (f'{p.ctrl.label} is taken, so {need.what} cannot go '
                    'there.')
        self.at[need] = p
        self.mark[need] = PROPOSED
        self._recorded(need)
        return f'{need.what} -> {self.where(need)}  (proposed)'

    def propose_all(self):
        """Fill the gaps from the plan, and only the gaps.

        This touches nothing you chose, so it is safe to press at any
        time. A gap is a row with no control on it.

        A gap is not a row with no description. This fills the control and
        leaves `suits` alone, so a row it fills can still carry `·`.
        """
        done = 0
        for need in self.needs:
            if self.mark[need] == UNSET \
                    and self.propose(need).endswith('(proposed)'):
                done += 1
        return (f'The plan filled {done} rows. Each one is marked ?.'
                if done else 'The plan has nothing left to fill.')

    def confirm(self, need):
        at = self.at[need]
        if at is None:
            return f'{need.what} has nothing to confirm.'
        if self.mark[need] == MINE:
            return f'{need.what} is yours.'
        self._accept(need, at)
        self.touched('a binding confirmed')
        return f'{need.what} is confirmed on {self.where(need)}.'

    def _accept(self, need, at):
        """Mark it yours, and write down WHICH control you said yes to.

        The control, and not only the fact. You said yes to a home and
        not to a row, so the day the allocator moves it the mark stops
        claiming you agreed.
        """
        self.mark[need] = MINE
        need.assignment = {'role': at.role, 'control': at.ctrl.id,
                      'how': corneeds.ACCEPTED}
        if need.takes == corneeds.AXIS and at.slots:
            # Which axis of it, so saying yes to a lever says yes to
            # THAT lever. `button` makes the same claim for a press.
            need.assignment['axis'] = at.slots[0][0].index

    def confirm_all(self):
        # One mark for the lot, not one per need. Nothing is written
        # here, and `unsaved` does not get truer forty-five times.
        todo = [(n, self.at[n]) for n in self.needs
                if self.mark[n] == PROPOSED and self.at[n] is not None]
        for need, at in todo:
            self._accept(need, at)
        if todo:
            self.touched('confirmed in bulk')
        n = len(todo)
        return (f'You confirmed {ctui.plural(n, "proposal")}.' if n
                else 'Nothing is left to confirm.')

    def clear(self, need):
        """Take this row's control off it, and write that down.

        `how: cleared`, rather than no row at all. The file holds what
        sits where, so a row with nothing on it is a row the file does
        not mention. A fact the file cannot hold does not survive `s`:
        clearing a proposal then reports `nothing has changed since the
        last save`, truthfully, and the next open proposes it straight
        back.

        An empty row you chose is a decision, and it has somewhere to
        live.
        """
        # Nothing on it and nothing of yours to forget, or cleared
        # already. Either way there is nothing to do. Saying otherwise
        # marks the files out of date over a row that did not move.
        if self.at[need] is None and (
                not need.assignment
                or need.assignment.get('how') == corneeds.CLEARED):
            return f'{need.what} is already clear.'
        self.at[need] = None
        self.mark[need] = UNSET
        need.assignment = {'how': corneeds.CLEARED}
        self.touched('a binding cleared')
        return f'{need.what} is clear. The control is free.'

    def clear_all(self):
        """Take the control off every row.

        Every row, and not the proposals alone. On a screen you have just
        saved, everything is yours and there is no proposal to drop, so a
        key that dropped only those would do nothing there while the help
        offered it.

        `s` is still what writes this.
        """
        drop = [need for need in self.needs
                if self.at[need] is not None
                or (need.assignment
                    and need.assignment.get('how') != corneeds.CLEARED)]
        for need in drop:
            self.clear(need)
        n = len(drop)
        return (f'You cleared {ctui.plural(n, "row")}. Nothing is bound '
                'now.' if n else 'Nothing is bound.')

    def assign(self, need, role, ctrl, button=None, slot=None, axis=None):
        """Give a need a control by hand. Yours at once, with no
        confirming step, because you just chose it.

        `button` is the button actually pressed, where a press did this.

        `slot` says WHICH of the need's bindings that press was for,
        where you are taking one direction of a hat rather than the hat.
        The rest keep what they had. So a trim hat whose directions the
        game names in another order is put right one at a time, rather
        than re-taken whole and scrambled the same way again.
        """
        was = self.at[need]
        # Putting it back where it already was is not an override. A
        # panel that says "moved from Thumb button" about a binding ON
        # the thumb button argues with the person reading it.
        #
        # `is` on the control and not on the label. Two controls can
        # share a label across devices, and the role is checked
        # anyway.
        moved = was is not None and not (was.role == role
                                         and was.ctrl is ctrl)
        why = corneeds.Reason('yours', instead=was if moved else None)
        # What was already pinned per slot, kept across a re-take of the
        # same control. Taking one direction must not forget the three
        # you took before it.
        pinned = list((need.assignment or {}).get('buttons') or ())
        if slot is not None and button is not None:
            pinned += [None] * (len(need.bindings) - len(pinned))
            pinned[slot] = button
        elif moved or was is None:
            pinned = []
        placed = corneeds.put(need, role, ctrl, why, button=button,
                              pinned=pinned, axis=axis)
        self.at[need] = placed
        self.mark[need] = MINE
        need.assignment = {'role': role, 'control': ctrl.id,
                      'how': corneeds.CHOSE}
        if need.takes == corneeds.AXIS and axis is not None:
            need.assignment['axis'] = axis
        if any(b is not None for b in pinned):
            need.assignment['buttons'] = pinned
        elif button is not None and corneeds.honours_press(need, ctrl, button):
            need.assignment['button'] = button
        self.touched('a binding assigned by hand')
        return placed

    def categories(self):
        """Every group there is, so a menu offers them before it asks for
        a new name.

        The bands are included. Filing something under `in a turn` is a
        choice like any other, and the fallback left out is a place you
        leave and cannot return to.
        """
        return sorted({self.group_of(n) for n in self.needs})

    def touched(self, what=''):
        """Say that something changed and the files no longer match.

        This marks. It does not write. The capture wizard in
        sim-device-map marks the screen `unsaved` and writes on `s`, and
        one keystroke means one thing in both tools.

        `what` is kept so the save box names it. A box on the way out
        that says only "something is unsaved", to somebody who has just
        pressed `s`, is an argument the screen cannot win: twelve keys
        mark this screen, one of them is a button read off the stick, and
        the reader cannot tell which fired.
        """
        self.unsaved = True
        #: The last decision the files do not have yet, in words.
        self.since = what
        return ''

    def keep(self):
        """Write both files down. (what happened, is it still unsaved).

        The whole list every time, because that is what the files hold: a
        description per function and a row per placement. A partial write
        of either leaves a file that disagrees with the screen.
        """
        if self.save is None:
            # Still unsaved, and it stays that way. There is nowhere to
            # put it, so the frame goes on saying so rather than claiming
            # a file holds something no file holds.
            return ('This game makes its own list. There is no file to '
                    'write it to.'), True
        try:
            said = self.save(self.needs)
        except (OSError, RuntimeError) as e:
            return f'The write failed: {e}', True
        self.unsaved = False
        self.since = ''
        return said or 'The files are written.', False

    def refile_job(self, need, job):
        """Say what a function is FOR. Returns a line.

        Separate from `refile`, which is your own filing of the list.

        This is the word an overlay matches on, so it comes out of the
        closed table and not out of a prompt. A job nobody wrote costs
        this function every wish in every template, and it looks like a
        template that did not apply.
        """
        if job not in corneeds.JOBS:
            return f'{job!r} is not a job.'
        if need.suits == job and 'suits' not in need.guessed:
            # Picking the job it is filed under changes nothing, and
            # `unsaved` for that is a lie. A PROPOSAL is the exception:
            # agreeing with one is a decision, and the mark comes off.
            return f'{need.what} is already {job} work.'
        need.suits = job
        need.guessed.discard('suits')
        self.touched('a job changed')
        return f'{need.what} is {job} work.'

    def say(self, need, field, value):
        """Say one thing about what a function IS.

        A description is a judgement, and it is derived from nothing:
        which band a function is in, what shape of control it wants, and
        whether you hold it down. Every one of those is scored, and five
        games keep them in a needs file written by hand.

        The job goes through `refile_job`, which holds the word-list
        check. One validation, not two spellings of it. The rest come off
        a closed list the form read out of the scoring table, so there is
        nothing left here to check.

        The save box names the field, so `s` on the way out says which of
        the nine you changed. A flag takes no article: `held changed`,
        where a noun reads `a shape changed`.
        """
        if field == 'suits':
            self.refile_job(need, value)
            return
        if getattr(need, field, None) == value:
            # Answering a proposal with the value it proposed is still
            # answering it. The mark comes off, and the count of
            # functions that say nothing goes down by one.
            need.guessed.discard(field)
            return
        setattr(need, field, value)
        need.guessed.discard(field)
        label, kind = next(((l, k) for f, l, k, _w in DESCRIBED
                            if f == field), (field, ''))
        self.touched(f'{label} changed' if kind == 'flag'
                     else f'a {label} changed')

    def refile(self, need, category):
        """Move a need to another group. Returns a line.

        Naming its own band puts the need back on the fallback. It does
        not record the band as a category. Otherwise `in a turn` becomes
        a place you leave and cannot return to, and two rows that look
        identical on screen differ in the file.
        """
        was = need.category
        need.category = (None if category ==
                         corneeds.URGENCY_NAME[need.urgency] else category)
        if need.category == was:
            return f'{need.what} is already under {category}.'
        self.touched('a function refiled')
        return f'{need.what} moved to {category}.'

    def rename(self, old, new):
        """Call a group something else, without emptying it first.

        A band is refused. There are four of them and they are the
        allocator's scale, so they are not yours to name. Refiling out of
        one is how you leave it.
        """
        if old in corneeds.URGENCY_NAME:
            return (f'{old!r} is a band, not a category. Press r to file '
                    'a row out of it.')
        moved = [n for n in self.needs if n.category == old]
        for n in moved:
            n.category = new
        self.touched('a group renamed')
        return f'{len(moved)} rows moved from {old} to {new}.'

    def promote(self, action, category):
        """Put an action from the vocabulary on the list. Returns a line.

        Promoting says "this matters". It does not say "put it here".
        Where is the next question, and RETURN on the row answers it.
        """
        already = next((n for n in self.needs
                        if any(b.action == action.id
                               for slot in n.bindings for b in slot)), None)
        if already is not None:
            already.category = category
            self.touched('a function added')
            return (f'{action.name} is on the list. It moved to '
                    f'{category}.')
        # An axis is a function that wants an input, like every other row
        # here. An axis row needs a shape and a rest, and the vocabulary
        # says neither. `J` says both.
        if self.add is None:
            # No adapter behind this screen, which is a test or a caller
            # that keeps its own list. The same need, not planned for:
            # `plan_again` has nothing to ask.
            need = corneeds.from_action(action, category)
            self.needs.append(need)
            self.at[need] = None
            self.mark[need] = UNSET
        else:
            need = self.add(action, category)
            self.plan_again()
        self.touched('a function added')
        return f'{action.name} is on the list, under {category}.'

    def plan_again(self):
        """Ask the planner again, keeping every choice you made.

        Thirteen milliseconds. Without it the screen's proposals answer a
        description you have changed since: `J` sets the shape, the band,
        the device and the hand, which are four of the things the
        allocator scores on. A promoted need has no proposal at all, so
        `p` on it says the planner has no control for it.

        What you chose survives, because the allocator takes those
        controls in its first pass. `o` works the same way.
        """
        if self.rebuild is not None:
            self.relay(self.rebuild())

    def rules_lines(self, width=60):
        """How a control is chosen, read out of the tables that choose it.

        In the order somebody asks, and not the order the code runs.
        Seven tables with no thread between them explain nothing: they
        never say what the allocator is FOR, they use `band`, `reach`,
        `floor` and `ceiling` without defining any of them, and they
        print 0, 1 and 3 without saying that lower means closer to your
        hand.

        Every number is read from the table the allocator reads. Tune a
        limit and this screen rewrites itself.

        The `note` each band, term and fact carries is NOT here. A note
        is somebody's working: half a page of why a weight was retuned,
        under some rows and not others, which reads as noise that turns
        up at random. The notes are in `scoring.toml`, where whoever is
        about to change a number is already looking.
        """
        out = []

        def say(tone, text='', lead=''):
            out.extend((tone, piece) for piece in _fit(width, text, lead))

        say('head', 'WHAT THIS DOES')
        say('plain', 'You want more bindings than there are good '
                     'buttons.', lead='  ')
        say('plain')
        say('plain', 'Each binding has a band. The band says when you '
                     'reach for it: in a turn, or on the ramp with the '
                     'canopy open.', lead='  ')
        say('plain')
        say('plain', 'Each control has a reach. The reach says what it '
                     'costs to get to the control: a thumb, or your hand '
                     'off the grip.', lead='  ')
        say('plain')
        say('plain', 'The urgent bindings pick first. A near control '
                     'stays free for them until every other binding has '
                     'had a turn.', lead='  ')
        say('plain')

        say('head', 'HOW FAR A CONTROL IS')
        for tier in sorted(corneeds.REACH_MEANS):
            say('plain', corneeds.REACH_MEANS[tier], lead=f'  {tier}  ')
        say('meta', 'A low number is closer. The device map measures '
                    'this on your own desk, finger by finger. A control '
                    f'that nobody measured sorts at {corneeds.UNMEASURED}. '
                    'It goes below all of them.', lead='  ')
        say('plain')

        say('head', 'WHEN YOU REACH FOR IT')
        for band in self.rules['band']:
            low, high = band['takes']
            say('plain', f'takes reach {low} to {high}',
                lead=f'  {band["name"]:16} ')
        say('plain')

        say('head', 'WHICH BINDING GOES FIRST')
        # Written out from `allocate`'s sort key, in its order. Prose
        # here does not move when the key does: it said pins went first
        # long after what you choose by hand started outranking them.
        for n, (what, why) in enumerate(corneeds.ORDERED_BY, 1):
            say('plain', f'{_sentence(what)} {why}', lead=f'  {n}  ')
        say('plain')

        say('head', 'WHEN IT REFUSES A CONTROL')
        # Read out, not written out. A transcription here is the one
        # thing on this screen that can disagree with the allocator, and
        # it does so the day a fifth refusal arrives.
        #
        # The table holds a fragment, because its own column is where
        # most of these are read: `-60  it is the wrong shape` takes no
        # capital and no full stop. A bullet is a line of its own, so the
        # screen makes the fragment a sentence here. The file holds one
        # spelling.
        for gate in self.rules['gate']:
            say('plain', _sentence(gate['says']), lead='  · ')
        for fact in self.rules['fact']:
            if fact.get('refuses'):
                say('plain', _sentence(fact['says'])
                    + f' This refuses a binding marked {fact["asked"]}.',
                    lead='  · ')
        say('plain')

        say('head', 'WHO CHOOSES, ONCE THE SCORES ARE IN')
        say('meta', 'Most of a layout is ties. A dozen thumb buttons are '
                    'worth the same to a binding that asks for a button. '
                    'The --solver flag makes that choice.', lead='  ')
        for name, what, _why_not in csolvers.choices():
            say('plain', what, lead=f'  {name:9} ')
        say('plain')

        say('head', 'HOW MANY TRIES IT GETS')
        say('meta', f'{len(corneeds.PASSES)} tries. Each try gives up '
                    'more than the try before it:', lead='  ')
        for n, (how, what) in enumerate(corneeds.PASSES, 1):
            say('plain', what, lead=f'  {n}  {how:9} ')
        say('plain')

        say('head', 'WHAT MAKES ONE CONTROL BEAT ANOTHER')
        for term in self.rules['term']:
            # `says` carries the run's own values, such as `{role}` and
            # `{label}`. There is no run here, so a term that needs them
            # says the same rule with nothing in the holes.
            say('plain', term.get('general', term['says']),
                lead=f'  {term["weight"]:+5}  ')
        say('plain')

        say('head', 'WHAT A BINDING ASKS OF A CONTROL')
        say('meta', 'The device map measures these on your own desk, one '
                    'control at a time. Each fact counts only for a '
                    'binding that asks for it. A fact counts for nothing '
                    'if nobody answered it. An unanswered control is an '
                    'unwalked desk. It is not a middling one.', lead='  ')
        say('plain')
        for fact in self.rules['fact']:
            say('plain', f'a binding marked {fact["asked"]}', lead='  ')
            words = fact.get('general', fact['says'])
            if fact.get('refuses'):
                say('plain', words, lead=f'{"refuses":>9}  ')
            elif 'yes' in fact:
                say('plain', fact['says'], lead=f'    {fact["yes"]:+5}  ')
                say('plain', fact['not'], lead=f'    {fact["no"]:+5}  ')
            elif 'same' in fact:
                # The shape for a closed field the need names a value
                # of. Both answers are weighed, like a bool, and the
                # words say which way round.
                say('plain', fact['says'], lead=f'    {fact["same"]:+5}  ')
                say('plain', fact['not'], lead=f'    {fact["other"]:+5}  ')
            else:
                say('plain', words, lead=f'    {fact["scale"]:+5}  ')
            say('plain')

        say('head', 'WHAT COUNTS AS THE RIGHT SHAPE')
        say('meta', f'{"asked for":11} will also take', lead='  ')
        for shape, subs in self.rules['shapes'].items():
            say('plain', ', '.join(subs[1:]) or 'nothing else',
                lead=f'  {shape:11} ')
        say('plain')
        say('meta', 'These controls lend their click and nothing else: '
                    + ', '.join(corneeds.ONE_MECHANISM) + '.', lead='  ')
        say('plain')
        say('meta', 'A binding that names a direction accepts another '
                    'word for it:', lead='  ')
        for want, names in corneeds.SAME_WAY.items():
            if len(names) > 1:
                say('plain', ', '.join(names[1:]), lead=f'  {want:11} ')
        return out

    # ----------------------------------------------------------------- rows

    def matches(self, need):
        return (not self.filter
                or self.filter.lower() in need.what.lower())

    def narrowed(self):
        """What `f` is hiding, for the header. '' where it hides nothing.

        This stays up for as long as it is true. Said once on the
        keystroke and cleared by the next movement, a screen showing
        three rows of thirty-one looks like a game that has three.
        """
        if not self.filter:
            return ''
        shown = sum(1 for n in self.needs if self.matches(n))
        return f'filter {self.filter!r} · {shown} of {len(self.needs)}'

    def group_of(self, need):
        """What this need is filed under.

        Yours where you have said. The band where you have not. Nothing
        carries a category on the day this lands, so the fallback is what
        keeps the screen from opening empty.
        """
        return need.category or corneeds.URGENCY_NAME[need.urgency]

    def groups(self):
        """[(name, [Need])] -- the list's shape, most urgent group first.

        A group sorts by the most urgent thing in it, and for a band that
        is the band itself. So a category you invent lands where its
        contents say, and not where you happened to make it.

        Inside a group, by the name. The needs list runs every placement
        and then everything unplaced, so rows in that order move:
        clearing a binding sends its row to the bottom of the group on
        the next open, and a row you are walking towards is not where you
        left it. The name is the one thing about a row that does not
        change when you bind or clear it.

        The list itself is NOT reordered. It keeps the order the needs
        file is written in, and that file is edited by hand.
        """
        held = {}
        for need in self.needs:
            held.setdefault(self.group_of(need), []).append(need)
        return [(name, sorted(held[name], key=lambda n: n.what.lower()))
                for name in
                sorted(held, key=lambda g: (min(n.urgency for n in held[g]),
                                            g.lower()))]

    def rows(self):
        out = []
        for name, members in self.groups():
            band = [n for n in members if self.matches(n)]
            if not band:
                # The heading stays for what is there, not for what the
                # filter took away. An empty group is a line you scroll
                # past to reach the rows you asked for.
                continue
            out.append(Row('head', name.upper(), group=name,
                           held=len(band)))
            # Shut, the rows are left out and the heading stays. The
            # heading is what `→` acts on, and a list that dropped it
            # would have nowhere to put the cursor.
            if name in self.shut:
                out.append(Row('gap', ''))
                continue
            for need in band:
                out.append(Row('need', need.what, need=need))
                # What it binds, under it. In the footer instead, you
                # move onto a row to learn what it does and never see two
                # at once. X4 puts six lines there for one hat, so the
                # footer is the wrong size for the answer.
                if need in self.open_binds:
                    for part, what in self.binds(need):
                        out.append(Row('bind', f'{part:10} {what}',
                                       need=need))
            out.append(Row('gap', ''))
        return out


# ------------------------------------------------------------------- drawing

#: Two lines. One line is 96 characters and a terminal is 80, so `s
#: write` and `q quit` fall off the end of the screen that documents
#: them. Moving comes first: you need it before the rest is reachable.
#: The whole list, shown by `?`. The border carries the handful you
#: reach for constantly. This carries everything, including the capital
#: forms, and those are most of what somebody presses `?` to find out.
#: What `?` shows.
#:
#: It says what the screen IS. A list of key names answers "which key"
#: and never "what am I doing here", and the second question is why
#: somebody reaches for help.
#:
#: One entry per line. Two entries on some rows and one on others is a
#: table a reader cannot scan. The browse screen's own keys belong to
#: that screen and sit in its own footer.
KEYS = (
    ('head', 'NAME'),
    ('plain', '  review - put a game\'s actions onto HOTAS controls'),
    ('plain', ''),
    ('head', 'DESCRIPTION'),
    ('plain', "  A row is an entry. An entry is one or more of the game's"),
    ('plain', '  actions and the control they landed on. The entries are'),
    ('plain', '  grouped by category. Press s to keep what you decided.'),
    ('plain', '  Nothing reaches the game until you press w.'),
    ('plain', ''),
    ('head', 'MARKS'),
    ('mine', f'  {MARK[MINE]}           {MARK_SAID[MINE]}'),
    ('proposed', f'  {MARK[PROPOSED]}           {MARK_SAID[PROPOSED]}'),
    ('unset', f'  (none)      {MARK_SAID[UNSET]}'),
    ('plain', f'  {BARE}           This row has no job.'),
    ('plain', ''),
    ('head', 'MOVING'),
    ('plain', '  TAB         Move between the panels. Shift-TAB goes back.'),
    ('plain', '  ↑↓  j k     Move or scroll, in the panel TAB is on.'),
    ('plain', '  ←→          Open or shut what the cursor is on.'),
    ('plain', '  g  G        Go to its first or its last line.'),
    ('plain', '  f           Filter by text. An empty filter clears it.'),
    ('plain', '  h           Show or hide the bindings under each entry.'),
    ('plain', ''),
    ('head', 'ASSIGNING'),
    ('plain', '  ↵           Assign by pressing a control.'),
    ('plain', '  l           Assign from the free controls that fit.'),
    ('plain', '  c  C        Accept this proposal, or every proposal.'),
    ('plain', '  SPACE       Accept, then move down.'),
    ('plain', '  p  P        Restore the proposal here, or in every gap.'),
    ('plain', '  x           Unassign this row, yours or a proposal.'),
    ('plain', '  X           Unassign every row.'),
    ('plain', ''),
    ('head', 'THE LIST'),
    ('plain', '  a           Browse the game\'s vocabulary. Add entries.'),
    ('plain', '  J           Say what this function is.'),
    ('plain', '  Z           Guess what every function is.'),
    ('plain', '  r           Move this entry to another category.'),
    ('plain', '  R           Rename the category.'),
    ('plain', ''),
    ('head', 'OTHER'),
    ('plain', '  i           Invert an axis.'),
    ('plain', '  o           Apply an overlay.'),
    ('plain', '  y           Say why a control is chosen.'),
    ('plain', '  m           Show the device map and the install paths.'),
    ('plain', '  s           Save what you decided.'),
    ('plain', '  w           Write the plan to the game.'),
    ('plain', '  q           Quit.'),
)


def _sentence(said):
    """A fragment from a table, as a sentence.

    The tables hold fragments. A term or a fact is read in a column of
    them, where `the shape and the count fit` is right and `The shape and
    the count fit.` is a sentence pretending to be a label.

    A screen that puts one at the start of a line wants the other
    spelling. This is the one place that makes it.
    """
    said = said.strip()
    if not said:
        return said
    return said[0].upper() + said[1:] + ('' if said.endswith('.') else '.')


def _hand(ctrl):
    """`0 thumb` -- how far, and what gets there, for a column.

    A number and a finger. The words cut to twenty characters give
    `thumb` for a control reached with a named finger and `the hand off
    the dev` for one with no finger recorded, and the second is not a
    word.

    Half a sentence in a column is worse than a number. A number is
    explained once at the top. A truncation cannot be explained at all.
    The legend above says what 0 to 3 mean.
    """
    tier = corneeds.reach_tier(ctrl)
    far = '-' if tier == corneeds.UNMEASURED else str(tier)
    return f'{far} {corneeds.reach_finger(ctrl)}'.strip()


def _tilde(path):
    """`/home/you/x` -> `~/x`. Fourteen characters a reader knows."""
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if path.startswith(home + os.sep) else path


def _fold(path, width=74):
    """A long path over several lines, broken at directory boundaries.

    A Proton prefix is ninety characters before it says which game, so a
    terminal cuts off the part that answers the question.
    """
    if len(path) <= width:
        return [path]
    lead = os.sep if path.startswith(os.sep) else ''
    out, line = [], ''
    for part in path.lstrip(os.sep).split(os.sep):
        piece = (line + os.sep + part) if line else part
        if line and len(piece) > width:
            out.append(line + os.sep)
            line = part
        else:
            line = piece
    if line:
        out.append(line)
    return [lead + out[0]] + out[1:] if out else [path]


def _put(scr, y, x, text, attr=curses.A_NORMAL):
    """Draw, clipped to the screen.

    Clipped to `w - x`, not `w - x - 1`. Writing the bottom-right cell
    raises, and that is one cell on one row. A whole spare column for it
    eats the right-hand border of every panel that reaches the screen
    edge. The `except` covers that cell.
    """
    h, w = scr.getmaxyx()
    if 0 <= y < h:
        try:
            scr.addstr(y, x, text[:max(0, w - x)], attr)
        except curses.error:
            pass


#: Below this width the two panels stop fitting. The list needs about 52
#: columns before `throttle · Middle finger hat` is cut, and the detail
#: panel is unreadable under about 26.
SPLIT_AT = 90

#: Where the divider sits in a list row: the mark, then the action name,
#: then the line, then what it is bound to.
NAME_W = 29

#: The detail panel never gets less than this, however wide the list
#: wants to be. Under this width the wrapping gives one word per line.
DETAIL_MIN = 26


#: The free panel's own height, frame included. Seven rows of controls
#: under a lid and a sill: enough to read a desk's spare hats and levers
#: without scrolling on any of the four games but MSFS, which has 20.
FREE_H = 9

#: Under this the free panel is dropped. The detail panel is unreadable
#: below about 26 columns and pointless below about ten rows, and the
#: free list is the half you can reach another way.
FREE_AT = 24


def _layout(width, height, wants=None):
    """((y, x, h, w) for the list, the detail, and the free controls).

    Side by side where there is room. `wants` is how wide the list would
    like to be for the rows it has, and the rest goes to the right
    rather than to blank space. A fixed split leaves that space between
    the two.

    The right column is split again, in height. The detail is about the
    row the cursor is on and the free list is about the desk, so neither
    answers the other's question and neither can be the other's tail.

    The free panel is dropped where the column is too short for both.
    Its answer is reachable another way and the detail's is not.

    Below `SPLIT_AT` the two columns stack. A list cut off in the middle
    of a control's name is worse than a shorter one, and a stack has no
    room for a third panel.
    """
    if width >= SPLIT_AT:
        left = width - DETAIL_MIN
        if wants:
            left = max(SPLIT_AT - DETAIL_MIN, min(left, wants))
        right = width - left
        if height >= FREE_AT:
            tall = min(FREE_H, height // 3)
            return ((0, 0, height, left),
                    (0, left, height - tall, right),
                    (height - tall, left, tall, right))
        return (0, 0, height, left), (0, left, height, right), None
    # Stacked. The list keeps what it needs and the detail takes the
    # rest, never more than a third and never less than a frame plus two
    # lines.
    tall = max(4, min(height // 3, 10))
    listed = max(6, height - tall)
    return ((0, 0, listed, width), (listed, 0, height - listed, width),
            None)


#: The panels TAB walks, in the order it walks them. The arrows move
#: inside whichever one has the focus, and every other key goes on
#: acting on the row under the cursor in the list: `c` accepts that row
#: whatever the arrows are pointed at.
#:
#: A panel that is not drawn is skipped. The free list is dropped on a
#: short column, and a stacked screen has no room for it at all.
LIST, DETAIL, FREE = 'list', 'detail', 'free'

#: What the focused panel says in its sill, where the arrows scroll it
#: rather than move a cursor.
SCROLL = '↑↓ scroll'

#: Which way `←` and `→` go from a heading. A group with its rows hidden
#: points at the key that brings them back.
SHUT, OPEN = '▸', '▾'

#: Which way a movement key goes, by one. Separate from the ends below
#: so the loop needs one dispatch branch for all six: a second line
#: starting `if k in` is a branch an earlier one has already answered,
#: and `test_no_key_is_answered_twice` reads the source for exactly
#: that shape.
STEP = {'up': -1, 'k': -1, 'down': 1, 'j': 1}

#: And the two that go to an end. Which way, not how far: how far is the
#: length of whatever the arrows are pointed at, and only the loop knows
#: which panel that is.
END = {'g': -1, 'G': 1}

#: How long the corner box stays up after something is touched. Long
#: enough to read a control's name, short enough that the box is about
#: the thing in your hand rather than about the last hour.
HOLD = 2.0

#: How long the loop waits for a key. The corner box is drawn between
#: ticks, so this is also how late a press can show.
TICK = 0.05

#: In the sill, most-needed first. What is dropped on a narrow panel is
#: dropped from the end, and nothing else is reachable without moving.
HINTS = ('↑↓ move', '←→ fold', '↵ assign', 'l from free', 'c accept',
         'x unassign',
         'a add', 'J what it is', 'Z guess', 'i invert', 'r category', 'f filter',
         'h binds',
         'o overlay', 'y why', 'm map', 's save', 'w write', 'tab panel')


def _fit(width, text, lead=''):
    """`text` as lines no wider than `width`, hanging under `lead`.

    The panel wraps its own lines. `_draw` wraps flush left, so a ledger
    line it breaks lands under the `+40` rather than beside it, and stops
    reading as a ledger.
    """
    room = max(6, width - len(lead))
    bits = textwrap.wrap(text, room) if text else ['']
    pad = ' ' * len(lead)
    return [lead + bits[0]] + [pad + b for b in bits[1:]]


def _foot(rv, row, width=DETAIL_MIN - 4):
    """The lines pinned to the BOTTOM of the detail panel.

    `WHAT HAPPENS TO IT` was asked for at the end of the box, and the end
    of a scrolling list is not the end of a box.

    Measured on Elite at 120 by 40: the panel holds 29 lines and `Power
    distribution` wants 48. The one section a reader needs on every row
    sat 19 lines under the fold, where the row's state and what moves it
    are exactly what you came to the panel for.

    `_what_happens` writes it, here and in `_side`, so the two cannot
    disagree about the words.
    """
    if row is None or row.kind != 'need':
        return []
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    _what_happens(rv, row.need, say)
    return out


def _side(rv, row, width=DETAIL_MIN - 4, foot=True):
    """The detail panel's body: where the row sits, what it fires, and
    why.

    Three questions, and they are not one question. A panel that names
    the control and its reach and stops leaves the third unanswered, and
    the planner's choice is the thing a reader argues with.

    `foot` off leaves `WHAT HAPPENS TO IT` out, for the caller that pins
    it to the bottom of the panel instead of scrolling it. On means the
    whole panel in one list, which is what a reader of the text wants.

    `Reason` is the account of that choice, written where the decision
    was made. This is its first human reader.

    The score is shown as the terms it was made of, and not as its total.
    137 says nothing. `+40 the stick it asked for` is the sentence the
    number stood for.

    The device's full product name is here rather than in a header of its
    own. A row that says "stick" does not say WHICH stick, and this is
    the moment that question is asked.
    """
    if row is not None and row.kind == 'head':
        return _group_side(rv, row.group, width)
    if row is None or row.kind != 'need':
        return []
    need, p = row.need, rv.at[row.need]
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    if p is None:
        plan = rv.plan.get(need)
        say('head', 'NOWHERE')
        # The count only where it says something the shape does not. `a
        # button and 1 button` is one fact written twice.
        say('meta', f'This row needs a {need.first_shape}.'
            if need.wanted == 1 else
            f'This row needs a {need.first_shape} with '
            f'{ctui.plural(need.wanted, "button")}.')
        say('plain')
        # First, because it is the only one of these you act on, and
        # because it is the reason the row is empty. The planner was not
        # asked, so what the planner would have done is beside the
        # point.
        gone = rv.unhonoured(need)
        if gone:
            say('unset', gone)
            say('note', 'The row stays empty. Press x to give the row '
                        'to the planner.')
            say('plain')
        # Only where there is nothing below to say it. The table names
        # the planner's choice and marks it.
        if plan is None:
            say('meta', 'The planner has no control for this row.')
            say('plain')
        _asked_for(need, say)
        say('plain')
        # And the account for it. An empty row is where "why there?" is
        # still open, and it is the row that answers least: the planner's
        # choice named and never costed leaves nothing on screen to agree
        # or disagree with.
        say('head', 'WHAT WOULD TAKE IT')
        _against(rv, need, plan.role if plan else '',
                 plan.ctrl if plan else None, say, width)
        if foot:
            say('plain')
            _what_happens(rv, need, say)
        return out

    say('head', 'WHERE')
    dev = rv.layout.devices.get(p.role)
    said = [('role', p.role)]
    if dev is not None:
        said.append(('device', dev.product))
    if need.takes == corneeds.AXIS:
        # The axis's own label, not its control's. Three of the stick's
        # axes are `Main stick`, and one of them is pitch.
        a = rv.lever(p)
        said += [('lever', a.label), ('axis', str(a.index))]
    else:
        said += [('control', p.ctrl.label), ('shape', p.ctrl.kind),
                 ('bindings', str(len(p.slots)))]
    _fields(say, said)

    binds = rv.binds(need)
    if binds:
        say('plain')
        say('head', 'BINDS')
        # Fields, like every other panel. A shape of its own, with the
        # part cut to seven characters and left-aligned, reads `press
        # Map: Map pan to rotate` under three lines that read `  control
        # Thumb hat`. The column the eye follows then moves between
        # sections of one box.
        _fields(say, list(binds))

    say('plain')
    _why(rv, need, p, say, width)
    if foot:
        say('plain')
        _what_happens(rv, need, say)
    return out


def _what_happens(rv, need, say):
    """The last section of the panel: the row's state, and what moves it.

    Every other section answers a question about the past. This one
    answers the two a reader has next: where does this row stand, and
    what changes it.

    Four states and one line each, because the four differ in what moves
    them. A proposal moves on the next plan. A choice of yours moves on
    nothing. A row you emptied is left alone by every pass. A row the
    planner found nowhere for waits for a press.

    The job gets a line of its own, because a row without one is
    invisible to every template and that looks like a template which did
    not apply.
    """
    mark = rv.mark[need]
    say('head', 'WHAT HAPPENS TO IT')
    if mark == MINE:
        # Two decisions wear one mark, and they differ in exactly what
        # this section answers. `chose` takes the control before anything
        # is scored, so nothing moves it. `accepted` changes no
        # allocation: the row still competes, and the day the desk or the
        # list changes the allocator can move it and the mark goes back
        # to `?`. `Need.assignment` is where the two are told apart.
        if (need.assignment or {}).get('how') == corneeds.ACCEPTED:
            say('mine', 'You accepted this control.')
            say('note', f'A new desk or a new list can move it back to '
                        f'{MARK[PROPOSED]}.')
        else:
            say('mine', 'You put this here. Nothing moves it.')
            say('note', 'Press x to hand the row back to the program.')
    elif mark == PROPOSED:
        say('proposed', 'The program put this here. The next plan can '
                        'move it.')
        say('note', 'Press c to keep it. Press x to empty the row.')
    elif (need.assignment or {}).get('how') == corneeds.CLEARED:
        say('unset', 'You emptied this row. No pass fills it.')
        say('note', 'Press p to ask the program again.')
    else:
        say('unset', 'Nothing is on this row. The program found no '
                     'control.')
        say('note', 'Press RETURN to put it on a control.')
    if not corneeds.described(need):
        say('plain')
        say('unset', 'This row has no job. No overlay rule reaches it.')


def _one_of(names):
    """`Strafe +1` -- one name and a count, where there is room for one.

    A control carries more than the need that took it: the share pass
    hands a leftover need a spare button of a control something else
    owns, so four names can belong on one line.

    The first name and a count, rather than as many as fit. A list cut
    mid-word reads as a name nobody gave: `INPUT_RANGE_STEERING_PRIMARY,
    INPUT_RANG` is what X4's main stick comes out as. The map screen has
    room for all of them.
    """
    if not names:
        return ''
    return names[0] + (f' +{len(names) - 1}' if len(names) > 1 else '')


def _free_side(rv, got, width):
    """[(tone, text)] -- the controls nothing sits on, device by device.

    The answer to "where could this go", which the detail panel cannot
    give: that one is about the row the cursor is on, and this is about
    the desk.

    Each row says what the control is and what it offers, because a name
    alone does not say whether a thing fits. `T1 rocker` takes two
    bindings and `Side lever` takes an axis, and the shape is what tells
    them apart.

    Grouped by device, like everything else on this screen. One run of
    twenty control names makes you work out which stick each is on.
    """
    if not got:
        return [('meta', 'Every control carries something.')]
    out, role = [], None
    for this, ctrl in got:
        if this != role:
            role = this
            out.append(('subhead', this))
        says = ctrl.kind
        n = len(ctrl.bindable_buttons)
        if n:
            says += f'  {ctui.plural(n, "button")}'
        axes = corneeds.axes_of(rv.layout.devices[this], ctrl)
        if axes:
            says += f'  {ctui.plural(len(axes), "axis", "axes")}'
        out.append(('plain', f'  {ctrl.label}'[:width]))
        out.append(('meta', f'    {says}'[:width]))
    return out


def _title_of(row):
    """What the detail panel is headed with. Never None.

    Every kind has a branch, and that is the point. A kind with none
    gives a title of None, and slicing that takes the screen down the
    moment the cursor reaches those rows.
    """
    if row is None:
        return ''
    if row.kind == 'need':
        return row.need.what
    if row.kind == 'head':
        return row.group or row.text
    return ''


def _group_side(rv, name, width):
    """What a heading is, where the cursor is on one.

    An unanswered heading leaves an empty box, and that reads as a hole
    rather than as a thing you are standing on.
    """
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    members = dict(rv.groups()).get(name, [])
    tally = collections.Counter(rv.mark[n] for n in members)
    say('head', 'GROUP')
    # Fields, like every other panel. `a band, not yours to rename` and
    # `r files things out of it` are keystroke notes in the grammar of
    # statements, under a heading that says neither which key nor what it
    # does.
    _fields(say, [('name', name),
                  ('kind', 'band of urgency' if name in corneeds.URGENCY_NAME
                   else 'yours'),
                  ('entries', str(len(members)))]
            + [(MARK[state], f'{tally[state]} {MARK_SAID[state]}')
               for state in (MINE, PROPOSED, UNSET) if tally[state]])
    return out


#: What a need asks of a control: the flag in the file, and the phrase a
#: reader gets. Beside the flags rather than inside the panel, so a sixth
#: one is a row here.
ASKS = (('held', 'held down'), ('rapid', 'tapped'),
        ('by_feel', 'found blind'), ('costly', 'a slip hurts'),
        ('modifier', 'held as a modifier'))


def _fields(say, rows):
    """`label  value`, one field to a line, aligned on the gutter.

    A field, not a loose sentence. `thumb, your hand where it lives,
    nothing moved` under WHERE says nothing about what it answers, so a
    reader has to work out that it is a measurement and not a remark.

    The gutter comes from the longest label there is. Fixed at twelve it
    puts twenty characters, `         shape  hat4`, into a panel eighteen
    wide. Right-aligning in a narrower field does not shorten a label. It
    stops padding it.
    """
    gutter = max(len(label) for label, _v in rows)
    for label, value in rows:
        say('plain', value, lead=f'  {label:>{gutter}}  ')


#: The four fields the scorer reads that a row can be without. Each one
#: is drawn whether it has a value or not, because the absence changes
#: where the row lands and nothing else on the screen says so.
#:
#:     job     an overlay matches on it, so a row without one is a row
#:             no `[[want]]` rule reaches
#:     device  `device_right` pays +40 and `device_wrong` costs -50, so a
#:             row without one is scored on reach and shape alone
#:     on      a hat without it lands in press order, and not where the
#:             switch moves
#:     rests   an axis without it takes a lever that rests anywhere
#:
#: `shape` and `when` are not here. Every need has both, and the file
#: requires them.
MISSING = 'MISSING'


def _asked_for(need, say):
    """The need's own row, one field to a line.

    Its shape, its band and whichever flags somebody set come from
    `games/<g>/<g>-needs.json`, which describes the function. The device
    comes from the overlay, which is where wanting one is said. Nothing
    here is derived, and nothing here is prose.

    A field the scorer reads is drawn empty as `MISSING`. Left out, the
    row says nothing about it, and a reader cannot tell a field nobody
    answered from a field this panel does not show.
    """
    say('head', 'WHAT IT ASKED FOR')
    said = [('shape', need.first_shape),
            ('job', need.suits or MISSING),
            ('device', need.device or MISSING)]
    # `on` is three questions under one name, and `_applies` answers
    # which one this row asks. A lone button press has no direction to
    # choose, so there is nothing missing from it.
    if _applies('family', need):
        said.append(('on', ', '.join(str(w) for w in need.on)
                     if need.on else MISSING))
    if need.takes == corneeds.AXIS:
        said.append(('rests', need.rests or MISSING))
    said.append(('when', corneeds.URGENCY_NAME[need.urgency]))
    said += [('', phrase) for flag, phrase in ASKS
             if getattr(need, flag, False)]
    _fields(say, said)


def _how_it_moves(rv, p, say):
    """What the map measured about this lever.

    Where a lever rests decides whether zero means off. Two levers that
    move together are one lever until you uncouple them. Both are the
    sort of thing you otherwise find out by flying.

    The heading says what the lines answer. `THE LEVER` names the thing
    instead, and names it wrong for most of them: a twist and a
    mini-stick are not levers.
    """
    dev = rv.layout.devices.get(p.role)
    a = rv.lever(p)
    facts = [('rests', a.rest)] if getattr(a, 'rest', '') else []
    if getattr(a, 'moves_with', None) and dev is not None:
        facts.append(('moves with',
                      ', '.join(dev.axis_label(i) for i in a.moves_with)))
        if getattr(a, 'coupling', ''):
            facts.append(('coupling', a.coupling))
    if facts:
        say('plain')
        say('head', 'HOW IT MOVES')
        _fields(say, facts)


def _every_lever(rv, need, p, say):
    """The device's levers, and what is on each.

    This answers the one question an axis row raises: why this lever and
    not the one beside it. A button row has the candidate table for that,
    and this is the same question.
    """
    dev = rv.layout.devices.get(p.role)
    if dev is None:
        return
    here = rv.lever(p)
    rest = sorted(dev.axes(), key=lambda x: x.index)
    if len(rest) <= 1:
        return
    held = {}
    for other in rv.needs:
        at = rv.at[other]
        if at is not None and other.takes == corneeds.AXIS:
            held.setdefault((at.role, rv.lever(at).index), []).append(
                other.what)
    # What each lever is worth to this need, which is the comparison the
    # allocator made. `axes_for` scores every lever that answers the ask,
    # and the points pick among them. `answers this too` and no more is
    # what a resolver that took the first lever and recorded nothing
    # about the rest leaves to say.
    worth = {(r, a.index): s for s, r, _c, a
             in corneeds.axes_for(need, rv.layout.devices, rules=rv.rules)}
    say('plain')
    say('head', f'EVERY LEVER ON THE {p.role.upper()}')
    for got in rest:
        mine = got.index == here.index
        on = held.get((p.role, got.index), [])
        said = ', '.join(n for n in on if n != need.what) or 'free'
        points = worth.get((p.role, got.index))
        # A dash where it has no score, as the button table does. The ask
        # refused it, so there is no number to lose on.
        num = '\u2014' if points is None else str(points)
        say(rv.mark[need] if mine else 'meta',
            f'{"\u25b6" if mine else " "} {num:>5}  {got.label}')
        say('meta', said, lead='        ')


def _how_it_was_set(need, p, say):
    """Who put this where it is, and what you have said about it.

    Three states live on this screen, and all three have words here. Two
    of them are "the planner put it there and you agreed" and "the
    planner put it there and you have not looked". Unworded, the only
    thing that tells those apart is the colour of the row.

    This matters most at the moment you press `s`. All three go into the
    file, and `how` in the file is this.
    """
    mine = need.assignment or {}
    by_hand = p.why is not None and p.why.how == 'yours'
    say('plain')
    say('head', 'HOW IT WAS SET')
    # `set by`, not `put there by`. The gutter is the longest label and
    # `_fit` keeps six columns for the value, so a label past eight
    # characters is wider than the narrowest panel the screen draws.
    said = [('set by', 'by hand' if by_hand else 'the planner')]
    if by_hand:
        said.append(('kept as', 'yours'))
    elif mine.get('how') == corneeds.ACCEPTED and \
            mine.get('control') == p.ctrl.id:
        said.append(('you said', 'yes, to this control'))
    elif mine.get('how') == corneeds.ACCEPTED:
        # You agreed to a control, and this is not that control.
        said.append(('you said', 'yes, to another control'))
    else:
        said.append(('you said', 'nothing yet'))
    _fields(say, said)
    # Which pass placed it, in the words the table already has. Under
    # the candidate list instead, a share or a reach past the floor reads
    # as a note about the arrow. `yours` is left out, because `set by`
    # has just said it.
    how = p.why.how if p.why is not None else ''
    if how in corneeds.CAME_BY and how != 'yours':
        say('note', _sentence(corneeds.CAME_BY[how]), lead='  ')


def _why(rv, need, p, say, width=DETAIL_MIN - 4):
    """Why this binding is on this control, in the allocator's own terms.

    Every control is worth points to an action. The actions go in order,
    most urgent first. Each takes the free control worth most.

    So three things account for a placement, and the panel is those
    three: what the action asked for, what each control was worth and who
    sits on it, and what the winner's points were made of.

    The last of those alone is how the score was reached, and not why
    this control. Measured over the five games, 85 placements of 146 were
    ties and 24 more went where they went because something better was
    taken. For 109 of 146 the answer is in the middle section and nowhere
    else.
    """
    r = p.why
    how = r.how if r is not None else ''
    _asked_for(need, say)
    _how_it_was_set(need, p, say)
    if need.takes == corneeds.AXIS:
        # The same three answers as a button row, in the shapes an axis
        # has them in: what the map measured about the lever, every lever
        # that could have taken it and what each is worth, and what the
        # winner's points were made of.
        #
        # An axis that is named rather than chosen has no comparison to
        # report and no score to break down. An axis IS chosen, by
        # `axes_for`.
        _how_it_moves(rv, p, say)
        _every_lever(rv, need, p, say)
        if p.points is not None:
            _worth(say, need, p.role, p.ctrl, p.points, rv.rules,
                   axis=rv.lever(p), lead=5)
        return
    say('plain')
    say('head', 'WHICH CONTROL GOT IT')
    # What it is, where the heading's own answer is not the whole of it.
    # Not `you chose it`: HOW IT WAS SET says that. Said here, it answers
    # a heading about which control beat which, which is the wrong
    # question.
    # Nothing to say about a pin. The ledger below names the pin and the
    # control, as `+1000 pinned to 'Pinky button'`. A sentence that says
    # the same thing in words is one you learn to skip.
    plan = rv.plan.get(need)
    word = ''
    if how == 'yours' and plan and not (plan.role == p.role
                                        and plan.ctrl is p.ctrl):
        word = (word + ' ' if word else '') \
            + f'The planner wants {plan.ctrl.label}.'
    _against(rv, need, p.role, p.ctrl, say, width,
             how=how, said=word)


def _against(rv, need, role, ctrl, say, width, how='', said=''):
    """Every control that could take this, and what the one on it is
    worth.

    Drawn for a hand-placed row as well. What a control is worth to an
    action is a fact about the desk, and not about who typed it. Refused
    to any placement the allocator did not pick, this panel draws one
    line, the control's name, and stops: 45 rows of 174 across the six
    games, and 24 of those have a score and a field of candidates sitting
    unprinted.

    An empty row is the other half of the same hole. The planner's choice
    is named and never accounted for, so the one row where "why there?"
    is still open is the row that answers least.
    """
    LEAD, NUM = 2, 7
    # Scored without `stayed`, which pays whichever control the need is
    # already on. Counted, every alternative sits 20 below and the panel
    # reports that nothing else came close. So these totals are what the
    # controls are worth to the action, and not what the run added up.
    rules = corneeds.merge_rules(rv.rules, {'term': [{'name': 'stayed',
                                                      'weight': 0}]})
    ran = corneeds.ran_against(need, rv.layout.devices, rules=rv.rules,
                               floor=how != 'relaxed')
    mine = next((s for s, r, c in ran if c is ctrl and r == role), None)
    if ctrl is not None and mine is None:
        # Sitting on a control that was never a candidate: a hand-placed
        # need on one button of a hat, or a spare button the share pass
        # lent it. It goes at the head of the table with no number,
        # because it has none: `score` refuses the control for the whole
        # function. It is not left out of its own account.
        ran = [(None, role, ctrl)] + list(ran)
    if not ran:
        say('plain', 'No control on this desk fits this row.', lead='  ')
        return

    # Everything that could have had it, and the next best under it.
    # Only what beat it makes a binding that won outright read as the
    # only one that fitted, and that is a lie wherever anything else
    # fitted.
    rows = (ran if mine is None else
            [x for x in ran if x[0] >= mine]
            + [x for x in ran if x[0] < mine][:1])

    def whos_on(role, got):
        """`Strafe +1` -- a control carries more than one need.

        The share pass hands a leftover need a spare button of a control
        something else took, so four names can belong on one line. The
        first name and a count. The map screen has room for all of them
        and this column has room for one.
        """
        if got is ctrl:
            return ''
        on = [n.what for n in rv.who_has(role, got) if n is not need]
        return _one_of(on) or 'free'

    held = {(r, c.id): whos_on(r, c) for _s, r, c in rows}
    lab = max(len(c.label) for _s, _r, c in rows) + 2
    # One shape for the block, decided by whether the names fit whole.
    # Decided per row, a name a character too long wraps while the four
    # around it do not, and the block reads as though that line meant
    # something the others did not.
    #
    # The name wins over the columns. A control whose name you cannot
    # read is not one you can find, and `Thumb top butto` is what the
    # columns leave of it.
    room = width - LEAD - NUM - 2
    # The `taken by` column counts towards the width. Measured on the
    # label alone, a table that just fits wraps its last column to column
    # zero: `free` under the points, reading as a row of its own. That is
    # the shape the stacked form exists to avoid.
    wide = lab + max((len(w) for w in held.values()), default=0) <= room
    if wide:
        say('plain', 'taken by' if any(held.values()) else '',
            lead=f'  {"points":>{NUM}}  {"control":<{lab}}')
    for points, r, c in rows:
        here = c is ctrl and r == role
        tone = rv.mark[need] if here else 'plain'
        mark = '\u25b6' if here else ' '
        who = held[(r, c.id)]
        # A dash, not a zero. It has no score, because the control
        # cannot play this part at all. A zero reads as a score it lost
        # on.
        num = '\u2014' if points is None else str(points)
        if wide:
            say(tone, f'{mark} {num:>{NUM}}  {c.label:<{lab}}{who}')
            continue
        # Stacked. The name on its own line, and what it was worth under
        # it.
        say(tone, f'{mark} {c.label}')
        say('meta', who, lead=f'  {num:>{NUM}}  ')
    if how == 'relaxed':
        say('note', 'No closer control was free.', lead='  ')
    if said:
        say('meta', said, lead='  ')
    # No control, or no number for the one there is. That is an empty row
    # the planner had nowhere to put, or a control that cannot take the
    # whole function and lent it a button.
    if ctrl is None or mine is None:
        return

    _worth(say, need, role, ctrl, mine, rules, floor=how != 'relaxed')


def _worth(say, need, role, ctrl, points, rules, floor=True, axis=None,
           lead=7):
    """What the points were made of, term by term.

    Drawn for an axis as well as a button, from the same call. An axis is
    scored by the same table. It is chosen by `axes_for`, out of
    everything that answers the ask.
    """
    say('plain')
    # What makes it worth that, rather than where it `got` it. A control
    # you put this on yourself was never in a run to get anything, and
    # the number is what it is worth to the action either way.
    say('head', f'WHAT MAKES {ctrl.label.upper()} WORTH {points}')
    parts = []
    corneeds.score(ctrl, need, role, parts=parts, floor=floor, rules=rules,
                   axis=axis)
    for delta, text in sorted(parts, key=lambda q: -q[0]):
        say('meta', text, lead=f'  {delta:>+{lead}}  ')


def _panel(scr, theme, rect, title, right='', keys=(), tail='', note='',
           focus=False):
    """Frame a box and hand back the rectangle inside it.

    A framed panel is heavy where the arrows are pointed at it. A shape
    rather than a colour: the frame already spends its tone on being a
    frame, and these screens run on a terminal with no colour.
    """
    y, x, h, w = rect
    heavy = ctui.weight
    _put(scr, y, x, heavy(ctui.lid(w, title, right), focus), theme.head)
    side = heavy(ctui.V, focus)
    for row in range(y + 1, y + h - 1):
        _put(scr, row, x, side, theme.head)
        _put(scr, row, x + w - 1, side, theme.head)
    _put(scr, y + h - 1, x, heavy(ctui.sill(w, keys, tail, note), focus),
         theme.note if note else theme.head)
    return y + 1, x + 2, h - 2, w - 4


def _tally(rv):
    """What sits beside the title: the filter, or what is on the list.

    The filter where there is one, and the tally otherwise. Both answer
    "what am I looking at", and one of them is true at a time.

    Only what is there. `lid` drops a line whole where it does not fit
    beside the title, so a long form takes the counts off the screen
    with it.
    """
    mine, prop, unset = rv.counts()
    counts = [f'{MARK[MINE]}{mine}' if mine else '',
              f'{MARK[PROPOSED]}{prop}' if prop else '',
              f'{unset} {MARK_SAID[UNSET]}' if unset else '',
              # Which overlay this was laid out to. A state, so it goes
              # here and not in the status line. Said even where there is
              # none: "the planner had no wishes" and "the planner
              # ignored mine" look identical on a row.
              rv.overlay().name if rv.overlay() is not None
              else 'no overlay',
              # Last, and here rather than in the status line. A status
              # line says what just happened and goes on the next
              # keypress. This is a state of the files.
              'unsaved' if rv.unsaved else '']
    return rv.narrowed() or ctui.SEP.join(c for c in counts if c)


def _draw(scr, rv, sel, state, theme, focus=LIST, lit=()):
    h, w = scr.getmaxyx()
    rows = rv.rows()
    title = rv.title + (f' · {rv.subtitle}' if rv.subtitle else '')
    right = _tally(rv)
    # As wide as the widest row is, so the detail panel gets the space
    # and the gap does not. The header counts too. It sits on this panel,
    # `lid` drops its right-hand line whole, and that line carries the
    # overlay and `unsaved`: states of the files, not decoration.
    #
    # Measured before this asked: the rows wanted 68 columns on Elite and
    # 66 on X4, the header wanted 70 and 82, and both games lost the
    # tally at EVERY terminal width. A wider terminal did not help,
    # because the surplus goes to the detail panel.
    wants = max(4 + 2 + NAME_W + max((len(rv.where(r.need)) for r in rows
                                      if r.kind == 'need'), default=0),
                ctui.lid_wants(title, right))
    (ly, lx, lh, lw), side, spare = _layout(w, h, wants)
    visible = max(1, lh - 2)
    top = state['top']
    if sel < top:
        top = sel
    elif sel >= top + visible:
        top = sel - visible + 1
    state['top'] = top

    scr.erase()
    # Needs, not every selectable row. This says which of the things you
    # are placing you are on, and a heading is not one of them.
    pick = [i for i, r in enumerate(rows) if r.kind == 'need']
    at = sum(1 for i in pick if i <= sel)
    iy, ix, ih, iw = _panel(
        scr, theme, (ly, lx, lh, lw), title,
        # A game's own keys sit in the sill beside the family's. A key
        # nobody shows is a key nobody presses.
        right, HINTS + tuple(f'{key} {word}' for key, word, _do in rv.offers),
        _where(rows, sel, at, pick), note=rv.status,
        focus=focus == LIST)

    for n, i in enumerate(range(top, min(len(rows), top + visible))):
        row = rows[i]
        y = iy + n
        if row.kind == 'head':
            # The mark and the count are what the screen adds. `text` is
            # the group's own name, and a test that asks what a group is
            # called should not have to know which way it is folded.
            shut = row.group in rv.shut
            said = (f'{SHUT} {row.text}  {row.held}' if shut
                    else f'{OPEN} {row.text}')
            _put(scr, y, ix, said[:iw],
                 theme.sel if i == sel else theme.head)
        elif row.kind == 'bind':
            _put(scr, y, ix + 4, row.text[:iw - 4], theme.meta)
        elif row.kind == 'need':
            # The state name is the tone name, so this screen and the
            # map ask the theme the same question and get the same
            # answer.
            st = rv.mark[row.need]
            # The state decides the tone and the hand adds to it. A row
            # under a thumb is still a row you chose or the planner did,
            # and a tone of its own would take that away to say so.
            attr = (theme.sel if i == sel else theme[st])
            if row.need in lit:
                attr |= theme.touched
            # A divider, not a gap. At 68 columns the eye carries a name
            # across 26 blank spaces to reach what it is bound to, and it
            # loses the row on the way.
            # The dot costs the name one column of twenty-six. A
            # description is not a fourth mark. The mark says where the
            # row sits. This says whether anybody has said what it is.
            # `plan` counts the same thing in its last line.
            said = ' ' if corneeds.described(row.need) else BARE
            _put(scr, y, ix,
                 f'{MARK[st]} {row.text[:25]:25}{said}'[:iw], attr)
            if iw > NAME_W + 2:
                _put(scr, y, ix + NAME_W, ctui.V, theme.meta)
                _put(scr, y, ix + NAME_W + 2,
                     rv.where(row.need)[:iw - NAME_W - 2], attr)

    row = rows[sel] if 0 <= sel < len(rows) else None
    # The group on a heading, the need on a row. The panel is about
    # whatever the cursor is on, and its title says which.
    name = _title_of(row)
    dy, dx, dh, dw = _panel(scr, theme, side, name[:side[3] - 6],
                            tail=SCROLL if focus == DETAIL else '? help',
                            focus=focus == DETAIL)
    # One wrapper, not two. `_side` fits its own lines to `dw`, because
    # it is the half that knows which of them are a ledger and hang under
    # their `+40`. Wrapped again here, that indent goes the moment a line
    # lands one character over.
    #
    # The state and what moves it sit at the bottom of the BOX, so they
    # are on screen whatever the rest of the panel is scrolled to. The
    # scrolling half gets what is left, and a blank line keeps the two
    # apart.
    foot = _foot(rv, row, dw)
    if foot and dh > len(foot) + 2:
        _scroll(scr, theme, _side(rv, row, dw, foot=False),
                (dy, dx, dh - len(foot) - 1), state, DETAIL)
        for n, (tone, text) in enumerate(foot):
            _put(scr, dy + dh - len(foot) + n, dx, text, theme[tone])
    else:
        _scroll(scr, theme, _side(rv, row, dw), (dy, dx, dh), state, DETAIL)

    if spare is not None:
        got = rv.free()
        fy, fx, fh, fw = _panel(
            scr, theme, spare, f'{len(got)} free',
            tail=SCROLL if focus == FREE else 'l to take one',
            focus=focus == FREE)
        _scroll(scr, theme, _free_side(rv, got, fw), (fy, fx, fh),
                state, FREE)

    scr.refresh()


def _scroll(scr, theme, lines, rect, state, which):
    """Draw a panel's lines from wherever it is scrolled to.

    The offset is clamped HERE, where the height and the length are both
    known, and written back. So the key that scrolls adds one and knows
    nothing about either, and a panel whose content shrank under it comes
    back into view rather than going blank.

    A tail line says how much is below, because a box that drops what
    does not fit, in silence, is worse than no box. MSFS leaves 20
    controls free and the panel holds three.
    """
    y, x, h = rect
    top = max(0, min(state.get(which, 0), max(0, len(lines) - h)))
    state[which] = top
    room = h - 1 if len(lines) > h else h
    for n, (tone, text) in enumerate(lines[top:top + room]):
        _put(scr, y + n, x, text, theme[tone])
    left = len(lines) - top - room
    if len(lines) > h:
        _put(scr, y + room, x,
             f'+{left} below' if left > 0 else 'the end',
             theme.meta)


# -------------------------------------------------------------- the sticks

class Sticks:
    """The joystick nodes, opened once and matched to roles by USB id.

    Nothing asks you to press a button on each device. The map is loaded
    already and every device in it carries its USB id:
    `/proc/bus/input/devices` gives vendor and product per `js` node, and
    that pair is what `devicemap` matches on.

    Nothing is opened until the first capture. A review of a layout on a
    machine with no sticks plugged in costs nothing, and it fails only
    where you ask it to open one.
    """

    def __init__(self, layout):
        self.layout = layout
        self.devices = []
        self.why = ''
        self.opened = False
        #: (role, axis) -> where that lever was before a hand took it.
        self.rest = {}

    def open(self):
        if self.opened:
            return self.devices
        self.opened = True
        want = {(d.usb or '').lower(): role
                for role, d in self.layout.devices.items() if d.usb}
        try:
            proc = ccapture.proc_joysticks()
        except OSError as e:
            self.why = f'cannot read /proc/bus/input/devices: {e}'
            return []
        for name, info in sorted(proc.items()):
            role = want.get(f"{info['vid']}:{info['pid']}".lower())
            if role is None:
                continue
            try:
                dev = ccapture.Device(info['js'])
            except OSError as e:
                self.why = (f"{info['js']} will not open ({e}). Are you "
                            "in the `input` group?")
                continue
            dev.role = role
            self.devices.append(dev)
        if not self.devices and not self.why:
            self.why = ('none of the devices in the map are plugged in '
                        f'({", ".join(sorted(want)) or "no USB ids"})')
        return self.devices

    #: How far an axis travels before it counts as moved, out of
    #: +-32767. A lever at rest jitters by a few hundred either way, and
    #: a deliberate nudge clears this.
    #:
    #: Smaller than `capture.AXIS_THRESHOLD`, which is 14000, and the two
    #: answer different questions. A capture waits for one unambiguous
    #: answer, so it wants a shove. This says what is under your hand,
    #: and a third of a throttle's travel is a thing you did.
    MOVED = 3000

    def touched(self):
        """(role, 'button' or 'axis', index) for what moved, or None.

        Reads whatever is queued and answers the last thing in it, so a
        caller that polls once a tick sees the newest press rather than
        the oldest.

        Nothing is opened here. The screen opens the devices once, and a
        desk with none plugged in answers None for the rest of the
        session rather than trying again twenty times a second.

        An axis is measured against `rest`, and not against the value it
        had one tick ago. A tick is 50 ms: a lever moved by hand travels
        a few hundred units in that time, and a threshold against the
        previous tick asks for a fifth of the range inside a twentieth
        of a second. Nothing a hand does clears that, so nothing moving
        ever showed.

        `rest` is where the lever was before you took hold of it, which
        is the same baseline `capture.wait_input` takes once before it
        waits.
        """
        got = None
        for dev in self.devices:
            before = dict(dev.axis_vals)
            moved = {}
            for kind, number, value in dev.read_events():
                if kind == 'button' and value == 1:
                    got = (dev.role, 'button', number)
                elif kind == 'axis':
                    moved[number] = value
            for number, value in moved.items():
                was = self.rest.setdefault((dev.role, number),
                                           before.get(number, value))
                if abs(value - was) > self.MOVED:
                    got = (dev.role, 'axis', number)
            # An axis that reported nothing this tick is where it is
            # going to stay, so that is the place to measure the next
            # move from. A lever you are moving reports every tick and
            # keeps the baseline it started from.
            for number, value in dev.axis_vals.items():
                if number not in moved:
                    self.rest[(dev.role, number)] = value
        return got

    def close(self):
        for d in self.devices:
            try:
                os.close(d.fd)
            except OSError:
                pass
        self.devices = []
        self.opened = False


def _ask(scr, tui, prompt, start=''):
    """Read a line on the bottom row. -> the text, or None on ESC.

    The smallest thing that answers the question. `core/tui.py` has no
    text entry, and `sim-device-map`'s Tui cannot be imported here.

    ESC is None and not the empty string. Emptying the filter and
    abandoning the typing are different answers, and `f` offers both.
    """
    text = start
    while True:
        h, w = scr.getmaxyx()
        _put(scr, h - 1, 0, ' ' * (w - 1))
        _put(scr, h - 1, 0, f'{prompt}{text}_'[:w - 1], curses.A_REVERSE)
        scr.refresh()
        k = tui.key(0.5)
        if k is None:
            continue
        if k == 'enter':
            return text
        if k == 'esc':
            return None
        if k == 'backspace':
            text = text[:-1]
        elif len(k) == 1 and k.isprintable():
            text += k


def _head_of(rv, name, fallback):
    """Where this group's heading is now, after it was renamed."""
    for i, row in enumerate(rv.rows()):
        if row.kind == 'head' and row.group == name:
            return i
    return fallback


def _where(rows, sel, at, pick):
    """The sill's tail: which of the things you are placing you are on.

    A heading is not one of them, and `0/32` there reads as a fault, so
    on a heading this says what the heading holds.

    Counted from the rows on screen and not from the group. With a filter
    up, what the group holds and what you can see are different numbers,
    and the one in front of you is the one to report.
    """
    here = rows[sel] if 0 <= sel < len(rows) else None
    if here is None or here.kind != 'head':
        return f'{at}/{len(pick)}' if pick else 'none'
    n = 0
    for r in rows[sel + 1:]:
        if r.kind == 'head':
            break
        n += r.kind == 'need'
    return ctui.plural(n, 'entry', 'entries') + ' here'


def _row_of(rv, need, fallback):
    """Where this need's row is now.

    `sel` is an index and not a reference, so anything that reorders the
    list says where to look again.
    """
    for i, row in enumerate(rv.rows()):
        if row.kind == 'need' and row.need is need:
            return i
    return fallback


def _hits(action, find):
    """Does this action answer to what was typed? Name or id, either."""
    if not find:
        return True
    find = find.lower()
    return find in action.name.lower() or find in action.id.lower()


def _pick_category(scr, tui, rv):
    """Which group to file it under. None where you changed your mind.

    The existing groups first. Filing beside something is the common
    case, and a typed name that differs by a space from one you have is
    how you end up with two.
    """
    known = rv.categories()
    got = tui.choose('file it under',
                  [('plain', k) for k in known] + [('meta', 'a new one...')])
    if got is None:
        return None
    if got < len(known):
        return known[got]
    name = _ask(scr, tui, 'new category: ')
    return name.strip() or None if name is not None else None


#: Nothing said. The screen's own word for it, from `MARKS` above, so an
#: empty field and an unassigned row read the same way.
#: What a function may say about ITSELF, in the order the form offers it,
#: and which closed list each answer comes out of. No words here. A
#: vocabulary lives in the table the scorer reads, so a job or a shape
#: added there is offered by that fact alone.
#:
#: `on` is absent. For a hat it is which way each member points, and the
#: game's own data says that. For an axis it is which part of the stick.
#: Both are in the needs file, and neither is a judgement a screen can
#: improve.
DESCRIBED = (
    ('suits', 'job', 'job', 'always'),
    ('urgency', 'band', 'band', 'always'),
    ('shape', 'shape', 'shape', 'always'),
    ('device', 'device', 'device', 'always'),
    ('finger', 'finger', 'finger', 'always'),
    ('held', 'held', 'flag', 'always'),
    ('rapid', 'rapid', 'flag', 'always'),
    ('by_feel', 'by feel', 'flag', 'always'),
    ('costly', 'costly', 'flag', 'always'),
    ('rests', 'rests', 'rests', 'axis'),
    ('invert', 'inverted', 'flag', 'axis'),
    ('on', 'on', 'on', 'moves'),
)


def _said(need, field):
    """One field of a description, as the form shows it.

    A value the program proposed carries `MARK[PROPOSED]`. That is the
    same `?` a placement nobody has accepted wears, and it says the same
    thing: nobody has confirmed this.

    Answering the row takes the mark off. `Review.say` drops the field
    from `Need.guessed`.
    """
    got = getattr(need, field, None)
    if got is None or got == '':
        return NOTHING
    said = (', '.join(str(w) for w in got) if field == 'on'
            else _as_said(got, field))
    if field in need.guessed:
        return f'{said} {MARK[PROPOSED]}'
    return said


def _applies(when, need):
    """Is this row a question for this need?

    `on` is three questions under one name. For an axis it is which part
    of a control the axis is. For a family it is which way each member
    points. For a button with one binding it is nothing, because a lone
    press has no direction to choose.
    """
    if when == 'always':
        return True
    if when == 'axis':
        return need.takes == corneeds.AXIS
    return need.takes == corneeds.AXIS or len(need.bindings) > 1


def _ways(need, ctrl):
    """The words `on` may take for this need: the map's own.

    For an axis, which part of the control it is. Those are the roles the
    device's axes answer to.

    For a family, the direction words `[directions]` accepts, plus
    whatever the control it sits on calls its own positions. A trigger
    says `first` and `second`, and no table of compass words covers
    that.
    """
    if need.takes == corneeds.AXIS:
        return ('x', 'y', 'z')
    said = list(corneeds.RULES['directions'])
    if ctrl is not None:
        said += [w for w in (ctrl.direction(b)
                             for b in ctrl.bindable_buttons)
                 if w and w not in said]
    return tuple(said)


def _pick_on(tui, rv, need):
    """Which way each member of a family points. True where something
    changed.

    An axis asks once: which part of the control it is. A family asks per
    member, in the order the bindings are in. That order IS which button
    gets which, and `slots_for` reads them one to one.

    The names come from the game's own vocabulary, so this reads as the
    four commands of a four-way switch and not as four hashes.

    Two members on one word is shown and not refused. The allocator gives
    up on the lot and hands out presses in order, and a seed that read
    `AFT` and `DOWN` both as `down` leaves a switch in that state.
    """
    names = {a.id: a.name for a in rv.catalogue}
    p = rv.at.get(need)
    ctrl = p.ctrl if p is not None else None
    ways = _ways(need, ctrl)
    if need.takes == corneeds.AXIS:
        rows = [(MINE if (need.on or ('',))[0] == w else 'plain', w)
                for w in ways]
        got = tui.choose(_FORM % need.what, rows,
                         head=[('meta', 'on'), ('plain', '')])
        if got is None:
            return False
        rv.say(need, 'on', (ways[got],))
        return True
    slots = [[names.get(b.action, b.action) for b in slot]
             for slot in need.bindings]
    wide = max((len(', '.join(s)) for s in slots), default=0)
    at, said = 0, False
    while True:
        was = list(need.on or ()) + [''] * len(slots)
        rows = [('plain', f'{", ".join(s)[:wide]:{wide}}  '
                 + (was[i] or NOTHING)) for i, s in enumerate(slots)]
        got = tui.choose(_FORM % need.what, rows, index=at,
                         head=[('meta', 'on'), ('plain', '')])
        if got is None:
            return said
        at = got
        rows = [(MINE if was[at] == w else 'plain', w) for w in ways]
        pick = tui.choose(_FORM % need.what, rows,
                          head=[('meta', ', '.join(slots[at])),
                                ('plain', '')])
        if pick is None:
            continue
        now = list(need.on or ()) + [''] * (len(slots) - len(need.on or ()))
        now[at] = ways[pick]
        rv.say(need, 'on', tuple(now))
        said = True


def _choices(need, kind):
    """[(value, what it means)] -- the closed list behind one field."""
    if kind == 'job':
        says = corneeds.RULES['jobs']
        return [(k, says[k]) for k in corneeds.JOBS]
    if kind == 'band':
        return [(i, '') for i, _n in enumerate(corneeds.URGENCY_NAME)]
    if kind == 'shape':
        subs = corneeds.RULES['shapes']
        return [(k, ', '.join(list(subs[k])[1:])) for k in subs]
    if kind == 'flag':
        return [(True, ''), (False, '')]
    if kind == 'device':
        return [(r, '') for r in sorted(devmap.load().ROLES_ON_A_DESK)]
    if kind == 'finger':
        dm = devmap.load()
        return [(f, '') for f in sorted(set(dm.FINGERS) - {dm.HAND})]
    return [(r, '') for r in corneeds.RESTS]


def _pick_said(tui, need, field, label, kind):
    """One answer about what a function is. None where you changed your
    mind.

    The same box as the form it was opened from, with the field in the
    head and not in a sentence of its own. You pressed RETURN on that
    row, and the row is still the question.

    A job carries what it covers. The difference between `flight` and
    `systems` is a judgement, and `[jobs]` is where that is written down.
    The rest are words that say themselves.
    """
    rows = _choices(need, kind)
    was = getattr(need, field, None)
    wide = max(len(str(v)) for v, _m in rows)
    lines = [(MINE if v == was else 'plain',
              f'{_as_said(v, field):{wide}} {m}'.rstrip())
             for v, m in rows]
    # Taking an answer back is a choice like any other, and the job is
    # the answer you most want back. It is the only field that is either
    # said or not said, and a word picked by mistake makes the row look
    # described.
    #
    # Not a flag. `held` is yes or no, and a third state is a fact
    # nothing has a term for. Not the band or the shape either: every
    # need has those and the file requires them.
    clearable = kind not in ('flag', 'band', 'shape')
    if clearable:
        lines.append((MINE if was in (None, '') else 'plain', NOTHING))
    got = tui.choose(_FORM % need.what, lines,
                     head=[('meta', label), ('plain', '')])
    if got is None:
        return None, False
    if clearable and got == len(rows):
        return None, True
    return rows[got][0], True


def _as_said(value, field):
    """A value as the screen spells it."""
    if field == 'urgency':
        return corneeds.URGENCY_NAME[value]
    if value is True:
        return 'yes'
    if value is False:
        return 'no'
    return str(value)


#: The form's own title, and the title of every question inside it. The
#: question is which row you are on, and the row is on the screen.
_FORM = 'What is "%s"?'


def _describe(tui, rv, need):
    """The form behind `J`: what this function is, field by field.

    Everything the scorer reads about a function except where it ended
    up, in one place, each answer out of the closed list that scores it.

    One key per field runs out of keys. A screen where `J` asks the job
    and nothing asks the band, the shape or the hand leaves a game whose
    needs were worked out from its command names with no way to correct
    them.
    """
    at, changed = 0, False
    while True:
        rows = [(f, label, kind) for f, label, kind, when in DESCRIBED
                if _applies(when, need)]
        wide = max(len(label) for _f, label, _k in rows)
        lines = [('plain', f'{label:{wide}}  {_said(need, f)}')
                 for f, label, _k in rows]
        got = tui.choose(_FORM % need.what, lines, index=at)
        if got is None:
            # On the way out. The form is about what the function IS and
            # the proposals are about where things sit, and four of these
            # nine fields are scored. A description you corrected under a
            # plan nobody asked again is a screen answering the question
            # you had before.
            if changed:
                rv.plan_again()
            return
        at = got
        field, label, kind = rows[got]
        if kind == 'on':
            # Its own walk: one question per member, with the member
            # named by the game rather than numbered.
            changed = _pick_on(tui, rv, need) or changed
            continue
        value, said = _pick_said(tui, need, field, label, kind)
        if said:
            rv.say(need, field, value)
            changed = True


def _pick_overlay(tui, rv):
    """Which overlay to lay this out to. None where you changed your
    mind.

    `no overlay` is a choice like any other and it sits with the rest. It
    is not a second keystroke: laying one on and taking it off are the
    same question.
    """
    known = coverlay.names()
    on = rv.overlay()
    # By the file's own stem, and without reading one of them. Loading
    # each file and comparing display names lets an unreadable overlay
    # anywhere in the directory take the screen down on `o`. This way a
    # bad file bites when you pick it, and `lay_over` catches it.
    rows = [(MINE if on is not None and k == on.called else 'plain', k)
            for k in known]
    rows.append(('plain' if on is not None else MINE, 'no overlay'))
    got = tui.choose('lay it out to...', rows)
    if got is None:
        return None, False
    return (None if got == len(known) else known[got]), True


def _ran(tui, title, lines):
    """Show what a subprocess said, and wait.

    A box, like every other view on this screen. A full screen of its own
    is a second way of putting words up.
    """
    tui.popup(title, [('plain', f'  {line}') for line in lines]
              + [('plain', ''),
                 ('plain', '  The vocabulary on screen is the one from '
                           'the start of this run.'),
                 ('plain', '  Quit and come back to read the new one.')],
              full=True)


def _on_a_row(needs):
    """{action id: the row that binds it}.

    A row is not a binding. Elite shows 49 rows and binds 76 actions,
    because one row carries a hat's four directions, its press, and the
    buggy's command beside the ship's. The list names the rows and the
    other 27 actions are inside them, a row at a time, in `BINDS`.

    So this screen is the only one that holds all 76, and the name is
    what it was missing: which row has this.

    `push` counts. The press of a control is a binding like any other.
    Read off `bindings` alone, an action on a push came back free, and
    this screen then offered a second row for a thing that has one.
    Measured on Elite: `UI_Select` sits on the press of a hat and was the
    one action of 76 that this called free.

    First one wins. Two rows on one action is a thing to see rather than
    a thing to hide, and the vocabulary screen is where you see it.
    """
    out = {}
    for n in needs:
        for slot in list(n.bindings) + [n.push or []]:
            for b in slot or ():
                out.setdefault(b.action, n.what)
    return out


def _browse(scr, tui, rv):
    """The whole vocabulary, to take something out of. Returns a line.

    The list this screen is built around holds what somebody asked for.
    This holds what the game accepts: 147 rows against 5856 across the
    family.

    Windowed rather than sized to content. MSFS ships 3111 actions, and a
    box that drops what does not fit, in silence, is worse than no box.

    `page` is the body: every row between the lid and the sill. The draw
    took one fewer than that and the scroll clamped to `page`, so the
    cursor could sit on the row under the last one drawn. Moving down
    then kept it there, and the highlighted action was invisible for the
    whole way down a 440-row list.
    """
    order = [a for _cat, group in cactions.grouped(rv.catalogue)
             for a in group]
    bound = _on_a_row(rv.needs)
    find, sel, top, said = '', 0, 0, ''
    while True:
        h, w = scr.getmaxyx()
        shown = [a for a in order if _hits(a, find)]
        page = max(1, h - 2)
        sel = max(0, min(sel, len(shown) - 1))
        top = max(0, min(top, max(0, len(shown) - page)))
        if sel < top:
            top = sel
        elif sel >= top + page:
            top = sel - page + 1

        scr.erase()
        right = (f'filter {find!r} · {len(shown)} of {len(order)}'
                 if find else f'{len(order)} the game accepts')
        _put(scr, 0, 0, ctui.lid(w, rv.source or 'vocabulary', right),
             tui.theme.head)
        # The sides the corners promise. `lid` and `sill` end in `╭╮╰╯`,
        # so a box drawn without the sides reads as an unfinished one.
        for row in range(1, h - 1):
            _put(scr, row, 0, ctui.V, tui.theme.head)
            _put(scr, row, w - 1, ctui.V, tui.theme.head)
        for i, a in enumerate(shown[top:top + page]):
            y = 1 + i
            mark = '+' if a.id in bound else ' '
            tone = (tui.theme.sel if top + i == sel
                    else tui.theme.mine if a.id in bound else tui.theme.plain)
            _put(scr, y, 2, f'{mark} {a.name[:38]:38}', tone)
            # The row that has it, at the right, where the eye reads
            # down one column. The id keeps what is left, because a
            # reader who wants the id is checking spelling and a reader
            # who wants the row is finding where a thing went.
            held = bound.get(a.id, '')
            mine = max(50, w - 2 - len(held)) if held else w - 1
            _put(scr, y, 43, f'{a.kind:6} {a.id}'[:mine - 44],
                 tui.theme.meta)
            if held:
                _put(scr, y, mine, held[:w - 1 - mine], tui.theme.mine)
        _put(scr, h - 1, 0,
             ctui.sill(w, ('↑↓ move', '↵ add', 'f filter', 'h reread',
                           'D forget', 'q back'),
                       f'{sel + 1}/{len(shown)}' if shown else 'none',
                       note=said),
             tui.theme.note if said else tui.theme.head)
        scr.refresh()

        k = tui.key(0.5)
        if k is None:
            continue
        said = ''
        if k in ('esc', 'q', 'Q'):
            return ''
        elif k in ('up', 'k'):
            sel -= 1
        elif k in ('down', 'j'):
            sel += 1
        elif k == 'g':
            sel = 0
        elif k == 'G':
            sel = len(shown)
        elif k == ' ':
            sel += page
        elif k in ('f', 'F'):
            got = _ask(scr, tui, 'filter: ', find)
            if got is not None:
                find, sel, top = got, 0, 0
        elif k == 'h' and rv.harvest is not None:
            _ran(tui, 'reading the game again', rv.harvest())
        elif k == 'D' and rv.drop is not None:
            # Typed, not a keystroke. This is the one destructive thing
            # on this screen, and a finger landing on D beside the f it
            # was going for is not enough.
            sure = _ask(scr, tui, "type 'drop' to forget the vocabulary: ")
            if (sure or '').strip() == 'drop':
                _ran(tui, 'forgetting what was read', rv.drop())
            else:
                said = 'left alone'
        elif k == 'enter' and shown:
            where = _pick_category(scr, tui, rv)
            if where:
                said = rv.promote(shown[sel], where)
                bound = _on_a_row(rv.needs)


# ------------------------------------------------------------------ the loop

def _loop_keys():
    """The source of the key loop, for the collision check above.

    Read, not listed. A list of keys beside the loop is a second place to
    forget, and this only has to be right about which letters appear in
    the loop.
    """
    import inspect
    return inspect.getsource(_loop)


def run(layout, title, subtitle='', describe=None, write=None, paths=(),
        catalogue=(), source='', save=None, harvest=None, drop=None,
        rules=None, rebuild=None, game='', offers=(), add=None,
        guess=None):
    """Show the need list, let it be filled, write what has a control.

    Returns what was written, or the `Adapter` an offer asked to reopen
    on. A game's own key may change what the screen is OF: DCS lays out
    one aircraft at a time, and that is a different list, a different
    store and a different kneeboard. So it is a new screen.
    """
    sticks = Sticks(layout)
    rv = Review(layout, title, subtitle, describe, paths, catalogue,
                source, save, harvest, drop, rules, rebuild, game, offers,
                add, guess)
    try:
        return curses.wrapper(_loop, rv, write, sticks)
    finally:
        sticks.close()


def _loop(scr, rv, write, sticks):
    tui = ctui.setup(scr)
    state = {'top': 0}
    #: Which panel the arrows move in. Beside `sel` rather than in
    #: `state`, which holds the scroll offsets and is all integers:
    #: where you are is loop state, and `_draw` takes both.
    focus = LIST
    rows = rv.rows()
    sel = next((i for i, r in enumerate(rows) if r.selectable), 0)
    written = None

    def move(step):
        nonlocal sel
        pick = [i for i, r in enumerate(rv.rows()) if r.selectable]
        if not pick:
            return
        here = min(range(len(pick)), key=lambda j: abs(pick[j] - sel))
        sel = pick[max(0, min(len(pick) - 1, here + step))]

    # Opened once, here, rather than on the first capture. The corner
    # box answers "which one did I just press", and a box that opened a
    # device the first time you pressed one would miss that press.
    #
    # A desk with nothing plugged in costs one walk of
    # `/proc/bus/input/devices` and answers None for the rest of the
    # session. `Sticks.why` says what it found, and `↵` is where that
    # sentence belongs: it is the key that needs a device.
    sticks.open()
    #: What was touched last, and when. The box is up for `HOLD` and
    #: gone after, which is what says it is about the moment.
    touch, at = None, 0.0

    while True:
        rows = rv.rows()
        if sel >= len(rows) or not rows[sel].selectable:
            move(0)
        got = sticks.touched()
        if got is not None:
            touch, at = got, time.monotonic()
        # One answer about the moment, for both halves of it. The box
        # names what is under the hand and the list underlines the rows
        # that sit there, so a press says where a function lives without
        # reading a column of control names.
        #
        # The rows are marked and the cursor is left alone. The cursor
        # is what `c`, `x` and `↵` act on, and a lever nudged by a
        # sleeve would move it under them.
        up = (touch if touch is not None and time.monotonic() - at < HOLD
              else None)
        _draw(scr, rv, sel, state, tui.theme, focus,
              lit=frozenset(rv.on_input(*up)) if up else frozenset())
        if up:
            tui.corner('pressed', rv.pressed(*up))
            scr.refresh()
        # A tick a reader can feel. At 0.5 s a press shows up half a
        # second after the thumb, which reads as the screen missing it.
        # One redraw is 1.1 ms over 45 rows, so twenty a second is 2% of
        # a core.
        k = tui.key(TICK)
        if k is None:
            continue
        # By kind, not by `selectable`. A heading is selectable and
        # carries no need, so every handler that wants a need gets None
        # and does nothing. A handler that acts on a GROUP asks for the
        # kind itself.
        here = rows[sel] if 0 <= sel < len(rows) else Row('gap', '')
        need = here.need if here.kind == 'need' else None
        group = here.group if here.kind == 'head' else None

        if k in ('q', 'Q', 'esc'):
            if rv.unsaved and rv.save is not None:
                # The same box `s` puts up. Leaving is then not a second
                # way of saving with its own idea of what it writes.
                # sim-device-map does this on the way out.
                _save(scr, tui, rv)
            return written
        if k in ('tab', 'shift-tab'):
            # The panels that are drawn, which is what `_layout` just
            # decided: a short column has no free list and a stacked
            # screen has nowhere to put one. Asked of the layout rather
            # than remembered, so a terminal somebody resized cannot
            # leave the focus on a panel that is no longer there.
            _, _side_r, _free_r = _layout(*scr.getmaxyx()[::-1])
            panels = [LIST, DETAIL] + ([FREE] if _free_r else [])
            at = panels.index(focus) if focus in panels else 0
            focus = panels[(at + (1 if k == 'tab' else -1)) % len(panels)]
            rv.status = ''
        elif k in ('up', 'k', 'down', 'j', 'g', 'G'):
            # The arrows move inside whichever panel the focus is on.
            # Every other key goes on acting on the row under the cursor
            # in the list, so `c` accepts that row whatever the arrows
            # are pointed at.
            #
            # One branch for all six. `STEP` answers the four that move
            # by one, and the two that go to an end fall through its
            # `or`, because a step of one is truthy and a miss is 0.
            step = STEP.get(k, 0) or END[k] * (len(rows) + 1)
            if focus == LIST:
                move(step)
            else:
                # Clamped in `_scroll`, where the height and the length
                # are both known. This only has to say which way.
                state[focus] = max(0, state.get(focus, 0) + step)
            rv.status = ''
        elif k == 'c' and need is not None:
            rv.status = rv.confirm(need)
            move(+1)
        elif k == 'C':
            rv.status = rv.confirm_all()
        elif k == 'p' and need is not None:
            rv.status = rv.propose(need)
        elif k == 'P':
            rv.status = rv.propose_all()
        elif k == 'Z' and rv.guess is not None:
            # Replanned after, because `device` is a wish the allocator
            # reads. A field filled here moves rows, and the old places
            # under the new judgements are a screen telling you
            # something untrue.
            rv.status = rv.guess()
            rv.touched('the program proposed what things are')
            rv.plan_again()
        elif k == 'x' and need is not None:
            rv.status = rv.clear(need)
        elif k == 'X':
            rv.status = rv.clear_all()
        elif k == 'enter' and need is not None:
            rv.status = _by_press(scr, tui, rv, need, sticks)
        elif k in ('l', 'L') and need is not None:
            rv.status = _by_hand(scr, tui, rv, need)
        elif k in ('f', 'F'):
            # Typed and confirmed: narrow to it. Confirmed with nothing
            # in it: show everything again. ESC: leave the filter as it
            # was.
            got = _ask(scr, tui, 'filter: ', rv.filter)
            if got is not None:
                rv.filter = got
                state['top'] = 0
                move(-len(rv.rows()))
                rv.status = (f'showing what matches {got!r}' if got
                             else 'showing everything')
        elif k in ('h', 'H'):
            # Every row at once, which is the one thing `→` cannot do.
            # Any row open means this shuts the lot: with some open and
            # some not, "all" is the answer that changes something.
            if rv.open_binds:
                rv.open_binds.clear()
            else:
                rv.open_binds.update(n for n in rv.needs if rv.binds(n))
            state['top'] = 0
            rv.status = ('showing what each one binds'
                         if rv.open_binds else 'binds hidden')
        elif k in ('left', 'right'):
            # A heading opens and shuts its whole group. A row opens and
            # shuts what it binds. Both are the same question asked of
            # the thing under the cursor, so both are the same key.
            want = k == 'right'
            if group:
                rv.shut.discard(group) if want else rv.shut.add(group)
                # The rows under it came or went, so where the heading
                # is has changed. The cursor stays on the heading: it is
                # what you just acted on and what acts again.
                sel = _head_of(rv, group, sel)
            elif need is not None:
                (rv.open_binds.add(need) if want
                 else rv.open_binds.discard(need))
                sel = _row_of(rv, need, sel)
        elif k == '?':
            tui.popup('help', KEYS + tuple(
                ('plain', f'  {key}           {word}')
                for key, word, _do in rv.offers))
        elif k in ('a', 'A') and rv.catalogue:
            rv.status = _browse(scr, tui, rv)
            state['top'] = 0
            move(-len(rv.rows()))
        elif k == 'R' and (group or need is not None):
            was = group or rv.group_of(need)
            got = _ask(scr, tui, f'rename {was!r} to: ', was)
            if got and got.strip() and got.strip() != was:
                rv.status = rv.rename(was, got.strip())
                sel = (_head_of(rv, got.strip(), sel) if group
                       else _row_of(rv, need, sel))
        elif k == 'r' and need is not None:
            where = _pick_category(scr, tui, rv)
            if where:
                rv.status = rv.refile(need, where)
                # The row has moved to another group, so the index it was
                # at means nothing. Every other shape change here resets
                # to the top, and that loses what you were doing.
                sel = _row_of(rv, need, sel)
        elif k in ('o', 'O'):
            want, said = _pick_overlay(tui, rv)
            if said:
                rv.status = rv.lay_over(want)
                # Every row may have moved, so the index it was at means
                # nothing. The need under the cursor is still a need.
                sel = _row_of(rv, need, sel) if need is not None else sel
        elif any(k == key for key, _w, _do in rv.offers):
            got = next(do for key, _w, do in rv.offers if key == k)(rv, tui)
            if not isinstance(got, str):
                # An Adapter: reopen the screen on it. That drops
                # everything this screen holds, so it asks first.
                # Changing aircraft is a way out of this screen, and the
                # other way out asks.
                if rv.unsaved and rv.save is not None:
                    _save(scr, tui, rv)
                return got
            rv.status = got
        elif k == 'i' and need is not None:
            rv.status = rv.turn_round(need)
        # `J`, because `j` is a step down the list and the step wins. The
        # chain answers `j` first, and this branch is then unreachable:
        # the sill advertises a key that does nothing.
        elif k == 'J' and need is not None:
            _describe(tui, rv, need)
        elif k in ('y', 'Y'):
            tui.popup('why a control is chosen',
                   rv.rules_lines(tui.inner()), full=True)
        elif k in ('m', 'M'):
            tui.popup('device map', rv.map_lines(),
                   full=True)
        elif k in ('s', 'S'):
            _save(scr, tui, rv)
        elif k in ('w', 'W'):
            written = _write(scr, tui, rv, write) or written
        elif k == ' ' and need is not None:
            # SPACE confirms, because that is the key a walk through the
            # list presses over and over.
            rv.status = rv.confirm(need)
            move(+1)


def _by_press(scr, tui, rv, need, sticks):
    """Assign by pressing the control.

    A box. `wait_input` reads `tui` only to notice ESC, so the prompt
    stays on screen while it blocks. Everything else that interrupts this
    screen is a box.
    """
    devices = sticks.open()
    if not devices:
        return (f'No stick answers: {sticks.why} Press l to pick from a '
                'list.')

    # The product, as the map and the detail panel name it. `d.name` is
    # the raw evdev string, and it carries a vendor and a firmware date.
    # That is noise here, and a second name for one stick on one
    # screen.
    known = rv.layout.devices
    lines = [('head', 'DEVICES')]
    lines += [('plain', f'  {d.role:9}  '
                        + (known[d.role].product if d.role in known
                           else d.name))
              for d in devices]
    axis = need.takes == corneeds.AXIS
    lines += [('plain', ''), ('head', 'WANTS'),
              ('plain', f'  {need.first_shape}'
                        + (f', {ctui.plural(need.wanted, "button")}'
                           if need.wanted > 1 else '')),
              ('plain', ''), ('head', 'MOVE' if axis else 'PRESS')]
    if axis:
        lines.append(('plain', '  the axis you want this on'))
    elif len(need.bindings) == 1 and not need.on:
        lines.append(('plain', '  the exact position you want it on'))
    else:
        lines += [('plain', '  any position'),
                  ('plain', '  the whole control is taken, bindings in its '
                            'own order')]
    tui.box(need.what, lines, tail='ESC leaves it as it is')
    ccapture.drain(devices, tui)

    # One key, and it reads whichever kind of input the row is for. An
    # axis need is answered by moving a lever and a button need by
    # pressing a button. Two keys for that is two code paths.
    got = ccapture.wait_input(devices, want_axis=axis, tui=tui)
    if got == 'skip':
        return f'{need.what} stays as it was.'
    dev, _kind, number, _sign = got
    ccapture.drain(devices, tui)

    return rv.took(need, dev.role, number)


def _by_hand(scr, tui, rv, need):
    """Choose a control for this need yourself."""
    fits = rv.fits(need)
    if not fits:
        return f'No free control has the shape {need.what} asks for.'
    labels = [('plain', f'{role:9} {c.label:30} {c.kind:9} '
                                f'{corneeds.reach_said(c)}')
              for role, c in fits]
    idx = tui.choose(f'{need.what} wants {need.first_shape}', labels)
    if idx is None:
        return f'{need.what} stays as it was.'
    role, ctrl = fits[idx]
    rv.assign(need, role, ctrl)
    return f'{need.what} -> {role}/{ctrl.label}  (yours)'


def _write_plan(rv, width):
    """What `w` is about to do, before it does it.

    The keystroke overwrites a game's configuration file. What it writes
    and where is what a reader wants to check, and printed afterwards it
    is too late to check.
    """
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    kept = rv.result()
    mine, prop, _unset = rv.counts()
    if rv.paths:
        say('head', 'FILES')
        for label, path in rv.paths:
            say('subhead', f'  {label}')
            for line in _fold(_tilde(str(path)), max(20, width - 4)):
                say('meta', f'    {line}')
        say('plain')
    say('head', 'PLAN')
    say('plain', f'  {ctui.plural(len(kept.placed), "binding")}')
    # Named, because they go into the same files. A plan that reads `0
    # bindings` over a write about to lay down nine axes is a box that
    # has not said what it does.
    if kept.on_axes:
        say('plain',
            f'  {ctui.plural(len(kept.on_axes), "axis", "axes")}')
    if mine:
        say(MINE, f'  {MARK[MINE]}{mine} {MARK_SAID[MINE]}')
    if prop:
        # Before the keystroke, not after it. `?` means you have not been
        # through them, and they go into the file either way. That is a
        # thing to learn while you can still say no.
        say(PROPOSED, f'  {MARK[PROPOSED]}{prop} {MARK_SAID[PROPOSED]}')
        say(PROPOSED, '  The write includes them.', lead='  ')
    return out


def _save_plan(rv, width):
    """What `s` is about to keep, before it keeps it.

    The counts. A save writes the whole list, and the question a reader
    has is how much of that list is theirs now.
    """
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    mine, prop, unset = rv.counts()
    say('head', 'KEEPING')
    say('plain', f'  {ctui.plural(len(rv.needs), "entry", "entries")}')
    if mine:
        say(MINE, f'  {MARK[MINE]}{mine} {MARK_SAID[MINE]}')
    if prop:
        # They go in the file either way. That is a thing to learn while
        # you can still say no.
        say(PROPOSED, f'  {MARK[PROPOSED]}{prop} {MARK_SAID[PROPOSED]}')
        say(PROPOSED, '  The save includes them.', lead='  ')
    if unset:
        say('unset', f'  {unset} {MARK_SAID[UNSET]}')
    # And what it is that the files do not have. The counts answer how
    # much is being written. Somebody who sees this box on the way out
    # after pressing `s` is asking what changed since, and twelve keys
    # can have changed it. One of those keys is a button read off the
    # stick while the box that asked for it was on screen.
    if rv.since:
        say('plain')
        say('head', 'SINCE THE LAST SAVE')
        say('meta', f'  {rv.since}')
    return out


def _save(scr, tui, rv):
    """Keep what was decided. Asked, because these are the only copies."""
    if rv.save is None:
        rv.status = ('this game derives its needs, so there is nothing to '
                     'write them to')
        return
    if not rv.unsaved:
        rv.status = 'Nothing has changed since the last save.'
        return
    if not tui.confirm('save', _save_plan(rv, tui.inner())):
        rv.status = 'The save did not happen.'
        return
    rv.status, _still = rv.keep()


def _write(scr, tui, rv, write):
    if write is None:
        rv.status = 'This game has no writer on this screen yet.'
        return None
    kept = rv.result()
    # The axes count as something to write. Clear every button and the
    # layout still says which lever is pitch, which is throttle and
    # which way round they run. That is nine rows for the Hornet, and a
    # check on BUTTONS alone refuses to write any of it. One list, so the
    # question is whether anything is placed.
    if not kept.placed:
        rv.status = 'No row has a control. There is nothing to write.'
        return None
    if not tui.confirm('write', _write_plan(rv, tui.inner())):
        rv.status = 'The write did not happen.'
        return None
    # Every writer reports by printing, and some warn on stderr. Under
    # curses that lands on the screen being drawn, so it is caught here
    # and shown afterwards. Six writers returning text they already print
    # is the other way, and it costs more.
    out = io.StringIO()
    written = None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            extra = write(kept)
        written = kept
    except SystemExit as e:
        extra = [f'refused: {e}']
    except (RuntimeError, OSError, ValueError) as e:
        extra = [f'ERROR: {e}']
    said = [('meta', ln) for ln in out.getvalue().splitlines()]
    # The two that matter, in the tone that says so. A refusal or an
    # error is one line in whatever a writer printed, and finding that
    # line is otherwise the reader's problem.
    said += [('unset' if str(ln).startswith(('refused:', 'ERROR:'))
              else 'plain', str(ln)) for ln in (extra or [])]
    tui.popup('written' if written else 'not written',
           said or [('meta', 'The writer said nothing.')])
    rv.status = ('The files are written.' if written
                 else 'The write did not happen.')
    return written

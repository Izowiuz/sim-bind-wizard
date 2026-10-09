"""Walk the need list, fill it from the plan or by hand, then write it.

Every planner could already print its layout and write all of it. Between
those two there was nothing: no way to take most of a plan and not the rest,
and nothing at all to do about a need the allocator could not place.

DCS has had the answer since before this core existed -- `run_table` in its
capture wizard -- and this is that table, generalised. Its shape is worth
stating, because none of it is the obvious design:

    the rows are NEEDS, not bindings   a need with nothing on it is still a
                                       row, and clearing one leaves it where
                                       it was rather than making it vanish
    three states, not two              (unset) · proposed · yours
    proposing fills the GAPS only      it never overwrites what you chose,
                                       which is what makes "propose all" safe
                                       to press at any moment
    choosing it yourself means yours   no confirming a decision you just made
    `?` is advisory, not a filter      a proposal you never looked at is still
                                       written; the mark says you did not
                                       check it, not that it is switched off

DCS keeps that state in a results file, one dict per binding with a `proposed`
flag. Nothing else in the family has such a file, and inventing one per game
to get a review screen would be five more formats to keep in step -- so here
it lives for the length of the session, keyed by the need.

Rows group by urgency, not by device. Urgency belongs to the need, so a row
keeps its place when you clear it or move it to another control; grouping by
device made rows jump between sections while you worked.

A game supplies only what the core cannot know: `describe(placement)` turning
its own payload into `[(which part of the control, what it does)]`.

    review.run(layout, 'X4 Foundations', 'VIRPIL',
               describe=..., write=lambda layout: ...)

`write` is handed a `Layout` narrowed to the needs that ended up with a
control, which is why `Layout.but()` exists and why the two adapters that
derived their writer's tables inside `build()` had to stop.
"""

import collections
import contextlib
import curses
import io
import os
import re
import textwrap

from core import actions as cactions
from core import capture as ccapture
from core import needs as corneeds
from core import overlay as coverlay
from core import solvers as csolvers
from core import tui as ctui

#: What a row can be. `MINE` covers both "I confirmed the proposal" and "I
#: chose this myself": once you have looked at it, where it came from stops
#: mattering.
#:
#: They are also tone names in `core.tui.Theme`, which is not a coincidence
#: and is worth keeping: a state can be handed straight to the theme, so the
#: row for a need and the control that need sits on cannot drift apart.
UNSET, PROPOSED, MINE = 'unset', 'proposed', 'mine'

MARK = {UNSET: ' ', PROPOSED: '?', MINE: '+'}

#: What each mark means, in words, once. Three screens name them -- the
#: help, the map's legend and the detail panel -- and between them they had
#: grown three phrasings of the same three states.
#:
#: "proposed, not accepted" rather than "not checked": `+` is reached by
#: accepting (`c`) or by assigning it yourself, so `?` is the absence of a
#: decision, not of a glance. Neither gates anything -- `placements()` hands
#: a writer both -- so these say what you have not done, not what will not
#: happen.
MARK_SAID = {
    MINE: 'assigned by you',
    PROPOSED: 'proposed, not accepted',
    UNSET: 'unassigned',
}


class Row:
    """One line of the table. `kind` decides what it answers to."""

    def __init__(self, kind, text, need=None, group=None):
        self.kind = kind        # 'head' | 'need' | 'bind' | 'gap'
        self.text = text
        self.need = need
        #: on a heading, the group's real name. `text` is upper-cased for
        #: the screen and `rename` needs what the needs actually hold --
        #: 'IN A TURN' is not it.
        self.group = group

    @property
    def selectable(self):
        # A heading is a thing you act on: `R` renames it. It used to be
        # the one thing on the screen you could read and not touch, so a
        # category was renamed by standing on one of its members.
        #
        # A `bind` is the answer to the row above it, not a thing you put
        # anywhere, and a `gap` answers nothing -- moving skips both.
        return self.kind in ('need', 'head')


class Review:
    """What the reviewer has decided so far.

    All of it works without a terminal, and every key the screen answers to is
    one call on this -- which is the point of keeping them apart.
    """

    def __init__(self, layout, title, subtitle='', describe=None,
                 paths=(), catalogue=(), source='', save=None,
                 harvest=None, drop=None, rules=None, rebuild=None,
                 game='', offers=()):
        self.title = title
        #: `bind-wizard.py`'s own word for this game. Only the overlay needs
        #: it: a rule naming `what` belongs to one game, and two games can have
        #: a function of the same name wanting different things.
        self.game = game
        self.subtitle = subtitle
        self.describe = describe or (lambda p: [])
        #: [(label, path)] the game supplies: where it found the install, the
        #: file it will write. The core cannot know these -- every game hides
        #: its config somewhere else -- and a screen that will overwrite a
        #: file should say which file.
        self.paths = list(paths)
        #: Everything the game accepts a binding for. The list below is
        #: what somebody asked for out of it -- 147 rows across the family
        #: against 5856 actions -- and until this was passed in, nothing
        #: on this screen knew the rest existed.
        self.catalogue = list(catalogue)
        #: Which file it was read out of. The vocabulary screen puts it on
        #: its top bar: after `h` re-reads the game or `D` forgets it, the
        #: question that screen raises is which file is in front of you.
        self.source = source
        #: How the judgements get written down. A game that derives its
        #: needs has none, and the screen has to cope rather than raise:
        #: it cannot help, and taking the review down over it would be
        #: worse than saying so.
        self.save = save
        #: Something has changed and the files do not have it yet. The
        #: frame says `unsaved` while this is true and `s` clears it, the
        #: way the capture wizard in sim-device-map does.
        self.unsaved = False
        #: What that something was, for the box that asks about it.
        self.since = ''
        #: Reading the game again, and forgetting what was read. Both are
        #: `bind-wizard.py`'s own verbs run as subprocesses; neither can touch
        #: the judgements, because `drop` walks `CACHE` and the judgements are
        #: deliberately not in it.
        self.harvest = harvest
        self.drop = drop
        #: The scoring this game plays by: the core's, with the game's
        #: over the top. The screen that explains the allocator has to
        #: read the same set the allocator ran on, or it is explaining
        #: somebody else's -- DCS tightens a band.
        self.rules = rules or corneeds.RULES
        self.status = ''
        #: what `f` narrowed the action level to. Matched against the
        #: need's own name, not against what it binds: the question `f`
        #: answers is "where is the row for X".
        self.filter = ''
        #: whether `h` is showing what sits under each action. Off to
        #: start with: the list of what a game can do is the thing you come
        #: here to read, and a plan that binds two actions to a button puts
        #: two lines under every row of it before you have asked.
        self.show_binds = False
        #: Laying the whole thing out again, for `o`. A game that cannot
        #: -- there is none, but the argument is optional like `save` --
        #: says so rather than raising: the screen cannot help, and taking
        #: the review down over it would be worse than a sentence.
        self.rebuild = rebuild
        #: [(key, word, what it does)] a game puts on this screen itself.
        #: DCS lays out one aircraft module at a time and had a menu of
        #: its own to change which; a game that needs a key of its own
        #: asks for one rather than keeping a whole screen for it.
        #:
        #: The callable is handed this Review and the `tui`, and answers
        #: with a line for the status bar, or with an Adapter to reopen on --
        #: changing module is a different list of needs, a different
        #: store and a different kneeboard, so it is a new screen rather
        #: than a redraw of this one.
        taken = set(''.join(re.findall(r"'([a-zA-Z])'", _loop_keys())))
        for key, word, _do in offers:
            if key in taken:
                # Loudly, at construction: a game's key that the family
                # already holds either shadows the family's or is dead,
                # and which of the two depends on the order of an elif
                # chain. Neither is a thing to find out at the keyboard.
                raise ValueError(
                    f'{key!r} ({word}) is a key this screen already '
                    f'answers to. Taken: {", ".join(sorted(taken))}')
        self.offers = list(offers)
        self.relay(layout)

    def relay(self, layout):
        """Take a freshly allocated layout and show that instead.

        Four fields and nothing else, which is why this is small enough to
        call from a keystroke: the `Need` objects are the same objects, so
        everything you decided about them -- what you chose, what you
        accepted, what you filed them under, what job they do -- is on
        them already and comes through untouched.

        """
        self.layout = layout
        #: what the planner worked out, per need. A need it could not place
        #: has none, and `p` on that row has nothing to offer.
        self.plan = {p.need: p for p in layout.placed}
        #: every need the planner was asked about, placed or not --
        #: axes among them, in the same list, because an axis is a
        #: function wanting an input like every other row here.
        self.needs = ([p.need for p in layout.placed]
                      + list(layout.unplaced))
        #: where each need sits now, and how it got there
        self.at = {n: self.plan.get(n) for n in self.needs}
        # Who put it there, not merely that something did. A placement
        # the allocator made from `yours` carries `how == 'yours'`, so a
        # choice you made last week opens green and the planner's opens
        # purple -- which is what the mark was always for and what it
        # could not do while it was rebuilt from nothing each time.
        self.mark = {n: self._came_by(n) for n in self.needs}

    def desk(self):
        """Which rig this layout is for, or '' if nothing says."""
        return corneeds.desk_of(self.layout)

    def overlay(self):
        """The overlay this layout was laid out to, or None."""
        return corneeds.OVERLAY

    def wishes(self):
        """(kept, of how many) for the overlay on, or None if none is."""
        got = corneeds.OVERLAY
        if got is None:
            return None
        kept, broken, _lost = got.kept(self.layout)
        return kept, kept + broken

    def lay_over(self, name):
        """Put an overlay on -- or take every one off -- and plan again.

        Returns a line. The count comes with it, because "f-18 is on" and
        "f-18 got 19 of its 34 wishes" are different facts and only the
        second one tells you whether to keep it.
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

    def _came_by(self, need):
        """Who put this where it is, as a mark.

        The mark was rebuilt from nothing on every open -- anything placed
        was `?` -- so an evening spent walking the list came back purple
        and in the planner's order. It now reads what the placement says
        about itself.

        `accepted` is checked against WHERE it landed, not merely that it
        landed: you said yes to a control, not to a row. If the desk or
        the needs have changed since and the allocator has moved it, the
        row goes back to `?`, which is the one moment the mark has
        something to tell you.
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

        The axes included, by being rows like any other.
        """
        m = [self.mark[n] for n in self.needs]
        return m.count(MINE), m.count(PROPOSED), m.count(UNSET)

    def binds(self, need):
        """[(part of the control, what it does)] -- the game's own answer.

        `describe` is the adapter's hook and this is the only caller, so it
        is also the only place that has to cope with a need sitting on
        nothing.
        """
        p = self.at[need]
        return self.describe(p) if p is not None else []

    def where(self, need):
        """The one-line answer to 'what is this on?'.

        The lever's own label for an axis, not the control's: three of
        the stick's axes are `Main stick` and only one of them is pitch.
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

        The one thing about an axis you might want to change from a
        screen: which end is which is a fact about your hardware and your
        wrist, not about the game. DCS had this on its own screen and the
        family had it nowhere.
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
        """[(role, control)] with every button still spare.

        Worked out from what is assigned rather than read off the layout,
        because clearing a need hands its control back and assigning one takes
        a control the allocator had left over.
        """
        busy = self.occupied()
        return [(role, ctrl)
                for role, dev in sorted(self.layout.devices.items())
                for ctrl in dev.groups(bindable=True)
                if not any((role, b) in busy for b in ctrl.bindable_buttons)]

    def fits(self, need):
        """Free controls this need could live on.

        The shape and capacity tests `score()` makes, without the reach
        tables: someone placing a thing by hand has already decided it is
        worth the reach, and being told "nothing fits" when four controls do
        would be the tool arguing with them.
        """
        return [(role, c) for role, c in self.free()
                if c.kind in need.shapes
                and len(c.bindable_buttons) >= need.wanted]

    def who_has(self, role, ctrl):
        """Every need sitting on this control right now, in row order.

        A list, and it answered with the first one it found. A control
        carries more than the need that took it: the borrow pass hands a
        leftover need one spare button of a control something else owns,
        so X4's bottom thumb hat holds Weapon group AND three borrowed
        needs. The map named one of the four and read as if the other
        three were nowhere -- on the screen you open to find out what is
        still spare. Thirteen controls across the five games are like
        this.
        """
        return [need for need in self.needs
                if (p := self.at[need]) is not None
                and p.role == role and p.ctrl is ctrl]

    def why_not(self, need, role, ctrl):
        """None if this need may go on this control, else the reason.

        The by-hand list can only offer what fits, so it never needs this.
        Pressing a button can land anywhere -- on a lever, on a hat with too
        few positions, on something another need already has -- and answering
        "no" without saying why is the worst of the three.
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

    def took(self, need, role, button):
        """Assign from the input somebody moved, or say why not.

        Everything that happens after `capture.wait_input` returns, in one
        call with no terminal in it -- so the only part of pressing a control
        that cannot be tested is reading the kernel, which two shipping
        wizards already do with this same code.

        `button` is an axis index where the need wants an axis: the
        capture reads whichever kind the row is for, and one key means
        one thing on every row.
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
                # Already yours and already this lever. Saying `unsaved`
                # over a keystroke that changed nothing is how a save box
                # comes up on the way out to somebody who has just saved
                # -- and with a stick on the desk this is the easiest one
                # to press by accident, because the lever you nudge is
                # the one it is on.
                return f'{need.what} is yours, and it is already here.'
            self.assign(need, role, ctrl, axis=button)
            return f'{need.what} -> {role}/{got.label}  (yours)'
        ctrl = self.control_at(role, button)
        no = self.why_not(need, role, ctrl)
        if no:
            # `why_not` answers with a fragment: the control is the
            # subject of it, and this puts the row's name in front.
            return f'{need.what} cannot go there: {no}.'
        # `why_not` answers 'not in the device map' first of all, so a
        # control that got past it exists. Saying so is cheaper than
        # hoisting the check and keeping its sentence in two places.
        assert ctrl is not None
        p = self.assign(need, role, ctrl, button)
        said = f'{need.what} -> {role}/{ctrl.label}'
        if len(need.bindings) == 1 and p.slots:
            landed = p.slots[0][0]
            said += f' · {ctrl.direction(landed) or f"button {landed}"}'
            if landed != button:
                said += (' — not where you pressed: that contact carries no '
                         'binding' if button not in ctrl.bindable_buttons
                         else ' — its own direction')
        return f'{said}  (yours)'

    def devices(self):
        """[(role, Device)] in a fixed order, for the header and the map."""
        return sorted(self.layout.devices.items())

    def device_line(self):
        """`stick R-VPC Stick WarBRD-D · throttle L-VPC VMAX...`

        A role is not a device. `devmap.by_role` keys on the map's `kind`, so
        a second stick makes you choose between them with SIM_DEVICE_ROLES --
        and once you have, a row reading "stick" no longer says which one you
        chose. The header carries the answer so no row has to.
        """
        return '   '.join(f'{role} {d.product}' for role, d in self.devices())

    def map_lines(self):
        """The device map as the review sees it, with what sits on each
        control -- the answer to "is that really a hat, and what is on it".

        `[(tone, text)]` rather than bare lines. The tone is the one thing
        only this method knows, and naming it here is what keeps the two
        screens honest: a control wears the state of the need on it, and
        that state is the same word the table draws its row with.

        Every control also carries the table's own `?`/`+` mark. Colour was
        the only thing saying which controls were spoken for, and a colour
        nobody has been taught is just some of the rows being a different
        colour -- so the mark says it in text, the legend says what the mark
        means, and the colour is left to do what it is good at.

        The map comes first and the paths last. This is the screen you open
        to find a spare control; nine lines of Proton prefix ahead of it is
        what made it read like a newspaper.
        """
        out = []
        # What this layout is OF, before what is in it. The screen you
        # open to ask "what am I actually working on" named neither the
        # desk nor the overlay, and both decide where everything landed.
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
        # The legend is three lines because a line carries one tone, and a
        # legend not drawn in the colours it explains explains nothing.
        for state in (MINE, PROPOSED, UNSET):
            out.append((state, f'  {MARK[state]} {MARK_SAID[state]}'))
        # The number the REACH column prints. One line, because the column
        # is ten characters and a phrase does not fit in ten characters.
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
            # Named columns. There were five of them and nothing saying
            # which was which: `2,3,4` is a button list, and the only way
            # to learn that was to work it out from the numbers.
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
                # Carrying something -> that need's state, mark and colour
                # alike, which is exactly how the table draws it. Free and
                # bindable -> plain, because a spare control is the normal
                # case and colouring the normal case says nothing. Bindable
                # by nothing -> as dim as the ids above it.
                # The first one's mark and colour. They can differ -- one
                # accepted, one still proposed -- and a row carries one
                # tone, so the names say the rest.
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
            # Each path on its own lines: a Proton prefix is 120 characters
            # before it says anything, and a truncated path answers nothing.
            # Shortened at the home directory, which is 14 of them and the
            # one part a reader already knows.
            for label, path in self.paths:
                out.append(('subhead', f'  {label}'))
                out.extend(('meta', f'    {ln}')
                           for ln in _fold(_tilde(str(path))))
        return out

    # -------------------------------------------------------------- writing

    def placements(self):
        """Every need that ended up with a control.

        Proposed and yours alike: the `?` says you did not check it, not that
        it is off -- the same call DCS makes, whose generator has never
        filtered on the flag either.
        """
        return [self.at[n] for n in self.needs if self.at[n] is not None]

    def result(self):
        """The layout to hand a writer: the same plan, narrowed."""
        return self.layout.but(self.placements())

    # ---------------------------------------------------------------- doing

    def propose(self, need):
        """Put the planner's suggestion on this need.

        A row you cleared has no suggestion to put back: the allocator is
        told to leave it alone, so the last plan has nothing for it. So
        the clear is forgotten first and the game lays itself out again --
        otherwise `x` on a saved row could only be undone by assigning
        the thing by hand, and the key that says it restores a proposal
        would answer that there is none.
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
        return f'{need.what} -> {self.where(need)}  (proposed)'

    def propose_all(self):
        """Fill the gaps from the plan, and only the gaps.

        Never touching what you chose is what makes this safe to press at any
        time -- the same rule as DCS's `propose_into`, which skips anything
        already bound.
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

        The control, not just the fact: you said yes to a home, not to a
        row, so the day the allocator moves it the mark has to stop
        claiming you agreed.
        """
        self.mark[need] = MINE
        need.assignment = {'role': at.role, 'control': at.ctrl.id,
                      'how': corneeds.ACCEPTED}
        if need.takes == corneeds.AXIS and at.slots:
            # Which axis of it, so that saying yes to a lever is saying
            # yes to THAT lever -- the same claim `button` makes for a
            # press.
            need.assignment['axis'] = at.slots[0][0].index

    def confirm_all(self):
        # One mark for the lot rather than one per need: nothing is
        # written here, and `unsaved` does not get truer forty-five times.
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

        `how: cleared` rather than no row at all. The file holds what
        sits where, so a row with nothing on it used to be a row the file
        did not mention -- and a fact the file cannot hold is a fact that
        does not survive `s`: clearing a proposal reported `nothing has
        changed since the last save`, truthfully, and the next open
        proposed it straight back. An empty row you chose is a decision
        and now has somewhere to live.
        """
        # Nothing on it and nothing of yours to forget -- or already
        # cleared. Either way there is nothing to do, and saying there is
        # would mark the files out of date over a row that did not move.
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

        It used to drop the proposals and nothing else, on the argument
        that a key which could undo an hour of your own decisions is one
        you would stop pressing. That left it doing nothing at all on a
        screen you had just saved -- everything there is yours, so there
        was never a proposal to drop -- while the help said `unassign
        this / every proposal` and the pair read as one key with two
        scopes. It clears the lot; `s` is still what writes it.
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
        """Give a need a control by hand. Yours at once, with no confirming
        step: you just chose it.

        `button` is the one actually pressed, when a press is what did this.

        `slot` says WHICH of the need's bindings that press was for, when
        you are taking one direction of a hat rather than the hat. The
        rest keep whatever they had, so a trim hat whose directions the
        game names in another order can be put right one at a time
        instead of re-taken whole and scrambled the same way again.
        """
        was = self.at[need]
        # Putting it back where it already was is not an override, and a
        # panel saying "moved from Thumb button" about a binding ON the
        # thumb button would be the screen arguing with the person reading
        # it. `is` on the control rather than the label: two controls can
        # share a label across devices, and the role is checked anyway.
        moved = was is not None and not (was.role == role
                                         and was.ctrl is ctrl)
        why = corneeds.Reason('yours', instead=was if moved else None)
        # What was already pinned per slot, kept across a re-take of the
        # same control: taking one direction must not forget the three
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
        """Every group there is, so a menu can offer them before asking
        for a new name. Bands included: filing something under `in a
        turn` is a choice like any other, and refusing to offer it would
        make the fallback a place you can leave but not return to."""
        return sorted({self.group_of(n) for n in self.needs})

    def touched(self, what=''):
        """Say that something changed and the files no longer match.

        It used to WRITE, here, on every decision -- eight call sites, a
        whole-file rewrite each. The capture wizard in sim-device-map does
        not: it marks the screen `unsaved` and `s` writes. One keystroke
        means one thing in both tools now, which is worth more than the
        saved keystroke.

        `what` is kept so the save box can name it. A box that comes up
        on the way out saying only that something is unsaved, to somebody
        who has just pressed `s`, is an argument the screen cannot win:
        twelve keys mark this screen, one of them is a button read off
        the stick, and the reader has no way to tell which fired.
        """
        self.unsaved = True
        #: the last decision the files do not have yet, in words
        self.since = what
        return ''

    def keep(self):
        """Write both files down. (what happened, is it still unsaved).

        The whole list every time, because that is what the files hold --
        a description per function and a row per placement, and a partial
        write of either is a file that disagrees with the screen.
        """
        if self.save is None:
            # Still unsaved, and it will stay that way: there is nowhere
            # to put it, so the frame goes on saying so rather than
            # claiming a file has something no file does.
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
        This is the word an overlay matches on, so it comes from the
        closed table rather than from a prompt -- a job nobody wrote
        would cost this function every wish in every template, and look
        exactly like a template that did not apply.
        """
        if job not in corneeds.JOBS:
            return f'{job!r} is not a job.'
        if need.suits == job:
            # Picking the job it is already filed under changed nothing,
            # and said `unsaved` for it.
            return f'{need.what} is already {job} work.'
        need.suits = job
        self.touched('a job changed')
        return f'{need.what} is {job} work.'

    def refile(self, need, category):
        """Move a need to another group. Returns a line.

        Naming its own band puts it back on the fallback rather than
        recording the band as a category: otherwise `in a turn` becomes a
        place you can leave and not return to, and two things that look
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

        A band is refused: there are four, they are the allocator's scale,
        and renaming one here would say they are yours to name when they
        are not. Refiling out of one is how you leave it.
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

        It arrives carrying nothing. Promoting says "this matters", not
        "put it here" -- where is the next question, and pressing RETURN
        on the row already answers it.
        """
        already = next((n for n in self.needs
                        if any(b.action == action.id
                               for slot in n.bindings for b in slot)), None)
        if already is not None:
            already.category = category
            self.touched('a function added')
            return (f'{action.name} is on the list. It moved to '
                    f'{category}.')
        if action.kind == 'axis':
            # Axes never went through the allocator in any game in the
            # family, so there is nothing for a promoted one to land on.
            return (f'{action.name} is an axis. This screen cannot add '
                    'an axis: an axis row needs a shape and a rest, and '
                    'the vocabulary does not say either.')
        need = corneeds.Need(action.name, 'button',
                             [[cactions.Bind(action.id)]],
                             category=category)
        self.needs.append(need)
        self.at[need] = None
        self.mark[need] = UNSET
        self.touched('a function added')
        return f'{action.name} is on the list, under {category}.'

    def rules_lines(self, width=60):
        """How a control is chosen, read out of the tables that choose it.

        In the order somebody asks, not the order the code runs. The first
        version was seven tables with no thread: it never said what the
        allocator was FOR, used `band`, `reach`, `floor` and `ceiling`
        without defining any of them, and printed 0, 1 and 3 without
        saying that lower means closer to your hand.

        Every number is still read from the table the allocator itself
        reads -- tune a limit and this rewrites itself -- but a number
        with nothing around it explained nothing.

        What is NOT here is the `note` each band, term and fact carries.
        Those were drawn here once, on the argument that the reason a
        limit is what it is was the most valuable text in the repo and
        belonged beside the limit. On a screen they are somebody else's
        working: half a page of why a weight was retuned, under some rows
        and not others, so they read as noise that turns up at random.
        They are in `scoring.toml`, where whoever is about to change a
        number is already looking.
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
        # Written out from `allocate`'s sort key, in its order, because
        # this paragraph was prose and prose does not move when the key
        # does. It said pins went first -- they had not since what you
        # choose by hand started outranking them -- and stopped at the
        # factory count, which is no longer the last word.
        for n, (what, why) in enumerate(corneeds.ORDERED_BY, 1):
            say('plain', f'{_sentence(what)} {why}', lead=f'  {n}  ')
        say('plain')

        say('head', 'WHEN IT REFUSES A CONTROL')
        # Read out, not written out. These four were transcribed here and
        # the transcription was already the only thing on this screen that
        # could disagree with the allocator -- which it then did, the day a
        # fifth refusal arrived and nobody thought to come back here.
        # The table holds a fragment, because its own column is where
        # most of these are read: `-60  it is the wrong shape` wants no
        # capital and no full stop. A bullet is a line of its own, so the
        # screen makes it a sentence here rather than the file holding two
        # spellings of each one.
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
            # `says` carries the run's own values -- `{role}`, `{label}` --
            # and there is no run here, so a term that needs them says the
            # same rule with nothing in the holes.
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
                # The shape for a closed field the need names a value of:
                # both answers are weighed, like a bool, and the words
                # say which way round.
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
        """What `f` is hiding, for the header. '' when it is hiding nothing.

        The status line said this once, on the keystroke, and the next
        movement cleared it -- so a screen showing three rows of thirty-one
        looked exactly like a game that has three. It has to stay up for as
        long as it is true.
        """
        if not self.filter:
            return ''
        shown = sum(1 for n in self.needs if self.matches(n))
        return f'filter {self.filter!r} · {shown} of {len(self.needs)}'

    def group_of(self, need):
        """What this need is filed under.

        Yours where you have said, the band where you have not. Nothing
        carries a category on the day this lands, so falling back is what
        keeps every screen in the family from emptying.
        """
        return need.category or corneeds.URGENCY_NAME[need.urgency]

    def groups(self):
        """[(name, [Need])] -- the list's shape, most urgent group first.

        A group sorts by the most urgent thing in it, which for a band is
        the band itself: the order the screen had, derived instead of
        declared, so a category you invent lands where its contents say
        rather than where you happened to make it.

        Inside a group, the name. The rows came in the order the needs
        list happens to be in, which is every placement followed by
        everything unplaced -- so clearing a binding moved its row to the
        bottom of the group on the next open, and a row you are walking
        towards was not where you left it. The name is the one thing
        about a row that does not change when you bind or clear it.

        The list itself is NOT reordered: it is the order the needs file
        is written in, and that file is edited by hand.
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
                # filter took away -- an empty group is a line you scroll
                # past to reach the rows you asked for.
                continue
            out.append(Row('head', name.upper(), group=name))
            for need in band:
                out.append(Row('need', need.what, need=need))
                # What it binds, under it. This was the footer's job, which
                # meant moving onto a row to learn what it does and never
                # seeing two at once -- and X4 puts six lines there for one
                # hat, so the footer was the wrong size for the answer.
                for part, what in (self.binds(need)
                                   if self.show_binds else ()):
                    out.append(Row('bind', f'{part:10} {what}', need=need))
            out.append(Row('gap', ''))
        return out


# ------------------------------------------------------------------- drawing

#: Two lines, because one was 96 characters and a terminal is 80: `s write`
#: and `q quit` fell off the end of the screen that documents them. Moving
#: comes first -- it is what you need before any of the rest is reachable.
#: The whole list, shown by `?`. The border carries the handful you reach
#: for constantly; this carries everything, including the capital forms --
#: which is most of what somebody presses `?` to find out.
#: What `?` shows. Two things it did not before.
#:
#: It says what the screen IS. A list of key names answers "which key"
#: and never "what am I doing here", and the second is why somebody
#: reaches for help in the first place.
#:
#: And one entry per line. It used to put two on the first two rows and
#: one on every other, and hang a keyless continuation under `a` for the
#: browse screen's own keys -- which belong to that screen, and are in
#: its own footer.
KEYS = (
    ('head', 'NAME'),
    ('plain', '  review — put a game\'s actions onto HOTAS controls'),
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
    ('plain', ''),
    ('head', 'MOVING'),
    ('plain', '  ↑↓  j k     Move to the previous or the next entry.'),
    ('plain', '  g  G        Move to the first or the last entry.'),
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
    ('plain', '  J           Say what this function is FOR.'),
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

    The tables hold fragments: a term or a fact is read in a column of
    them, where `the shape and the count fit` is right and `The shape and
    the count fit.` is a sentence pretending to be a label. A screen that
    puts one at the start of a line wants the other spelling, and this is
    the one place that makes it.
    """
    said = said.strip()
    if not said:
        return said
    return said[0].upper() + said[1:] + ('' if said.endswith('.') else '.')


def _hand(ctrl):
    """`0 thumb` -- how far, and what gets there, for a column.

    It printed the words, cut to twenty: a control somebody reached with
    a named finger came out as `thumb`, and one with no finger recorded
    came out as `the hand off the dev`, which is not a word. Half a
    sentence in a column is worse than a number, because a number can be
    explained once at the top and a truncation cannot be explained at
    all. The legend above says what 0 to 3 mean.
    """
    tier = corneeds.reach_tier(ctrl)
    far = '-' if tier == corneeds.UNMEASURED else str(tier)
    return f'{far} {corneeds.reach_finger(ctrl)}'.strip()


def _tilde(path):
    """`/home/you/x` -> `~/x`. Fourteen characters a reader already knows."""
    home = os.path.expanduser('~')
    return '~' + path[len(home):] if path.startswith(home + os.sep) else path


def _fold(path, width=74):
    """A long path over several lines, broken at directory boundaries.

    A Proton prefix is ninety characters before it says which game, so the
    part that answers the question is the part a terminal cuts off.
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

    Clipped to `w - x`, not `w - x - 1`. The spare column existed because
    writing the bottom-right cell raises -- but that is one cell on one
    row, and reserving a whole column for it ate the right-hand border of
    every panel that reaches the screen edge. The `except` already covers
    the cell it was guarding against.
    """
    h, w = scr.getmaxyx()
    if 0 <= y < h:
        try:
            scr.addstr(y, x, text[:max(0, w - x)], attr)
        except curses.error:
            pass


#: Below this the two panels stop fitting: the list needs about 52
#: columns before `throttle · Middle finger hat` starts being cut, and the
#: detail panel is unreadable under about 26.
SPLIT_AT = 90

#: Where the divider sits in a list row: the mark, then the action
#: name, then the line, then what it is bound to.
NAME_W = 29

#: The detail panel never gets less than this, however wide the list
#: wants to be -- under it the wrapping turns into one word per line.
DETAIL_MIN = 26


def _layout(width, height, wants=None):
    """((y, x, h, w) for the list, same for the detail) -- or stacked.

    Side by side where there is room. `wants` is how wide the list would
    like to be for the rows it actually has; the rest goes to the detail
    panel rather than to blank space, which is what a fixed split left
    between the two.

    Below `SPLIT_AT` they stack, because a list cut off mid-control-name
    is worse than a shorter one.
    """
    if width >= SPLIT_AT:
        left = width - DETAIL_MIN
        if wants:
            left = max(SPLIT_AT - DETAIL_MIN, min(left, wants))
        return (0, 0, height, left), (0, left, height, width - left)
    # Stacked: the list keeps what it needs and the detail takes the rest,
    # never more than a third and never less than a frame plus two lines.
    tall = max(4, min(height // 3, 10))
    listed = max(6, height - tall)
    return (0, 0, listed, width), (listed, 0, height - listed, width)


#: In the sill, most-needed first: what is dropped on a narrow panel is
#: dropped from the end, and nothing else is reachable without moving.
HINTS = ('↑↓ move', '↵ assign', 'l from free', 'c accept', 'x unassign',
         'a add', 'J job', 'i invert', 'r category', 'f filter', 'h binds',
         'o overlay', 'y why', 'm map', 's save', 'w write')


def _fit(width, text, lead=''):
    """`text` as lines no wider than `width`, hanging under `lead`.

    The panel wraps its own. `_draw` wraps too, but flush left -- so a
    ledger line it had to break landed under the `+40` rather than beside
    it and stopped reading as a ledger.
    """
    room = max(6, width - len(lead))
    bits = textwrap.wrap(text, room) if text else ['']
    pad = ' ' * len(lead)
    return [lead + bits[0]] + [pad + b for b in bits[1:]]


def _side(rv, row, width=DETAIL_MIN - 4):
    """The detail panel's body: where the row sits, what it fires, and why.

    Three questions, and they are not one question. The third had no answer
    at all before: the panel named the control and its reach and stopped, so
    the one thing a reader actually argues with -- the planner's choice --
    was the one thing it would not account for.

    `Reason` is that account, written where the decision was made, and this
    is its first human reader. The score is shown as the terms it was made
    of rather than as its total: 137 tells nobody anything, and `+40 the
    stick it asked for` is the sentence the number stood for.

    The device's full product name is here rather than in a header of its
    own. A row saying "stick" does not say WHICH stick, and this is the
    moment that question is being asked.
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
        # The count only where it says something the shape does not: `a
        # button and 1 button` is one fact written twice.
        say('meta', f'This row needs a {need.first_shape}.'
            if need.wanted == 1 else
            f'This row needs a {need.first_shape} with '
            f'{ctui.plural(need.wanted, "button")}.')
        say('plain')
        # First, because it is the only one of these you can act on, and
        # because it is the reason the row is empty: the planner was not
        # asked, so what the planner would have done is beside the point.
        gone = rv.unhonoured(need)
        if gone:
            say('unset', gone)
            say('note', 'The row stays empty. Press x to give the row '
                        'to the planner.')
            say('plain')
        # Only when there is nothing below to say it: the table names
        # the planner's choice and marks it.
        if plan is None:
            say('meta', 'The planner has no control for this row.')
            say('plain')
        _asked_for(need, say)
        say('plain')
        # And the account for it. An empty row is where "why there?" is
        # still an open question, and it was the row that answered least:
        # the planner's choice was named and never costed, so there was
        # nothing on screen to agree or disagree with.
        say('head', 'WHAT WOULD TAKE IT')
        _against(rv, need, plan.role if plan else '',
                 plan.ctrl if plan else None, say, width,
                 said='The planner wants this control.' if plan else '')
        return out

    say('head', 'WHERE')
    dev = rv.layout.devices.get(p.role)
    said = [('role', p.role)]
    if dev is not None:
        said.append(('device', dev.product))
    if need.takes == corneeds.AXIS:
        # The axis's own label, not its control's: three of the stick's
        # axes are `Main stick` and only one of them is pitch.
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
        # Fields, like every other panel. It had its own shape -- the part
        # cut to seven characters and left-aligned -- so one panel read
        # `press   Map: Map pan to rotate` under three that read
        # `  control  Thumb hat`, and the column the eye follows moved
        # between sections of the same box.
        _fields(say, list(binds))

    say('plain')
    _why(rv, need, p, say, width)
    return out


def _title_of(row):
    """What the detail panel is headed with. Never None.

    Every kind has a branch, which is the point: the axis rows had none,
    so the title came back None and slicing it took the screen down the
    moment the cursor reached the AXES section.
    """
    if row is None:
        return ''
    if row.kind == 'need':
        return row.need.what
    if row.kind == 'head':
        return row.group or row.text
    return ''


def _group_side(rv, name, width):
    """What a heading is, when the cursor is on one.

    It answered nothing before, so landing on a heading left an empty box
    -- which reads as a hole rather than as a thing you are standing on.
    """
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    members = dict(rv.groups()).get(name, [])
    tally = collections.Counter(rv.mark[n] for n in members)
    say('head', 'GROUP')
    # Fields, like every other panel. `a band, not yours to rename` and
    # `r files things out of it` were two keystroke notes wearing the
    # grammar of statements, under a heading that says neither which key
    # nor what it would do.
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

    Loose sentences are what this replaced. `thumb, your hand where it
    lives, nothing moved` sat under WHERE with nothing saying what it
    was an answer to, so a reader had to work out that it was a
    measurement and not a remark.

    The gutter comes from the longest label there is. Fixed at twelve it
    put `         shape  hat4` -- twenty characters -- into a panel
    eighteen wide, and right-aligning in a narrower field does not
    shorten a label, it only stops padding it.
    """
    gutter = max(len(label) for label, _v in rows)
    for label, value in rows:
        say('plain', value, lead=f'  {label:>{gutter}}  ')


def _asked_for(need, say):
    """The need's own row, one field to a line.

    Its shape, its band and whichever flags somebody set come from
    `games/<g>/<g>-needs.json`, which describes the function. The device
    comes from the overlay, which is where wanting one is said. Nothing
    here is derived and nothing is prose.
    """
    say('head', 'WHAT IT ASKED FOR')
    said = [('shape', need.first_shape)]
    # The job, because it is the one word an overlay takes hold of: a
    # function filed under the wrong one quietly misses every wish in the
    # template, and until this line there was nowhere on screen to see it.
    if need.suits:
        said.append(('job', need.suits))
    if need.device:
        said.append(('device', need.device))
    said.append(('when', corneeds.URGENCY_NAME[need.urgency]))
    said += [('', phrase) for flag, phrase in ASKS
             if getattr(need, flag, False)]
    _fields(say, said)


def _how_it_moves(rv, p, say):
    """What the map measured about this lever.

    None of it reached a screen before: where it rests decides whether
    zero means off, and two levers that move together are one lever
    until you uncouple them -- which is the sort of thing you find out
    by flying. `THE LEVER` was the heading, which named the thing
    instead of saying what the lines answer, and named it wrong for most
    of them: a twist and a mini-stick are not levers.
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

    The answer to the one question an axis row raises -- why this lever
    and not the one beside it -- which had nowhere to be asked. A button
    row has the candidate table for that; this is the same question.
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
    # allocator made: `axes_for` scores every lever that answers the ask
    # and the points pick among them. The panel used to say `answers this
    # too` and no more, because the resolver it was written for took the
    # first lever that answered and recorded nothing about the rest.
    worth = {(r, a.index): s for s, r, _c, a
             in corneeds.axes_for(need, rv.layout.devices, rules=rv.rules)}
    say('plain')
    say('head', f'EVERY LEVER ON THE {p.role.upper()}')
    for got in rest:
        mine = got.index == here.index
        on = held.get((p.role, got.index), [])
        said = ', '.join(n for n in on if n != need.what) or 'free'
        points = worth.get((p.role, got.index))
        # A dash where it has no score, as the button table does: the ask
        # refused it, so there is no number to lose on.
        num = '\u2014' if points is None else str(points)
        say(rv.mark[need] if mine else 'meta',
            f'{"\u25b6" if mine else " "} {num:>5}  {got.label}')
        say('meta', said, lead='        ')


def _how_it_was_set(need, p, say):
    """Who put this where it is, and what you have said about it.

    Three states live on this screen and the panel named one of them, as
    a phrase under a heading about which control beat which: `you chose
    it`. The other two -- the planner put it there and you agreed, and
    the planner put it there and you have not looked -- had no words at
    all, so the only way to tell them apart was the colour of the row.

    It matters most at the moment you press `s`: what goes into the file
    is all three, and `how` in the file is exactly this.
    """
    mine = need.assignment or {}
    by_hand = p.why is not None and p.why.how == 'yours'
    say('plain')
    say('head', 'HOW IT WAS SET')
    # `set by`, not `put there by`: the gutter is the longest label and
    # `_fit` keeps six columns for the value, so a label past eight
    # characters is wider than the narrowest panel the screen draws.
    said = [('set by', 'by hand' if by_hand else 'the planner')]
    if by_hand:
        said.append(('kept as', 'yours'))
    elif mine.get('how') == corneeds.ACCEPTED and \
            mine.get('control') == p.ctrl.id:
        said.append(('you said', 'yes, to this control'))
    elif mine.get('how') == corneeds.ACCEPTED:
        # You agreed to a control, and this is not it.
        said.append(('you said', 'yes, to another control'))
    else:
        said.append(('you said', 'nothing yet'))
    _fields(say, said)


def _why(rv, need, p, say, width=DETAIL_MIN - 4):
    """Why this binding is on this control, in the allocator's own terms.

    Every control is worth points to an action; the actions go in order,
    most urgent first; each takes the free control worth most. So three
    things account for a placement, and the panel is those three: what
    the action asked for, what each control was worth and who is sitting
    on it, and what the winner's points were made of.

    It drew only the last of those once -- a total and its terms -- which
    is how the score was reached and not why this control. Measured over
    the five games, 85 placements of 146 were ties and 24 more went where
    they went because something better was taken: for 109 of 146 the
    answer is in the middle section and nowhere else.
    """
    r = p.why
    how = r.how if r is not None else ''
    _asked_for(need, say)
    _how_it_was_set(need, p, say)
    if need.takes == corneeds.AXIS:
        # The same three answers as a button row, in the shapes an axis
        # has them in: what the map measured about the lever, every lever
        # that could have taken it and what each is worth, and what the
        # winner's points were made of. The last two were not drawn at
        # all -- an axis was named rather than chosen when this panel was
        # written, so there was no comparison to report and no score to
        # break down.
        _how_it_moves(rv, p, say)
        _every_lever(rv, need, p, say)
        if p.points is not None:
            _worth(say, need, p.role, p.ctrl, p.points, rv.rules,
                   axis=rv.lever(p), lead=5)
        return
    say('plain')
    say('head', 'WHICH CONTROL GOT IT')
    # What it is, where the heading's own answer is not the whole of it.
    # Not `you chose it`: that is what HOW IT WAS SET says, and it said
    # it here as a phrase under a heading about which control beat which
    # -- the wrong question for it to be the answer to.
    word = {'pinned': 'You pinned this control by name.',
            'borrowed': 'This is a spare button.'}.get(how, '')
    if how == 'borrowed':
        owner = [n for n in rv.who_has(p.role, p.ctrl) if n is not need]
        if owner:
            word = (f'This is a spare button. {owner[0].what} has the '
                    'control.')
    plan = rv.plan.get(need)
    if how == 'yours' and plan and not (plan.role == p.role
                                        and plan.ctrl is p.ctrl):
        word = (word + ' ' if word else '') \
            + f'The planner wants {plan.ctrl.label}.'
    _against(rv, need, p.role, p.ctrl, say, width,
             how=how, said=word)


def _against(rv, need, role, ctrl, say, width, how='', said=''):
    """Every control that could take this, and what the one on it is worth.

    Both halves used to be refused to any placement the allocator had
    not picked: the panel drew one line, the control's name, and
    stopped. Counted over the six games that was 45 rows of 174 -- 31 of
    DCS's 32, all hand-placed -- and 24 of them had a score and a field
    of candidates sitting there unprinted. What a control is worth to an
    action is a fact about the desk, not about who typed it.

    An empty row is the other half of the same hole: the planner's
    choice was named and never accounted for, so the one row where the
    question "why there?" is still open was the one that answered least.
    """
    LEAD, NUM = 2, 7
    # Scored without `stayed`, which pays whichever control the need is
    # already on: counted, every alternative sits 20 below and the panel
    # reports that nothing else came close. So these totals are what the
    # controls are worth to the action, not what the run added up.
    rules = corneeds.merge_rules(rv.rules, {'term': [{'name': 'stayed',
                                                      'weight': 0}]})
    ran = corneeds.ran_against(need, rv.layout.devices, rules=rv.rules,
                               floor=how != 'relaxed')
    mine = next((s for s, r, c in ran if c is ctrl and r == role), None)
    if ctrl is not None and mine is None:
        # Sitting on a control that was never a candidate: a hand-placed
        # need on one button of a hat, or a spare button the borrow pass
        # lent it. It goes at the head of the table with no number,
        # because it has none -- `score` refuses the control for the
        # whole function -- rather than being left out of its own
        # account.
        ran = [(None, role, ctrl)] + list(ran)
    if not ran:
        say('plain', 'No control on this desk fits this row.', lead='  ')
        return

    # Everything that could have had it, and the next best under it. Only
    # what beat it made a binding that won outright read as the only one
    # that fitted, which was a lie wherever anything else fitted at all.
    rows = (ran if mine is None else
            [x for x in ran if x[0] >= mine]
            + [x for x in ran if x[0] < mine][:1])

    def whos_on(role, got):
        """`Strafe +1` -- a control carries more than one need.

        The borrow pass hands a leftover need a spare button of a
        control something else took, so four names can belong on one
        line. The first and a count: the map screen has room for all of
        them and this column has room for one.
        """
        if got is ctrl:
            return ''
        on = [n.what for n in rv.who_has(role, got) if n is not need]
        if not on:
            return 'free'
        return on[0] + (f' +{len(on) - 1}' if len(on) > 1 else '')

    held = {(r, c.id): whos_on(r, c) for _s, r, c in rows}
    lab = max(len(c.label) for _s, _r, c in rows) + 2
    # One shape for the block, decided by whether the names fit whole.
    # Per row, a name a character too long wrapped while the four around
    # it did not, and the block read as though that line meant something
    # the others did not. And the name wins over the columns: a control
    # whose name you cannot read is not one you can find, and `Thumb top
    # butto` was on screen before this.
    room = width - LEAD - NUM - 2
    # The `taken by` column counts towards the width. Measured on the
    # label alone, a table that just fitted wrapped its last column to
    # column zero -- `free` under the points, reading as a row of its
    # own -- which is the shape the stacked form exists to avoid.
    wide = lab + max((len(w) for w in held.values()), default=0) <= room
    if wide:
        say('plain', 'taken by' if any(held.values()) else '',
            lead=f'  {"points":>{NUM}}  {"control":<{lab}}')
    for points, r, c in rows:
        here = c is ctrl and r == role
        tone = rv.mark[need] if here else 'plain'
        mark = '\u25b6' if here else ' '
        who = held[(r, c.id)]
        # A dash, not a zero: it has no score because the control cannot
        # play this part at all, and a zero would read as one it lost on.
        num = '\u2014' if points is None else str(points)
        if wide:
            say(tone, f'{mark} {num:>{NUM}}  {c.label:<{lab}}{who}')
            continue
        # Stacked: the name on its own line, what it was worth under it.
        say(tone, f'{mark} {c.label}')
        say('meta', who, lead=f'  {num:>{NUM}}  ')
    if how == 'relaxed':
        say('note', 'No closer control was free.', lead='  ')
    if said:
        say('meta', said, lead='  ')
    # No control, or no number for the one there is: an empty row the
    # planner had nowhere to put, or a control that cannot take the
    # whole function and lent it a button.
    if ctrl is None or mine is None:
        return

    _worth(say, need, role, ctrl, mine, rules, floor=how != 'relaxed')


def _worth(say, need, role, ctrl, points, rules, floor=True, axis=None,
           lead=7):
    """What the points were made of, term by term.

    Drawn for an axis as well as a button, from the same call: an axis is
    scored by the same table and this panel said nothing about it, on the
    argument that a lever is named rather than chosen. It is chosen -- by
    `axes_for`, out of everything that answers the ask.
    """
    say('plain')
    # What makes it worth that, rather than where it `got` it: a control
    # you put this on yourself was never in a run to get anything, and
    # the number is what it is worth to the action either way.
    say('head', f'WHAT MAKES {ctrl.label.upper()} WORTH {points}')
    parts = []
    corneeds.score(ctrl, need, role, parts=parts, floor=floor, rules=rules,
                   axis=axis)
    for delta, text in sorted(parts, key=lambda q: -q[0]):
        say('meta', text, lead=f'  {delta:>+{lead}}  ')


def _panel(scr, theme, rect, title, right='', keys=(), tail='', note=''):
    """Frame a box and hand back the rectangle inside it."""
    y, x, h, w = rect
    _put(scr, y, x, ctui.lid(w, title, right), theme.head)
    for row in range(y + 1, y + h - 1):
        _put(scr, row, x, ctui.V, theme.head)
        _put(scr, row, x + w - 1, ctui.V, theme.head)
    _put(scr, y + h - 1, x, ctui.sill(w, keys, tail, note),
         theme.note if note else theme.head)
    return y + 1, x + 2, h - 2, w - 4


def _tally(rv):
    """What sits beside the title: the filter, or what is on the list.

    The filter when there is one and the tally otherwise -- both answer
    "what am I looking at", and only one of them can be true at a time.
    Only what is there: the long form was dropped whole by `lid` for not
    fitting beside the title, so the counts vanished from a screen that
    had always carried them.
    """
    mine, prop, unset = rv.counts()
    counts = [f'{MARK[MINE]}{mine}' if mine else '',
              f'{MARK[PROPOSED]}{prop}' if prop else '',
              f'{unset} {MARK_SAID[UNSET]}' if unset else '',
              # Which overlay this was laid out to. A state, so it goes
              # here rather than in the status line -- and said even when
              # there is none, because "the planner had no wishes" and
              # "the planner ignored mine" look identical on a row.
              rv.overlay().name if rv.overlay() is not None
              else 'no overlay',
              # Last, and here rather than in the status line: a status
              # line says what just happened and goes on the next
              # keypress, and this is a state of the files.
              'unsaved' if rv.unsaved else '']
    return rv.narrowed() or ctui.SEP.join(c for c in counts if c)


def _draw(scr, rv, sel, state, theme):
    h, w = scr.getmaxyx()
    rows = rv.rows()
    # As wide as the widest row actually is, so the detail panel gets the
    # space instead of the gap getting it.
    wants = 4 + 2 + NAME_W + max((len(rv.where(r.need)) for r in rows
                                  if r.kind == 'need'), default=0)
    (ly, lx, lh, lw), side = _layout(w, h, wants)
    visible = max(1, lh - 2)
    top = state['top']
    if sel < top:
        top = sel
    elif sel >= top + visible:
        top = sel - visible + 1
    state['top'] = top

    scr.erase()
    right = _tally(rv)
    # Needs, not every selectable row: this says which of the things you
    # are placing you are on, and a heading is not one of them.
    pick = [i for i, r in enumerate(rows) if r.kind == 'need']
    at = sum(1 for i in pick if i <= sel)
    iy, ix, ih, iw = _panel(
        scr, theme, (ly, lx, lh, lw),
        rv.title + (f' · {rv.subtitle}' if rv.subtitle else ''),
        # A game's own keys sit in the sill beside the family's, because
        # a key nobody shows is a key nobody presses.
        right, HINTS + tuple(f'{key} {word}' for key, word, _do in rv.offers),
        _where(rows, sel, at, pick), note=rv.status)

    for n, i in enumerate(range(top, min(len(rows), top + visible))):
        row = rows[i]
        y = iy + n
        if row.kind == 'head':
            _put(scr, y, ix, row.text[:iw],
                 theme.sel if i == sel else theme.head)
        elif row.kind == 'bind':
            _put(scr, y, ix + 4, row.text[:iw - 4], theme.meta)
        elif row.kind == 'need':
            # The state name is the tone name, so this screen and the map
            # ask the theme the same question and get the same answer.
            st = rv.mark[row.need]
            attr = theme.sel if i == sel else theme[st]
            # A divider, not a gap: at 68 columns the eye has to carry a
            # name across 26 blank spaces to reach what it is bound to,
            # and it loses the row on the way.
            _put(scr, y, ix, f'{MARK[st]} {row.text[:26]:26}'[:iw], attr)
            if iw > NAME_W + 2:
                _put(scr, y, ix + NAME_W, ctui.V, theme.meta)
                _put(scr, y, ix + NAME_W + 2,
                     rv.where(row.need)[:iw - NAME_W - 2], attr)

    row = rows[sel] if 0 <= sel < len(rows) else None
    # The group on a heading, the need on a row: the panel is about
    # whatever the cursor is on, and its title should say which.
    name = _title_of(row)
    dy, dx, dh, dw = _panel(scr, theme, side, name[:side[3] - 6],
                            tail='? help')
    # One wrapper, not two. `_side` fits its own lines to `dw` because it
    # is the half that knows which of them are a ledger and need hanging
    # under their `+40`; wrapping them again here would have dropped that
    # indent the moment a line landed one character over.
    for n, (tone, text) in enumerate(_side(rv, row, dw)):
        if n >= dh:
            break
        _put(scr, dy + n, dx, text, theme[tone])

    scr.refresh()


# -------------------------------------------------------------- the sticks

class Sticks:
    """The joystick nodes, opened once and matched to roles by USB id.

    The two capture wizards ask you to press a button on each device to work
    out which is which, because they run before anything knows what hardware
    you have. Here the map has already been loaded and every device in it
    carries its USB id, so the same question can be answered without asking:
    `/proc/bus/input/devices` gives vendor and product per `js` node, and that
    pair is exactly what `devicemap` matches on.

    Nothing is opened until the first capture, so a review of a layout on a
    machine with no sticks plugged in costs nothing and fails only if you ask
    it to.
    """

    def __init__(self, layout):
        self.layout = layout
        self.devices = []
        self.why = ''
        self.opened = False

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
                self.why = (f"{info['js']} will not open ({e}) — are you in "
                            "the `input` group?")
                continue
            dev.role = role
            self.devices.append(dev)
        if not self.devices and not self.why:
            self.why = ('none of the devices in the map are plugged in '
                        f'({", ".join(sorted(want)) or "no USB ids"})')
        return self.devices

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

    `core/tui.py` has no text entry -- the capture wizards never needed one
    and `sim-device-map`'s Tui cannot be imported here -- so this is the
    smallest thing that answers the question. ESC is None rather than the
    empty string, because emptying the filter and abandoning the typing are
    different answers and `f` offers both.
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

    On a heading there is no such thing -- `0/32` read like a fault -- so
    it says what the heading holds. Counted from the rows on screen, not
    from the group: with a filter up, what it holds and what you can see
    are different numbers, and the one to report is the one in front of
    you.
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
    """Where this need's row is now. `sel` is an index, not a reference,
    so anything that reorders the list has to say where to look again."""
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
    """Which group to file it under. None if you changed your mind.

    Existing ones first, because filing beside something is the common
    case and typing a name that differs by a space from one you already
    have is how you end up with two.
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


def _pick_job(tui, need):
    """Which job this function does. None if you changed your mind.

    The ten from `[jobs]`, with what each covers beside it, because the
    difference between `flight` and `systems` is a judgement and the
    table is where it is written down.
    """
    known = list(corneeds.JOBS)
    says = corneeds.RULES['jobs']
    got = tui.choose(
        f'{need.what} is...',
        [(MINE if k == need.suits else 'plain', f'{k:8} {says[k]}')
         for k in known])
    return None if got is None else known[got]


def _pick_overlay(tui, rv):
    """Which overlay to lay this out to. None if you changed your mind.

    `no overlay` is a choice like any other and sits with the rest rather
    than being a second keystroke: laying one on and taking it off are the
    same question asked twice.
    """
    known = coverlay.names()
    on = rv.overlay()
    # By the file's own stem, without reading a single one: working this
    # out by loading each and comparing display names meant an unreadable
    # overlay anywhere in the directory took the screen down on `o`. Now
    # a bad file only bites when you pick it, and `lay_over` catches it.
    rows = [(MINE if on is not None and k == on.called else 'plain', k)
            for k in known]
    rows.append(('plain' if on is not None else MINE, 'no overlay'))
    got = tui.choose('lay it out to...', rows)
    if got is None:
        return None, False
    return (None if got == len(known) else known[got]), True


def _ran(tui, title, lines):
    """Show what a subprocess said, and wait. The transcript model, which
    is what `core/tui.py` keeps it for."""
    tui.page(title)
    for line in lines:
        tui.log(f'  {line}')
    tui.log('')
    tui.log('  The vocabulary on screen is the one from the start of '
            'this run.')
    tui.log('  Quit and come back to read the new one.')
    tui.wait_any_key()


def _browse(scr, tui, rv):
    """The whole vocabulary, to take something out of. Returns a line.

    The list this screen was built around holds what somebody asked for;
    this holds what the game accepts. 147 rows against 5856 across the
    family, and until now nothing here knew the rest was there.

    Windowed rather than sized to content: MSFS ships 3111 actions
    and a box that quietly drops what does not fit would be worse
    than no box.
    """
    order = [a for _cat, group in cactions.grouped(rv.catalogue)
             for a in group]
    bound = {b.action for n in rv.needs for slot in n.bindings for b in slot}
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
        # so a box drawn without them reads as an unfinished one.
        for row in range(1, h - 1):
            _put(scr, row, 0, ctui.V, tui.theme.head)
            _put(scr, row, w - 1, ctui.V, tui.theme.head)
        for i, a in enumerate(shown[top:top + page - 1]):
            y = 1 + i
            mark = '+' if a.id in bound else ' '
            tone = (tui.theme.sel if top + i == sel
                    else tui.theme.mine if a.id in bound else tui.theme.plain)
            _put(scr, y, 2, f'{mark} {a.name[:38]:38}', tone)
            _put(scr, y, 43, f'{a.kind:6} {a.id[:w - 46]}', tui.theme.meta)
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
            # Typed, not a keystroke. It is the one destructive thing on
            # this screen, and a finger landing on D beside the f it was
            # going for should not be enough.
            sure = _ask(scr, tui, "type 'drop' to forget the vocabulary: ")
            if (sure or '').strip() == 'drop':
                _ran(tui, 'forgetting what was read', rv.drop())
            else:
                said = 'left alone'
        elif k == 'enter' and shown:
            where = _pick_category(scr, tui, rv)
            if where:
                said = rv.promote(shown[sel], where)
                bound = {b.action for n in rv.needs
                         for slot in n.bindings for b in slot}


# ------------------------------------------------------------------ the loop

def _loop_keys():
    """The source of the key loop, for the collision check above.

    Read rather than listed: a list of keys beside the loop is a second
    place to forget, and this one only has to be right about which
    letters appear in it.
    """
    import inspect
    return inspect.getsource(_loop)


def run(layout, title, subtitle='', describe=None, write=None, paths=(),
        catalogue=(), source='', save=None, harvest=None, drop=None,
        rules=None, rebuild=None, game='', offers=()):
    """Show the need list, let it be filled, write what has a control.

    Returns what was written, or the `Adapter` an offer asked to reopen
    on: a game's own key may change what the screen is OF -- DCS lays out
    one aircraft at a time -- and that is a different list, a different
    store and a different kneeboard, so it is a new screen.
    """
    sticks = Sticks(layout)
    rv = Review(layout, title, subtitle, describe, paths, catalogue,
                source, save, harvest, drop, rules, rebuild, game, offers)
    try:
        return curses.wrapper(_loop, rv, write, sticks)
    finally:
        sticks.close()


def _loop(scr, rv, write, sticks):
    tui = ctui.setup(scr)
    state = {'top': 0}
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

    while True:
        rows = rv.rows()
        if sel >= len(rows) or not rows[sel].selectable:
            move(0)
        _draw(scr, rv, sel, state, tui.theme)
        k = tui.key(0.5)
        if k is None:
            continue
        # By kind, not by `selectable`: a heading is selectable now and
        # carries no need, so every handler that wants one still gets
        # None and does nothing. The ones that act on a GROUP ask for the
        # kind themselves.
        here = rows[sel] if 0 <= sel < len(rows) else Row('gap', '')
        need = here.need if here.kind == 'need' else None
        group = here.group if here.kind == 'head' else None

        if k in ('q', 'Q', 'esc'):
            if rv.unsaved and rv.save is not None:
                # The same box `s` puts up, so leaving is not a second way
                # of saving with its own idea of what it is about to
                # write. This is what sim-device-map does on the way out.
                _save(scr, tui, rv)
            return written
        if k in ('up', 'k'):
            move(-1)
            rv.status = ''
        elif k in ('down', 'j'):
            move(+1)
            rv.status = ''
        elif k == 'g':
            move(-len(rows))
            rv.status = ''
        elif k == 'G':
            move(len(rows))
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
        elif k == 'x' and need is not None:
            rv.status = rv.clear(need)
        elif k == 'X':
            rv.status = rv.clear_all()
        elif k == 'enter' and need is not None:
            rv.status = _by_press(scr, tui, rv, need, sticks)
        elif k in ('l', 'L') and need is not None:
            rv.status = _by_hand(scr, tui, rv, need)
        elif k in ('f', 'F'):
            # Typed and confirmed: narrow to it. Confirmed with nothing in
            # it: show everything again. ESC: leave the filter as it was.
            got = _ask(scr, tui, 'filter: ', rv.filter)
            if got is not None:
                rv.filter = got
                state['top'] = 0
                move(-len(rv.rows()))
                rv.status = (f'showing what matches {got!r}' if got
                             else 'showing everything')
        elif k in ('h', 'H'):
            rv.show_binds = not rv.show_binds
            state['top'] = 0
            rv.status = ('showing what each one binds'
                         if rv.show_binds else 'binds hidden')
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
                # at means nothing now. Every other shape change here
                # resets to the top; that would lose what you were doing.
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
                # An Adapter: reopen the screen on it. Which drops
                # everything this one is holding, so it asks first --
                # changing aircraft is a way out of this screen, and the
                # other way out has asked since there was a file to ask
                # about. This one took the evening with it in silence.
                if rv.unsaved and rv.save is not None:
                    _save(scr, tui, rv)
                return got
            rv.status = got
        elif k == 'i' and need is not None:
            rv.status = rv.turn_round(need)
        # `J`, because `j` is a step down the list and the step wins:
        # the chain answered it there and this branch was unreachable,
        # so the sill advertised a key that did nothing at all.
        elif k == 'J' and need is not None:
            job = _pick_job(tui, need)
            if job:
                rv.status = rv.refile_job(need, job)
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
            # SPACE was keep/drop before the table grew a third state. It is
            # kept as confirm, because that is the one a walk through the list
            # presses over and over.
            rv.status = rv.confirm(need)
            move(+1)


def _by_press(scr, tui, rv, need, sticks):
    """Assign by pressing the control, the way the capture wizards do.

    A box rather than the transcript. `wait_input` only reads `tui` to
    notice ESC, so the prompt can stay on screen while it blocks -- and
    every other thing that interrupts this screen is a box.
    """
    devices = sticks.open()
    if not devices:
        return (f'No stick answers: {sticks.why} Press l to pick from a '
                'list.')

    # The product, as the map and the detail panel name it. `d.name` is
    # the raw evdev string, which carries a vendor and a firmware date --
    # noise here, and a second name for one stick on one screen.
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
        lines += [('plain', '  any position; the whole control is taken'),
                  ('plain', '  and the bindings go in its own order')]
    tui.box(need.what, lines, tail='ESC leaves it as it is')
    ccapture.drain(devices, tui)

    # One key, and it reads whichever kind of input the row is for: an
    # axis need is answered by moving a lever, a button need by pressing
    # a button, and that was two keys and two code paths.
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
    idx = tui.choose(f'{need.what} — wants {need.first_shape}', labels)
    if idx is None:
        return f'{need.what} stays as it was.'
    role, ctrl = fits[idx]
    rv.assign(need, role, ctrl)
    return f'{need.what} -> {role}/{ctrl.label}  (yours)'


def _write_plan(rv, width):
    """What `w` is about to do, before it does it.

    The keystroke overwrites a game's config and there was nothing between
    the press and the file. What it writes and where is exactly the thing
    a reader would want to check, and it was only ever printed afterwards.
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
    # Named, because they go into the same files and a plan reading `0
    # bindings` over a write that is about to lay down nine axes is a
    # box that has not said what it is about to do.
    if kept.on_axes:
        say('plain',
            f'  {ctui.plural(len(kept.on_axes), "axis", "axes")}')
    if mine:
        say(MINE, f'  {MARK[MINE]}{mine} {MARK_SAID[MINE]}')
    if prop:
        # Before the keystroke, not after it. `?` means you have not been
        # through them, and they go into the file either way -- which is
        # a thing to learn while you can still say no.
        say(PROPOSED, f'  {MARK[PROPOSED]}{prop} {MARK_SAID[PROPOSED]}')
        say(PROPOSED, '  The write includes them.', lead='  ')
    return out


def _save_plan(rv, width):
    """What `s` is about to keep, before it keeps it.

    The counts, because that is what changed: a save writes the whole
    list, and the question a reader has is how much of it is theirs now.
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
        # They go in the file either way, which is a thing to learn while
        # you can still say no.
        say(PROPOSED, f'  {MARK[PROPOSED]}{prop} {MARK_SAID[PROPOSED]}')
        say(PROPOSED, '  The save includes them.', lead='  ')
    if unset:
        say('unset', f'  {unset} {MARK_SAID[UNSET]}')
    # And what it is that the files do not have. The counts answer how
    # much is being written, which is not the question somebody has when
    # this box comes up on the way out after they pressed `s`: that
    # question is what changed since, and twelve keys can have changed
    # it -- one of them a button read off the stick while the box that
    # asked for it was on screen.
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
    # which way round they run -- nine rows for the Hornet -- and this
    # refused to write any of it because no BUTTON had a home. One list
    # now, so the question is simply whether anything is placed.
    if not kept.placed:
        rv.status = 'No row has a control. There is nothing to write.'
        return None
    if not tui.confirm('write', _write_plan(rv, tui.inner())):
        rv.status = 'The write did not happen.'
        return None
    # Every writer in the family reports by printing, and some warn on stderr.
    # Under curses that lands on the screen being drawn, so it is caught here
    # and shown afterwards -- cheaper than teaching six writers to return
    # text they already print.
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
    # The two that matter, in the tone that says so: a refusal or an error
    # is one line in whatever a writer printed, and finding it was the
    # reader's problem.
    said += [('unset' if str(ln).startswith(('refused:', 'ERROR:'))
              else 'plain', str(ln)) for ln in (extra or [])]
    tui.popup('written' if written else 'not written',
           said or [('meta', 'The writer said nothing.')])
    rv.status = ('The files are written.' if written
                 else 'The write did not happen.')
    return written

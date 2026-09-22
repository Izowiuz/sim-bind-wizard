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
import textwrap

from core import actions as cactions
from core import capture as ccapture
from core import needs as corneeds
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
        self.kind = kind                # 'head' | 'need' | 'bind' | 'gap'
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
                 paths=(), catalogue=(), save=None, harvest=None,
                 drop=None):
        self.layout = layout
        self.title = title
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
        #: How the judgements get written down. A game that derives its
        #: needs has none, and the screen has to cope rather than raise:
        #: it cannot help, and taking the review down over it would be
        #: worse than saying so.
        self.save = save
        #: Reading the game again, and forgetting what was read. Both are
        #: `bind`'s own verbs run as subprocesses; neither can touch the
        #: judgements, because `drop` walks `CACHE` and the judgements are
        #: deliberately not in it.
        self.harvest = harvest
        self.drop = drop
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

        #: what the planner worked out, per need. A need it could not place
        #: has none, and `p` on that row has nothing to offer.
        self.plan = {p.need: p for p in layout.placed}
        #: every need the planner was asked about, placed or not
        self.needs = [p.need for p in layout.placed] + list(layout.unplaced)
        #: where each need sits now, and how it got there
        self.at = {n: self.plan.get(n) for n in self.needs}
        self.mark = {n: (PROPOSED if self.at[n] else UNSET)
                     for n in self.needs}

    # -------------------------------------------------------------- reading

    def counts(self):
        """(yours, proposed, unset)."""
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
        """The one-line answer to 'what is this on?'."""
        p = self.at[need]
        return '(unset)' if p is None else f'{p.role} · {p.ctrl.label}'

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
        """The need sitting on this control right now, or None."""
        for need, p in self.at.items():
            if p is not None and p.role == role and p.ctrl is ctrl:
                return need
        return None

    def why_not(self, need, role, ctrl):
        """None if this need may go on this control, else the reason.

        The by-hand list can only offer what fits, so it never needs this.
        Pressing a button can land anywhere -- on a lever, on a hat with too
        few positions, on something another need already has -- and answering
        "no" without saying why is the worst of the three.
        """
        if ctrl is None:
            return 'that button is not in the device map'
        if not ctrl.bindable:
            return f'{ctrl.label} carries no binding'
        if ctrl.kind not in need.shapes:
            return (f'{ctrl.label} is a {ctrl.kind}; {need.what} wants '
                    f'{need.first_shape}')
        if len(ctrl.bindable_buttons) < need.wanted:
            return (f'{ctrl.label} has '
                    f'{ctui.plural(len(ctrl.bindable_buttons), "bindable "
                                       "button")}; {need.what} needs '
                    f'{need.wanted}')
        holder = self.who_has(role, ctrl)
        if holder is not None and holder is not need:
            return f'{ctrl.label} is carrying {holder.what} — x clears it'
        return None

    def control_at(self, role, button):
        """The map's control owning a raw kernel button number."""
        dev = self.layout.devices.get(role)
        return None if dev is None else dev.group_of(button)

    def took(self, need, role, button):
        """Assign from a button somebody pressed, or say why not.

        Everything that happens after `capture.wait_input` returns, in one
        call with no terminal in it -- so the only part of pressing a control
        that cannot be tested is reading the kernel, which two shipping
        wizards already do with this same code.
        """
        ctrl = self.control_at(role, button)
        no = self.why_not(need, role, ctrl)
        if no:
            return f'{need.what}: {no}'
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

        `[(tone, text)]` rather than bare lines. The pager cannot tell a
        device heading from a control carrying something, and the tone is the
        one thing only this method knows; naming it here is also what keeps
        the two screens honest, because a control wears the state of the need
        on it and that state is the same word the table draws its row with.

        Every control also carries the table's own `?`/`+` mark. Colour was
        the only thing saying which controls were spoken for, and a colour
        nobody has been taught is just some of the rows being a different
        colour -- so the mark says it in text, the legend says what the mark
        means, and the colour is left to do what it is good at, which is
        being seen without being read.
        """
        out = []
        if self.paths:
            out.append(('head', 'WHERE'))
            # Each path on its own line: a Proton prefix is 90 characters
            # before it says anything, and a truncated path answers nothing.
            for label, path in self.paths:
                out.append(('subhead', f'  {label}'))
                out.extend(('meta', f'    {ln}') for ln in _fold(str(path)))
            out.append(('plain', ''))
        out.append(('head', 'DEVICE MAP'))
        # The legend is four lines because a line carries one tone, and a
        # legend that is not drawn in the colours it explains explains
        # nothing. This is the screen somebody opens to find a spare
        # control, so what the colours mean is what they came for.
        for state in (MINE, PROPOSED, UNSET):
            out.append((state, f'  {MARK[state]} {MARK_SAID[state]}'))
        for role, dev in self.devices():
            ids = f'    {dev.slug} · usb {dev.usb or "?"}'
            if dev.serial:
                ids += f' · serial {dev.serial}'
            out.append(('plain', ''))
            out.append(('subhead', f'  {role}  {dev.product}'))
            out.append(('meta', ids))
            out.append(('meta', f'    {dev.n_buttons} buttons,'
                                f' {dev.n_axes} axes · {dev.path}'))
            out.append(('plain', ''))
            for ctrl in dev.groups():
                held = self.who_has(role, ctrl)
                parts = [','.join(str(b) for b in ctrl.buttons)]
                if ctrl.push is not None:
                    parts.append(f'+{ctrl.push}')
                if ctrl.axes:
                    parts.append('ax' + ','.join(str(a) for a in ctrl.axes))
                btns = ' '.join(x for x in parts if x)
                # Carrying something -> that need's state, mark and
                # colour alike, which is exactly how the table draws it.
                # Free and bindable -> plain, because a spare control is the
                # normal case and colouring the normal case says nothing.
                # Bindable by nothing -> as dim as the ids above it, which
                # is what it is worth.
                state = self.mark[held] if held else None
                tone = state or ('plain' if ctrl.bindable else 'meta')
                out.append((tone,
                            f'  {MARK[state] if state else " "} '
                            f'{ctrl.kind:10} {ctrl.label[:26]:26} '
                            f'{(btns or "-")[:16]:16} '
                            f'{(ctrl.reach or ""):24.24} '
                            + (held.what if held else
                               ('' if ctrl.bindable
                                else '(carries nothing)'))))
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
        """Put the planner's suggestion on this need."""
        if self.mark[need] == MINE:
            return f'{need.what}: yours already — x clears it first'
        p = self.plan.get(need)
        if p is None:
            return f'{need.what}: the planner had nowhere to put it'
        busy = self.occupied(besides=need)
        if any((p.role, b) in busy for b, _v in p.slots):
            return f'{need.what}: {p.ctrl.label} is taken now'
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
        return (f'proposed {done} from the plan — marked ?, walk them'
                if done else 'nothing left for the plan to fill')

    def confirm(self, need):
        if self.at[need] is None:
            return f'{need.what}: nothing to confirm'
        if self.mark[need] == MINE:
            return f'{need.what}: already yours'
        self.mark[need] = MINE
        return f'{need.what}: confirmed — {self.where(need)}'

    def confirm_all(self):
        n = sum(1 for need in self.needs if self.mark[need] == PROPOSED)
        for need in self.needs:
            if self.mark[need] == PROPOSED:
                self.mark[need] = MINE
        return (f'confirmed {n} proposal{"" if n == 1 else "s"}' if n
                else 'nothing left to confirm')

    def clear(self, need):
        if self.at[need] is None:
            return f'{need.what}: already unset'
        self.at[need] = None
        self.mark[need] = UNSET
        return f'{need.what}: cleared — its control is free again'

    def clear_all(self):
        """Drop every proposal, and only the proposals.

        The mirror of `confirm_all`, and the way back out of a `P` you did
        not want. What you chose by hand is never touched, for the same
        reason `propose_all` never overwrites it: a key that could undo an
        hour of your own decisions is one you would stop pressing.
        """
        drop = [need for need in self.needs if self.mark[need] == PROPOSED]
        for need in drop:
            self.clear(need)
        n = len(drop)
        return (f'dropped {n} proposal{"" if n == 1 else "s"} — what is '
                'yours stayed' if n else 'no proposals left to drop')

    def honours_press(self, need, ctrl, button):
        """Whether the exact button pressed is what this need should land on.

        `slots_for` picks for a need with one binding: on a control that
        clicks it takes the click, otherwise the first position -- which is
        right when nobody said where, and wrong the moment somebody presses a
        thing. Pressing the second detent of a trigger and being given the
        first is the tool overruling a choice you just made by hand.

        Two exceptions. A need wanting several bindings is asking for the
        whole control and its own direction order decides, not the corner you
        happened to touch. And a need with `on` has made a claim about the
        hardware -- a speedbrake is fore/aft whatever hat it lands on -- which
        is exactly the lie `on` exists to stop, so it keeps winning.
        """
        return (len(need.bindings) == 1 and not need.on
                and button in ctrl.bindable_buttons)

    def assign(self, need, role, ctrl, button=None):
        """Give a need a control by hand. Yours at once, with no confirming
        step: you just chose it.

        `button` is the one actually pressed, when a press is what did this.
        """
        spots = []
        buttons = corneeds.slots_for(need, ctrl, why=spots)
        if button is not None and self.honours_press(need, ctrl, button):
            buttons = [button]
            spots = [(button, 'the button you pressed')]
        slots = [(b, v) for b, v in zip(buttons, need.bindings)
                 if v]
        if need.push is not None and ctrl.push is not None:
            slots.append((ctrl.push, need.push))
        was = self.at[need]
        # Putting it back where it already was is not an override, and a
        # panel saying "moved from Thumb button" about a binding ON the
        # thumb button would be the screen arguing with the person reading
        # it. `is` on the control rather than the label: two controls can
        # share a label across devices, and the role is checked anyway.
        moved = was is not None and not (was.role == role
                                         and was.ctrl is ctrl)
        why = corneeds.Reason('yours', instead=was if moved else None)
        corneeds.hand_out(slots, role, why, spots)
        placed = corneeds.Placement(need, role, ctrl, slots, 0, why)
        self.at[need] = placed
        self.mark[need] = MINE
        return placed

    def categories(self):
        """Every group there is, so a menu can offer them before asking
        for a new name. Bands included: filing something under `in a
        turn` is a choice like any other, and refusing to offer it would
        make the fallback a place you can leave but not return to."""
        return sorted({self.group_of(n) for n in self.needs})

    def _kept(self):
        """Write the judgements down, and say what happened either way."""
        if self.save is None:
            return ' (nowhere to write it, so it lasts until you quit)'
        try:
            self.save(self.needs)
        except (OSError, RuntimeError) as e:
            return f' -- but it could not be written: {e}'
        return ''

    def refile(self, need, category):
        """Move a need to another group. Returns a line.

        Naming its own band puts it back on the fallback rather than
        recording the band as a category: otherwise `in a turn` becomes a
        place you can leave and not return to, and two things that look
        identical on screen differ in the file.
        """
        need.category = (None if category ==
                         corneeds.URGENCY_NAME[need.urgency] else category)
        return f'{need.what} filed under {category}{self._kept()}'

    def rename(self, old, new):
        """Call a group something else, without emptying it first.

        A band is refused: there are four, they are the allocator's scale,
        and renaming one here would say they are yours to name when they
        are not. Refiling out of one is how you leave it.
        """
        if old in corneeds.URGENCY_NAME:
            return f'{old!r} is a band, not a category -- use r to file '\
                   'things out of it'
        moved = [n for n in self.needs if n.category == old]
        for n in moved:
            n.category = new
        return f'{len(moved)} moved from {old} to {new}{self._kept()}'

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
            return (f'{action.name} was already on the list, moved to '
                    f'{category}{self._kept()}')
        if action.kind == 'axis':
            # Axes never went through the allocator in any game in the
            # family, so there is nothing for a promoted one to land on.
            return (f'{action.name} is an axis; those are planned by the '
                    'game, not placed here')
        need = corneeds.Need(action.name, 'button',
                             [[cactions.Bind(action.id)]],
                             category=category)
        self.needs.append(need)
        self.at[need] = None
        self.mark[need] = UNSET
        return f'{action.name} added to {category}{self._kept()}'

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
        """
        held = {}
        for need in self.needs:
            held.setdefault(self.group_of(need), []).append(need)
        return [(name, held[name]) for name in
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

#: Two lines, because one was 96 characters and a terminal is 80: `w write`
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
    ('plain', '  One entry per thing to be able to do, and the control it'),
    ('plain', '  got. Nothing reaches the game until w.'),
    ('plain', ''),
    ('head', 'MARKS'),
    ('mine', f'  {MARK[MINE]}           {MARK_SAID[MINE]}'),
    ('proposed', f'  {MARK[PROPOSED]}           {MARK_SAID[PROPOSED]}'),
    ('unset', f'  (none)      {MARK_SAID[UNSET]}'),
    ('plain', ''),
    ('head', 'MOVING'),
    ('plain', '  ↑↓  j k     previous / next entry'),
    ('plain', '  g  G        first / last entry'),
    ('plain', '  f           filter by text; empty clears'),
    ('plain', '  h           toggle the bindings under each entry'),
    ('plain', ''),
    ('head', 'ASSIGNING'),
    ('plain', '  ↵           assign by pressing a control'),
    ('plain', '  l           assign from a list of controls that fit'),
    ('plain', '  c  C        accept this proposal / every proposal'),
    ('plain', '  SPACE       accept, then move down'),
    ('plain', '  p  P        restore the proposal here / in every gap'),
    ('plain', '  x  X        unassign this / every proposal'),
    ('plain', ''),
    ('head', 'THE LIST'),
    ('plain', '  a           browse the game\'s vocabulary and add entries'),
    ('plain', '  r           move this entry to another category'),
    ('plain', '  R           rename the category it is in; all of it moves'),
    ('plain', ''),
    ('head', 'OTHER'),
    ('plain', '  m           device map and install paths'),
    ('plain', '  w           write the plan to the game'),
    ('plain', '  q           quit'),
)


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
HINTS = ('↑↓ move', '↵ assign', 'l list', 'c accept', 'x unassign',
         'a add', 'r category', 'f filter', 'h binds', 'm map', 'w write')


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
        say('meta', f'wants {need.first_shape}, '
            f'{ctui.plural(need.wanted, "button")}')
        say('plain')
        say('meta', f'the planner would use {plan.ctrl.label}' if plan
            else 'the planner had nowhere to put it')
        say('plain')
        say('note', f'{ctui.plural(len(rv.fits(need)), "control")} fit')
        return out

    say('head', 'WHERE')
    say('subhead', p.role)
    dev = rv.layout.devices.get(p.role)
    if dev is not None:
        say('meta', dev.product)
    say('plain', p.ctrl.label)
    say('meta', f'{p.ctrl.kind} · {ctui.plural(len(p.slots), "binding")}')
    if p.ctrl.reach:
        say('meta', p.ctrl.reach)

    binds = rv.binds(need)
    if binds:
        say('plain')
        say('head', 'BINDS')
        for part, what in binds:
            say('plain', what, lead=f'{part[:7]:<7} ')

    say('plain')
    say('head', 'WHY')
    _why(rv, need, p, say)
    return out


def _group_side(rv, name, width):
    """What a heading is, when the cursor is on one.

    It answered nothing before, so landing on a heading left an empty box
    -- which reads as a hole rather than as a thing you are standing on.
    """
    out = []

    def say(tone, text='', lead=''):
        out.extend((tone, piece) for piece in _fit(width, text, lead))

    members = dict(rv.groups()).get(name, [])
    say('head', 'CATEGORY')
    say('subhead', name)
    if name in corneeds.URGENCY_NAME:
        # Before the keystroke rather than after it: `R` refuses a band,
        # and finding that out by pressing it is finding it out late.
        say('note', 'a band, not yours to rename')
        say('meta', 'r files things out of it')
    say('plain')
    say('head', 'HOLDS')
    say('plain', ctui.plural(len(members), 'entry', 'entries'))
    tally = collections.Counter(rv.mark[n] for n in members)
    for state in (MINE, PROPOSED, UNSET):
        if tally[state]:
            say(state, f'{tally[state]} {MARK_SAID[state]}')
    return out


def _why(rv, need, p, say):
    """The account of how this binding came to be here.

    Whose decision it was comes first, because it is the one a reader may
    want to undo. `instead` is not consulted for the wording: it records
    the placement a hand displaced, which is the immediate history, while
    the question on screen is what the PLANNER wanted -- and `rv.plan` is
    the only thing that still answers that after a second move.
    """
    r, plan = p.why, rv.plan.get(need)
    # The legend's words, not new ones: three screens name these states
    # and one wording is one thing to learn.
    state = rv.mark[need]
    say(state, MARK_SAID[state])
    if r is not None and r.overridden:
        if plan is None:
            say('meta', 'planner had no control for it')
        elif plan.role == p.role and plan.ctrl is p.ctrl:
            say('meta', "same as the planner's choice")
        else:
            say('meta', f'moved from {plan.ctrl.label}')
    elif state == MINE:
        say('meta', 'proposal accepted')

    say('plain')
    say('meta', corneeds.URGENCY_NAME[need.urgency])
    if need.rank:
        say('meta', f'{ctui.plural(need.rank, "factory profile")} bind it')
    if r is None:
        say('note', 'no account recorded')
        return
    if r.how in corneeds.CAME_BY:
        say('note', corneeds.CAME_BY[r.how])

    # Biggest first: the term that decided it should be the one read first,
    # and the order `score()` applies them in is an accident of how the
    # rules are written down rather than of what mattered.
    if r.parts:
        say('plain')
        for delta, what in sorted(r.parts, key=lambda q: -abs(q[0])):
            say('meta', what, lead=f'{delta:+5} ')

    if need.note:
        say('plain')
        say('note', need.note)

    # Only where there is something to tell apart. One bind on one button
    # has nothing to say about which, and a heading over the obvious is a
    # line you learn to skip past.
    spots = [(p.ctrl.direction(n) or 'press', b.reason.spot)
             for n, slot in p.slots for b in slot
             if getattr(b, 'reason', None) and b.reason.spot]
    if len(p.slots) > 1 and spots:
        say('plain')
        say('head', 'WHICH BUTTON')
        if len({t for _part, t in spots}) == 1:
            # One sentence four times is one sentence. The labels add
            # nothing here -- BINDS above already lists them in order.
            say('meta', spots[0][1])
        else:
            for part, spot in spots:
                say('meta', spot, lead=f'{part[:7]:<7} ')


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


def box_for(body, h, w, title):
    """(y, x, height, width) for a box holding `body` on an h x w screen.

    Sized to what it holds and no larger: a help box with three inches of
    blank border says the list is longer than it is. Capped at the screen,
    which is where `overflows` takes over.
    """
    inner = max((len(t) for t in body), default=0)
    bw = min(w - 2, max(len(title) + 6, inner + 4))
    bh = min(h - 2, len(body) + 2)
    return (h - bh) // 2, (w - bw) // 2, bh, bw


def overflows(body, h, w, title):
    """Is there more than the box can show at once?"""
    return len(body) > box_for(body, h, w, title)[2] - 2


def _box(scr, theme, title, lines, keys=(), tail='', top=0, sel=None):
    """Draw a framed box over the middle of the screen. Returns its page.

    Framed by the same `lid`/`sill` the panels use, so every box on this
    screen -- the help, the control list, the prompt to press something --
    reads as one kind of thing rather than three.
    """
    body = [t for _tone, t in lines]
    h, w = scr.getmaxyx()
    y, x, bh, bw = box_for(body, h, w, title)
    page = bh - 2
    _put(scr, y, x, ctui.lid(bw, title), theme.head)
    for n in range(page):
        _put(scr, y + 1 + n, x, ctui.V + ' ' * (bw - 2) + ctui.V, theme.head)
    _put(scr, y + bh - 1, x, ctui.sill(bw, keys, tail), theme.head)
    for n, (tone, text) in enumerate(lines[top:top + page]):
        lit = theme.sel if sel is not None and top + n == sel else theme[tone]
        _put(scr, y + 1 + n, x + 2, text[:bw - 4], lit)
    scr.refresh()
    return page


def _popup(scr, tui, theme, title, lines):
    """A box you read and dismiss.

    Scrolls rather than truncates. It used to draw `lines[:bh - 2]` and
    stop, so on a short terminal the help simply ended -- and what fell
    off the bottom was the least-used half, which is the half somebody
    opening the help is most likely to be after.
    """
    body = [t for _tone, t in lines]
    top = 0
    while True:
        h, w = scr.getmaxyx()
        page = box_for(body, h, w, title)[2] - 2
        more = overflows(body, h, w, title)
        top = max(0, min(top, len(body) - page)) if more else 0
        _box(scr, theme, title, lines,
             ('↑↓ more', 'any other key closes') if more else (),
             f'{top + page} of {len(body)}' if more else 'any key to close',
             top)
        k = tui.key(0.5)
        if k is None:
            continue
        if more and k in ('up', 'k'):
            top -= 1
        elif more and k in ('down', 'j'):
            top += 1
        elif more and k == ' ':
            top += page
        else:
            return


def _choose(scr, tui, title, lines, tail=''):
    """A box you pick a line out of. Returns the index, or None on ESC."""
    sel = top = 0
    while True:
        h, w = scr.getmaxyx()
        page = box_for([t for _tone, t in lines], h, w, title)[2] - 2
        sel = max(0, min(sel, len(lines) - 1))
        if sel < top:
            top = sel
        elif sel >= top + page:
            top = sel - page + 1
        _box(scr, tui.theme, title, lines,
             ('↑↓ move', '↵ choose', 'ESC back'),
             f'{sel + 1} of {len(lines)}', top, sel)
        k = tui.key(0.5)
        if k in ('up', 'k'):
            sel -= 1
        elif k in ('down', 'j'):
            sel += 1
        elif k == 'g':
            sel = 0
        elif k == 'G':
            sel = len(lines)
        elif k == 'enter':
            return sel
        elif k == 'esc':
            return None


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
    mine, prop, unset = rv.counts()
    # The filter when there is one, the tally otherwise: both answer "what
    # am I looking at", and only one of them can be true at a time.
    # Only what is there. The long form was dropped whole by `lid` for
    # not fitting beside the title, so the counts vanished from a screen
    # that had always carried them.
    counts = [f'{MARK[MINE]}{mine}' if mine else '',
              f'{MARK[PROPOSED]}{prop}' if prop else '',
              f'{unset} {MARK_SAID[UNSET]}' if unset else '']
    right = rv.narrowed() or ctui.SEP.join(c for c in counts if c)
    # Needs, not every selectable row: this says which of the things you
    # are placing you are on, and a heading is not one of them.
    pick = [i for i, r in enumerate(rows) if r.kind == 'need']
    at = sum(1 for i in pick if i <= sel)
    iy, ix, ih, iw = _panel(
        scr, theme, (ly, lx, lh, lw),
        rv.title + (f' · {rv.subtitle}' if rv.subtitle else ''),
        right, HINTS,
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
    name = (row.need.what if row and row.kind == 'need'
            else row.group if row and row.kind == 'head' else '')
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


def _pager(scr, tui, title, lines):
    """Show `(tone, text)` lines, scroll them, leave on ESC or q.

    `core/tui.py` keeps a transcript and repaints its tail, which is right for
    a capture prompt and wrong for a listing longer than the screen -- the
    device map is thirty lines before it has said anything about the second
    stick.
    """
    top = 0
    while True:
        h, w = scr.getmaxyx()
        page = max(1, h - 3)
        top = max(0, min(top, max(0, len(lines) - page)))
        scr.erase()
        _put(scr, 0, 0, title, tui.theme.title)
        for i, (tone, text) in enumerate(lines[top:top + page]):
            _put(scr, 1 + i, 0, text, tui.theme[tone])
        more = f'{top + 1}-{min(len(lines), top + page)} of {len(lines)}'
        _put(scr, h - 1, 0,
             f'↑↓ jk scroll · SPACE page · g/G first/last · '
             f'q back    {more}')
        scr.refresh()
        k = tui.key(0.5)
        if k in ('esc', 'q', 'Q', 'enter'):
            return
        if k in ('up', 'k'):
            top -= 1
        elif k in ('down', 'j'):
            top += 1
        elif k == 'g':
            top = 0
        elif k == 'G':
            top = len(lines)
        elif k == ' ':
            top += page


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
    got = _choose(scr, tui, 'file it under',
                  [('plain', k) for k in known] + [('meta', 'a new one...')])
    if got is None:
        return None
    if got < len(known):
        return known[got]
    name = _ask(scr, tui, 'new category: ')
    return name.strip() or None if name is not None else None


def _ran(tui, title, lines):
    """Show what a subprocess said, and wait. The transcript model, which
    is what `core/tui.py` keeps it for."""
    tui.page(title)
    for line in lines:
        tui.log(f'  {line}')
    tui.log('')
    tui.log('  the vocabulary on screen is the one loaded at start --')
    tui.log('  quit and come back to read the new one')
    tui.wait_any_key()


def _browse(scr, tui, rv):
    """The whole vocabulary, to take something out of. Returns a line.

    The list this screen was built around holds what somebody asked for;
    this holds what the game accepts. 147 rows against 5856 across the
    family, and until now nothing here knew the rest was there.

    Windowed like `_pager` and not sized to content like `_popup`: MSFS
    ships 3111 actions and a box that quietly drops what does not fit
    would be worse than no box.
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
        _put(scr, 0, 0, ctui.lid(w, 'vocabulary', right), tui.theme.head)
        for i, a in enumerate(shown[top:top + page - 1]):
            y = 1 + i
            mark = '+' if a.id in bound else ' '
            tone = (tui.theme.sel if top + i == sel
                    else tui.theme.mine if a.id in bound else tui.theme.plain)
            _put(scr, y, 2, f'{mark} {a.name[:38]:38}', tone)
            _put(scr, y, 43, f'{a.kind:6} {a.id[:w - 58]}', tui.theme.meta)
            if a.rank:
                _put(scr, y, w - 12, f'{a.rank:>4} bind', tui.theme.meta)
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

def run(layout, title, subtitle='', describe=None, write=None, paths=(),
        catalogue=(), save=None, harvest=None, drop=None):
    """Show the need list, let it be filled, write what has a control.
    Returns the `Layout` that was written, or None if nothing was."""
    sticks = Sticks(layout)
    rv = Review(layout, title, subtitle, describe, paths, catalogue,
                save, harvest, drop)
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
            _popup(scr, tui, tui.theme, 'help', KEYS)
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
        elif k in ('m', 'M'):
            _pager(scr, tui, f'{rv.title} — device map', rv.map_lines())
        elif k in ('w', 'W'):
            written = _write(tui, rv, write) or written
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
        return f'no sticks to read: {sticks.why} — l picks from a list'

    # The product, as the map and the detail panel name it. `d.name` is
    # the raw evdev string, which carries a vendor and a firmware date --
    # noise here, and a second name for one stick on one screen.
    known = rv.layout.devices
    lines = [('head', 'DEVICES')]
    lines += [('plain', f'  {d.role:9}  '
                        + (known[d.role].product if d.role in known
                           else d.name))
              for d in devices]
    lines += [('plain', ''), ('head', 'WANTS'),
              ('plain', f'  {need.first_shape}'
                        + (f', {ctui.plural(need.wanted, "button")}'
                           if need.wanted > 1 else '')),
              ('plain', ''), ('head', 'PRESS')]
    if len(need.bindings) == 1 and not need.on:
        lines.append(('plain', '  the exact position you want it on'))
    else:
        lines += [('plain', '  any position; the whole control is taken'),
                  ('plain', '  and the bindings go in its own order')]
    _box(scr, tui.theme, need.what, lines, tail='ESC leaves it as it is')
    ccapture.drain(devices, tui)

    got = ccapture.wait_input(devices, want_axis=False, tui=tui)
    if got == 'skip':
        return f'{need.what}: left as it was'
    dev, _kind, number, _sign = got
    ccapture.drain(devices, tui)

    return rv.took(need, dev.role, number)


def _by_hand(scr, tui, rv, need):
    """Choose a control for this need yourself."""
    fits = rv.fits(need)
    if not fits:
        return f'{need.what}: nothing free has that shape'
    labels = [('plain', f'{role:9} {c.label:30} {c.kind:9} {c.reach or ""}')
              for role, c in fits]
    idx = _choose(scr, tui, f'{need.what} — wants {need.first_shape}', labels)
    if idx is None:
        return f'{need.what}: left as it was'
    role, ctrl = fits[idx]
    rv.assign(need, role, ctrl)
    return f'{need.what} -> {role}/{ctrl.label}  (yours)'


def _write(tui, rv, write):
    if write is None:
        rv.status = 'this game has no writer wired to the review yet'
        return None
    kept = rv.result()
    if not kept.placed:
        rv.status = 'nothing has a control, so there is nothing to write'
        return None
    _mine, prop, _unset = rv.counts()
    tui.page(f'{rv.title} — writing '
         f'{ctui.plural(len(kept.placed), "binding")}')
    if prop:
        tui.log(f'{prop} of them are still marked ? — proposed and not '
                'looked at. They are written too.')
        tui.log('')
    # Every writer in the family reports by printing, and some warn on stderr.
    # Under curses that lands on the screen being drawn, so it is caught here
    # and replayed as log lines -- cheaper than teaching six writers to return
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
    for line in out.getvalue().splitlines():
        tui.log(line)
    for line in (extra or []):
        tui.log(str(line))
    tui.wait_any_key()
    rv.status = 'written' if written else 'not written'
    return written

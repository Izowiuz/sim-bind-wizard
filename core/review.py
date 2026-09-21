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

import contextlib
import curses
import io
import os

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


class Row:
    """One line of the table. `kind` decides what it answers to."""

    def __init__(self, kind, text, need=None):
        self.kind = kind                # 'head' | 'need' | 'bind' | 'gap'
        self.text = text
        self.need = need

    @property
    def selectable(self):
        # A `bind` is the answer to the row above it, not a thing you put
        # anywhere, so moving skips it.
        return self.kind == 'need'


class Review:
    """What the reviewer has decided so far.

    All of it works without a terminal, and every key the screen answers to is
    one call on this -- which is the point of keeping them apart.
    """

    def __init__(self, layout, title, subtitle='', describe=None,
                 paths=()):
        self.layout = layout
        self.title = title
        self.subtitle = subtitle
        self.describe = describe or (lambda p: [])
        #: [(label, path)] the game supplies: where it found the install, the
        #: file it will write. The core cannot know these -- every game hides
        #: its config somewhere else -- and a screen that will overwrite a
        #: file should say which file.
        self.paths = list(paths)
        self.status = ''
        #: what `f` narrowed the action level to. Matched against the
        #: need's own name, not against what it binds: the question `f`
        #: answers is "where is the row for X".
        self.filter = ''
        #: whether `h` is showing what sits under each action.
        self.show_binds = True

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
            return (f'{ctrl.label} has {len(ctrl.bindable_buttons)} '
                    f'bindable button(s); {need.what} needs {need.wanted}')
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
        out.append(('mine', f'  {MARK[MINE]} yours'))
        out.append(('proposed', f'  {MARK[PROPOSED]} the planner\'s,'
                                f' not yet checked'))
        out.append(('plain', f'  {MARK[UNSET]} free'))
        out.append(('meta', f'  {MARK[UNSET]} carries no binding at all'))
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
        buttons = corneeds.slots_for(need, ctrl)
        if button is not None and self.honours_press(need, ctrl, button):
            buttons = [button]
        slots = [(b, v) for b, v in zip(buttons, need.bindings)
                 if v]
        if need.push is not None and ctrl.push is not None:
            slots.append((ctrl.push, need.push))
        placed = corneeds.Placement(need, role, ctrl, slots, 0)
        self.at[need] = placed
        self.mark[need] = MINE
        return placed

    # ----------------------------------------------------------------- rows

    def matches(self, need):
        return (not self.filter
                or self.filter.lower() in need.what.lower())

    def rows(self):
        out = []
        for urgency in sorted({n.urgency for n in self.needs}):
            band = [n for n in self.needs
                    if n.urgency == urgency and self.matches(n)]
            if not band:
                # The heading stays for what is there, not for what the
                # filter took away -- an empty band is a line you scroll
                # past to reach the rows you asked for.
                continue
            out.append(Row('head', corneeds.URGENCY_NAME[urgency].upper()))
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
KEYS = ('↑/↓ j/k move · g/G first/last · RETURN press it · l from list',
        'c/C confirm · p/P from plan · x/X clear · f find · h binds',
        'm map · w write · q quit')


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
    h, w = scr.getmaxyx()
    if 0 <= y < h:
        try:
            scr.addstr(y, x, text[:max(0, w - x - 1)], attr)
        except curses.error:
            pass


def _detail(rv, row):
    """The three lines under the table, about the row you are on."""
    if row is None or row.kind != 'need':
        return []
    need = row.need
    p = rv.at[need]
    out = []
    if p is not None:
        # Nothing: what it binds is on the tree now, under the row. What is
        # left here is the case with no control, which is not a binding and
        # has nowhere else to go.
        pass
    else:
        plan = rv.plan.get(need)
        out.append(f'  wanted {need.first_shape}, {need.wanted} button(s)')
        out.append('  p would put it on ' + plan.ctrl.label if plan
                   else '  the planner had nowhere to put it')
        out.append(f'  {len(rv.fits(need))} free control(s) fit — RETURN to '
                   'choose one')
    return out


def _draw(scr, rv, sel, state, theme):
    h, w = scr.getmaxyx()
    rows = rv.rows()
    detail = 5
    visible = max(3, h - detail - 6)
    top = state['top']
    if sel < top:
        top = sel
    elif sel >= top + visible:
        top = sel - visible + 1
    state['top'] = top

    scr.erase()
    head = rv.title + (f'  ·  {rv.subtitle}' if rv.subtitle else '')
    _put(scr, 0, 0, head, theme.title)
    mine, prop, unset = rv.counts()
    tally = f'{mine} yours · {prop} proposed · {unset} unset'
    _put(scr, 0, max(0, w - len(tally) - 1), tally, theme.head)
    # Which device each role IS, always on screen: a row saying "stick" does
    # not say which stick, and with two of them you had to choose one.
    _put(scr, 1, 0, rv.device_line(), theme.head)
    _put(scr, 2, 0, '─' * (w - 1))

    for i in range(top, min(len(rows), top + visible)):
        row = rows[i]
        y = 3 + i - top
        if row.kind == 'head':
            _put(scr, y, 0, f' {row.text}', theme.head)
        elif row.kind == 'bind':
            _put(scr, y, 6, row.text[:w - 7], theme.meta)
        elif row.kind == 'need':
            # The state name is the tone name, so this screen and the map ask
            # the theme the same question and get the same answer.
            st = rv.mark[row.need]
            attr = theme.sel if i == sel else theme[st]
            line = f'{MARK[st]} {row.text[:28]:28} {rv.where(row.need)}'
            _put(scr, y, 2, line[:w - 3], attr)

    _put(scr, h - detail - 1, 0, '─' * (w - 1))
    for j, line in enumerate(
            _detail(rv, rows[sel] if 0 <= sel < len(rows) else None)[:detail]):
        _put(scr, h - detail + j, 0, line)
    _put(scr, h - 3, 0, rv.status[:w - 1], theme.note)
    for i, line in enumerate(KEYS):
        _put(scr, h - len(KEYS) + i, 0, line[:w - 1])
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


# ------------------------------------------------------------------ the loop

def run(layout, title, subtitle='', describe=None, write=None, paths=()):
    """Show the need list, let it be filled, write what has a control.
    Returns the `Layout` that was written, or None if nothing was."""
    sticks = Sticks(layout)
    rv = Review(layout, title, subtitle, describe, paths)
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
        need = rows[sel].need if rows[sel].selectable else None

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
            rv.status = _by_press(tui, rv, need, sticks)
        elif k in ('l', 'L') and need is not None:
            rv.status = _by_hand(tui, rv, need)
        elif k in ('f', 'F'):
            # Typed and confirmed: narrow to it. Confirmed with nothing in
            # it: show everything again. ESC: leave the filter as it was.
            got = _ask(scr, tui, 'find: ', rv.filter)
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


def _by_press(tui, rv, need, sticks):
    """Assign by pressing the control, the way the capture wizards do."""
    devices = sticks.open()
    if not devices:
        return f'no sticks to read: {sticks.why} — l picks from a list'

    tui.page(f'{need.what} — press the control you want it on')
    tui.log('')
    for d in devices:
        tui.log(f'  {d.role:9} {d.name}')
    tui.log('')
    tui.log(f'  it wants a {need.first_shape}'
            + (f', {need.wanted} buttons' if need.wanted > 1 else ''))
    if len(need.bindings) == 1 and not need.on:
        tui.log('  press the exact position you want it on')
    else:
        tui.log('  press any position — the whole hat, trigger or encoder is')
        tui.log('  taken, and the bindings go in its own order')
    tui.log('')
    tui.log('  ESC to leave it as it is')
    ccapture.drain(devices, tui)

    got = ccapture.wait_input(devices, want_axis=False, tui=tui)
    if got == 'skip':
        return f'{need.what}: left as it was'
    dev, _kind, number, _sign = got
    ccapture.drain(devices, tui)

    return rv.took(need, dev.role, number)


def _by_hand(tui, rv, need):
    """Choose a control for this need yourself."""
    fits = rv.fits(need)
    if not fits:
        return f'{need.what}: nothing free has that shape'
    labels = [f'{role:9} {c.label:34} {c.kind:10} {c.reach or ""}'
              for role, c in fits]
    idx = tui.menu(f'{need.what} — wanted {need.first_shape}', labels,
                   footer='arrows = move, RETURN = put it here, ESC = leave '
                          'it as it is')
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
    tui.page(f'{rv.title} — writing {len(kept.placed)} binding(s)')
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

"""Match things a pilot must be able to do against controls that suit them.

This is the part that existed four times over. Each copy grew its own way and
the differences were not improvements, they were drift: War Thunder's copy
never got the reach floor, so a command you touch once a flight could outbid
the afterburner for a thumb button, and the fix was to keep reordering a list
by hand. What follows is the union of the four, with each idea taken from
whichever copy had it right.

A `Need` says WHAT and WHAT SHAPE. What a slot *means* is the game's business:
`bindings` is an opaque payload the core only ever indexes, so an entry can be
a War Thunder action id, a BMS callback, or a pair of X4 source/code strings
without the allocator knowing the difference.
"""

import sys
import typing


# ---------------------------------------------------------------- vocabulary

#: What may stand in for what when the exact shape is not on the hardware.
#: Order matters: the first entry is the shape actually asked for and scores a
#: bonus, the rest are substitutes.
FITS = {
    'hat2': ('hat2', 'switch2', 'switch3', 'hat4', 'selector'),
    'hat4': ('hat4', 'hat8', 'selector'),
    'button': ('button', 'paddle', 'dial'),
    'paddle': ('paddle', 'button'),
    'trigger': ('trigger',),
    'ministick': ('ministick',),
    'encoder': ('encoder', 'dial'),
    'dial': ('dial', 'encoder'),
    'latch': ('latch',),
    'selector': ('selector',),
}

#: WHEN you touch a thing, which is what decides how good a home it deserves.
#: 0 you reach for with something on your tail, 3 on the ramp with the canopy
#: open.
IN_A_TURN, ON_APPROACH, IN_THE_AIR, ON_THE_RAMP = 0, 1, 2, 3
URGENCY_NAME = ('in a turn', 'on approach', 'in the air', 'on the ramp')

#: How precious a control is, read from the map's own words about reach.
REACH_TIER = [('thumb', 0), ('index finger', 0),
              ('without releasing', 1),
              ('needs letting go', 3)]

#: The worst reach an urgency can live with in the floored pass. Only a
#: preference: the relaxed pass lifts it.
#:
#: Tier 2 was tried at 1, to keep `in the air` off controls you must let go of
#: the grip for. Measured on this hardware it did the opposite of its
#: intention: War Thunder's airbrake, bombs, radar ACM, sight stabilisation
#: and air-to-ground lock -- all `in a turn` -- were being served by the
#: BORROW pass, which runs last, so tightening the ceiling let `in the air`
#: needs take the whole controls whose presses they were borrowing. Five
#: combat functions moved from the thumb to the keyboard panel and five cruise
#: functions took their place. The fault is the pass order, not the ceiling:
#: borrowing happens after every main pass, so a need that can only borrow
#: loses to anything that can claim a control outright, however less urgent.
MAX_REACH = {0: 1, 1: 3, 2: 3, 3: 3}
#: ...and the best it may take. Without a floor, something you do once on the
#: ramp grabs a thumb position the moment one is free, and the only defence is
#: hand-sorting the need list -- which is what War Thunder was reduced to.
MIN_REACH = {0: 0, 1: 0, 2: 0, 3: 2}

#: Controls whose buttons are one physical mechanism rather than independent
#: positions. They may lend their click and nothing else.
ONE_MECHANISM = ('latch', 'trigger', 'selector', 'encoder')

#: Hats are captured with whichever words fitted the control at the time, so a
#: need asking for "forward" has to accept "up" from a hat that calls it that.
SAME_WAY = {'forward': ('forward', 'up', 'fwd'),
            'up': ('up', 'forward', 'fwd'),
            'back': ('back', 'down', 'aft'),
            'down': ('down', 'back', 'aft'),
            'left': ('left',), 'right': ('right',),
            'push': ('push',)}


def reach_tier(ctrl):
    for word, tier in REACH_TIER:
        if word in (ctrl.reach or ''):
            return tier
    return 2                            # unknown: somewhere in between


# --------------------------------------------------------------------- needs

class Need:
    """One thing a pilot has to be able to do.

    `bindings` runs in the order of the control's own directions or stages, so
    a four-way hat takes four and a two-stage trigger takes one per detent. An
    entry may be None to leave that direction alone.
    """

    def __init__(self, what, shape, bindings=(), push=None,
                 urgency=IN_THE_AIR, suits=None, dev=None, prefer=None,
                 on=None, rank=0, note=''):
        self.what = what
        self.shape = shape
        self.bindings = list(bindings)
        #: for a control that also clicks
        self.push = push
        self.urgency = urgency
        self.suits = suits
        #: which device this belongs on, by the map's `kind` ('stick', ...)
        self.dev = dev
        #: pin to a control by its label in the map. The allocator ranks by
        #: shape, reach and urgency, which is right for everything nobody has
        #: an opinion about -- but when you DO have one it should win rather
        #: than be argued with at every regeneration.
        self.prefer = prefer
        #: the directions this control physically moves in, when it matters. A
        #: speedbrake switch is fore/aft whatever hat it lands on, and putting
        #: it on "up" and "right" because those came first would be a lie about
        #: the hardware.
        self.on = tuple(on) if on else None
        #: how much the game itself asks for this, counted rather than judged
        #: -- how many factory profiles bind it. Breaks ties WITHIN an urgency
        #: band and never across one: a cockpit switch a hundred profiles bind
        #: still does not outrank something you reach for in a turn. Games that
        #: ship no profiles to count (X4, Elite) leave it at 0, which orders
        #: them by urgency alone exactly as before.
        self.rank = rank
        self.note = note
        #: set by the allocator when it had to reach past the floor
        self.relaxed = False

    @property
    def slots(self):
        return len(self.bindings)

    @property
    def wanted(self):
        """Buttons this need occupies, press included."""
        return self.slots + (1 if self.push is not None else 0)

    @property
    def shapes(self):
        first = self.shape if isinstance(self.shape, str) else self.shape[0]
        if isinstance(self.shape, str):
            return FITS.get(self.shape, (self.shape,))
        # an explicit tuple is taken as written, widened by the first entry
        out = list(self.shape)
        for s in FITS.get(first, ()):
            if s not in out:
                out.append(s)
        return tuple(out)

    @property
    def first_shape(self):
        return self.shape if isinstance(self.shape, str) else self.shape[0]

    def __repr__(self):
        return f'<Need {self.what!r} {self.shape} u{self.urgency}>'


def directional(ctrl):
    """Does this control move in named directions rather than sit in positions?

    A hat answers 'up'/'left', a selector '1'..'5' and an encoder 'ccw'/'cw'.
    Only the first kind can honour a need's `on`.
    """
    return any(ctrl.direction(b) in SAME_WAY
               for b in ctrl.bindable_buttons)


def satisfies_on(need, ctrl):
    """Can this control put each binding on the direction the need names?

    `need.on` is a claim about the hardware -- a speedbrake switch is fore/aft
    whatever hat it lands on -- and `slots_for` falls back to press order when
    it cannot be honoured. Silently: so a four-way need landed on a five
    position selector, whose positions are '1'..'5' and are not directions at
    all, and Elite's panel focus went onto a switch that HOLDS its position.
    """
    if not need.on:
        return True
    order = list(ctrl.buttons)
    if ctrl.push is not None and need.push is None:
        order.append(ctrl.push)
    picked = []
    for want in need.on:
        names = SAME_WAY.get(want, (want,))
        hit = next((b for b in order
                    if ctrl.direction(b) in names and b not in picked), None)
        if hit is None:
            return False
        picked.append(hit)
    return True


def slots_for(need, ctrl):
    """[button index] this need's bindings land on, in binding order.

    Normally the first N in press order. But when the need names the directions
    it moves in, find them. A control whose only button is its click -- the
    VMAX side dials are like that -- offers the click as an ordinary button,
    unless the need has something of its own to put there.
    """
    order = list(ctrl.buttons)
    if ctrl.push is not None and need.push is None:
        order.append(ctrl.push)
    # One binding on a control with several buttons belongs on its CLICK, not
    # on the first direction. A lone action on `buttons[0]` reads as "push the
    # hat left" when the obvious gesture is to press the hat -- and it leaves
    # the click, the one position a single action actually wants, idle.
    if (need.slots == 1 and not need.on and need.push is None
            and ctrl.push is not None and len(ctrl.bindable_buttons) > 1):
        return [ctrl.push]
    if need.on:
        picked = []
        for want in need.on:
            names = SAME_WAY.get(want, (want,))
            hit = next((b for b in order
                        if ctrl.direction(b) in names and b not in picked), None)
            if hit is None:
                break
            picked.append(hit)
        if len(picked) == len(need.on):
            return picked
    return order[:need.slots]


# ----------------------------------------------------------------- the match

def score(ctrl, need, role, floor=True, usable=None, reach=None):
    """How well a control plays this part. None means it cannot.

    `reach` overrides MAX_REACH for a game whose need list is ranked and
    truncated rather than written out by hand -- see allocate().
    """
    if usable is not None and not usable(role, ctrl):
        return None
    if ctrl.kind not in need.shapes:
        return None
    if len(ctrl.bindable_buttons) < need.wanted:
        return None

    # A pin outranks the reach tables, not just the ranking. `prefer` used to
    # be a +500 bonus applied AFTER the ceiling, so a pinned control the
    # ceiling excluded scored None and the bonus never ran: BMS's pinky shift,
    # pinned to the grip pinky button, scored 721 with a loose ceiling and
    # None with a tight one, and silently moved to the thumb mini-stick --
    # a control you cannot hold as a modifier while working the thumb hats the
    # shifted layer sits on. Shape and capacity still have to fit; a pin cannot
    # put four directions on a single button.
    if need.prefer and need.prefer == ctrl.label:
        return 1000

    tier = reach_tier(ctrl)
    # The ceiling yields in the relaxed pass, but only for a need the borrow
    # pass could never serve.
    #
    # Borrowing hands a need one spare button on a control somebody else took,
    # so it only ever works for a need that wants ONE button -- and for those a
    # borrowed thumb press beats a whole control you must let go of the grip to
    # reach. Lifting the ceiling for them made it lose: War Thunder's radar ACM
    # and sight stabilisation, both `in a turn`, left the thumb for the side
    # dials because a whole dial became legal in the relaxed pass, which runs
    # BEFORE borrowing.
    #
    # A need wanting several buttons has no such fallback. Every encoder and
    # selector on this hardware needs letting go of the grip, so without the
    # lift BMS's MAN RANGE knob, radar gain, ICP master mode and IFF MASTER had
    # nowhere to go at all.
    table = reach or MAX_REACH
    ceiling = table[need.urgency]
    if not floor and need.wanted > 1:
        ceiling = max(table.values())
    if tier > ceiling:
        return None
    if floor and tier < MIN_REACH[need.urgency]:
        return None

    # Take the LEAST precious control that still does the job. Needs are placed
    # most-urgent-first, so the thumb positions are already spoken for by the
    # time anything from the ramp gets a look -- and it has no reason to want
    # one anyway.
    s = 100 + 12 * tier
    if need.dev == role:
        s += 40
    elif need.dev and need.dev != role:
        s -= 50
    if ctrl.kind == need.first_shape:
        s += 20
    if need.suits and need.suits in ctrl.suits:
        s += 25
    if need.push is not None and ctrl.push is not None:
        s += 15
    if not satisfies_on(need, ctrl):
        # A control whose directions merely differ is still a home -- a rocker
        # is up/down and a need asking for left/right is happy enough on it --
        # so that is a nudge towards one that does match. A control with no
        # DIRECTIONS at all is a different matter, and the test has to be
        # against the direction vocabulary rather than "has any label": a
        # selector answers '1'..'5' and an encoder 'ccw'/'cw', which are
        # positions, not directions. Reading those as directions let Elite's
        # four panel-focus actions onto a five-position switch that HOLDS
        # whichever position it is in.
        s -= 8 if directional(ctrl) else 60
    s -= 4 * (len(ctrl.bindable_buttons) - need.wanted)
    return s


class Placement:
    """A need, the control it got, and which button each binding landed on."""

    def __init__(self, need, role, ctrl, slots, points):
        self.need = need
        self.role = role
        self.ctrl = ctrl
        #: [(button index, binding)], plus (push, need.push) when there is one
        self.slots = slots
        self.points = points

    def __iter__(self):
        return iter(self.slots)

    def __repr__(self):
        return f'<Placement {self.need.what!r} -> {self.role}/{self.ctrl.label}>'


class Layout:
    """What a planner worked out: the one shape every adapter returns.

    `build()` was in the adapter contract from the start, but its shape was
    not, and five adapters drifted into five orders -- x4 and elite
    `(devs, placed, unmet, free, axes)`, MSFS the same with the last two
    swapped, BMS and War Thunder leading with their own derived tables. Every
    one is defensible on its own and no caller outside its own file could rely
    on any of them, which is why nothing generic could be written over the top.

    The core five are here. Anything a game derives for its own writer -- BMS's
    DX numbers, War Thunder's resolved action ids -- is a function of `placed`
    and belongs beside that writer, not in this shape: a table computed inside
    `build()` cannot be narrowed afterwards, and narrowing it is exactly what a
    reviewer accepting some bindings and not others is doing.

        def build():
            devs = devmap.by_role('stick', 'throttle')
            return Layout(devs, *allocate(NEEDS, devs), axes=axis_plan(devs))
    """

    def __init__(self, devices, placed, unplaced, free, axes=()):
        #: {role: Device}, from devmap.by_role
        self.devices = devices
        #: [Placement], most urgent first
        self.placed = list(placed)
        #: [Need] that found no home
        self.unplaced = list(unplaced)
        #: [(role, control)] with every button still spare
        self.free = list(free)
        #: game-shaped; the core counts it and passes it on, nothing more
        self.axes = list(axes)

    def __iter__(self) -> typing.Iterator[typing.Any]:
        """(devices, placed, unplaced, free, axes), so a caller may still
        unpack it into five names.

        `Any` because an iterator has one element type and these five are
        not one type; a checker otherwise joins them and then objects to
        whichever name is used for what it actually is.
        """
        return iter((self.devices, self.placed, self.unplaced,
                     self.free, self.axes))

    def __repr__(self):
        return (f'<Layout {len(self.placed)} placed, {len(self.unplaced)} '
                f'unplaced, {len(self.free)} free, {len(self.axes)} axes>')

    def but(self, placed):
        """The same layout with a different set of placements.

        What a reviewer hands a writer: everything else about the plan is
        unchanged, and only the bindings that were accepted go in.
        """
        return Layout(self.devices, placed, self.unplaced, self.free,
                      self.axes)

    def by_device(self):
        """[(role, [Placement])] -- placements grouped for display, in the
        order a reader expects: stick first, and inside it by urgency."""
        out = {}
        for p in self.placed:
            out.setdefault(p.role, []).append(p)
        for group in out.values():
            group.sort(key=lambda p: (p.need.urgency, p.ctrl.label))
        return sorted(out.items())


def allocate(needs, devices, usable=None, reach=None):
    """(placements, unplaced, free), most urgent first.

    Two passes. The first keeps the reach floor: something you do on the ramp
    may not take a control your thumb rests on, however many are spare at that
    moment. The second drops the floor for whatever is left, because an unbound
    engine start is worse than a canopy switch under the thumb -- and by then
    everything urgent has already chosen.

    `usable(role, ctrl)` lets a game veto a control the hardware has but the
    game cannot address: BMS sees only a device's first 32 buttons, so the
    VMAX's last nineteen are real to your hand and invisible to the sim.

    `reach` replaces MAX_REACH for this run, because the same ceiling means
    different things depending on where the needs came from. A hand-written
    list saturates the good controls, so a tight ceiling displaces something
    more urgent -- War Thunder lost its airbrake off the thumb that way. A list
    derived from the game's vocabulary and cut at a vote threshold, as DCS's
    is, has room to spare, and there a tight ceiling on `in the air` simply
    steers sensor and radio switches onto borrowed finger positions instead of
    whole keyboard buttons, which is what it was for.
    """
    pool = [(role, c) for role, d in sorted(devices.items())
            for c in d.groups(bindable=True)]
    taken, placed = set(), []
    #: Pinned needs go first, before urgency is consulted at all. `prefer` used
    #: to only tip the scales, which is no use once something more urgent has
    #: already taken the control: BMS's pinky shift was pinned to the grip
    #: pinky button and still lost it to the landing lights, because they are
    #: touched on approach and it is not. An explicit choice has to outrank the
    #: ordering as well as the ranking, or it is not a choice.
    order = sorted(range(len(needs)),
                   key=lambda i: (needs[i].prefer is None, needs[i].urgency,
                                  -needs[i].rank))

    def pass_over(todo, floor):
        left = []
        for i in todo:
            need = needs[i]
            best, best_s = None, None
            for j, (role, c) in enumerate(pool):
                if j in taken:
                    continue
                s = score(c, need, role, floor=floor,
                          usable=usable, reach=reach)
                if s is not None and (best_s is None or s > best_s):
                    best, best_s = j, s
            if best is not None and need.prefer and floor \
                    and pool[best][1].label != need.prefer:
                # it is pinned and this is not the pin: say so rather than
                # quietly put it somewhere else and look like it worked
                print(f'!! {need.what!r} is pinned to {need.prefer!r}, which is '
                      f'not free; leaving it for the relaxed pass',
                      file=sys.stderr)
                left.append(i)
                continue
            if best is None:
                left.append(i)
                continue
            taken.add(best)
            role, ctrl = pool[best]
            need.relaxed = not floor
            buttons = slots_for(need, ctrl)
            slots = [(b, v) for b, v in zip(buttons, need.bindings)
                     if v is not None]
            if need.push is not None and ctrl.push is not None:
                slots.append((ctrl.push, need.push))
            placed.append(Placement(need, role, ctrl, slots, best_s))
        return left

    unplaced = pass_over(pass_over(order, True), False)

    # A control carries more than the need that took it. A hat has four
    # directions AND a press; a rocker nobody claimed has two positions. What
    # is spare is counted per BUTTON, not per control, because a need having
    # one binding does not make the other three buttons of its hat spoken for.
    occupied = {(p.role, b) for p in placed for b, _ in p.slots}
    still = []
    for i in unplaced:
        need = needs[i]
        if need.wanted != 1:
            still.append(i)        # nothing to borrow for a whole-control need
            continue
        best = None
        for j, (role, c) in enumerate(pool):
            if usable is not None and not usable(role, c):
                continue
            if reach_tier(c) > (reach or MAX_REACH)[need.urgency]:
                continue
            spare = [b for b in c.bindable_buttons
                     if (role, b) not in occupied]
            if not spare:
                continue
            if c.kind in ONE_MECHANISM:
                # These do not lend a position. A trigger's stages are the gun,
                # a selector's positions are one switch, an encoder's two
                # contacts are one more/less pair, and a latch HOLDS whichever
                # position it is in -- so a press action borrowed from one
                # fires for as long as the lever sits there. Bomb release
                # landed on the master-arm latch exactly that way. Their click,
                # where they have one, is a real button and is fair game.
                if c.push is None or (role, c.push) in occupied:
                    continue
                button = c.push
            else:
                button = (c.push if c.push is not None
                          and (role, c.push) not in occupied else spare[0])
            # The main passes reward a HIGHER tier -- take the least precious
            # control that still does the job, because something more urgent
            # may still be coming. Nothing is coming here: borrowing is the
            # last pass, so the polarity flips and a leftover need gets the
            # BEST leftover. Rewarding tier here instead sent War Thunder's
            # airbrake, bombs and sight stabilisation off the thumb onto the
            # middle-finger hat for no gain to anybody. (DCS's own borrow pass,
            # which this is lifted from, still has the old sign.)
            s = 60 + 12 * ((reach or MAX_REACH)[ON_THE_RAMP]
                           - reach_tier(c))
            s += 30 if need.dev == role else 0
            if j not in taken:
                # Prefer borrowing a spare position over opening a control
                # nothing has touched: four idle two-way rockers should not sit
                # there while a cold-start switch goes homeless, but neither
                # should one be broken open while a real spare exists.
                s -= 15
            if best is None or s > best[0]:
                best = (s, role, c, button)
        if best is None:
            still.append(i)
            continue
        _s, role, ctrl, button = best
        occupied.add((role, button))
        need.relaxed = True
        placed.append(Placement(need, role, ctrl,
                                [(button, need.bindings[0])], _s))

    # Free means every button of it is free, not merely that no need chose it.
    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken
            and not any((r, b) in occupied for b in c.bindable_buttons)]
    return placed, [needs[i] for i in still], free

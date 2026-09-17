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

#: The worst reach an urgency can live with...
MAX_REACH = {0: 1, 1: 3, 2: 3, 3: 3}
#: ...and the best it may take. Without a floor, something you do once on the
#: ramp grabs a thumb position the moment one is free, and the only defence is
#: hand-sorting the need list -- which is what War Thunder was reduced to.
MIN_REACH = {0: 0, 1: 0, 2: 0, 3: 2}

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
                 on=None, note=''):
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

def score(ctrl, need, role, floor=True, usable=None):
    """How well a control plays this part. None means it cannot."""
    if usable is not None and not usable(role, ctrl):
        return None
    if ctrl.kind not in need.shapes:
        return None
    if len(ctrl.bindable_buttons) < need.wanted:
        return None
    tier = reach_tier(ctrl)
    if tier > MAX_REACH[need.urgency]:
        return None
    if floor and tier < MIN_REACH[need.urgency]:
        return None

    # Take the LEAST precious control that still does the job. Needs are placed
    # most-urgent-first, so the thumb positions are already spoken for by the
    # time anything from the ramp gets a look -- and it has no reason to want
    # one anyway.
    s = 100 + 12 * tier
    if need.prefer and need.prefer == ctrl.label:
        s += 500                        # an explicit choice outranks the ranking
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


def allocate(needs, devices, usable=None):
    """(placements, unplaced), most urgent first.

    Two passes. The first keeps the reach floor: something you do on the ramp
    may not take a control your thumb rests on, however many are spare at that
    moment. The second drops the floor for whatever is left, because an unbound
    engine start is worse than a canopy switch under the thumb -- and by then
    everything urgent has already chosen.

    `usable(role, ctrl)` lets a game veto a control the hardware has but the
    game cannot address: BMS sees only a device's first 32 buttons, so the
    VMAX's last nineteen are real to your hand and invisible to the sim.
    """
    pool = [(role, c) for role, d in sorted(devices.items())
            for c in d.groups(bindable=True)]
    taken, placed = set(), []
    order = sorted(range(len(needs)), key=lambda i: needs[i].urgency)

    def pass_over(todo, floor):
        left = []
        for i in todo:
            need = needs[i]
            best, best_s = None, None
            for j, (role, c) in enumerate(pool):
                if j in taken:
                    continue
                s = score(c, need, role, floor=floor, usable=usable)
                if s is not None and (best_s is None or s > best_s):
                    best, best_s = j, s
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

    # A hat carries its directions AND a press; if the need that took it had
    # nothing for the press, that press is still a button somebody can use.
    spoken = {id(p.ctrl) for p in placed
              if any(b == p.ctrl.push for b, _ in p.slots)}
    still = []
    for i in unplaced:
        need = needs[i]
        if need.wanted != 1:
            still.append(i)
            continue
        best = None
        for role, c in pool:
            if c.push is None or id(c) in spoken:
                continue
            if usable is not None and not usable(role, c):
                continue
            if reach_tier(c) > MAX_REACH[need.urgency]:
                continue
            s = score(c, need, role, floor=False, usable=usable)
            if s is None:
                s = 60                  # borrowing a press, not the shape
            if best is None or s > best[0]:
                best = (s, role, c)
        if best is None:
            still.append(i)
            continue
        _s, role, ctrl = best
        spoken.add(id(ctrl))
        need.relaxed = True
        placed.append(Placement(need, role, ctrl,
                                [(ctrl.push, need.bindings[0])], _s))

    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken and id(c) not in spoken]
    return placed, [needs[i] for i in still], free

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

import os
import sys
import tomllib
import typing


def _read_rules(path):
    """The scoring rules, as written down."""
    with open(path, 'rb') as f:
        return tomllib.load(f)


#: Which key identifies an entry in each list of the file. Merging by
#: POSITION would mean inserting a band in the core file silently
#: repointed every override in the family at the wrong one.
#: `term` is keyed by a name of its own and not by `when`: three of them
#: are conditioned on `always`, so the condition does not tell them apart
#: and an override would have hit whichever came last.
KEYED_BY = {'band': 'name', 'pass': 'name', 'term': 'name', 'gate': 'when'}


def merge_rules(base, extra):
    """`base` with `extra` laid over it. Neither is changed.

    A game says only what it differs on. Two already need to: DCS replaces
    a band's limits, because its needs come from a vocabulary cut at a
    vote threshold rather than written out by hand, so it has room to
    spare where the others saturate.

    An entry naming something the base does not have is refused rather
    than added. A typo would otherwise be a fifth band nothing places
    into, or a weight applied to a condition nobody wrote.
    """
    #  because the file's sections are two shapes -- a list of
    # entries keyed by name, or a plain table -- and a checker asked to
    # join them objects at whichever branch is using one as itself.
    out: dict[str, typing.Any] = {
        k: (list(v) if isinstance(v, list) else dict(v))
        for k, v in base.items()}
    for section, given in (extra or {}).items():
        if section not in out:
            raise ValueError(f'{section!r} is not a section of the rules')
        if section not in KEYED_BY:
            out[section] = {**out[section], **given}
            continue
        key = KEYED_BY[section]
        at = {row[key]: n for n, row in enumerate(out[section])}
        for row in given:
            if row[key] not in at:
                raise ValueError(
                    f'{section} {row[key]!r} is not one the rules define')
            out[section][at[row[key]]] = {**out[section][at[row[key]]], **row}
    return out


from core import actions as cactions


# ---------------------------------------------------------------- vocabulary

#: The rules, read once from the file beside this one. Everything below is
#: a view of it: the tables the allocator works from have one definition,
#: and it is the one the screen that explains them also reads.
#:
#: Read at import because it ships with the code -- it is source, not a
#: cache and not a judgement about a game, so there is nothing here that a
#: clone with nothing installed could be missing.
RULES = _read_rules(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'scoring.toml'))

#: What a control nobody has measured is worth: worse than anything that
#: has been. The map hands over a tier or None, and None is not a middling
#: control -- it is one nothing is known about.
UNMEASURED = RULES['reach']['unmeasured']

#: What each tier means, in the words a reader has.
REACH_MEANS = {tier: says for tier, says in RULES['reach']['means']}

#: WHEN you touch a thing, which is what decides how good a home it
#: deserves. 0 you reach for with something on your tail, 3 on the ramp
#: with the canopy open.
IN_A_TURN, ON_APPROACH, IN_THE_AIR, ON_THE_RAMP = 0, 1, 2, 3
URGENCY_NAME = tuple(b['name'] for b in RULES['band'])

#: The best reach a band may take, and the worst it may live with. Without
#: the floor, something you do once on the ramp grabs a thumb position the
#: moment one is free; without the ceiling, nothing is kept close.
MIN_REACH = {n: b['takes'][0] for n, b in enumerate(RULES['band'])}
MAX_REACH = {n: b['takes'][1] for n, b in enumerate(RULES['band'])}

#: The passes, in the order `allocate` runs them.
PASSES = tuple((p['name'], p['does']) for p in RULES['pass'])

#: What makes one control beat another, and why one is refused outright.
TERMS = RULES['term']
GATES = RULES['gate']

#: What may stand in for what when the exact shape is not on the hardware.
#: Order matters: the first entry is the shape actually asked for and
#: scores a bonus, the rest are substitutes.
FITS = {shape: tuple(subs) for shape, subs in RULES['shapes'].items()}

#: Controls whose buttons are one physical mechanism rather than
#: independent positions. They may lend their click and nothing else.
ONE_MECHANISM = tuple(RULES['mechanisms']['one'])

#: Hats are captured with whichever words fitted the control at the time,
#: so a need asking for "forward" has to accept "up" from a hat that calls
#: it that.
SAME_WAY = {want: tuple(names)
            for want, names in RULES['directions'].items()}


def reach_tier(ctrl):
    """How far this control is from flying, measured by the map.

    `None` there means nobody has walked the fingers on that desk, which
    is why the wizard asks for a rig at all. It is not a tier: it sorts
    below every measured one, so a control somebody checked wins over one
    nobody has.
    """
    return UNMEASURED if ctrl.tier is None else ctrl.tier


def reach_said(ctrl):
    """How it is reached, in words, or '' when nobody has measured it.

    Built from the nearest spot rather than read off the control: where a
    thing ended up is a fact about the desk, and the same stick on a
    chair rail is reached differently.
    """
    spots = [a for a in ctrl.access if a.tier == ctrl.tier]
    if not spots:
        return ''
    spot = spots[0]
    said = REACH_MEANS.get(spot.tier, '')
    return f'{spot.finger}, {said}' if spot.finger else said


# --------------------------------------------------------------------- needs

class Need:
    """One thing a pilot has to be able to do.

    `bindings` runs in the order of the control's own directions or stages, so
    a four-way hat takes four and a two-stage trigger takes one per detent. An
    entry may be None to leave that direction alone.
    """

    def __init__(self, what, shape, bindings=(), push=None,
                 urgency=IN_THE_AIR, suits=None, dev=None, prefer=None,
                 on=None, rank=0, note='', category=None):
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
        #: Yours: what you filed this under. Separate from `urgency` on
        #: purpose -- "Combat" can hold something you reach for in a turn
        #: and something you set on the ramp, and the allocator still has
        #: to know which is which. Absent means the screen falls back to
        #: the band, which is what it grouped by before there were any.
        self.category = category
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


def dump_needs(needs, also=()):
    """[Need] -> [dict], the judgements a game no longer keeps in source.

    Only what a human decided. The per-context split every game's
    constructor takes -- `air`/`heli`, `plane`/`glob`, `ship`/`map`/`foot`
    -- is absent: it zips into the slots and reads back off the binds, so
    writing it too would be the same fact recorded twice, free to drift.

    `relaxed` is absent for a different reason: it is set BY a run rather
    than decided before one, and a list that remembered the last outcome
    would have every run start from where the previous one ended up.

    `also` names the attributes one game keeps of its own -- BMS marks a
    need as living on the shifted layer and nobody else has the idea. The
    game says which, rather than a generic bag being carried for all six;
    an unnamed bag is the opaque payload this contract replaced.
    """
    out = []
    for n in needs:
        row = {'what': n.what, 'shape': n.shape,
               'bindings': [cactions.dump_binds(slot) for slot in n.bindings]}
        if n.push:
            row['push'] = cactions.dump_binds(n.push)
        if n.urgency != IN_THE_AIR:
            row['urgency'] = n.urgency
        for field in ('suits', 'dev', 'prefer', 'note', 'category'):
            if getattr(n, field):
                row[field] = getattr(n, field)
        if n.on:
            row['on'] = list(n.on)
        if n.rank:
            row['rank'] = n.rank
        for field in also:
            if getattr(n, field, None):
                row[field] = getattr(n, field)
        out.append(row)
    return out


def save_needs(directory, filename, needs, also=()):
    """Write the judgements down. One place, because five games had none.

    They are not derived from anything: delete one and it is gone. So a
    screen that lets somebody make one has to be able to write it, and
    until this existed, promoting an action lasted until `q`.
    """
    from core import vocab
    return vocab.save(directory, filename, needs=dump_needs(needs, also))


def read_needs(rows, also=(), make=None):
    """[dict] -> [Need]. `make` is a game's own subclass, when it has one.

    A shape written as a choice comes back a tuple rather than the list
    JSON gives, because `first_shape` is the one asked for and the rest
    are substitutes -- and a list and a tuple are the same to every reader
    except the one asking whether a shape is a single name.
    """
    out = []
    for r in rows:
        shape = r['shape']
        if not isinstance(shape, str):
            shape = tuple(shape)
        push = cactions.read_binds(r['push']) if r.get('push') else None
        need = (make or Need)(
            r['what'], shape,
            bindings=[cactions.read_binds(slot) for slot in r['bindings']],
            push=push, urgency=r.get('urgency', IN_THE_AIR),
            suits=r.get('suits'), dev=r.get('dev'),
            prefer=r.get('prefer'), on=r.get('on'),
            rank=r.get('rank', 0), note=r.get('note', ''),
            category=r.get('category'))
        for field in also:
            setattr(need, field, r.get(field))
        out.append(need)
    return out


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


def slots_for(need, ctrl, why=None):
    """[button index] this need's bindings land on, in binding order.

    Normally the first N in press order. But when the need names the directions
    it moves in, find them. A control whose only button is its click -- the
    VMAX side dials are like that -- offers the click as an ordinary button,
    unless the need has something of its own to put there.

    `why` collects `(button, what put it there)`, one per button returned.
    Four binds on a hat share a control, so they share every word of the
    account except this one; without it they carry four copies of the same
    sentence, which looks like an answer and is not.
    """
    order = list(ctrl.buttons)
    if ctrl.push is not None and need.push is None:
        order.append(ctrl.push)

    def said(buttons, how):
        if why is not None:
            why.extend((b, how(b) if callable(how) else how) for b in buttons)
        return buttons

    # One binding on a control with several buttons belongs on its CLICK, not
    # on the first direction. A lone action on `buttons[0]` reads as "push the
    # hat left" when the obvious gesture is to press the hat -- and it leaves
    # the click, the one position a single action actually wants, idle.
    if (need.slots == 1 and not need.on and need.push is None
            and ctrl.push is not None and len(ctrl.bindable_buttons) > 1):
        return said([ctrl.push],
                    'the click; one action on a multi-button control')
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
            asked = dict(zip(picked, need.on))
            # The same words where nothing surprising happened, different
            # words where it did: a reader wants to know when a binding is
            # NOT where the label suggests, and four spellings of "as
            # asked" bury the one line that says otherwise.
            return said(picked,
                        lambda b: ('as asked'
                                   if ctrl.direction(b) == asked[b]
                                   else f'asked for {asked[b]}; this '
                                        f'control calls it '
                                        f'{ctrl.direction(b)}'))
        # Falling back was silent, so a four-way need on a five-position
        # selector landed on '1'..'4' while the need went on claiming it
        # was bound fore and aft.
        return said(order[:need.slots],
                    lambda b: f'press order; {"/".join(need.on)} not on '
                              f'this control')
    return said(order[:need.slots], 'press order')


# ----------------------------------------------------------------- the match

#: What each condition in `scoring.toml` MEANS. The file names them and
#: this writes them, because a condition is a predicate over a control and
#: a need -- a file that could define one would need an expression
#: language, and that is a worse thing to own than the file.
#:
#: Every one is held to the file by `tests/test_scoring.py`, both ways: a
#: name with no predicate is a weight nobody applies, and a predicate no
#: name reaches is a rule left behind in the code.
WHEN = {
    'always': lambda c, n, r, t: True,
    # The reach term rewards the FURTHEST control that still does the job,
    # because that leaves the near ones for something more urgent. An
    # unmeasured control must not collect that: nobody knows it is far,
    # and paying it for distance nobody measured is how it beat a thumb
    # button somebody had measured.
    'measured': lambda c, n, r, t: c.tier is not None,
    'pinned': lambda c, n, r, t: bool(n.prefer) and n.prefer == c.label,
    'device_matches': lambda c, n, r, t: n.dev == r,
    'device_differs': lambda c, n, r, t: bool(n.dev) and n.dev != r,
    'exact_shape': lambda c, n, r, t: c.kind == n.first_shape,
    'has_click': lambda c, n, r, t: n.push is not None and c.push is not None,
    'directions_differ': lambda c, n, r, t: (not satisfies_on(n, c)
                                             and directional(c)),
    'no_directions': lambda c, n, r, t: (not satisfies_on(n, c)
                                         and not directional(c)),
}

#: What a weight is multiplied by, where it is multiplied by anything.
PER = {
    'tier': lambda c, n, r, t: t,
    'spare': lambda c, n, r, t: len(c.bindable_buttons) - n.wanted,
}

#: Why a control is refused outright. `x` is the run's own state, which is
#: what tells these from `WHEN`: a gate reads the pass it is in.
REFUSE = {
    'unusable': lambda x: x.usable is not None and not x.usable(x.role,
                                                                x.ctrl),
    'wrong_shape': lambda x: x.ctrl.kind not in x.need.shapes,
    'too_few': lambda x: len(x.ctrl.bindable_buttons) < x.need.wanted,
    # Only where somebody has measured. How far a control is is what this
    # gate is about, and on a desk nobody has walked the fingers on there
    # is no answer to refuse it with -- refusing anyway places nothing at
    # all, which reads as a broken planner rather than as an unmeasured
    # desk. It still scores last, so anything measured wins.
    'out_of_reach': lambda x: x.measured and (x.tier > x.ceiling
                                              or (x.floor
                                                  and x.tier < x.lowest)),
}


class _Run:
    """What a gate reads besides the control and the need."""

    __slots__ = ('ctrl', 'need', 'role', 'tier', 'measured', 'floor',
                 'ceiling', 'lowest', 'usable')

    def __init__(self, ctrl, need, role, tier, floor, ceiling, lowest,
                 usable):
        self.ctrl, self.need, self.role = ctrl, need, role
        self.tier, self.floor = tier, floor
        self.measured = ctrl.tier is not None
        self.ceiling, self.lowest, self.usable = ceiling, lowest, usable


def score(ctrl, need, role, floor=True, usable=None, parts=None,
          rules=None):
    """How well a control plays this part. None means it cannot.

    The weights and their words come from `scoring.toml`; what each
    condition means comes from `WHEN` above. `rules` is a game's own set
    merged over the core's -- DCS tightens one band, because its needs
    come from a vocabulary cut at a vote threshold rather than written out
    by hand, so it has room to spare where the others saturate.

    `parts` collects `(delta, what it was for)` for every term that fired,
    which is what a `Reason` carries. It is off by default because the
    allocator scores every control against every need and wants a number
    to compare; the winner is scored a second time, with the terms, once
    it has won. `score()` is pure, so the second call describes the first.

    A term worth nothing is left out rather than listed as zero: a screen
    saying `0  suits gunnery` reads as a fact about the control, and it is
    the absence of one.
    """
    rules = rules or RULES
    def part(delta, text):
        if parts is not None and delta:
            parts.append((delta, text))
        return delta

    tier = reach_tier(ctrl)
    table = {n: b['takes'][1] for n, b in enumerate(rules['band'])}
    ceiling = table[need.urgency]
    # The ceiling yields in the relaxed pass, but only for a need the
    # borrow pass could never serve. Borrowing hands a need one spare
    # button on a control somebody else took, so it only works for a need
    # wanting ONE button -- and for those a borrowed thumb press beats a
    # whole control you must let go of the grip to reach. Lifting the
    # ceiling for them made it lose: War Thunder's radar ACM and sight
    # stabilisation, both `in a turn`, left the thumb for the side dials
    # because a whole dial became legal in the relaxed pass, which runs
    # BEFORE borrowing. A need wanting several buttons has no such
    # fallback: every encoder and selector on this hardware needs letting
    # go of the grip, so without the lift BMS's MAN RANGE knob, radar
    # gain, ICP master mode and IFF MASTER had nowhere to go at all.
    if not floor and need.wanted > 1:
        ceiling = max(table.values())
    run = _Run(ctrl, need, role, tier, floor, ceiling,
               rules['band'][need.urgency]['takes'][0], usable)

    # The order is here rather than in the file because it is load-bearing
    # and has a story. A pin outranks the reach tables, not just the
    # ranking, so it is taken BETWEEN the gates that are about the control
    # and the one that is about the pass: `prefer` used to be a bonus
    # applied after the ceiling, so a pinned control the ceiling excluded
    # scored nothing and the bonus never ran -- BMS's pinky shift scored
    # 721 with a loose ceiling and nothing with a tight one, and moved
    # silently to a control you cannot hold as a modifier.
    for name in ('unusable', 'wrong_shape', 'too_few'):
        if REFUSE[name](run):
            return None
    for term in rules['term']:
        if term.get('stops') and WHEN[term['when']](ctrl, need, role, tier):
            return part(term['weight'], _says(term, ctrl, need, role, 1))
    if REFUSE['out_of_reach'](run):
        return None

    s = 0
    for term in rules['term']:
        if term.get('stops') or not WHEN[term['when']](ctrl, need, role,
                                                       tier):
            continue
        n = PER[term['per']](ctrl, need, role, tier) if 'per' in term else 1
        s += part(term['weight'] * n, _says(term, ctrl, need, role, n))
    return s


def _says(term, ctrl, need, role, n):
    """A term's words, with the run's own values in them."""
    form = term['plural'] if n != 1 and 'plural' in term else term['says']
    return form.format(role=role, dev=need.dev, kind=ctrl.kind,
                       suits=need.suits, label=ctrl.label, n=n)


class Reason:
    """Why a binding is where it is, written by whoever decided.

    `points` reached the Layout from the start and two readers tried to get
    a reason back out of it. BMS prints it. DCS asks `p.points == 200`, and
    its own docstring owns up: "the claim marker `place()` sets, and it was
    the same magic number before". A score is a comparison and an
    explanation is not, so wanting the second means reverse-engineering the
    first -- and a sentinel that survives being read that way is a sentinel
    nobody dares change.

    Written at the moment of the decision by the code making it, which is
    the only place that does not have to infer. Five things decide:

        pinned    you named the control and it was free
        floored   the ordinary pass, reach floor and ceiling both honoured
        relaxed   nothing legal was left, so the ceiling came off
        borrowed  a spare button on a control something else owns
        claimed   a planner put it here outright, past the allocator
        yours     a hand, on the review screen

    `parts` is `score()`'s own arithmetic: every term that fired, with what
    it was for. They add up to `points`, and a test holds them to it --
    once they stop adding up, the explanation is describing a run that did
    not happen.
    """

    __slots__ = ('how', 'points', 'parts', 'tier', 'ceiling', 'instead',
                 'spot')

    def __init__(self, how, points=None, parts=(), tier=None,
                 ceiling=None, instead=None, spot=''):
        self.how = how
        self.points = points
        #: [(delta, what it was for)], most valuable first is NOT imposed --
        #: the order is the order `score()` applies them, because that is the
        #: order the rules are written in and the one a reader can check.
        self.parts = list(parts)
        #: the reach tier of the control it got, and the worst tier this
        #: urgency was allowed in the pass that placed it. Without both,
        #: "reached past the floor" is a claim with nothing behind it.
        self.tier = tier
        self.ceiling = ceiling
        #: the Placement a hand displaced, when one did. This is what the
        #: detail panel says out loud, and it is a fact recorded at the
        #: moment of the move rather than a guess made later by comparing
        #: `at` with `plan` -- those agree only until something else moves.
        self.instead = instead
        #: Why THIS button of that control, which `slots_for` decides by
        #: three rules. The rest of this record is about the control, and
        #: four binds on a hat share it -- so without this they carry four
        #: copies of one sentence, which looks like an answer.
        self.spot = spot

    @property
    def overridden(self):
        """Did a person put this here rather than the planner."""
        return self.how == 'yours'

    def __repr__(self):
        return f'<Reason {self.how} {self.points}>'


#: The passes, in the order `allocate` runs them. A table because the
#: screen that explains the allocator has to read it from somewhere, and
#: `CAME_BY` is not that somewhere: it holds what is worth SAYING about a
#: placement, so it leaves out the ordinary pass and takes in two things
#: that are not passes at all. Using it as the list showed three of four.
PASSES = (
    ('pinned', 'a control you named, before anything else is placed'),
    ('floored', 'the ordinary one; the limits above both hold'),
    ('relaxed', 'nothing was left inside them, so the far end opens up'),
    ('borrowed', 'a spare button on a control something else owns'),
)

#: How a placement came about, as a reader wants it said. `floored` is
#: absent on purpose: it is the ordinary case, and a line announcing that
#: nothing unusual happened is a line you learn to skip past.
CAME_BY = {
    'relaxed': 'reached past the floor',
    'borrowed': 'borrowed a spare button',
    'claimed': 'claimed, not allocated',
    'yours': 'assigned by you',
}


def why_bits(p, out_of=None):
    """[str] -- the account of one placement, in the order a reader reads it.

    Five planners and one proposer had each grown their own copy of this --
    about 199 lines between them, roughly forty apiece -- and every one
    reads the same fields: which band, whether the floor held, what was
    pinned, what a human wrote down. One paragraph written six times.

    What stays a game's own is what only it knows: War Thunder's factory
    count, BMS's DX number, X4's slot. Those are appended by the game
    rather than reassembled here, which is the whole difference between a
    shared skeleton and a sixth copy.

    `out_of` is what the factory count is a count OF, which is the game's
    to say: Elite ships 13 presets, BMS 22 vendor profiles, War Thunder 29.
    The number is a shared field; its denominator is not, and six games
    spelling it their own way was six spellings of one sentence.

    Degrades rather than raises when there is no `Reason`. A planner may
    build a `Placement` itself -- DCS does -- and the band is a fact about
    the need rather than about the run that placed it.
    """
    n, r = p.need, p.why
    out = [URGENCY_NAME[n.urgency]]
    if n.rank:
        out.append(f'{n.rank}/{out_of} factory profiles bind it' if out_of
                   else f'{n.rank} factory profile'
                        + ('' if n.rank == 1 else 's') + ' bind it')
    if reach_said(p.ctrl):
        # Printed every time, not only for the reflex ones: it is what the
        # floor acts on, so it is what a disputed placement turns on.
        out.append(f'reach: {reach_said(p.ctrl)}')
    if r is None:
        return out
    if r.how == 'pinned' and n.prefer:
        out.append(f'pinned to {n.prefer!r}')
    elif r.how in CAME_BY:
        out.append(CAME_BY[r.how])
    # Biggest first: the term that decided it is the one to read first, and
    # the order `score()` applies them in is an accident of how the rules
    # are written rather than of what mattered.
    out += [f'{d:+} {t}'
            for d, t in sorted(r.parts, key=lambda q: -abs(q[0]))]
    return out


def hand_out(slots, role, why, spots=()):
    """Tell every binding in `slots` where it went and why.

    A payload is still whatever a game put there -- the allocator only ever
    indexes it -- so this asks rather than assumes: anything that knows how
    to be told is told, and anything else is carried as before.

    Each binding gets its OWN `Reason`. They agree about the control,
    because they share it, and differ in `spot`, because that is the only
    thing that distinguishes four binds on one hat.
    """
    said = dict(spots)
    for button, payload in slots:
        for b in payload if isinstance(payload, (list, tuple)) else [payload]:
            tell = getattr(b, 'placed_on', None)
            if tell is None:
                continue
            tell(role, button,
                 Reason(why.how, why.points, why.parts, why.tier,
                        why.ceiling, why.instead, spot=said.get(button, '')))


class Placement:
    """A need, the control it got, and which button each binding landed on."""

    def __init__(self, need, role, ctrl, slots, points, why=None):
        self.need = need
        self.role = role
        self.ctrl = ctrl
        #: [(button index, binding)], plus (push, need.push) when there is one
        self.slots = slots
        self.points = points
        #: a `Reason`. Defaulted rather than required because a planner may
        #: build a Placement itself -- DCS does, for its trigger claims --
        #: and a missing reason should read as "nobody said", not crash a
        #: screen.
        self.why = why

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

    def unmeasured(self):
        """(controls with no measured reach, controls) on this desk.

        Worth saying out loud wherever a layout is explained: with none of
        them measured every control scores the same on reach, so the
        layout is real but it is not reach-aware, and nothing else on
        screen would tell you that.
        """
        every = [g for dev in self.devices.values()
                 for g in dev.groups(bindable=True)]
        return sum(1 for g in every if g.tier is None), len(every)

    def reach_note(self):
        """One line about what the map has not been told, or ''."""
        left, every = self.unmeasured()
        if not left or not every:
            return ''
        if left == every:
            return ('no control on this desk has a measured reach, so'
                    ' nothing here knows what is near your hand'
                    ' — sim-device-map/capture.py, then `r`')
        return (f'{left} of {every} controls have no measured reach, so'
                ' they sort below every control that has')

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


def allocate(needs, devices, usable=None, rules=None):
    """(placements, unplaced, free), most urgent first.

    Two passes. The first keeps the reach floor: something you do on the ramp
    may not take a control your thumb rests on, however many are spare at that
    moment. The second drops the floor for whatever is left, because an unbound
    engine start is worse than a canopy switch under the thumb -- and by then
    everything urgent has already chosen.

    `usable(role, ctrl)` lets a game veto a control the hardware has but the
    game cannot address: BMS sees only a device's first 32 buttons, so the
    VMAX's last nineteen are real to your hand and invisible to the sim.

    `rules` is a game's own scoring merged over the core's, which is how
    a band's limits get replaced for one game: the same ceiling means
    different things depending on where the needs came from. A hand-written
    list saturates the good controls, so a tight ceiling displaces something
    more urgent -- War Thunder lost its airbrake off the thumb that way. A list
    derived from the game's vocabulary and cut at a vote threshold, as DCS's
    is, has room to spare, and there a tight ceiling on `in the air` simply
    steers sensor and radio switches onto borrowed finger positions instead of
    whole keyboard buttons, which is what it was for.
    """
    rules = rules or RULES
    top = {n: b['takes'][1] for n, b in enumerate(rules['band'])}
    low = {n: b['takes'][0] for n, b in enumerate(rules['band'])}
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
                          usable=usable, rules=rules)
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
            # Score the winner a second time, collecting the terms. `score()`
            # is pure, so this describes the call that won rather than a
            # second opinion -- and the hot loop above stays a comparison
            # between numbers instead of building a record per candidate.
            terms = []
            score(ctrl, need, role, floor=floor, usable=usable,
                  rules=rules, parts=terms)
            # The BAND's ceiling, not the lifted one. The relaxed pass
            # raises it, and recording the raised number made a placement
            # that had reached past the floor read as one that had not --
            # `how` is what says the floor came off.
            table = top
            ceiling = table[need.urgency]
            why = Reason(
                'pinned' if need.prefer and need.prefer == ctrl.label
                else ('floored' if floor else 'relaxed'),
                points=best_s, parts=terms, tier=reach_tier(ctrl),
                ceiling=ceiling)
            spots = []
            buttons = slots_for(need, ctrl, why=spots)
            # `if v` rather than `is not None`: a payload is now a
            # list of Binds and an empty one means this direction was
            # left alone, which is what `None` used to say.
            slots = [(b, v) for b, v in zip(buttons, need.bindings)
                     if v]
            if need.push is not None and ctrl.push is not None:
                slots.append((ctrl.push, need.push))
                spots.append((ctrl.push, 'the click, as asked'))
            hand_out(slots, role, why, spots)
            placed.append(Placement(need, role, ctrl, slots, best_s, why))
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
            if reach_tier(c) > top[need.urgency]:
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
            s = 60 + 12 * (top[ON_THE_RAMP] - reach_tier(c))
            s += 30 if need.dev == role else 0
            if j not in taken:
                # Prefer borrowing a spare position over opening a control
                # nothing has touched: four idle two-way rockers should not sit
                # there while a cold-start switch goes homeless, but neither
                # should one be broken open while a real spare exists.
                s -= 15
            if best is None or s > best[0]:
                best = (s, role, c, button, j)
        if best is None:
            still.append(i)
            continue
        _s, role, ctrl, button, j = best
        occupied.add((role, button))
        need.relaxed = True
        # The same two-step as the main passes, except the sum is inline up
        # there rather than in `score()`, so the terms are rebuilt here from
        # what decided them. They still have to add up to `_s`.
        terms = [(60, 'last pass; still free')]
        lent = 12 * (top[ON_THE_RAMP] - reach_tier(ctrl))
        if lent:
            terms.append((lent, 'best of what was left'))
        if need.dev == role:
            terms.append((30, f'on the {role}, as asked'))
        if j not in taken:
            terms.append((-15, 'opens an untouched control'))
        why = Reason('borrowed', points=_s, parts=terms,
                     tier=reach_tier(ctrl),
                     ceiling=top[need.urgency])
        slots = [(button, need.bindings[0])]
        hand_out(slots, role, why, [(button, 'the one spare button')])
        placed.append(Placement(need, role, ctrl, slots, _s, why))

    # Free means every button of it is free, not merely that no need chose it.
    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken
            and not any((r, b) in occupied for b in c.bindable_buttons)]
    return placed, [needs[i] for i in still], free

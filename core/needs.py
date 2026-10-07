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

import dataclasses
import json
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
from core import solvers as csolvers


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

#: The passes, in the order `allocate` runs them. From the file, because
#: the screen that explains the allocator has to read them from somewhere
#: and `CAME_BY` is not that somewhere: it holds what is worth SAYING
#: about a placement, so it leaves out the ordinary pass and takes in two
#: things that are not passes at all. Using it as the list showed three of
#: four -- and the fix, a literal written out here, was worse: it shadowed
#: THIS line, so the file's table became decoration and the screen went on
#: reading source. Two definitions of one name, and the second wins
#: silently.
PASSES = tuple((p['name'], p['does']) for p in RULES['pass'])

#: What makes one control beat another, and why one is refused outright.
TERMS = RULES['term']
GATES = RULES['gate']

#: What the map measured about a control, and what turns it on in a need.
#: Unlike a term, a fact names no predicate: every row has one of three
#: fixed shapes, so `_facts` builds the test from the row. See the table's
#: own header in scoring.toml for what each key means.
FACTS = tuple(RULES['fact'])

#: The flags the facts put on every Need, taken from the table rather than
#: written out -- which is what makes a sixth fact a block in a file and
#: nothing else. A need that sets none of them scores exactly as before.
FLAGS = tuple(f['asked'] for f in FACTS if f.get('asked'))

#: What an overlay may ask for, and so what the needs file does NOT carry.
#: These are not facts about a function -- `stick` is not a property of
#: firing a gun, and neither is `this one carries the shift`. They used to
#: be written per need, 86 times, which is one opinion recorded 86 times
#: and therefore an opinion nobody could change.
#:
#: Defined here rather than in `core.overlay` because `Need` is here and
#: this says which of its attributes are wishes; the overlay reads it.
WISHES = ('device', 'prefer', 'shift', 'modifier', 'finger', 'level')

#: The wishes that describe a PLACE on the hand rather than a decision of
#: their own, and so the ones a control is judged against by counting.
#: `device` is not here: it has its own measured pair of terms (+40/-50),
#: tuned against five games, and folding it into a generic count would
#: reweigh every layout for nothing. `prefer` is a pin, `shift` is a layer
#: and `modifier` is a fact flag; none of the three is a place.
#:
#: These are what makes an overlay a cockpit template rather than a device
#: preference: `finger = "thumb"`, `level = "HOME"` is the castle switch
#: said in words that survive leaving the Hornet's grip.
PLACED_BY = ('finger', 'level')

#: The flags that ARE about the function, which is what gets written down.
TOLD = tuple(f for f in FLAGS if f not in WISHES)

#: What `how` says when it was the allocator rather than you. Read back as
#: nothing: see `dump_assignments`.
SOLVED = 'solver'

#: What a function is for, as a closed list. The one word a game's needs
#: file and an overlay can both say, which is what lets one overlay lay out
#: six games. See the table's own header in scoring.toml.
JOBS = tuple(RULES['jobs'])

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


def check_rules(rules, devicemap):
    """Every control word the rules use is one the map can produce.

    Three tables here name shapes and directions, and nothing checked
    them: a shape nobody has -- a typo, or a kind the map has since
    renamed -- simply never matched, and a need asking for it went
    unplaced with no word about why. `FITS` said `switch2` long after
    the map spelled anything that way, and the only sign was a need
    quietly at the bottom of the unplaced list.

    Not at import: this module has to load on a clone with no map at
    all. `devmap.load()` calls it, which is the first moment both exist.
    """
    bad = []
    kinds = set(devicemap.KINDS)
    for want, subs in rules['shapes'].items():
        for one in [want] + list(subs):
            if one not in kinds:
                bad.append(f'shapes: {one!r} is not a kind')
    for one in rules['mechanisms']['one']:
        if one not in kinds:
            bad.append(f'mechanisms: {one!r} is not a kind')
    ways = set(devicemap.DIRECTIONS) | {'push'}
    for want, names in rules['directions'].items():
        for one in names:
            if one not in ways:
                bad.append(f'directions: {want} accepts {one!r},'
                           ' which no control says')
    # A fact names a field on the control rather than a predicate in this
    # module, which is the whole point of the table -- so this is the only
    # thing standing between a typo and a fact that silently never fires.
    told = {f.name for f in dataclasses.fields(devicemap.Group)}
    for fact in rules['fact']:
        if fact['reads'] not in told:
            bad.append(f'fact: {fact["reads"]!r} is not something the map'
                       ' measures about a control')
        if 'asked' not in fact:
            bad.append(f'fact: {fact["reads"]} has no `asked`, so nothing'
                       ' turns it on; a fact is what a NEED asks of a'
                       ' control, not a charge on every control')
        if 'below' in fact and 'scale' not in fact:
            bad.append(f'fact: {fact["reads"]} charges below'
                       f' {fact["below"]} but has no `scale` to charge')
        kinds = [k for k in ('yes', 'scale', 'refuses') if k in fact]
        if len(kinds) != 1:
            bad.append(f'fact: {fact["reads"]} is {" and ".join(kinds)}'
                       ' at once; it has to be exactly one of yes/no,'
                       ' scale, refuses' if kinds else
                       f'fact: {fact["reads"]} weighs nothing')
        if ('yes' in fact) != ('no' in fact):
            bad.append(f'fact: {fact["reads"]} answers yes and no, so it'
                       ' needs a weight for both')
    if bad:
        raise ValueError('scoring.toml:\n  ' + '\n  '.join(sorted(set(bad))))
    return rules


def reach_tier(ctrl):
    """How far this control is from flying, measured by the map.

    `None` there means nobody has walked the fingers on that desk, which
    is why the wizard asks for a rig at all. It is not a tier: it sorts
    below every measured one, so a control somebody checked wins over one
    nobody has.
    """
    return UNMEASURED if ctrl.tier is None else ctrl.tier


def reach_finger(ctrl):
    """The finger that gets there, or '' where nobody recorded one.

    Read off the spot, not split out of `reach_said`: that string is
    `finger, how far` only WHEN there is a finger, and the how-far half
    has a comma of its own -- so splitting gave `your hand where it
    lives` as the name of a finger.
    """
    spots = [a for a in ctrl.access if a.tier == ctrl.tier]
    return spots[0].finger if spots else ''


def reach_level(ctrl):
    """Where the hand is when it reaches this, or '' if nobody measured.

    The level of the nearest spot, the same way `reach_finger` takes its
    finger: a control is as close as its best way in, and the rest are
    other ways to the same place.
    """
    spots = [a for a in ctrl.access if a.tier == ctrl.tier]
    return spots[0].level if spots else ''


#: How to ask a control what an overlay's place words are asking about.
PLACE = {'finger': reach_finger, 'level': reach_level}


def place_wishes(ctrl, need):
    """(kept, broken) -- this control against the overlay's place words.

    Neither, where nobody has measured: a control with no spots has no
    finger and no level, and counting that as broken would charge it for
    a desk nobody has walked rather than for being the wrong place.
    """
    kept = broken = 0
    for word in PLACED_BY:
        want = getattr(need, word, None)
        if not want:
            continue
        got = PLACE[word](ctrl)
        if not got:
            continue
        if got == want:
            kept += 1
        else:
            broken += 1
    return kept, broken


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
                 urgency=IN_THE_AIR, suits=None, device=None,
                 prefer=None, on=None, rank=0, category=None,
                 assignment=None):
        self.what = what
        self.shape = shape
        self.bindings = list(bindings)
        #: for a control that also clicks
        self.push = push
        self.urgency = urgency
        self.suits = suits
        #: which device this belongs on, by the map's `kind` ('stick',
        #: ...). Not written in the needs file and not a judgement about
        #: the function: `stick` is not a property of firing a gun. An
        #: overlay sets it, which is what lets one line say it for a
        #: whole family instead of 76 lines saying it one at a time.
        self.device = device
        #: pin to a control by its label in the map. The allocator ranks by
        #: shape, reach and urgency, which is right for everything nobody has
        #: an opinion about -- but when you DO have one it should win rather
        #: than be argued with at every regeneration.
        self.prefer = prefer
        #: Where on the hand an overlay wants this, as the map's own words:
        #: `finger = "thumb"`, `level = "HOME"` is the Hornet's castle
        #: switch said so that it survives leaving the Hornet's grip.
        #:
        #: Written here rather than left to `setattr`, unlike the fact
        #: flags: those exist because scoring.toml says so, and a sixth
        #: fact must not need an edit here. These two are named in
        #: `WISHES` in this file, so this IS where they are declared.
        #: Not constructor parameters -- no needs file carries them, and
        #: an overlay is the only thing that may set one.
        self.finger = None
        self.level = None
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
        #: Yours: what you filed this under. Separate from `urgency` on
        #: purpose -- "Combat" can hold something you reach for in a turn
        #: and something you set on the ramp, and the allocator still has
        #: to know which is which. Absent means the screen falls back to
        #: the band, which is what it grouped by before there were any.
        self.category = category
        #: How this got where it is, when it was you who decided:
        #: {role, control, how} plus `button` when a press picked one.
        #: `control` is the map's own id rather than the label, because
        #: the map promises an id survives renaming a control and
        #: renumbering its buttons.
        #:
        #: `how` is the strength, and there are two because pressing ENTER
        #: and pressing `c` are not the same claim:
        #:
        #:   chose     you put it here. The allocator is not asked: the
        #:             control is taken before anything is scored.
        #:   accepted  you looked at where the allocator put it and said
        #:             yes. It scores exactly as before -- so if the desk
        #:             or the needs change and it lands somewhere else,
        #:             the row goes back to `?` and tells you.
        #:
        #: `accepted` is deliberately weak. `c` over a full list is one
        #: keystroke, and if it froze every row the allocator would never
        #: speak again and there would be no way back but clearing each
        #: row by hand.
        #:
        #: Neither is `prefer`, which is the third thing: an opinion
        #: written into the file by hand that outranks the ordering but
        #: that the scoring still has to agree with -- a gate can refuse
        #: it, and one did, which is how BMS's pinky shift left the button
        #: it was pinned to.
        #:
        #: Until this was written down, all of it lasted until `q`.
        self.assignment = assignment
        #: What this need ASKS OF a control, against what the map measured
        #: about one: `held` meets `hold_ok`, `costly` meets `accident_risk`.
        #: Not written out, because the fact table in scoring.toml is what
        #: decides they exist -- a sixth fact grows a sixth flag here with
        #: nothing to edit. Three of the map's five questions answer "can
        #: you", and a score needs "must you", which is what these say.
        for flag in FLAGS:
            setattr(self, flag, False)
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


def desk_of(layout):
    """Which rig a layout is for, or '' if nothing says.

    Off the devices, because that is where it already is: a device
    remembers the profile it was laid out under (`Device.under`) and a
    profile has a name. Nothing had to be added to the map for this, and
    nothing has to be threaded through a planner.
    """
    for dev in layout.devices.values():
        got = getattr(dev, 'profile', None)
        if got is not None:
            return got.name
    return ''


def forget_wishes(needs):
    """Take every overlay wish off these needs. Returns how many it found.

    An overlay is a REPLACEMENT, not an addition, and until this existed
    `apply` only ever wrote. One overlay per process hid it: a second one
    laid over the first left every need it says nothing about wearing the
    first file's finger, and `place_right` then counted a wish nobody had
    asked for. `--overlay none` after an overlay had the same hole.

    It walks `WISHES` rather than a list of its own, so a seventh wish is
    cleared by the fact of being in that tuple.
    """
    found = 0
    for need in needs:
        for wish in WISHES:
            if getattr(need, wish, None):
                found += 1
            setattr(need, wish, None if wish not in FLAGS else False)
    return found


def dump_needs(needs):
    """[Need] -> [dict], what each function IS and how you use it.

    Only what a human decided ABOUT THE FUNCTION. The per-context split
    every game's constructor takes -- `air`/`heli`, `plane`/`glob`,
    `ship`/`map`/`foot` -- is absent: it zips into the slots and reads back
    off the binds, so writing it too would be the same fact recorded twice,
    free to drift.

    `WISHES` are absent because they are not about the function: `stick` is
    not a property of firing a gun. An overlay says those, once per family
    rather than once per need -- 76 hand-written copies of one opinion is
    an opinion you cannot change.

    `relaxed` is absent for a third reason: it is set BY a run rather than
    decided before one, and a list that remembered the last outcome would
    have every run start from where the previous one ended up. So is
    `assignment` -- that is the answer, and it lives in the binds file.
    """
    out = []
    for n in needs:
        row = {'what': n.what, 'shape': n.shape,
               'bindings': [cactions.dump_binds(slot) for slot in n.bindings]}
        if n.push:
            row['push'] = cactions.dump_binds(n.push)
        if n.urgency != IN_THE_AIR:
            row['urgency'] = n.urgency
        for field in ('suits', 'category') + TOLD:
            if getattr(n, field):
                row[field] = getattr(n, field)
        if n.on:
            row['on'] = list(n.on)
        # Derived, and written down anyway. It counts how many of the
        # game's own profiles bind the thing, so it COULD be read from the
        # harvest's `*-rank.json` -- and then a refreshed cache would
        # silently reorder a plan you had already walked. Elite froze it
        # here on purpose, and that freeze is the judgement.
        if n.rank:
            row['rank'] = n.rank
        out.append(row)
    return out


def save_needs(directory, filename, needs):
    """Write the description down. One place, because five games had none.

    It is derived from nothing: delete it and it is gone. So a screen that
    lets somebody make one has to be able to keep it, and until this
    existed, promoting an action lasted until `q`.
    """
    from core import vocab
    path, _said = vocab.save(directory, filename, needs=dump_needs(needs))
    return path


def read_needs(rows, make=None):
    """[dict] -> [Need]. `make` is a game's own subclass, when it has one.

    A shape written as a choice comes back a tuple rather than the list
    JSON gives, because `first_shape` is the one asked for and the rest are
    substitutes -- and a list and a tuple are the same to every reader
    except the one asking whether a shape is a single name.

    What comes back wants nothing and sits nowhere: an overlay puts the
    wishes on, `read_assignments` puts back where things sit.
    """
    out = []
    for r in rows:
        shape = r['shape']
        if not isinstance(shape, str):
            shape = tuple(shape)
        push = cactions.read_binds(r['push']) if r.get('push') else None
        if r.get('suits') and r['suits'] not in JOBS:
            # Loudly, the way the overlay reader refuses a rule nobody
            # wrote. A job nobody knows is a word no overlay can match, so
            # a typo would quietly cost that need every wish in the file.
            raise ValueError(
                f'{r["what"]!r} is filed under {r["suits"]!r}, which is not '
                f'a job. There are: {", ".join(JOBS)}')
        need = (make or Need)(
            r['what'], shape,
            bindings=[cactions.read_binds(slot) for slot in r['bindings']],
            push=push, urgency=r.get('urgency', IN_THE_AIR),
            suits=r.get('suits'), on=r.get('on'),
            rank=r.get('rank', 0), category=r.get('category'))
        for flag in TOLD:
            setattr(need, flag, r.get(flag, False))
        out.append(need)
    return out


def dump_assignments(needs):
    """[Need] -> [dict], what sits where. The answer, not the question.

    Every need that is placed, not only the ones you touched: the file
    answers "what is on my desk right now", and one holding only the
    hand-picked rows could not.

    `how` says who decided, and that is the whole weight of the file.
    `chose` and `accepted` are yours and come back as yours. `SOLVED` is
    the allocator's own, written so a screen can show what moved since
    last time and read back as nothing at all -- it pins no control, so the
    next run scores from scratch rather than starting from wherever the
    last one happened to stop.
    """
    out = []
    for n in needs:
        if not n.assignment:
            continue
        row = {'what': n.what}
        for field in ('role', 'control', 'button', 'how'):
            if n.assignment.get(field) is not None:
                row[field] = n.assignment[field]
        out.append(row)
    return out


def load_assignments(directory, filename, needs):
    """Put back what sits where, if anything has been written yet.

    A missing file is not a fault: a game somebody has planned but never
    saved has no answers on disk, and the allocator is about to produce
    them. That is why this does not go through `vocab.load`, whose missing
    file is an error telling you to run the harvest -- a cache is built
    from the installed game and this is not.
    """
    path = os.path.join(directory, filename)
    if not filename or not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8') as f:
        return read_assignments(json.load(f).get('binds', []), needs)


def save_assignments(directory, filename, needs):
    """Write down what sits where."""
    from core import vocab
    path, _said = vocab.save(directory, filename,
                             binds=dump_assignments(needs))
    return path


def read_assignments(rows, needs):
    """Put the assignments back on these needs, by name. Returns how many.

    A row the allocator wrote is read and dropped: see
    `dump_assignments`. A row
    naming a function the game no longer has is dropped with a word -- the
    quiet alternative is a file that keeps growing graves.
    """
    at = {n.what: n for n in needs}
    kept = 0
    for row in rows:
        if row.get('how') == SOLVED:
            continue
        need = at.get(row['what'])
        if need is None:
            print(f'!! {row["what"]!r} is not a function this game has any '
                  'more; dropping where it used to sit', file=sys.stderr)
            continue
        need.assignment = {k: v for k, v in row.items() if k != 'what'}
        kept += 1
    return kept


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

    It used to write down WHY each button, one phrase per binding, for
    a panel that drew them under `WHICH BUTTON`. Of 223 phrases across
    the five games, 221 said nothing had happened: `press order` where
    the need named no directions, `as asked` where it named one the
    control agrees about, and `asked for back; this control calls it
    aft` where the two words mean one direction and the table above says
    so. Naming the rule that ran is not an answer to which button.
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
    # Where you last accepted it. The layout is a thing you learn with
    # your hands, so it is worth points for its own sake: without this,
    # anything better that came free took it, and moving ONE binding by
    # hand re-let 21 of X4's 32 because every other decision was made
    # afresh against a board that had shifted.
    'stayed': lambda c, n, r, t: (bool(n.assignment)
                                  and n.assignment.get('role') == r
                                  and n.assignment.get('control') == c.id),
    'device_matches': lambda c, n, r, t: n.device == r,
    'device_differs': lambda c, n, r, t: (bool(n.device)
                                         and n.device != r),
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
    'place kept': lambda c, n, r, t: place_wishes(c, n)[0],
    'place broken': lambda c, n, r, t: place_wishes(c, n)[1],
}

def _adder(parts):
    """The two-step, in one place: score everything, describe the winner.

    Scoring runs over every control against every need and wants a number.
    The winner is scored a second time, with somewhere to put the terms,
    which is what makes the explanation the same arithmetic as the
    decision rather than a second telling of it.

    A term worth nothing is left out rather than listed as zero: a screen
    saying `0  findable by feel` reads as a fact about the control, and it
    is the absence of one.
    """
    def part(delta, text):
        if parts is not None and delta:
            parts.append((delta, text))
        return delta
    return part


def _facts(rules, ctrl, need, role, part, named=None):
    """What the map measured about this control, weighed against the need.

    Not in `WHEN`, because none of these is a predicate somebody wrote: a
    row in the fact table names a FIELD on the control, and the three
    shapes a row can take are fixed here instead. That is what makes a
    sixth question the wizard starts asking cost a block in a file.

    Two rules live here rather than in each row, so that no future fact
    can be written without them:

    A fact nobody answered counts for nothing. `None` is not a middling
    answer, it is an unwalked desk -- the same reasoning that keeps the
    reach term off an unmeasured control, where paying for distance
    nobody measured let an unmeasured button beat a measured thumb.

    A fact only counts where the need asks for it. "Can you hold this
    down" is a fact about a control; whether it matters is a fact about
    the action, and charging every control for it would push everything
    away from the same homes when something still has to go there. The
    fact that counted for every need, however sensibly chosen, moves half
    the list at once: the one that rode the band instead of asking
    reshuffled 99 bindings, 46 of them between controls that answered it
    the same way.
    """
    s = 0
    for fact in rules['fact']:
        if fact.get('refuses'):
            continue
        told = getattr(ctrl, fact['reads'])
        if told is None:
            continue
        if not getattr(need, fact['asked']):
            continue
        if 'scale' in fact:
            # A 0/1/2 answer pays per step. `below` charges the SHORTFALL
            # instead -- how far under the best answer this control is --
            # which is what a fact almost everything answers well has to
            # do to say anything: your desk has 20 of 22 home controls at
            # the top of `blind_distinct`, so paying for it paid everyone
            # the same +20 and merely disturbed the ties underneath. 99
            # bindings moved between equally findable controls for it.
            # Either way the best answer costs nothing, and `part` drops a
            # term worth nothing, so nothing says `0 findable by feel`.
            n = fact['below'] - told if 'below' in fact else told
            words = (fact['plural'] if n != 1 and 'plural' in fact
                     else fact['says'])
            if named is not None and fact['scale'] * n:
                named.append((fact['reads'], fact['scale'] * n, words))
            s += part(fact['scale'] * n, words)
        else:
            delta = fact['yes'] if told else fact['no']
            words = fact['says'] if told else fact['not']
            if named is not None and delta:
                named.append((fact['reads'], delta, words))
            s += part(delta, words)
    return s


def _fact_refuses(rules, ctrl, need):
    """The fact that puts this control out of the question, or None.

    Only on a measured "no". A map nobody has answered would otherwise
    refuse every control for a need asking to be a modifier, and a need
    with nowhere to go reads as a broken planner rather than as a desk
    nobody has walked -- which is the argument `out_of_reach` makes.
    """
    for fact in rules['fact']:
        if (fact.get('refuses') and getattr(need, fact['asked'])
                and getattr(ctrl, fact['reads']) is False):
            return fact
    return None


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
          rules=None, named=None):
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
    part = _adder(parts)

    def mark(name, delta, text):
        """The same term, under its own name. `parts` carries the WORDS,
        which are the run's -- and `1 spare button` and `2 spare buttons`
        are one term wearing two of them, so anything comparing two
        controls by their words sees a term neither of them has."""
        if named is not None and delta:
            named.append((name, delta, text))
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
    # With the shape gates rather than the pass gate, and so BEFORE the pin,
    # which stops. A pin is an opinion about which control is right and this
    # is a fact about which cannot do the job at all: pinning a shift to
    # something you cannot hold down while working the layer it reaches is
    # exactly the failure the `pinned` term's own note describes.
    if _fact_refuses(rules, ctrl, need):
        return None
    for term in rules['term']:
        if term.get('stops') and WHEN[term['when']](ctrl, need, role, tier):
            said = _says(term, ctrl, need, role, 1)
            mark(term['name'], term['weight'], said)
            return part(term['weight'], said)
    if REFUSE['out_of_reach'](run):
        return None

    s = 0
    for term in rules['term']:
        if term.get('stops') or not WHEN[term['when']](ctrl, need, role,
                                                       tier):
            continue
        n = PER[term['per']](ctrl, need, role, tier) if 'per' in term else 1
        said = _says(term, ctrl, need, role, n)
        mark(term['name'], term['weight'] * n, said)
        s += part(term['weight'] * n, said)
    return s + _facts(rules, ctrl, need, role, part, named=named)


def _says(term, ctrl, need, role, n):
    """A term's words, with the run's own values in them."""
    form = term['plural'] if n != 1 and 'plural' in term else term['says']
    return form.format(role=role, device=need.device, kind=ctrl.kind,
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
                 )

    def __init__(self, how, points=None, parts=(), tier=None,
                 ceiling=None, instead=None):
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

    @property
    def overridden(self):
        """Did a person put this here rather than the planner."""
        return self.how == 'yours'

    def __repr__(self):
        return f'<Reason {self.how} {self.points}>'


#: How a placement came about, as a reader wants it said. `floored` is
#: absent on purpose: it is the ordinary case, and a line announcing that
#: nothing unusual happened is a line you learn to skip past.
CAME_BY = {
    'relaxed': 'reached past the floor',
    'borrowed': 'borrowed a spare button',
    'claimed': 'claimed, not allocated',
    'yours': 'assigned by you',
}


def ran_against(need, devices, rules=None, usable=None, floor=True):
    """[(points, role, ctrl)] -- every control that could have taken this
    need, best first. What the allocator compared, kept.

    Scored WITHOUT `stayed`. That term pays whichever control the need is
    already on, so a comparison counting it answers "it is here because
    it is here": every alternative sits 20 below and the screen reports
    that nothing else fitted. Being where you left it is a reason, but it
    is not a reason one CONTROL beat another, so it is said separately.

    `offers` computes this set at every placement and throws it away. It
    is recomputed rather than carried because the screen asks for one
    need at a time and the allocator would have to carry it for all of
    them, through a Layout, through five adapters.

    `floor` has to be the one the placement was made under. A binding
    that reached past the floor is refused by the floored pass, so asking
    with the floor on answers that the control it is sitting on was never
    a candidate.
    """
    rules = merge_rules(rules or RULES, {'term': [{'name': 'stayed',
                                                   'weight': 0}]})
    out = []
    for role, dev in sorted(devices.items()):
        for ctrl in dev.groups(bindable=True):
            got = score(ctrl, need, role, floor=floor, usable=usable,
                        rules=rules)
            if got is not None:
                out.append((got, role, ctrl))
    return sorted(out, key=lambda x: -x[0])


def what_differs(need, mine, theirs, rules=None):
    """[(delta, words)] -- the terms that tell two controls apart.

    Both of them fit, both are the right shape, both are on the device it
    asked for: those cancel. What is left is the whole of why one beat
    the other, and it is usually one line where the score was ten.
    """
    rules = merge_rules(rules or RULES, {'term': [{'name': 'stayed',
                                                   'weight': 0}]})
    said = []
    for role, ctrl in (mine, theirs):
        named = []
        score(ctrl, need, role, named=named, rules=rules)
        said.append({name: (delta, text) for name, delta, text in named})
    a, b = said
    out = []
    for name in set(a) | set(b):
        da, wa = a.get(name, (0, ''))
        db, _wb = b.get(name, (0, ''))
        if da != db:
            out.append((da - db, wa or b[name][1]))
    return sorted(out)


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


def hand_out(slots, role, why):
    """Tell every binding in `slots` where it went and why.

    A payload is still whatever a game put there -- the allocator only ever
    indexes it -- so this asks rather than assumes: anything that knows how
    to be told is told, and anything else is carried as before.

    Each binding gets its OWN `Reason`, and they now say the same
    thing. What distinguished them was a phrase about which button of
    the control it was, and 221 of the 223 that phrase ever produced
    said nothing had happened.
    """
    for button, payload in slots:
        for b in payload if isinstance(payload, (list, tuple)) else [payload]:
            tell = getattr(b, 'placed_on', None)
            if tell is None:
                continue
            tell(role, button,
                 Reason(why.how, why.points, why.parts, why.tier,
                        why.ceiling, why.instead))


#: The two strengths a decision of yours can have. `CHOSE` takes the
#: control before anything is scored; `ACCEPTED` changes no allocation at
#: all and only tells the screen you have looked. See `Need.assignment`.
CHOSE, ACCEPTED = 'chose', 'accepted'


def assigned_at(pool, want):
    """Where in the pool the control you chose is, or None if it is gone.

    On the id, not the label: the map promises an id outlives renaming a
    control and renumbering its buttons, and a label is the thing the
    capture wizard lets you retype. The role is checked too, because one
    desk had the same label on both devices.
    """
    for j, (role, ctrl) in enumerate(pool):
        if role == want.get('role') and ctrl.id == want.get('control'):
            return j
    return None


def honours_press(need, ctrl, button):
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


def put(need, role, ctrl, why, button=None, points: int | None = 0):
    """The placement: which button takes which binding, and everyone told.

    Two callers had a copy -- the allocator's passes and the review
    screen's assign -- and they had already drifted: one told the click
    what it was for and the other did not. A third copy was about to be
    written for the pass that honours what you chose, which is the point
    at which a copy becomes a definition.

    `button` is the one actually pressed, when a press is what decided.
    """
    buttons = slots_for(need, ctrl)
    if button is not None and honours_press(need, ctrl, button):
        buttons = [button]
    # `if v` rather than `is not None`: a payload is a list of Binds and an
    # empty one means this direction was left alone, which is what `None`
    # used to say.
    slots = [(b, v) for b, v in zip(buttons, need.bindings) if v]
    if need.push is not None and ctrl.push is not None:
        slots.append((ctrl.push, need.push))
    hand_out(slots, role, why)
    return Placement(need, role, ctrl, slots, points, why)


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


#: What decides which need is looked at first, in the order it decides.
#: Beside `allocate`'s sort key, because the screen that explains the
#: allocator had this as a paragraph and a paragraph does not move when
#: the key does: it still said a pin went first long after what you chose
#: by hand started outranking one, and stopped at the factory count after
#: a fourth step was added under it.
ORDERED_BY = (
    ('what you put there yourself', 'the control leaves the pool'),
    ('a control you pinned by name', 'offered its pin and nothing else'),
    ('how soon you reach for it', 'the bands above'),
    ('how many of the game\'s own profiles bind it', 'within a band only'),
    ('its name', 'so the file\'s line order decides nothing'),
)

#: The solver this run uses, which `--solver` sets once at startup. A
#: module-level default rather than an argument threaded through seven
#: call sites, because it is one decision per run and not a property of
#: any one allocation -- `allocate` still takes it explicitly, which is
#: how the tests ask for one without touching anything else.
SOLVER = None

#: The overlay this run uses, which `--overlay` sets once at startup. Same
#: argument as `SOLVER`: one decision per run, not a property of any one
#: allocation, and `allocate` still takes it explicitly so a test can ask
#: for one without touching anything else.
#:
#: Typed loosely because `core.overlay` imports THIS module, so naming
#: `Overlay` here would be a cycle -- and a bare `= None` narrows to
#: `Never` for every caller past the `is None` guard.
OVERLAY: typing.Any = None


def allocate(needs, devices, usable=None, rules=None, solver=None,
             overlay=None):
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

    `overlay` is what you want of the layout, as opposed to what the game
    wants of it: which device a family belongs on, which control carries
    the shift, which two things your hand must be able to work at once.
    Without one, nothing is asked for and every control is judged on reach
    and shape alone.
    """
    rules = rules or RULES
    overlay = overlay if overlay is not None else OVERLAY
    #: (need, need, what the rule accepts) -- the rule as a callable, not
    #: as a name to look up later, so nothing below has to hold the
    #: overlay to ask it a question.
    pairs = overlay.bound(needs) if overlay is not None else []
    who = solver or SOLVER or csolvers.best()
    top = {n: b['takes'][1] for n, b in enumerate(rules['band'])}
    low = {n: b['takes'][0] for n, b in enumerate(rules['band'])}
    pool = [(role, c) for role, d in sorted(devices.items())
            for c in d.groups(bindable=True)]
    taken, placed = set(), []
    #: which control each need ended up on, by identity, for the pair
    #: rules. Not read off `placed`: that holds `Placement` objects and
    #: the question here is asked per candidate, in the hot loop.
    sat = {}

    # Before anything is scored: what YOU put there. Not a strong opinion
    # -- `prefer` below is the strong opinion, and the difference is the
    # whole point. A pin outranks the ordering and the ranking, and the
    # scoring still has to agree with it: a gate can refuse a pinned
    # control, and one did, which is how BMS's pinky shift left the button
    # it was pinned to and turned up on the throttle. Nothing refuses
    # this. You sat at the desk with the stick in your hand and put the
    # thing where you wanted it; there is no opinion here to overrule.
    #
    # Until it was written down it lasted until `q`: every mark and every
    # hand-placed binding was rebuilt from the planner on the next open,
    # so an evening of walking the list came back purple and in the
    # planner's order.
    chose, orphan = set(), []
    for i, need in enumerate(needs):
        if not need.assignment \
                or need.assignment.get('how') != CHOSE:
            continue
        j = assigned_at(pool, need.assignment)
        if j is None:
            # Say it and leave the need empty. Quietly allocating it
            # somewhere else is the one thing this must not do: the whole
            # reason it is written down is that it does not move.
            print(f'!! {need.what!r} is where you put it, on '
                  f'{need.assignment.get("control")!r}, and this desk has '
                  'no such control; leaving it unplaced rather than '
                  'moving it',
                  file=sys.stderr)
            chose.add(i)
            orphan.append(i)
            continue
        if j in taken:
            print(f'!! {need.what!r} and something else are both on '
                  f'{need.assignment.get("control")!r}; the first keeps it',
                  file=sys.stderr)
            chose.add(i)
            orphan.append(i)
            continue
        taken.add(j)
        role, ctrl = pool[j]
        placed.append(put(need, role, ctrl, Reason('yours'),
                          button=need.assignment.get('button')))
        sat[id(need)] = ctrl
        chose.add(i)

    #: Pinned needs go first, before urgency is consulted at all. `prefer` used
    #: only to tip the scales, which is no use once something more urgent has
    #: already taken the control. It is belt and braces now -- `offers` gives a
    #: pinned need its pin and nothing else, and the term stops -- and taking
    #: this out moves no binding in any of the five games. It stays because the
    #: other two are about SCORING and this is about the queue, and the day one
    #: of them changes shape is the day it matters again.
    #: (The paragraph that follows is the original, kept for the story.)
    #: Pinned needs go first, before urgency is consulted at all. `prefer` used
    #: to only tip the scales, which is no use once something more urgent has
    #: already taken the control: BMS's pinky shift was pinned to the grip
    #: pinky button and still lost it to the landing lights, because they are
    #: touched on approach and it is not. An explicit choice has to outrank the
    #: ordering as well as the ranking, or it is not a choice.
    # `what` last, and it is load-bearing. Without it this is not a total
    # order, `sorted` is stable, and every tie falls back to the order the
    # needs happen to sit in the file -- so the layout was a function of
    # the file's line order. Moving two lines about moved bindings, and
    # the review screen moved them itself: it saves the list back in
    # PLACEMENT order, so every save reshuffled the ties, and the next
    # open placed them differently. X4 came back with four rows purple
    # after a save that changed nothing but the order they were written
    # in. Nothing in a layout should turn on that.
    order = sorted((i for i in range(len(needs)) if i not in chose),
                   key=lambda i: (needs[i].prefer is None, needs[i].urgency,
                                  -needs[i].rank, needs[i].what))

    def offers(i, floor):
        """{pool index: points} -- where this need may go, and what each
        is worth. A pinned need is offered its pin and nothing else, so
        the choice is a choice rather than a nudge the ranking can undo.
        """
        need = needs[i]
        out = {}
        for j, (role, c) in enumerate(pool):
            if j in taken:
                continue
            if need.prefer and floor and c.label != need.prefer:
                continue
            if not allowed(need, c):
                continue
            s = score(c, need, role, floor=floor, usable=usable, rules=rules)
            if s is not None:
                out[j] = s
        return out

    def allowed(need, ctrl):
        """Does this control keep every pair rule this need is half of?

        Against what is already down, which is why this is not a gate:
        `score` sees one control and one need, and a pair rule is a claim
        about two placements. The partner that has not been placed yet
        says nothing -- the rule is kept by whichever of the two is placed
        second, and both orders give the same answer.
        """
        for one, other, keeps in pairs:
            mine = other if one is need else one if other is need else None
            if mine is None or not sat.get(id(mine)):
                continue
            if not keeps(ctrl, sat[id(mine)]):
                return False
        return True

    #: need -> its index, for the pair rules, which hold Needs
    which = {id(n): i for i, n in enumerate(needs)}

    def broken(got, wants):
        """The one placement to forbid, or None if the batch keeps every
        pair rule.

        `allowed` above cannot see this: it filters a candidate against
        what is already DOWN, and a batch is solved as one model, so both
        halves of a pair are decided at once and neither is down yet. So
        the batch is checked after the fact and re-solved without the
        offending option -- the cheaper half of the pair, because the one
        that wanted its control less is the one to move.
        """
        points = dict(wants)
        for one, other, keeps in pairs:
            a, b = which.get(id(one)), which.get(id(other))
            if a not in got or b not in got:
                continue
            if keeps(pool[got[a]][1], pool[got[b]][1]):
                continue
            # Lower points first, then the later control, so the same
            # inputs always forbid the same option.
            return min(((a, got[a]), (b, got[b])),
                       key=lambda p: (points[p[0]].get(p[1], 0), -p[1]))
        return None

    def chosen(todo, floor):
        """{need index: pool index} for as many as can be placed.

        One model rather than one choice per need in turn. Greedy cannot
        undo a choice, so an early urgent need takes the control a later
        one needed more -- and there is no pass that gives it back.
        """
        wants = [(i, offers(i, floor)) for i in todo]
        banned = set()
        got = {}
        # One option forbidden per round, so the walk is bounded by the
        # pool: every round either answers or takes a control out of play.
        for _ in range(len(pool) + 1):
            trimmed = [(i, {j: s for j, s in room.items()
                            if (i, j) not in banned})
                       for i, room in wants]
            said = who.best(trimmed, range(len(pool)))
            if said is None:
                # It could not answer -- a model that ran out of time with
                # nothing feasible. Walking the list is worse than the best
                # answer and much better than none.
                said = csolvers.FALLBACK().best(trimmed, range(len(pool)))
            got = dict(said)
            if not pairs:
                return got
            bad = broken(got, trimmed)
            if bad is None:
                return got
            banned.add(bad)
        return got

    def pass_over(todo, floor):
        left = []
        picked = chosen(todo, floor)
        for i in todo:
            need = needs[i]
            best = picked.get(i)
            best_s = None if best is None else score(
                pool[best][1], need, pool[best][0], floor=floor,
                usable=usable, rules=rules)
            if best is None and need.prefer and floor:
                # it is pinned and the pin is not free: say so rather than
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
            placed.append(put(need, role, ctrl, why, points=best_s))
            sat[id(need)] = ctrl
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
            if not low[need.urgency] <= reach_tier(c) <= top[need.urgency]:
                # The floor as well as the ceiling, which this pass alone
                # used to skip. `on the ramp` takes [2, 3], and the band's
                # own note in scoring.toml says what the floor is for --
                # "without it, something you do once with the canopy open
                # grabs a thumb position the moment one is free". Every
                # other pass honoured that; borrowing handed it a thumb
                # anyway, and then paid it `+12` per tier for being CLOSE.
                # X4's Pause and Cockpit menu sat on the hat that cycles
                # weapon groups. No other band has a floor above 0, so
                # nothing else can notice this.
                continue
            if _fact_refuses(rules, c, need):
                continue
            if not allowed(need, c):
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
            s += 30 if need.device == role else 0
            if j not in taken:
                # Prefer borrowing a spare position over opening a control
                # nothing has touched: four idle two-way rockers should not sit
                # there while a cold-start switch goes homeless, but neither
                # should one be broken open while a real spare exists.
                s -= 15
            # The whole table, not a subset. A fact is a property of the
            # CONTROL, and a borrowed button sits on a control: whether you
            # can hold it down does not become irrelevant because something
            # else owns the rest of it. Called rather than copied, because
            # the terms below are rebuilt by hand and a hand-kept copy of
            # this would have to grow with every fact anybody adds.
            s += _facts(rules, c, need, role, _adder(None))
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
        if need.device == role:
            terms.append((30, f'on the {role}, as asked'))
        if j not in taken:
            terms.append((-15, 'opens an untouched control'))
        _facts(rules, ctrl, need, role, _adder(terms))
        why = Reason('borrowed', points=_s, parts=terms,
                     tier=reach_tier(ctrl),
                     ceiling=top[need.urgency])
        slots = [(button, need.bindings[0])]
        hand_out(slots, role, why)
        placed.append(Placement(need, role, ctrl, slots, _s, why))
        sat[id(need)] = ctrl

    # A need whose chosen control is gone comes back here and NOT through
    # the borrow pass above: borrowing it a spare button somewhere else is
    # moving it, which is the one thing writing the choice down was for.
    # It waits, empty, for you to say where it goes now.
    still += orphan

    # Free means every button of it is free, not merely that no need chose it.
    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken
            and not any((r, b) in occupied for b in c.bindable_buttons)]
    return placed, [needs[i] for i in still], free

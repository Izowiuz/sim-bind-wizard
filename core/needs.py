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

import collections
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
            raise ValueError(
                f'{section!r} is not a section of the rules.')
        if section not in KEYED_BY:
            out[section] = {**out[section], **given}
            continue
        key = KEYED_BY[section]
        at = {row[key]: n for n, row in enumerate(out[section])}
        for row in given:
            if row[key] not in at:
                raise ValueError(
                    f'{section} {row[key]!r} is not one that the rules '
                    'define.')
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

#: Where an axis sits when you let go of it, in the map's own words. A
#: need names the one its function needs: pitch has to spring back or the
#: aircraft will not fly level, a throttle has to stay or it returns to
#: half power, a brake has to rest at the minimum or it is part-on from
#: the moment the game starts. `check_rules` holds this to
#: `devicemap.RESTS`, so the day the map renames one of them the load
#: fails instead of the match quietly never firing.
RESTS = ('centred', 'min', 'max', 'mid')

#: The two kinds of input a control offers. Not two kinds of NEED: a
#: function that wants an axis is a function like any other, wanting a
#: part of a control, and the axes were a second model of everything --
#: their own object, their own resolver, their own file section, their
#: own rows on the screen and in the sheet, their own branch of every
#: key -- for no reason but that they grew separately.
BUTTON, AXIS = 'button', 'axis'

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
FLAGS = tuple(f['asked'] for f in FACTS
              if f.get('asked') and 'same' not in f)

#: What a fact of the fourth shape asks for: a WORD out of a closed
#: vocabulary, not a flag. `rests` names which resting position the
#: function needs, against what the map measured about the lever -- so
#: the field holds one of `RESTS` or None, where every `FLAGS` field
#: holds True or False.
VALUES = tuple(f['asked'] for f in FACTS if 'same' in f)

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
    if set(RESTS) != set(devicemap.RESTS):
        bad.append(f'rests: this file says {sorted(RESTS)} and the map '
                   f'says {sorted(devicemap.RESTS)}')
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
    told |= {n for n in vars(devicemap.Group) if not n.startswith('_')}
    # A row says which thing it reads. What the map measured about a
    # LEVER is on the axis, and half of those answers are properties
    # derived from `rest` and `moves_with` rather than fields.
    on_axis = {f.name for f in dataclasses.fields(devicemap.Axis)}
    on_axis |= {n for n in vars(devicemap.Axis) if not n.startswith('_')}
    for fact in rules['fact']:
        where = on_axis if fact.get('on') == 'axis' else told
        if fact['reads'] not in where:
            bad.append(f'fact: {fact["reads"]!r} is not something the map'
                       f' measures about {fact.get("on", "a control")}')
        if 'asked' not in fact:
            bad.append(f'fact: {fact["reads"]} has no `asked`, so nothing'
                       ' turns it on; a fact is what a NEED asks of a'
                       ' control, not a charge on every control')
        if 'below' in fact and 'scale' not in fact:
            bad.append(f'fact: {fact["reads"]} charges below'
                       f' {fact["below"]} but has no `scale` to charge')
        kinds = [k for k in ('yes', 'scale', 'same', 'refuses') if k in fact]
        if len(kinds) != 1:
            bad.append(f'fact: {fact["reads"]} is {" and ".join(kinds)}'
                       ' at once; it has to be exactly one of yes/no,'
                       ' scale, same/other, refuses' if kinds else
                       f'fact: {fact["reads"]} weighs nothing')
        if ('yes' in fact) != ('no' in fact):
            bad.append(f'fact: {fact["reads"]} answers yes and no, so it'
                       ' needs a weight for both')
        if ('same' in fact) != ('other' in fact):
            bad.append(f'fact: {fact["reads"]} matches a value, so it'
                       ' needs a weight for both answers')
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
                 prefer=None, on=None, category=None,
                 assignment=None, takes=BUTTON, invert=False, find=None,
                 rests=None):
        self.what = what
        self.shape = shape
        self.bindings = list(bindings)
        #: BUTTON or AXIS: which of a control's two kinds of input this
        #: takes. A control can have both -- the throttle's mini-stick is
        #: two axes and a click -- so the need says which it wants, and
        #: `shape`, `device` and `on` name the rest the same way for
        #: either: `shape stick, device stick, on ('y',)` is the stick's
        #: pitch axis, and `shape hat4, on ('up','down')` is two
        #: directions of a hat.
        self.takes = takes
        #: which way round an axis runs. An attribute of an axis binding
        #: like `on` is an attribute of a hat binding, and the one thing
        #: about an axis you change from the screen.
        self.invert = invert
        #: What the game's own FILE asked for, by field -- as opposed to
        #: what an overlay wished. `device` and `prefer` are a wish when
        #: an overlay sets them and the game's ASK when the file does:
        #: `device throttle, prefer left throttle lever` is the file
        #: saying which lever the throttle is.
        #:
        #: Kept as the VALUES, because taking an overlay off has to put
        #: the ask BACK, not merely leave it alone. Told apart by `takes`
        #: instead, an overlay rule that matched an axis need overwrote
        #: the ask and survived `--overlay none`: `f-18.toml` put the
        #: Hornet's pitch on the throttle, and the next save would have
        #: written that into the needs file as the game's own ask.
        self.from_file = {}
        #: A search only the game can answer, carried and not read: War
        #: Thunder's brake is "a slider or lever on the stick you can
        #: read absolutely", and no vocabulary of kinds and labels says
        #: that. `allocate(finds=...)` is asked when this is set -- the
        #: one place a game still answers for itself, and it is two rows
        #: of nineteen in one of the six.
        self.find = find
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
        #: pin to a control by its label in the map. The allocator scores
        #: by shape, reach and urgency, which is right for everything nobody
        #: has an opinion about -- but when you DO have one it should win
        #: rather than be argued with at every regeneration.
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
        # A fact that matches a word, not a bool: the field exists on
        # every need the moment somebody writes the block, same as the
        # flags above.
        for named in VALUES:
            setattr(self, named, None)
        self.rests = rests
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


@dataclasses.dataclass(frozen=True)
class OnAxis:
    """Which axis of a control a binding went on: a slot index that says
    it is an axis and not a button.

    A control's buttons and its axes are numbered in different
    namespaces -- the throttle's mini-stick is button 23 and axes 0 and
    1 -- so a slot index has to say which one it means. A plain integer
    cannot: `(throttle, 2)` would be a lever and a hat direction at
    once, and `occupied` would have them collide silently. Frozen, so it
    is a dict key like the integers it sits beside.
    """
    index: int

    def __str__(self):
        return f'axis {self.index}'



def answers_need(dev, axis, need):
    """Would this axis answer what this need asked for?

    The ask is a GATE and the points choose among what passes it: on a
    throttle with three levers, "a lever that rests at zero" is answered
    by all three and only the scoring can say which. A search the game
    answers is not asked -- the core does not know what it was looking
    for.
    """
    if need.find:
        return False
    ctrl = dev.axis_group(axis.index)
    if ctrl is None:
        return False
    if need.prefer:
        if ctrl.label.lower() != need.prefer.lower():
            return False
    elif ctrl.kind not in need.shapes:
        return False
    return not need.on or axis.role == need.on[0]


def axes_of(dev, ctrl):
    """[axis] of this control, in the device's own order."""
    return [a for a in sorted(dev.axes(), key=lambda x: x.index)
            if dev.axis_group(a.index) is ctrl]


def axis_for(need, dev, ctrl):
    """The axis of this control this need asks for, or None.

    `on` names which one the way it names a hat's directions: `('y',)`
    is the stick's pitch, and the map calls that the axis's own role.
    Nothing named takes the control's first, which is what a lever has
    anyway.
    """
    got = axes_of(dev, ctrl)
    if not need.on:
        return got[0] if got else None
    want = need.on[0]
    return next((a for a in got if a.role == want), None)


def group_of(dev, axis):
    """Which input this axis IS, as a key -- itself and whatever travels
    with it.

    Two axes that move together are one input: the VMAX's throttle levers
    travel as a pair until you release the catch, so a function on the
    second one moves with whatever is on the first. `moves_with` is the
    map's answer, AS THE HARDWARE IS SET UP NOW.
    """
    return frozenset({axis.index} | set(axis.moves_with or ()))


def context_of(need):
    """Which context this binding answers in, or '' where a game has one.

    The game says it, on the binding: MSFS writes `plane`/`heli`/`glob`
    because it chooses a file by it. It is what tells a shared axis from
    a clash -- you are never flying the aeroplane and the helicopter at
    the same time.
    """
    for slot in need.bindings:
        for b in slot:
            got = getattr(b, 'mode', None)
            if got:
                return got
    return ''


def axes_for(need, devices, usable=None, rules=None):
    """[(points, role, control, axis)] -- every lever that could take this
    need, best first. What the allocator compares, for an axis.

    The ask is a GATE and the measurement decides among what passes it:
    `device` says which stick, `shape` which kind of control, `on` which
    axis of it, `prefer` names one outright. Where the ask leaves one
    candidate -- `on ('y',)` is the stick's pitch and there is one of it
    -- the points change nothing. Where it leaves three levers, the
    points are what chooses, instead of whichever the device happened to
    report first.

    That `first` was the last place in the tool where a binding was
    decided without comparing anything, and three games had written
    their own comparisons around it as chains of `if`: "a dial first,
    else a slider that rests at its minimum", "a slider or lever you can
    read absolutely", "steadiest first: something that stays where you
    leave it". All three are over what the map measures, which is what
    the scoring table is for.
    """
    out = []
    for role, dev in sorted(devices.items()):
        if need.device and need.device != role:
            continue
        for ctrl in dev.groups(bindable=True):
            if need.prefer:
                if ctrl.label.lower() != need.prefer.lower():
                    continue
            elif ctrl.kind not in need.shapes:
                continue
            for axis in axes_of(dev, ctrl):
                if need.on and axis.role != need.on[0]:
                    continue
                got = score(ctrl, need, role, usable=usable, rules=rules,
                            axis=axis)
                if got is not None:
                    out.append((got, role, ctrl, axis))
    # Lowest index first among equals, so the same desk always answers the
    # same way: a tie settled by report order is a layout that moves when
    # the firmware renumbers something.
    out.sort(key=lambda x: (-x[0], x[3].index))
    return out


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

    What the game's own file asked for comes BACK rather than going with
    them: `device throttle, prefer left throttle lever` is the file
    saying which lever the throttle is, and a need cleared of it asks for
    nothing. `from_file` holds those values, so this reads the same for
    either kind of need -- and a button need whose file names a device
    keeps it too, which it did not before.
    """
    found = 0
    for need in needs:
        for wish in WISHES:
            was = need.from_file.get(wish)
            got = getattr(need, wish, None)
            # Truthy AND not what the file said. A flag nobody set is
            # False while the file says nothing (None), and counting that
            # as a wish found makes `forget_wishes` answer 4 where it
            # should answer 2.
            if got and got != was:
                found += 1
            setattr(need, wish,
                    was if was is not None
                    else (None if wish not in FLAGS else False))
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
        if n.takes != BUTTON:
            row['takes'] = n.takes
            if n.invert:
                row['invert'] = True
            if n.rests:
                row['rests'] = n.rests
        # What the FILE asked for, which is not what the need is wearing:
        # an overlay sets `device` and `prefer` too, and saving those
        # would write a wish into the file as the game's own ask.
        for field in ('device', 'prefer', 'find'):
            if n.from_file.get(field):
                row[field] = n.from_file[field]
        out.append(row)
    return out


def save_needs(directory, filename, needs):
    """Write the description down. One place, because five games had none.

    It is derived from nothing: delete it and it is gone. So a screen that
    lets somebody make one has to be able to keep it, and until this
    existed, promoting an action lasted until `q`.

    One section. The axes were a second one, with rows of their own
    shape, which is what made every reader of this file need two code
    paths: an axis row is a need row that takes an axis.
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
        if r.get('rests') and r['rests'] not in RESTS:
            # Loudly, like a job nobody wrote: a resting word the map
            # does not use is a match that can never fire, and the only
            # sign would be an axis quietly on the wrong lever.
            raise ValueError(
                f'{r["what"]!r} wants an axis that rests {r["rests"]!r}. '
                f'The map does not use that word. It uses these: '
                f'{", ".join(RESTS)}.')
        if r.get('suits') and r['suits'] not in JOBS:
            # Loudly, the way the overlay reader refuses a rule nobody
            # wrote. A job nobody knows is a word no overlay can match, so
            # a typo would quietly cost that need every wish in the file.
            raise ValueError(
                f'{r["what"]!r} is filed under {r["suits"]!r}. That is '
                f'not a job. These are: {", ".join(JOBS)}.')
        need = (make or Need)(
            r['what'], shape,
            bindings=[cactions.read_binds(slot) for slot in r['bindings']],
            push=push, urgency=r.get('urgency', IN_THE_AIR),
            suits=r.get('suits'), on=r.get('on'),
            category=r.get('category'),
            takes=r.get('takes', BUTTON), invert=r.get('invert', False),
            find=r.get('find'), rests=r.get('rests'),
            # An overlay sets these too, so which of the two this is gets
            # written down: `forget_wishes` has to tell them apart and
            # `takes` is not the difference.
            device=r.get('device'), prefer=r.get('prefer'))
        need.from_file = {f: r[f] for f in ('device', 'prefer', 'find')
                          if r.get(f)}
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
        # `axis` where a button row says `button`: which part of the
        # control it landed on, in the namespace that control uses.
        for field in ('role', 'control', 'button', 'buttons', 'axis', 'how'):
            if n.assignment.get(field) is not None:
                row[field] = n.assignment[field]
        # Which way round you left it. Also in the needs file, as the
        # game's own default, and this one wins: it is your decision
        # about your wrist, and the other is what the game shipped.
        if n.takes == AXIS and n.invert:
            row['invert'] = True
        out.append(row)
    return out





def _answers_file(directory, filename):
    """What the answers file holds, or None if nothing is written yet.

    A missing file is not a fault: a game somebody has planned but never
    saved has no answers on disk, and the allocator is about to produce
    them. That is why this does not go through `vocab.load`, whose missing
    file is an error telling you to run the harvest -- a cache is built
    from the installed game and this is not.
    """
    path = os.path.join(directory, filename)
    if not filename or not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)



def load_assignments(directory, filename, needs):
    """Put back what sits where, if anything has been written yet."""
    got = _answers_file(directory, filename)
    if got is None:
        return 0
    return read_assignments(got.get('binds', []), needs)


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

    Paired by name AND by order within a name, because a name is not
    unique: MSFS asks for `KEY_BRAKES` twice, once for the aeroplane and
    once for the helicopter, and keying on the name alone gave the second
    one the first one's answer.
    """
    at = {}
    for n in needs:
        at.setdefault(n.what, []).append(n)
    taken = collections.Counter()
    kept = 0
    for row in rows:
        if row.get('how') == SOLVED:
            continue
        same = at.get(row['what']) or []
        i = taken[row['what']]
        taken[row['what']] += 1
        if i >= len(same):
            if not i:
                print(f'!! {row["what"]!r} is not a function of this game '
                      'any more. This drops the control it sat on.',
                      file=sys.stderr)
            continue
        need = same[i]
        need.assignment = {k: v for k, v in row.items()
                           if k not in ('what', 'invert')}
        if need.takes == AXIS and 'invert' in row:
            need.invert = bool(row['invert'])
        kept += 1
    return kept


def directional(ctrl):
    """Does this control move in named directions rather than sit in positions?

    A hat answers 'up'/'left', a selector '1'..'5' and an encoder 'ccw'/'cw'.
    Only the first kind can honour a need's `on`.
    """
    return any(ctrl.direction(b) in SAME_WAY
               for b in ctrl.bindable_buttons)


def on_buttons(need, ctrl):
    """[button] for a need that names its directions, or None if this
    control has not got one of the ones it named.

    `need.on` may name some and leave others None: a DCS hat family often
    has two members whose direction the module's prose makes legible and
    two it does not. The named ones are found first, so a nameless one
    cannot take the button a named one wanted, and the gaps are then
    filled from what is left in press order.
    """
    order = list(ctrl.buttons)
    if ctrl.push is not None and need.push is None:
        order.append(ctrl.push)
    got: list = [None] * len(need.on)
    for i, want in enumerate(need.on):
        if want is None:
            continue
        names = SAME_WAY.get(want, (want,))
        hit = next((b for b in order
                    if ctrl.direction(b) in names and b not in got), None)
        if hit is None:
            return None
        got[i] = hit
    spare = [b for b in order if b not in got]
    for i, b in enumerate(got):
        if b is None:
            if not spare:
                return None
            got[i] = spare.pop(0)
    return got


def satisfies_on(need, ctrl):
    """Can this control put each binding on the direction the need names?

    `need.on` is a claim about the hardware -- a speedbrake switch is fore/aft
    whatever hat it lands on -- and `slots_for` falls back to press order when
    it cannot be honoured. Silently: so a four-way need landed on a five
    position selector, whose positions are '1'..'5' and are not directions at
    all, and Elite's panel focus went onto a switch that HOLDS its position.
    """
    return not need.on or on_buttons(need, ctrl) is not None


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

    An axis need has no buttons to pick from: which axis of the control
    it goes on is resolved against the device, which this cannot see, so
    `put` is told the answer and never asks.
    """
    if need.takes == AXIS:
        return []
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
        picked = on_buttons(need, ctrl)
        if picked is not None:
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
#: Every one takes the `_Run` and nothing else, which is the same
#: signature `REFUSE` has: what a term may read and what a gate may read
#: are the same list, and two spellings of one argument list is one
#: spelling too many. `run.axis` is the candidate lever where the need
#: takes one and None where it takes buttons -- a condition about a lever
#: cannot be written against the control, because three of the stick's
#: axes belong to one control and only one of them is pitch.
WHEN = {
    'always': lambda x: True,
    # The reach term rewards the FURTHEST control that still does the job,
    # because that leaves the near ones for something more urgent. An
    # unmeasured control must not collect that: nobody knows it is far,
    # and paying it for distance nobody measured is how it beat a thumb
    # button somebody had measured.
    'measured': lambda x: x.measured,
    'pinned': lambda x: bool(x.need.prefer) and x.need.prefer == x.ctrl.label,
    # Where you last accepted it. The layout is a thing you learn with
    # your hands, so it is worth points for its own sake: without this,
    # anything better that came free took it, and moving ONE binding by
    # hand re-let 21 of X4's 32 because every other decision was made
    # afresh against a board that had shifted.
    'stayed': lambda x: (bool(x.need.assignment)
                         and x.need.assignment.get('role') == x.role
                         and x.need.assignment.get('control') == x.ctrl.id),
    # Per axis: the map answers it about the lever, not about the control
    # carrying it, so there is nothing to ask of a button need.
    'coupled': lambda x: x.axis is not None and not x.axis.independent,
    'device_matches': lambda x: x.need.device == x.role,
    'device_differs': lambda x: (bool(x.need.device)
                                 and x.need.device != x.role),
    'exact_shape': lambda x: x.ctrl.kind == x.need.first_shape,
    'has_click': lambda x: (x.need.push is not None
                            and x.ctrl.push is not None),
    'directions_differ': lambda x: (not satisfies_on(x.need, x.ctrl)
                                    and directional(x.ctrl)),
    'no_directions': lambda x: (not satisfies_on(x.need, x.ctrl)
                                and not directional(x.ctrl)),
    # Nothing is on this control yet, so taking a button of it breaks it
    # open. Only the borrow pass can tell: every other pass takes whole
    # controls, so for them the answer is always yes and says nothing.
    'untouched': lambda x: x.opening,
}

#: What a weight is multiplied by, where it is multiplied by anything.
PER = {
    'tier': lambda x: x.tier,
    'spare': lambda x: len(x.ctrl.bindable_buttons) - x.need.wanted,
    'place kept': lambda x: place_wishes(x.ctrl, x.need)[0],
    'place broken': lambda x: place_wishes(x.ctrl, x.need)[1],
    # The reach term's polarity, upside down. The ordinary passes reward
    # the furthest control that still does the job, because something more
    # urgent may still be coming; nothing is coming after the borrow pass,
    # so there the best of what is left should win. A control nobody
    # measured sits past the furthest band and so comes out negative,
    # which is the answer: it is not known to be good.
    'closeness': lambda x: x.furthest - x.tier,
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


def _facts(rules, ctrl, need, role, part, named=None, axis=None):
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
        # A row says which thing it reads. What the map measured about a
        # LEVER is on the axis, not on the control carrying it: three of
        # the stick's axes are one control and they rest differently.
        where = axis if fact.get('on') == 'axis' else ctrl
        if where is None:
            continue
        told = getattr(where, fact['reads'], None)
        if told is None:
            continue
        want = getattr(need, fact['asked'])
        if not want:
            continue
        if 'same' in fact:
            # The fourth shape: a closed field the need names a value of.
            # `rest` is the map's own word for where an axis sits when you
            # let go, and the need says which it has to be -- pitch has to
            # spring back, a throttle has to stay.
            hit = told == want
            delta = fact['same'] if hit else fact['other']
            words = fact['says'] if hit else fact['not']
            if named is not None and delta:
                named.append((fact['reads'], delta, words))
            s += part(delta, words)
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
    # Buttons, for a need that takes buttons. An axis need takes one axis
    # and the candidate IS an axis, so there is nothing to count here: a
    # lever has no buttons at all and would be refused for every one.
    'too_few': lambda x: (x.axis is None
                          and len(x.ctrl.bindable_buttons) < x.need.wanted),
    # A mini-hat wired to an axis reports its extremes and nothing in
    # between, so it is a two-way switch pretending to be an axis:
    # binding pitch to it gives full nose-up, full nose-down and no
    # flying. Measured, like every other gate: `None` is an unswept axis.
    'stepped': lambda x: x.axis is not None and x.axis.stepped is True,
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
    """What a gate or a term reads besides the control and the need."""

    __slots__ = ('ctrl', 'need', 'role', 'tier', 'measured', 'floor',
                 'ceiling', 'lowest', 'usable', 'axis', 'furthest',
                 'borrowed', 'opening')

    def __init__(self, ctrl, need, role, tier, floor, ceiling, lowest,
                 usable, axis=None, furthest=0, borrowed=False,
                 opening=False):
        self.ctrl, self.need, self.role, self.axis = ctrl, need, role, axis
        self.tier, self.floor = tier, floor
        self.measured = ctrl.tier is not None
        self.ceiling, self.lowest, self.usable = ceiling, lowest, usable
        #: the furthest tier any band will take, which is what the borrow
        #: pass measures closeness against
        self.furthest = furthest
        #: which pass is asking, and -- for the one that lends a button --
        #: whether this control has anything on it yet
        self.borrowed, self.opening = borrowed, opening


#: The two ways a control can be had, which is what a row of the table may
#: narrow itself to. Four of the five passes hand over a whole control and
#: score it the same way; the fifth lends one button of a control
#: something else owns, and scores that its own way.
PLACED, BORROWED = 'placed', 'borrowed'


def in_pass(row, borrowed):
    """Does this row of the table apply to the pass now running?

    `pass` is `placed`, `borrowed`, or absent for both. Borrowing is
    scored on its own terms and always was -- it is the last pass, so
    nothing better is coming and the polarity of reach flips, and the
    control already belongs to something else, so its shape is not the
    question. All of that used to be eleven lines of arithmetic in
    `allocate` with its own hand-rebuilt copy of the words. It is the
    same table now, with a column saying which pass each row is for.
    """
    want = row.get('pass')
    return want is None or want == (BORROWED if borrowed else PLACED)


def score(ctrl, need, role, floor=True, usable=None, parts=None,
          rules=None, named=None, axis=None, borrowed=False,
          opening=False):
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

    `borrowed` says the last pass is asking -- it lends a need one spare
    button of a control something else owns -- and the table's `pass`
    column says which rows that pass uses. `opening` is whether this
    control has anything on it yet, which only that pass can answer and
    only it charges for. The whole of it used to be arithmetic in
    `allocate`, written twice: once to compare and once, by hand, to
    explain.
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
               rules['band'][need.urgency]['takes'][0], usable, axis,
               furthest=max(table.values()), borrowed=borrowed,
               opening=opening)

    # The order is here rather than in the file because it is load-bearing
    # and has a story. A pin outranks the reach tables, not just the
    # ordering, so it is taken BETWEEN the gates that are about the control
    # and the one that is about the pass: `prefer` used to be a bonus
    # applied after the ceiling, so a pinned control the ceiling excluded
    # scored nothing and the bonus never ran -- BMS's pinky shift scored
    # 721 with a loose ceiling and nothing with a tight one, and moved
    # silently to a control you cannot hold as a modifier.
    gates = {g['when']: g for g in rules['gate']}
    for name in ('unusable', 'wrong_shape', 'too_few', 'stepped'):
        if in_pass(gates[name], borrowed) and REFUSE[name](run):
            return None
    # With the shape gates rather than the pass gate, and so BEFORE the pin,
    # which stops. A pin is an opinion about which control is right and this
    # is a fact about which cannot do the job at all: pinning a shift to
    # something you cannot hold down while working the layer it reaches is
    # exactly the failure the `pinned` term's own note describes.
    if _fact_refuses(rules, ctrl, need):
        return None
    for term in rules['term']:
        if (term.get('stops') and for_this(term, need)
                and in_pass(term, borrowed) and WHEN[term['when']](run)):
            said = _says(term, ctrl, need, role, 1)
            mark(term['name'], term['weight'], said)
            return part(term['weight'], said)
    # Not for an axis. The reach limits are about competing for the homes
    # near your hand -- a band's ceiling keeps a cold-start switch off the
    # thumb, its floor keeps it off a thumb position something urgent may
    # still need. Nothing competes for levers: there is one pitch axis and
    # it is where it is, so a ceiling would refuse the only candidate.
    if axis is None and REFUSE['out_of_reach'](run):
        return None

    s = 0
    for term in rules['term']:
        if (term.get('stops') or not for_this(term, need)
                or not in_pass(term, borrowed)):
            continue
        if not WHEN[term['when']](run):
            continue
        n = PER[term['per']](run) if 'per' in term else 1
        said = _says(term, ctrl, need, role, n)
        mark(term['name'], term['weight'] * n, said)
        s += part(term['weight'] * n, said)
    return s + _facts(rules, ctrl, need, role, part, named=named,
                      axis=axis)


def for_this(term, need):
    """Does this term apply to a need that takes what this one takes?

    Three terms are about buttons and nothing else, and they leaked into
    an axis: `reach` paid a lever +12 for being far from the hand, which
    is a competition no lever is in, and `spare` paid +4 for a control
    with MINUS one spare button, because a lever has none and the need
    wanted one. Said in the file rather than in the condition, so a term
    nobody has thought about applies to both and says so by being silent.
    """
    want = term.get('takes')
    return want is None or want == need.takes


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
        yours     a hand, on the review screen

    There was a sixth, `claimed`: a planner putting a placement here
    itself, past the allocator. DCS did it for a trigger two commands
    both wanted, because naming one BUTTON of a control was something no
    need could ask for. It can: `prefer` and `on` together.

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
    'relaxed': 'it reached past the floor',
    'borrowed': 'it borrowed a spare button',
    'yours': 'you assigned it',
    # Not scored and not compared: the need named the input and the map
    # had exactly one of it.
    'named': 'it asked for this one by name',
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


def why_bits(p):
    """[str] -- the account of one placement, in the order a reader reads it.

    Five planners and one proposer had each grown their own copy of this --
    about 199 lines between them, roughly forty apiece -- and every one
    reads the same fields: which band, whether the floor held, what was
    pinned, what a human wrote down. One paragraph written six times.

    What stays a game's own is what only it knows: BMS's DX number, X4's
    slot. Those are appended by the game rather than reassembled here,
    which is the whole difference between a shared skeleton and a sixth
    copy.

    Degrades rather than raises when there is no `Reason`: the band is a
    fact about the need rather than about the run that placed it, so
    there is something to say either way. DCS used to build a
    `Placement` itself and this is what let that read.
    """
    n, r = p.need, p.why
    out = [URGENCY_NAME[n.urgency]]
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

#: And the third thing you can decide, which is that this is to stay
#: empty. It carries no control, which is the whole point: the file could
#: say where a row sits and that you agreed, and had no way at all to say
#: "I took this off". So `x` cleared the screen, `s` answered that nothing
#: had changed -- truthfully, about the file -- and the next open proposed
#: the row straight back.
CLEARED = 'cleared'


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


def put(need, role, ctrl, why, button=None, points: int | None = 0,
        pinned=(), axis=None):
    """The placement: which button takes which binding, and everyone told.

    Two callers had a copy -- the allocator's passes and the review
    screen's assign -- and they had already drifted: one told the click
    what it was for and the other did not. A third copy was about to be
    written for the pass that honours what you chose, which is the point
    at which a copy becomes a definition.

    `button` is the one actually pressed, when a press is what decided.

    `pinned` is one button per SLOT, `None` where nothing was said -- what
    you get from pressing for one direction of a hat rather than for the
    hat. `slots_for` answers in the control's own order, which is right
    until somebody has pressed: a trim hat whose directions the module
    names in another order came out scrambled, and the only way back was
    to re-take the whole control and get the same order again. DCS
    captures a direction at a time and had its own file to keep them in;
    this is that, where every game can reach it.
    """
    if need.takes == AXIS:
        # `axis` is the resolved index: a lever is not chosen, it is
        # named, and whoever named it looked at the device. One slot,
        # because an axis need binds one thing -- `OnAxis` so that the
        # index can never be mistaken for a button number.
        slots = []
        if need.bindings and axis is not None:
            slots = [(OnAxis(axis), need.bindings[0])]
        hand_out(slots, role, why)
        return Placement(need, role, ctrl, slots, points, why)
    buttons = slots_for(need, ctrl)
    if button is not None and honours_press(need, ctrl, button):
        buttons = [button]
    if pinned:
        buttons = [want if want is not None and want in ctrl.bindable_buttons
                   else got for want, got in
                   zip(list(pinned) + [None] * len(buttons), buttons)]
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
        #: a `Reason`. Defaulted rather than required: a missing one
        #: should read as "nobody said" rather than crash a screen. DCS
        #: used to build a Placement itself, for a trigger two commands
        #: both wanted, and that is what it left out.
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
            return Layout(devs, *allocate(NEEDS, devs))
    """

    def __init__(self, devices, placed, unplaced, free):
        #: {role: Device}, from devmap.by_role
        self.devices = devices
        #: [Placement], most urgent first -- buttons and axes alike. One
        #: list: an axis placement is a placement. There used to be two,
        #: and the second was the reason everything downstream had two
        #: code paths.
        self.placed = list(placed)
        #: The two views a FORMAT needs, where it spells the two kinds of
        #: input differently -- DCS has `axisDiffs` and `keyDiffs`, X4 has
        #: `INPUT_SOURCE_JOYAXES` and `INPUT_SOURCE_JOYBUTTONS`. That is a
        #: fact about the file being written, so the split belongs to the
        #: writer; what the split IS belongs here, once.
        self.on_axes = [p for p in self.placed if p.need.takes == AXIS]
        self.on_buttons = [p for p in self.placed
                           if p.need.takes != AXIS]
        #: [Need] that found no home
        self.unplaced = list(unplaced)
        #: [(role, control)] with every button still spare
        self.free = list(free)

    def __iter__(self) -> typing.Iterator[typing.Any]:
        """(devices, placed, unplaced, free), so a caller may still
        unpack it into four names.

        `Any` because an iterator has one element type and these four are
        not one type; a checker otherwise joins them and then objects to
        whichever name is used for what it actually is.
        """
        return iter((self.devices, self.placed, self.unplaced, self.free))

    def __repr__(self):
        return (f'<Layout {len(self.placed)} placed '
                f'({len(self.on_axes)} on axes), {len(self.unplaced)} '
                f'unplaced, {len(self.free)} free>')

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
        return Layout(self.devices, placed, self.unplaced, self.free)

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
#: a fourth step was added under it. That count is gone -- it was how many
#: of the game's own HOTAS profiles bound the thing, which is a fact about
#: other people's hardware -- and the name now breaks every tie a band
#: leaves.
ORDERED_BY = (
    ('what you put there yourself', 'The control leaves the pool.'),
    ('a control you pinned by name', 'It is offered the pin and nothing '
                                     'else.'),
    ('how soon you reach for it', 'The bands above decide.'),
    ('its name', 'The line order of the file decides nothing.'),
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
             overlay=None, finds=None):
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
    # Before that: the ones that are NAMED rather than chosen. An
    # aircraft's pitch axis is the stick's pitch axis on every desk there
    # is, so there is nothing to compare and nothing to score -- the need
    # says `device stick, shape stick, on ('y',)` and the map has exactly
    # one of those. This is the whole of what used to be a second model
    # of the program: its own object, its own resolver, its own file
    # section, its own rows and its own branch of every key.
    #
    # It takes no control out of play. Two functions on one axis is the
    # normal case, not a conflict -- X4 steers with the stick's y and
    # walks with it, Elite flies and drives with the same lever, War
    # Thunder has an aeroplane and a helicopter on every one of them --
    # and a control's axes do not stop its buttons being free.
    # What you took off, which no pass may hand back. `x` on the review
    # screen writes `how: cleared` and nothing else, so this is the one
    # decision of yours that names no control -- and it has to be read
    # before any pass, because every one of them would otherwise fill the
    # gap it made. The row comes out unplaced, which is what it is.
    empty = {i for i, n in enumerate(needs)
             if (n.assignment or {}).get('how') == CLEARED}
    named, nowhere = [], []
    for i, need in enumerate(needs):
        if need.takes == AXIS and i not in empty:
            named.append(i)
    #: (role, coupling group, context) -> the need sitting there. An axis
    #: is exclusive, and the thing it is exclusive WITHIN is a context:
    #: X4 steers with the stick's y axis and walks with it, Elite flies
    #: and drives with the same lever, War Thunder has an aeroplane and a
    #: helicopter on every one. You are never doing both at once, so
    #: sharing there is the point rather than a clash.
    #:
    #: The group, not the axis, because two axes that travel together are
    #: ONE input: the VMAX's throttle levers move as a pair until you
    #: release the catch, so a function on the second one moves with
    #: whatever is on the first. Counting them separately put MSFS's prop
    #: pitch on the twin of its own throttle.
    held = {}
    # Best fit first, so the need a lever suits most gets it and the next
    # one takes what is left: zoom wants a dial that rests at zero and
    # the antenna only wants one that stays put, so zoom has the better
    # claim on the one dial that rests at zero. Ties keep the file's
    # order, which is the only thing here that is not a measurement.
    #
    # Worked out before anything is placed, and the RESULT is put back
    # into the file's order below: the order a pass happens to visit
    # things in has no business reaching the layout, and letting it
    # rewrote every game's profile with the same bindings shuffled.
    def fits_best(i):
        got = axes_for(needs[i], devices, usable=usable, rules=rules)
        return -(got[0][0] or 0) if got else 1
    first = len(placed)
    for i in sorted(named, key=fits_best):
        need = needs[i]
        # A game may NAME the control, and then the points pick the axis
        # within it. It is asked first and may answer None: which command
        # is pitch is the module's own vocabulary, which the core cannot
        # read -- but which LEVER pitch goes on is a comparison, and that
        # is not the game's business.
        said = finds(need, devices) if need.find and finds else None
        ran = axes_for(need, devices, usable=usable, rules=rules)
        if said is not None:
            _role, ctrl, axis = said
            if axis is not None:
                ran = [(None, _role, ctrl, axis)]
            else:
                ran = [x for x in ran if x[2] is ctrl]
        if not ran:
            nowhere.append(i)
            # Quiet when the GAME answered. A search that comes back
            # empty is the game's own decision, and it says so in its own
            # words. Where the ask was the core's own and the desk answers
            # none of it, nobody else is going to say so.
            if not need.find:
                print(f'!! nothing on this desk answers {need.what!r}. '
                      'It asks for '
                      f'{need.prefer or need.first_shape}'
                      + (f' {need.on[0]}' if need.on else '') + '.',
                      file=sys.stderr)
            continue
        where = context_of(need)
        free = [x for x in ran
                if (x[1], group_of(devices[x[1]], x[3]), where) not in held]
        # Nothing free in this context: share rather than go homeless.
        # War Thunder brakes both wheels off one lever because the desk
        # has one brake lever, and splitting them across two would be a
        # worse answer than the one it has.
        points, role, ctrl, axis = (free or ran)[0]
        held[(role, group_of(devices[role], axis), where)] = need
        terms = []
        if points is not None:
            score(ctrl, need, role, parts=terms, usable=usable, rules=rules,
                  axis=axis)
        placed.append(put(need, role, ctrl,
                          Reason('named' if points is None else 'floored',
                                 points=points, parts=terms,
                                 tier=reach_tier(ctrl)),
                          axis=axis.index, points=points))
        sat[id(need)] = ctrl
    mine = {id(n): i for i, n in enumerate(needs)}
    placed[first:] = sorted(placed[first:], key=lambda p: mine[id(p.need)])
    named = set(named)

    #: pool index -> the buttons of it that needs naming both a control
    #: and a button have taken. A control is only `taken` once every
    #: button of it is spoken for, which is what lets two of them share
    #: one: a four-way hat carrying four separate commands is how DCS's
    #: own vocabulary names a hat, and a trigger's two stages are two
    #: commands on one control by construction.
    spoken = {}
    chose, orphan = set(), []
    for i, need in enumerate(needs):
        if i in named or i in empty:
            continue
        # Two claims, one shape: a control named AND which of its buttons.
        # Yours is an assignment; a game's is `prefer` with `on`, which is
        # the only way to ask for ONE BUTTON of a control -- the scored
        # passes hand over whole controls, so two needs could never share
        # a trigger there. DCS built the placement by hand for exactly
        # that, with a Reason of its own and 200 points chosen to look
        # like a score.
        yours = (need.assignment or {}).get('how') == CHOSE
        said = bool(need.prefer) and bool(need.on)
        if not (yours or said):
            continue
        j = (assigned_at(pool, need.assignment) if yours else
             next((k for k, (_r, c) in enumerate(pool)
                   if c.label == need.prefer), None))
        if said and (j is None or not satisfies_on(need, pool[j][1])):
            # Not an error here: the pin is read again by the scored
            # passes, which say so in their own words and offer the need
            # nothing else. The directions have to be THERE as well as the
            # control -- without that `slots_for` falls back to press
            # order, and a need that asked for the second stage of a
            # trigger would take the first and say nothing.
            continue
        if j is None:
            # Say it and leave the need empty. Quietly allocating it
            # somewhere else is the one thing this must not do: the whole
            # reason it is written down is that it does not move.
            print(f'!! you put {need.what!r} on '
                  f'{need.assignment.get("control")!r}. This desk does not '
                  'have that control. The row stays empty: nothing moves '
                  'what you put down.',
                  file=sys.stderr)
            chose.add(i)
            orphan.append(i)
            continue
        role, ctrl = pool[j]
        mine = need.assignment or {}
        here = put(need, role, ctrl,
                   Reason('yours' if yours else 'pinned'),
                   button=mine.get('button') if yours else None,
                   pinned=(mine.get('buttons') or ()) if yours else (),
                   axis=mine.get('axis') if yours else None)
        clash = {b for b, _v in here.slots} & spoken.get(j, set())
        if clash and said:
            # Somebody else's already. Nothing is said and nothing is
            # left empty: this is the game's opinion about where the
            # thing goes, not yours, so it goes back in the queue and
            # takes what the points give it.
            continue
        if clash:
            # The BUTTONS, not the control. Two things you put by hand on
            # one hat -- a four-way carrying four separate commands, which
            # is how DCS's vocabulary names them -- are not a conflict;
            # two things on one button are. This refused the whole control
            # to the second comer, so a hat you had filled a direction at a
            # time came back with one direction on it and three orphans.
            print(f'!! {need.what!r} and something else are both on '
                  f'{need.assignment.get("control")!r} button '
                  f'{sorted(clash)[0]}. The first one keeps it.',
                  file=sys.stderr)
            chose.add(i)
            orphan.append(i)
            continue
        spoken.setdefault(j, set()).update(b for b, _v in here.slots)
        if set(ctrl.bindable_buttons) <= spoken[j]:
            taken.add(j)        # nothing spare on it any more
        placed.append(here)
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
    #: ordering, or it is not a choice.
    # `what` last, and it is load-bearing. Without it this is not a total
    # order, `sorted` is stable, and every tie falls back to the order the
    # needs happen to sit in the file -- so the layout was a function of
    # the file's line order. Moving two lines about moved bindings, and
    # the review screen moved them itself: it saves the list back in
    # PLACEMENT order, so every save reshuffled the ties, and the next
    # open placed them differently. X4 came back with four rows purple
    # after a save that changed nothing but the order they were written
    # in. Nothing in a layout should turn on that.
    order = sorted((i for i in range(len(needs))
                    if i not in chose and i not in named
                    and i not in empty),
                   key=lambda i: (needs[i].prefer is None, needs[i].urgency,
                                  needs[i].what))

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
                print(f'!! {need.what!r} is pinned to {need.prefer!r}. '
                      'That control is not free. The relaxed try gets '
                      'this row.',
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
            # The same scorer as every other pass, told which pass it is.
            # `scoring.toml` says what that changes -- the shape gate comes
            # off, the reward for distance turns around -- and before this
            # the answer was computed here instead: four numbers in source,
            # with the reach floor and the ceiling checked by hand beside
            # them, and the facts called for a sum nobody could see the
            # parts of. The parts had to be rebuilt by hand for the screen
            # and the two copies had to agree.
            s = score(c, need, role, usable=usable, rules=rules,
                      borrowed=True, opening=j not in taken)
            if s is None:
                continue
            if best is None or s > best[0]:
                best = (s, role, c, button, j)
        if best is None:
            still.append(i)
            continue
        _s, role, ctrl, button, j = best
        occupied.add((role, button))
        need.relaxed = True
        terms = []
        score(ctrl, need, role, usable=usable, rules=rules, parts=terms,
              borrowed=True, opening=j not in taken)
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
    still += orphan + nowhere + sorted(empty)

    # Free means every INPUT of it is free, not merely that no need chose
    # it -- and an axis is an input. The main stick has no buttons at all,
    # so all zero of them were spare and it was offered as a free control
    # with pitch, roll and rudder on it. Same for both throttle levers and
    # both mini-sticks: five controls on this desk, every one of them a
    # flight control, offered to a cold-start switch.
    on_axes = {(p.role, b) for p in placed for b, _v in p.slots
               if isinstance(b, OnAxis)}
    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken
            and not any((r, b) in occupied for b in c.bindable_buttons)
            and not any((r, OnAxis(a.index)) in on_axes
                        for a in axes_of(devices[r], c))]
    return placed, [needs[i] for i in still], free

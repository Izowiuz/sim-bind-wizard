"""Match things a pilot must be able to do against controls that suit them.

A `Need` says WHAT and WHAT SHAPE. What a slot MEANS is the game's
business. `bindings` is an opaque payload that the core only indexes, so
one entry can be a War Thunder action id, a Falcon BMS callback or a pair
of X4 source and code strings, and the allocator does not know the
difference.

One copy of this per game drifts. A copy without the reach floor lets a
command you touch once a flight outbid the afterburner for a thumb button,
and the fix there is to keep reordering a list by hand.
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


#: Which key identifies an entry in each list of the file. A merge by
#: POSITION means that a band inserted in the core file repoints every
#: override at the wrong one.
#:
#: `term` is keyed by a name of its own and not by `when`. Three terms are
#: conditioned on `always`, so the condition does not tell them apart and
#: an override would hit whichever came last.
KEYED_BY = {'band': 'name', 'pass': 'name', 'term': 'name', 'gate': 'when'}


def merge_rules(base, extra):
    """`base` with `extra` laid over it. Neither one is changed.

    A game says only what it differs on. DCS replaces a band's limits,
    because it has room to spare where the others saturate.

    An entry that names something the base does not have is refused. Added
    instead, a typo becomes a fifth band nothing places into, or a weight
    applied to a condition nobody wrote.
    """
    # The file's sections come in two shapes: a list of entries keyed by
    # name, and a plain table. A checker asked to join the two objects at
    # whichever branch uses one as itself.
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
#: a view of it. The tables the allocator works from have one definition,
#: and the screen that explains them reads the same one.
#:
#: Read at import, because the file ships with the code. It is source. It
#: is not a cache and not a judgement about a game, so a clone with
#: nothing installed is missing nothing here.
RULES = _read_rules(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'scoring.toml'))

#: What a control nobody has measured is worth: worse than every measured
#: control. The map hands over a tier or None. None is not a middling
#: control. It is a control nothing is known about.
UNMEASURED = RULES['reach']['unmeasured']

#: What each tier means, in the words a reader has.
REACH_MEANS = {tier: says for tier, says in RULES['reach']['means']}

#: WHEN you touch a thing. That decides how good a home it deserves. 0 is
#: what you reach for with something on your tail. 3 is what you reach for
#: on the ramp with the canopy open.
IN_A_TURN, ON_APPROACH, IN_THE_AIR, ON_THE_RAMP = 0, 1, 2, 3
URGENCY_NAME = tuple(b['name'] for b in RULES['band'])

#: Where an axis sits when you let go of it, in the map's own words. A
#: need names the position its function needs. Pitch has to spring back,
#: or the aircraft will not fly level. A throttle has to stay, or it
#: returns to half power. A brake has to rest at the minimum, or it is
#: part on from the moment the game starts.
#:
#: `check_rules` holds this to `devicemap.RESTS`. The day the map renames
#: one of these words, the load fails. The match does not quietly stop
#: firing.
RESTS = ('centred', 'min', 'max', 'mid')

#: The two kinds of input a control offers. These are not two kinds of
#: NEED. A function that wants an axis is a function like any other,
#: wanting a part of a control.
#:
#: Modelled separately, an axis grows its own object, its own resolver,
#: its own file section, its own rows on the screen and in the sheet, and
#: its own branch of every key.
BUTTON, AXIS = 'button', 'axis'

#: The best reach a band may take, and the worst it may live with.
#: Without the floor, something you do once on the ramp takes a thumb
#: position the moment one is free. Without the ceiling, nothing is kept
#: close.
MIN_REACH = {n: b['takes'][0] for n, b in enumerate(RULES['band'])}
MAX_REACH = {n: b['takes'][1] for n, b in enumerate(RULES['band'])}

#: The passes, in the order `allocate` runs them. Read from the file,
#: because the screen that explains the allocator reads them from
#: somewhere.
#:
#: `CAME_BY` is not that somewhere. It holds what is worth SAYING about a
#: placement, so it leaves the ordinary pass out and takes in two things
#: that are not passes. Used as this list it shows three of four.
#:
#: A literal written out here is worse still. It shadows this line, the
#: file's table becomes decoration, and the screen reads source. One name
#: with two definitions, and the second one wins in silence.
PASSES = tuple((p['name'], p['does']) for p in RULES['pass'])

#: What makes one control beat another, and why one is refused outright.
TERMS = RULES['term']
GATES = RULES['gate']

#: What the map measured about a control, and what turns it on in a need.
#: A fact names no predicate, unlike a term. Every row has one of three
#: fixed shapes, so `_facts` builds the test out of the row. The table's
#: own header in scoring.toml says what each key means.
FACTS = tuple(RULES['fact'])

#: The flags the facts put on every Need. Taken from the table rather
#: than written out, so a sixth fact is a block in a file and nothing
#: else. A need that sets none of them scores as it did before.
FLAGS = tuple(f['asked'] for f in FACTS
              if f.get('asked') and 'same' not in f)

#: What a fact of the fourth shape asks for: a WORD out of a closed
#: vocabulary, and not a flag. `rests` names the resting position the
#: function needs, against what the map measured about the lever. So this
#: field holds one of `RESTS`, or None. A `FLAGS` field holds True or
#: False.
VALUES = tuple(f['asked'] for f in FACTS if 'same' in f)

#: What an overlay may ask for, and so what the needs file does NOT
#: carry. These are not facts about a function. `stick` is not a property
#: of firing a gun, and neither is `this one carries the shift`. Written
#: per need, they are one opinion recorded 86 times, which is an opinion
#: nobody can change.
#:
#: Defined here and not in `core.overlay`, because `Need` is here and this
#: says which of its attributes are wishes. The overlay reads it.
WISHES = ('device', 'prefer', 'shift', 'modifier', 'finger', 'level')

#: The wishes that describe a PLACE on the hand rather than a decision of
#: their own. A control is judged against these by counting.
#:
#: `device` is not here. It has its own measured pair of terms, +40 and
#: -50, tuned against five games. Folded into a generic count it reweighs
#: every layout for nothing.
#:
#: `prefer` is a pin, `shift` is a layer and `modifier` is a fact flag.
#: None of the three is a place.
#:
#: These two make an overlay a cockpit template rather than a device
#: preference. `finger = "thumb"`, `level = "HOME"` is the castle switch,
#: said in words that survive leaving the Hornet's grip.
PLACED_BY = ('finger', 'level')

#: The flags that ARE about the function, which is what gets written down.
TOLD = tuple(f for f in FLAGS if f not in WISHES)

#: What `how` says where the allocator decided rather than you. Read back
#: as nothing. See `dump_assignments`.
SOLVED = 'solver'

#: What a function is for, as a closed list. This is the one word a
#: game's needs file and an overlay both say, and that is what lets one
#: overlay lay out six games. The table's own header in scoring.toml says
#: more.
JOBS = tuple(RULES['jobs'])

#: What stands in for what, where the exact shape is not on the hardware.
#: The order matters. The first entry is the shape asked for, and it
#: scores a bonus. The rest are substitutes.
FITS = {shape: tuple(subs) for shape, subs in RULES['shapes'].items()}

#: Controls whose buttons are one physical mechanism rather than
#: independent positions. Each may lend its click and nothing else.
ONE_MECHANISM = tuple(RULES['mechanisms']['one'])

#: A hat is captured with whichever words fitted the control at the time.
#: So a need that asks for "forward" accepts "up" from a hat that calls it
#: that.
SAME_WAY = {want: tuple(names)
            for want, names in RULES['directions'].items()}


def check_rules(rules, devicemap):
    """Every control word the rules use is one the map can produce.

    Three tables here name shapes and directions. An unchecked shape
    nobody has, from a typo or from a kind the map has renamed, never
    matches. A need that asks for it goes unplaced with no word about
    why. `FITS` said `switch2` long after the map stopped spelling
    anything that way, and the only sign was a need at the bottom of the
    unplaced list.

    Not at import. This module loads on a clone with no map at all.
    `devmap.load()` calls this, which is the first moment both exist.
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
    # A fact names a field on the control rather than a predicate in
    # this module. That is the point of the table, and it leaves this
    # check as the only thing between a typo and a fact that never
    # fires.
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
                       ' turns it on. A fact is what a NEED asks of a'
                       ' control. It is not a charge on every control.')
        if 'below' in fact and 'scale' not in fact:
            bad.append(f'fact: {fact["reads"]} charges below'
                       f' {fact["below"]} but has no `scale` to charge')
        kinds = [k for k in ('yes', 'scale', 'same', 'refuses') if k in fact]
        if len(kinds) != 1:
            bad.append(f'fact: {fact["reads"]} is {" and ".join(kinds)}'
                       ' at once. It has to be exactly one of yes/no,'
                       ' scale, same/other, refuses.' if kinds else
                       f'fact: {fact["reads"]} weighs nothing.')
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
    """How far this control is from flying, as the map measured it.

    `None` means nobody has walked the fingers on that desk. It is not a
    tier. It sorts below every measured tier, so a control somebody
    checked beats one nobody has checked.
    """
    return UNMEASURED if ctrl.tier is None else ctrl.tier


def reach_finger(ctrl):
    """The finger that gets there, or '' where nobody recorded one.

    Read off the spot. Not split out of `reach_said`: that string is
    `finger, how far` only WHERE there is a finger, and the how-far half
    carries a comma of its own. Split, it gives `your hand where it
    lives` as the name of a finger.
    """
    spots = [a for a in ctrl.access if a.tier == ctrl.tier]
    return spots[0].finger if spots else ''


def reach_level(ctrl):
    """Where the hand is when it reaches this, or '' where nobody
    measured.

    The level of the nearest spot, the way `reach_finger` takes its
    finger. A control is as close as its best way in. The other spots are
    other ways to the same place.
    """
    spots = [a for a in ctrl.access if a.tier == ctrl.tier]
    return spots[0].level if spots else ''


#: How to ask a control what an overlay's place words are asking about.
PLACE = {'finger': reach_finger, 'level': reach_level}


def place_wishes(ctrl, need):
    """(kept, broken) -- this control against the overlay's place words.

    Neither one, where nobody has measured. A control with no spots has no
    finger and no level. Counted as broken, it is charged for a desk
    nobody has walked rather than for being the wrong place.
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
    """How it is reached, in words, or '' where nobody has measured it.

    Built from the nearest spot rather than read off the control. Where a
    thing sits is a fact about the desk, and the same stick on a chair
    rail is reached differently.
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

    `bindings` runs in the order of the control's own directions or
    stages. A four-way hat takes four and a two-stage trigger takes one
    per detent. An entry may be None, which leaves that direction alone.
    """

    def __init__(self, what, shape, bindings=(), push=None,
                 urgency=IN_THE_AIR, suits=None, device=None,
                 prefer=None, on=None, category=None,
                 assignment=None, takes=BUTTON, invert=False, find=None,
                 rests=None, finger=None):
        self.what = what
        self.shape = shape
        self.bindings = list(bindings)
        #: BUTTON or AXIS: which of a control's two kinds of input this
        #: takes. A control can offer both. The throttle's mini-stick is
        #: two axes and a click, so the need says which kind it wants.
        #:
        #: `shape`, `device` and `on` name the rest the same way for
        #: either kind. `shape stick, device stick, on ('y',)` is the
        #: stick's pitch axis. `shape hat4, on ('up','down')` is two
        #: directions of a hat.
        self.takes = takes
        #: Which way round an axis runs. This is an attribute of an axis
        #: binding, the way `on` is an attribute of a hat binding. It is
        #: the one thing about an axis you change from the screen.
        self.invert = invert
        #: What the GAME asked for, by field, as against what an overlay
        #: wished. `device` and `prefer` are a wish where an overlay sets
        #: them and the game's ASK where the game does. `device throttle,
        #: prefer left throttle lever` is the game saying which lever the
        #: throttle is.
        #:
        #: Kept as the VALUES. Taking an overlay off has to put the ask
        #: BACK, not merely leave it alone. Told apart by `takes` instead,
        #: an overlay rule that matches an axis need overwrites the ask
        #: and survives `--overlay none`. `f-18.toml` puts the Hornet's
        #: pitch on the throttle that way, and the next save writes that
        #: into the needs file as the game's own ask.
        #:
        #: None until somebody says, which is not an empty dict.
        #: `forget_wishes` fills it on first sight, for a game with no
        #: needs file to read it out of. A game that derives its needs
        #: from the module on every run has no file to hold them, so a
        #: name like `from_file` here is a bug: every `--overlay` run
        #: wipes that game's own cockpit.
        self.ask: dict[str, str] | None = None
        #: A search only the game can answer. Carried here and not read.
        #: War Thunder's brake is "a slider or lever on the stick you can
        #: read absolutely", and no vocabulary of kinds and labels says
        #: that. `allocate(finds=...)` is asked where this is set. It is
        #: the one place a game still answers for itself, and it holds
        #: two rows of nineteen in one of the six games.
        self.find = find
        #: For a control that also clicks.
        self.push = push
        self.urgency = urgency
        self.suits = suits
        #: Which device this belongs on, by the map's `kind`, such as
        #: 'stick'. Not written in the needs file, and not a judgement
        #: about the function: `stick` is not a property of firing a gun.
        #: An overlay sets it, so one line says it for a whole family.
        self.device = device
        #: Pin to a control, by its label in the map. The allocator
        #: scores by shape, reach and urgency, and that is right for
        #: everything nobody has an opinion about. Where you DO have one,
        #: it wins. It is not argued with at every regeneration.
        self.prefer = prefer
        #: Where on the hand this belongs, in the map's own words.
        #: `finger = "thumb"`, `level = "HOME"` is the Hornet's castle
        #: switch, said so that it survives leaving the Hornet's grip.
        #:
        #: Written here rather than left to `setattr`, unlike the fact
        #: flags. A fact flag exists because scoring.toml says so, and a
        #: sixth fact must not need an edit here. These two are named in
        #: `WISHES` in this file, so this is where they are declared.
        #:
        #: `finger` is a constructor parameter and `level` is not. The
        #: difference is who knows. A template wishes either one. A game
        #: whose own table knows the cockpit ASKS for the finger, one row
        #: per concept. `ask` tells the two apart, as it does for
        #: `device`.
        self.finger = finger
        self.level = None
        #: The directions this control physically moves in, where that
        #: matters. A speedbrake switch is fore and aft whatever hat it
        #: lands on. On "up" and "right", because those came first, it is
        #: a lie about the hardware.
        self.on = tuple(on) if on else None
        #: Yours. What you filed this under. Separate from `urgency` on
        #: purpose: "Combat" holds something you reach for in a turn and
        #: something you set on the ramp, and the allocator still has to
        #: know which is which. Absent, and the screen groups by the
        #: band.
        self.category = category
        #: How this got where it is, where you decided: {role, control,
        #: how}, plus `button` where a press picked one. `control` is the
        #: map's own id and not the label, because the map promises that
        #: an id survives renaming a control and renumbering its buttons.
        #:
        #: `how` is the strength. There are two, because pressing RETURN
        #: and pressing `c` are not the same claim:
        #:
        #:   chose     you put it here. The allocator is not asked. The
        #:             control is taken before anything is scored.
        #:   accepted  you looked at where the allocator put it and said
        #:             yes. It scores as it did before, so if the desk or
        #:             the needs change and it lands somewhere else, the
        #:             row goes back to `?` and tells you.
        #:
        #: `accepted` is weak on purpose. `c` over a full list is one
        #: keystroke. Frozen, every row it touched would silence the
        #: allocator, and the way back would be clearing each row by
        #: hand.
        #:
        #: `prefer` is neither of the two. It is a third thing: an opinion
        #: written into the file by hand. It outranks the ordering, and
        #: the scoring still has to agree with it. A gate can refuse a
        #: pin, which is how a pinky shift leaves the button it is pinned
        #: to.
        #:
        #: Unwritten, all of this lasts until `q`.
        self.assignment = assignment
        #: What this need ASKS OF a control, against what the map
        #: measured about one. `held` meets `hold_ok`, and `costly` meets
        #: `accident_risk`.
        #:
        #: Not written out. The fact table in scoring.toml decides that
        #: these exist, so a sixth fact grows a sixth flag here with
        #: nothing to edit.
        #:
        #: Three of the map's five questions answer "can you". A score
        #: needs "must you", and these say that.
        for flag in FLAGS:
            setattr(self, flag, False)
        # A fact that matches a word, not a bool. The field exists on
        # every need the moment somebody writes the block, like the flags
        # above.
        for named in VALUES:
            setattr(self, named, None)
        self.rests = rests
        #: Set by the allocator where it had to reach past the floor.
        self.relaxed = False
        #: {field} the program proposed, rather than you deciding.
        #:
        #: A third thing beside `ask` and an overlay's wish. `ask` is what
        #: the GAME said. A wish is what you want of the layout. This is
        #: what nobody has confirmed.
        #:
        #: The screen draws these with `MARK[PROPOSED]`, which is the mark
        #: a placement nobody has accepted already wears.
        #:
        #: `core/guess.py` skips a field that is NOT in here. A field's
        #: absence from this set means you decided it.
        #:
        #: Without this set, a description derived from command names on
        #: every run cannot be told from one you wrote, and it cannot be
        #: corrected: the table overwrites the file next time.
        self.guessed = set()

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
        # An explicit tuple is taken as written, widened by the first
        # entry.
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
    namespaces. The throttle's mini-stick is button 23 and axes 0 and 1,
    so a slot index has to say which namespace it means.

    A plain integer cannot say it. `(throttle, 2)` is then a lever and a
    hat direction at once, and `occupied` has the two collide in silence.

    Frozen, so it is a dict key like the integers beside it.
    """
    index: int

    def __str__(self):
        return f'axis {self.index}'



def answers_need(dev, axis, need):
    """Would this axis answer what this need asked for?

    The ask is a GATE. The points choose among what passes it. On a
    throttle with three levers, "a lever that rests at zero" is answered
    by all three, and only the scoring says which.

    A search the game answers is not asked here. The core does not know
    what that search was looking for.
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


def group_of(dev, axis):
    """Which input this axis IS, as a key: itself and whatever travels
    with it.

    Two axes that move together are one input. The VMAX's throttle levers
    travel as a pair until you release the catch, so a function on the
    second lever moves with whatever is on the first.

    `moves_with` is the map's answer, AS THE HARDWARE IS SET UP NOW.
    """
    return frozenset({axis.index} | set(axis.moves_with or ()))


def context_of(need):
    """Which context this binding answers in, or '' where a game has one.

    The game says it, on the binding. MSFS writes `plane`, `heli` or
    `glob`, because it chooses a file by that word.

    This is what tells a shared axis from a clash. You never fly the
    aeroplane and the helicopter at the same time.
    """
    for slot in need.bindings:
        for b in slot:
            got = getattr(b, 'mode', None)
            if got:
                return got
    return ''


def axes_for(need, devices, usable=None, rules=None):
    """[(points, role, control, axis)] -- every lever that could take
    this need, best first. What the allocator compares, for an axis.

    The ask is a GATE and the measurement decides among what passes it.
    `device` says which stick. `shape` says which kind of control. `on`
    says which axis of it. `prefer` names one outright.

    Where the ask leaves one candidate the points change nothing. `on
    ('y',)` is the stick's pitch, and there is one of those.

    Where the ask leaves three levers the points choose. Without them the
    answer is whichever lever the device reported first, and a game then
    writes its own comparison around that as a chain of `if`: "a dial
    first, else a slider that rests at its minimum", "a slider or lever
    you can read absolutely", "steadiest first: something that stays
    where you leave it". All three are over what the map measures, and
    the scoring table is where that belongs.
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
    # Lowest index first among equals, so the same desk answers the same
    # way every time. A tie settled by report order is a layout that
    # moves when the firmware renumbers something.
    out.sort(key=lambda x: (-x[0], x[3].index))
    return out


def desk_of(layout):
    """Which desk a layout is for, or '' where nothing says.

    Read off the devices, because the answer is already there. A device
    remembers the profile it was laid out under, in `Device.under`, and a
    profile has a name. Nothing is added to the map for this, and nothing
    is threaded through a planner.
    """
    for dev in layout.devices.values():
        got = getattr(dev, 'profile', None)
        if got is not None:
            return got.name
    return ''


def from_action(action, category='', make=None):
    """A need for one of the game's actions, from the catalogue alone.

    This is what `a` on the review screen makes. The catalogue says the
    name, the identifier, and whether the action is an axis. That is all
    of it: an axis asks for any lever, a button asks for any button, and
    `J` says what the function IS.

    `make` is a game's own subclass, the way `read_needs` takes one. A
    core `Need` on the list of a game that carries more fails inside the
    planner.
    """
    axis = action.kind == 'axis'
    return (make or Need)(
        action.name, 'axis' if axis else 'button',
        bindings=[[cactions.Bind(action.id)]],
        takes=AXIS if axis else BUTTON, category=category or '')


def described(need):
    """Has anybody said what this function IS?

    The job, and nothing else. Every other field of a description either
    has a default, such as the band and the flags, or is legitimately
    empty. `suits` is the one field that is either said or not said.

    All 209 rows of the five hand-written needs files name one. A row
    with none is a row the screen added, or a row a seed could not
    describe.

    One definition for the two places that show it: the dot on the list,
    and the line under the plan.
    """
    return bool(need.suits)


def asked(need):
    """What the GAME asked for, by field.

    `need.ask` where somebody has written it down. Otherwise what the
    need is wearing, because nothing has wished anything yet.

    `apply` takes the wishes off before it sets any, and taking them off
    is what writes this down. So a need whose `ask` is None has never met
    an overlay, and it carries what the game put there.

    That is the whole answer for a game with no needs file to read it out
    of. DCS builds its needs from the module's own command table on every
    run, and no file holds them.
    """
    if need.ask is not None:
        return need.ask
    return {w: getattr(need, w, None) for w in WISHES
            if getattr(need, w, None)}


def forget_wishes(needs):
    """Take every overlay wish off these needs. Returns how many it
    found.

    An overlay REPLACES. It does not add. Without this, a second overlay
    laid over the first leaves every need it says nothing about wearing
    the first file's finger, and `place_right` counts a wish nobody
    asked for. `--overlay none` after an overlay has the same hole.

    This walks `WISHES` rather than a list of its own, so a seventh wish
    is cleared by being in that tuple.

    What the game asked for comes BACK. It does not go with the wishes.
    `device throttle, prefer left throttle lever` is the game saying
    which lever the throttle is, and a need cleared of it asks for
    nothing.

    `need.ask` holds those values, and `asked` answers for either kind of
    need. So a need whose game has no file to say it in keeps what the
    game put there. Wiping that is how `--overlay f-18` puts the Hornet's
    pitch, roll and rudder on the throttle, where no axis answers them.
    """
    found = 0
    for need in needs:
        if need.ask is None:
            need.ask = asked(need)
        for wish in WISHES:
            was = need.ask.get(wish)
            got = getattr(need, wish, None)
            # Truthy AND not what the file said. A flag nobody set is
            # False while the file says nothing, which is None. Counted
            # as a wish found, that makes `forget_wishes` answer 4 where
            # the answer is 2.
            if got and got != was:
                found += 1
            setattr(need, wish,
                    was if was is not None
                    else (None if wish not in FLAGS else False))
    return found


def dump_needs(needs):
    """[Need] -> [dict], what each function IS and how you use it.

    Only what a person decided ABOUT THE FUNCTION.

    The per-context split a game's constructor takes, such as `air` and
    `heli` or `plane` and `glob`, is absent. It zips into the slots and
    reads back off the binds, so writing it here records one fact twice.

    `WISHES` are absent, because they are not about the function. `stick`
    is not a property of firing a gun. An overlay says those once per
    family.

    `relaxed` is absent for a third reason. A run SETS it, rather than
    somebody deciding it before one. A list that remembered the last
    outcome would start every run from where the previous run stopped.

    `assignment` is absent too. That is the answer, and it lives in the
    binds file.
    """
    out = []
    for n in needs:
        # The judgements first and the game's own identifiers last, so a
        # record reads as what you decided with the machine's half under
        # it. `read_needs` reads by key, so this order is for you.
        row = {'what': n.what, 'shape': n.shape}
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
        # What the FILE asked for, which is not what the need is
        # wearing. An overlay sets `device` and `prefer` too, and saving
        # those writes a wish into the file as the game's own ask.
        said = asked(n)
        for field in ('device', 'prefer', 'find', 'finger'):
            if said.get(field):
                row[field] = said[field]
        # What nobody has confirmed, so the next run tells its own
        # proposals from your decisions. Sorted, because a set has no
        # order and a file you hand-edit must not reshuffle.
        if n.guessed:
            row['guessed'] = sorted(n.guessed)
        row['bindings'] = [cactions.dump_binds(slot) for slot in n.bindings]
        out.append(row)
    return out


def save_needs(directory, filename, needs):
    """Write the description down.

    A description is derived from nothing. Delete it and it is gone. So a
    screen that lets somebody make one has to be able to keep it.
    Unwritten, a promoted action lasts until `q`.

    One section. A second section for the axes, with rows of their own
    shape, makes every reader of this file need two code paths. An axis
    row is a need row that takes an axis.
    """
    from core import vocab
    # A line per judgement, with the identifiers and the directions on
    # that line. Those are the game's own words and nobody edits them.
    path, _said = vocab.save(directory, filename, inline=2,
                             needs=dump_needs(needs))
    return path


def read_needs(rows, make=None):
    """[dict] -> [Need]. `make` is a game's own subclass, where it has
    one.

    A shape written as a choice comes back as a tuple rather than the
    list JSON gives. `first_shape` is the shape asked for and the rest
    are substitutes. A list and a tuple read the same to everything
    except the test for whether a shape is a single name.

    What comes back wants nothing and sits nowhere. An overlay puts the
    wishes on. `read_assignments` puts back where things sit.
    """
    out = []
    for r in rows:
        shape = r['shape']
        if not isinstance(shape, str):
            shape = tuple(shape)
        push = cactions.read_binds(r['push']) if r.get('push') else None
        if r.get('rests') and r['rests'] not in RESTS:
            # Loudly, like a job nobody wrote. A resting word the map
            # does not use is a match that cannot fire, and the only sign
            # of it is an axis on the wrong lever.
            raise ValueError(
                f'{r["what"]!r} wants an axis that rests {r["rests"]!r}. '
                f'The map does not use that word. It uses these: '
                f'{", ".join(RESTS)}.')
        if r.get('suits') and r['suits'] not in JOBS:
            # Loudly, the way the overlay reader refuses a rule nobody
            # wrote. A job nothing knows is a word no overlay matches, so
            # a typo costs that need every wish in the file.
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
            # An overlay sets these too, so which of the two this one is
            # gets written down. `forget_wishes` tells them apart, and
            # `takes` is not the difference.
            device=r.get('device'), prefer=r.get('prefer'),
            finger=r.get('finger'))
        need.ask = {f: r[f] for f in ('device', 'prefer', 'find', 'finger')
                    if r.get(f)}
        need.guessed = set(r.get('guessed', ()))
        for flag in TOLD:
            setattr(need, flag, r.get(flag, False))
        out.append(need)
    return out


def dump_assignments(needs):
    """[Need] -> [dict], what sits where. The answer, not the question.

    Every need that is placed, and not only the ones you touched. The
    file answers "what is on my desk right now". A file holding only the
    hand-picked rows cannot answer that.

    `how` says who decided, and that is the whole weight of the file.
    `chose` and `accepted` are yours, and they come back as yours.

    `SOLVED` is the allocator's own. It is written so a screen shows what
    moved since last time, and it reads back as nothing. It pins no
    control, so the next run scores from scratch rather than from
    wherever the last run stopped.
    """
    out = []
    for n in needs:
        if not n.assignment:
            continue
        row = {'what': n.what}
        # `axis` where a button row says `button`. This says which part
        # of the control it landed on, in that control's own namespace.
        for field in ('role', 'control', 'button', 'buttons', 'axis', 'how'):
            if n.assignment.get(field) is not None:
                row[field] = n.assignment[field]
        # Which way round you left it. The needs file holds the game's
        # own default, and this one wins. This is your decision about
        # your wrist. That one is what the game shipped.
        if n.takes == AXIS and n.invert:
            row['invert'] = True
        out.append(row)
    return out





def _answers_file(directory, filename):
    """What the answers file holds, or None where nothing is written yet.

    A missing file is not a fault. A game somebody planned and never
    saved has no answers on disk, and the allocator is about to produce
    them.

    So this does not go through `vocab.load`. A missing file there is an
    error that tells you to run the harvest, because a cache is built
    from the installed game. This file is not.
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


def filed_overlay(directory, filename):
    """Which template this game was last laid out to, or ''.

    A second section of the answers file, beside the placements. Which
    template you want is a judgement like the rest of that file: `o` on
    the review screen is where you make it, and a judgement nothing
    writes down lasts until `q`.

    Unwritten, the layout comes back to the planner's declaration on the
    next open. Measured on the Hornet: `o f-18` took the list from 33
    accepted rows to 45, and the next open put it back to 33, because 12
    of those rows sit somewhere else under `by-hand` and `_came_by` is
    right to send them back to `?`.
    """
    got = _answers_file(directory, filename)
    return (got or {}).get('overlay') or ''


def save_assignments(directory, filename, needs, overlay=None):
    """Write down what sits where, and which template it was laid out to.

    `overlay` is the file's own stem, as `--overlay` and the menu spell
    it, or None for a run that asked for no template. Both are written:
    "no template" is a decision, and absent it reads as a game nobody
    has laid out.
    """
    from core import vocab
    path, _said = vocab.save(directory, filename,
                             binds=dump_assignments(needs),
                             overlay=overlay or '')
    return path


def read_assignments(rows, needs):
    """Put the assignments back on these needs, by name. Returns how
    many.

    A row the allocator wrote is read and dropped. See
    `dump_assignments`.

    A row that names a function the game no longer has is dropped with a
    word. Dropped in silence, it leaves a file that grows graves.

    Paired by name AND by order within a name, because a name is not
    unique. MSFS asks for `KEY_BRAKES` twice, once for the aeroplane and
    once for the helicopter. Keyed on the name alone, the second one
    takes the first one's answer.
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
    """Does this control move in named directions rather than sit in
    positions?

    A hat answers 'up' and 'left'. A selector answers '1' to '5'. An
    encoder answers 'ccw' and 'cw'. Only the first kind honours a need's
    `on`.
    """
    return any(ctrl.direction(b) in SAME_WAY
               for b in ctrl.bindable_buttons)


def on_buttons(need, ctrl):
    """[button] for a need that names its directions, or None where this
    control lacks one of the directions it named.

    `need.on` may name some directions and leave others None. A DCS hat
    family often has two members whose direction the module's prose makes
    legible and two it does not.

    The named ones are found first, so a nameless one cannot take the
    button a named one wanted. The gaps are then filled from what is left,
    in press order.
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

    `need.on` is a claim about the hardware. A speedbrake switch is fore
    and aft whatever hat it lands on.

    `slots_for` falls back to press order where the claim cannot be
    honoured, and it does that in silence. So a four-way need lands on a
    five-position selector, whose positions are '1' to '5' and are not
    directions, and a panel-focus need lands on a switch that HOLDS its
    position.
    """
    return not need.on or on_buttons(need, ctrl) is not None


def slots_for(need, ctrl):
    """[button index] this need's bindings land on, in binding order.

    The first N in press order, normally. Where the need names the
    directions it moves in, find those.

    A control whose only button is its click offers that click as an
    ordinary button. The VMAX side dials are like that. A need with
    something of its own to put on the click takes it instead.

    An axis need has no buttons to pick from. Which axis of the control
    it goes on is resolved against the device, and this function cannot
    see the device, so `put` is told the answer and never asks.
    """
    if need.takes == AXIS:
        return []
    order = list(ctrl.buttons)
    if ctrl.push is not None and need.push is None:
        order.append(ctrl.push)

    # One binding on a control with several buttons belongs on its CLICK
    # and not on the first direction. A lone action on `buttons[0]` reads
    # as "push the hat left" where the gesture is to press the hat, and
    # it leaves the click idle. The click is the one position a single
    # action wants.
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
#: this table writes them. A condition is a predicate over a control and
#: a need, and a file that defined one would need an expression language.
#: That is a worse thing to own than the file.
#:
#: `tests/test_scoring.py` holds every one of these to the file, both
#: ways. A name with no predicate is a weight nobody applies. A predicate
#: no name reaches is a rule left behind in the code.
#:
#: Every one takes the `_Run` and nothing else, which is the signature
#: `REFUSE` has. What a term may read and what a gate may read are the
#: same list, and one argument list wants one spelling.
#:
#: `run.axis` is the candidate lever where the need takes one, and None
#: where it takes buttons. A condition about a lever cannot be written
#: against the control: three of the stick's axes belong to one control
#: and one of them is pitch.
WHEN = {
    'always': lambda x: True,
    # The reach term rewards the FURTHEST control that still does the
    # job, because that leaves the near ones for something more urgent.
    # An unmeasured control must not collect that. Nobody knows it is
    # far, and paid for distance nobody measured it beats a thumb button
    # somebody measured.
    'measured': lambda x: x.measured,
    'pinned': lambda x: bool(x.need.prefer) and x.need.prefer == x.ctrl.label,
    # Where you last accepted it. You learn a layout with your hands, so
    # staying put is worth points for its own sake. Without this term,
    # anything better that comes free takes the control: moving ONE
    # binding by hand re-let 21 of X4's 32, because every other decision
    # was made afresh against a board that had shifted.
    'stayed': lambda x: (bool(x.need.assignment)
                         and x.need.assignment.get('role') == x.role
                         and x.need.assignment.get('control') == x.ctrl.id),
    # Per axis. The map answers this about the lever and not about the
    # control carrying it, so there is nothing to ask of a button need.
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
    # open. Only the share pass can tell. Every other pass takes whole
    # controls, so for them the answer is always yes.
    'untouched': lambda x: x.opening,
}

#: What a weight is multiplied by, where it is multiplied at all.
PER = {
    'tier': lambda x: x.tier,
    'spare': lambda x: len(x.ctrl.bindable_buttons) - x.need.wanted,
    'place kept': lambda x: place_wishes(x.ctrl, x.need)[0],
    'place broken': lambda x: place_wishes(x.ctrl, x.need)[1],
    # The reach term's polarity, upside down. An ordinary pass rewards
    # the furthest control that still does the job, because something
    # more urgent may be coming. Nothing comes after the share pass, so
    # there the best of what is left wins.
    #
    # A control nobody measured sits past the furthest band, so it comes
    # out negative. That is the answer: it is not known to be good.
    'closeness': lambda x: x.furthest - x.tier,
}

def _adder(parts):
    """The two steps, in one place: score everything, describe the
    winner.

    Scoring runs over every control against every need, and it wants a
    number. The winner is scored a second time, with somewhere to put the
    terms. The explanation is then the same arithmetic as the decision,
    and not a second telling of it.

    A term worth nothing is left out. Listed as zero, `0 findable by
    feel` reads as a fact about the control, and it is the absence of
    one.
    """
    def part(delta, text):
        if parts is not None and delta:
            parts.append((delta, text))
        return delta
    return part


def _facts(rules, ctrl, need, role, part, named=None, axis=None):
    """What the map measured about this control, weighed against the
    need.

    Not in `WHEN`. None of these is a predicate somebody wrote: a row in
    the fact table names a FIELD on the control, and the three shapes a
    row can take are fixed here. So a sixth question the wizard asks
    costs a block in a file.

    Two rules live here rather than in each row, so no future fact can be
    written without them.

    First: a fact nobody answered counts for nothing. `None` is not a
    middling answer. It is an unwalked desk. The reach term keeps off an
    unmeasured control for the same reason, because paid for distance
    nobody measured an unmeasured button beats a measured thumb.

    Second: a fact counts only where the need asks for it. "Can you hold
    this down" is a fact about a control. Whether that matters is a fact
    about the action. Charged to every control, it pushes everything away
    from the same homes, and something still has to go there. A fact that
    counts for every need moves half the list at once: one that rode the
    band instead of asking reshuffled 99 bindings, 46 of them between
    controls that answered it the same way.
    """
    s = 0
    for fact in rules['fact']:
        if fact.get('refuses'):
            continue
        # A row says which thing it reads. What the map measured about a
        # LEVER is on the axis and not on the control carrying it. Three
        # of the stick's axes are one control, and they rest
        # differently.
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
            # The fourth shape: a closed field the need names a value
            # of. `rest` is the map's own word for where an axis sits when
            # you let go, and the need says which value it has to be.
            # Pitch has to spring back. A throttle has to stay.
            hit = told == want
            delta = fact['same'] if hit else fact['other']
            words = fact['says'] if hit else fact['not']
            if named is not None and delta:
                named.append((fact['reads'], delta, words))
            s += part(delta, words)
            continue
        if 'scale' in fact:
            # A 0/1/2 answer pays per step. `below` charges the
            # SHORTFALL instead: how far under the best answer this
            # control is.
            #
            # A fact almost everything answers well has to be charged
            # that way to say anything. This desk has 20 of 22 home
            # controls at the top of `blind_distinct`, so a bonus pays
            # them all the same +20 and disturbs the ties underneath. 99
            # bindings moved between equally findable controls for it.
            #
            # Either way the best answer costs nothing, and `part` drops
            # a term worth nothing. So nothing says `0 findable by
            # feel`.
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

    Only on a measured "no". On a map nobody has answered, a gate that
    refused out of ignorance would refuse every control for a need that
    asks to be a modifier. A need with nowhere to go reads as a broken
    planner, not as a desk nobody has walked. `out_of_reach` makes the
    same argument.
    """
    for fact in rules['fact']:
        if (fact.get('refuses') and getattr(need, fact['asked'])
                and getattr(ctrl, fact['reads']) is False):
            return fact
    return None


#: Why a control is refused outright. `x` is the run's own state, and
#: that is what tells these from `WHEN`. A gate reads the pass it is in.
REFUSE = {
    'unusable': lambda x: x.usable is not None and not x.usable(x.role,
                                                                x.ctrl),
    'wrong_shape': lambda x: x.ctrl.kind not in x.need.shapes,
    # Buttons, for a need that takes buttons. An axis need takes one
    # axis and the candidate IS an axis, so there is nothing to count
    # here. A lever has no buttons, and this gate would refuse every
    # one.
    'too_few': lambda x: (x.axis is None
                          and len(x.ctrl.bindable_buttons) < x.need.wanted),
    # A mini-hat wired to an axis reports its extremes and nothing in
    # between, so it is a two-way switch that looks like an axis. Pitch
    # bound to it gives full nose up, full nose down and no flying.
    # Measured, like every other gate: `None` is an unswept axis.
    'stepped': lambda x: x.axis is not None and x.axis.stepped is True,
    # Only where somebody has measured. This gate is about how far a
    # control is, and on a desk nobody has walked there is no answer to
    # refuse it with. A refusal there places nothing at all, which reads
    # as a broken planner rather than as an unmeasured desk. The control
    # still scores last, so anything measured beats it.
    'out_of_reach': lambda x: x.measured and (x.tier > x.ceiling
                                              or (x.floor
                                                  and x.tier < x.lowest)),
}


class _Run:
    """What a gate or a term reads besides the control and the need."""

    __slots__ = ('ctrl', 'need', 'role', 'tier', 'measured', 'floor',
                 'ceiling', 'lowest', 'usable', 'axis', 'furthest',
                 'shared', 'opening')

    def __init__(self, ctrl, need, role, tier, floor, ceiling, lowest,
                 usable, axis=None, furthest=0, shared=False,
                 opening=False):
        self.ctrl, self.need, self.role, self.axis = ctrl, need, role, axis
        self.tier, self.floor = tier, floor
        self.measured = ctrl.tier is not None
        self.ceiling, self.lowest, self.usable = ceiling, lowest, usable
        #: The furthest tier any band takes. The share pass measures
        #: closeness against this.
        self.furthest = furthest
        #: Which pass is asking. For the pass that lends a button, also
        #: whether this control has anything on it yet.
        self.shared, self.opening = shared, opening


#: The two ways a control can be had. A row of the table may narrow
#: itself to one of them. Four of the five passes hand over a whole
#: control and score it the same way. The fifth lends one button of a
#: control something else owns, and it scores that its own way.
PLACED, SHARED = 'placed', 'shared'


def in_pass(row, shared):
    """Does this row of the table apply to the pass now running?

    `pass` is `placed`, or `shared`, or absent for both.

    Borrowing is scored on its own terms. It is the last pass, so nothing
    better is coming and the polarity of reach flips. The control belongs
    to something else already, so its shape is not the question.

    One table with a column for the pass, rather than eleven lines of
    arithmetic in `allocate` and a hand-rebuilt copy of the words.
    """
    want = row.get('pass')
    return want is None or want == (SHARED if shared else PLACED)


def score(ctrl, need, role, floor=True, usable=None, parts=None,
          rules=None, named=None, axis=None, shared=False,
          opening=False):
    """How well a control plays this part. None means it cannot.

    The weights and their words come from `scoring.toml`. What each
    condition means comes from `WHEN` above. `rules` is a game's own set
    merged over the core's: DCS tightens one band, because it has room to
    spare where the others saturate.

    `parts` collects `(delta, what it was for)` for every term that
    fired, which is what a `Reason` carries. It is off by default,
    because the allocator scores every control against every need and
    wants one number to compare. The winner is scored a second time, with
    the terms. `score()` is pure, so the second call describes the first.

    A term worth nothing is left out. Listed as zero, `0 suits gunnery`
    reads as a fact about the control, and it is the absence of one.

    `shared` says the last pass is asking. That pass lends a need one
    spare button of a control something else owns, and the table's `pass`
    column says which rows it uses. `opening` says whether this control
    has anything on it yet. Only that pass can answer `opening`, and only
    that pass charges for it.
    """
    rules = rules or RULES
    part = _adder(parts)

    def mark(name, delta, text):
        """The same term, under its own name.

        `parts` carries the WORDS, and the words are the run's. `1 spare
        button` and `2 spare buttons` are one term wearing two of them,
        so anything that compares two controls by their words sees a term
        neither of them has.
        """
        if named is not None and delta:
            named.append((name, delta, text))
        return delta

    tier = reach_tier(ctrl)
    table = {n: b['takes'][1] for n, b in enumerate(rules['band'])}
    ceiling = table[need.urgency]
    # The ceiling yields in the relaxed pass, and only for a need the
    # share pass cannot serve.
    #
    # Borrowing hands a need one spare button on a control somebody else
    # took, so it serves a need that wants ONE button. For such a need a
    # shared thumb press beats a whole control you leave the grip to
    # reach. The ceiling lifted for them makes the thumb lose: two
    # `in a turn` needs left the thumb for the side dials, because a
    # whole dial became legal in the relaxed pass, and that pass runs
    # BEFORE sharing.
    #
    # A need that wants several buttons has no such fallback. Every
    # encoder and selector on this hardware needs leaving the grip, so
    # without the lift four of Falcon BMS's knobs have nowhere to go.
    if not floor and need.wanted > 1:
        ceiling = max(table.values())
    run = _Run(ctrl, need, role, tier, floor, ceiling,
               rules['band'][need.urgency]['takes'][0], usable, axis,
               furthest=max(table.values()), shared=shared,
               opening=opening)

    # The order is here rather than in the file, because it is
    # load-bearing. A pin outranks the reach tables and not only the
    # ordering, so the pin is taken BETWEEN the gates that are about the
    # control and the gate that is about the pass.
    #
    # Applied as a bonus after the ceiling instead, a pin never runs on a
    # control the ceiling excluded: that control scores nothing. A pinky
    # shift scored 721 with a loose ceiling and nothing with a tight one,
    # and moved in silence to a control you cannot hold as a modifier.
    gates = {g['when']: g for g in rules['gate']}
    for name in ('unusable', 'wrong_shape', 'too_few', 'stepped'):
        if in_pass(gates[name], shared) and REFUSE[name](run):
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
                and in_pass(term, shared) and WHEN[term['when']](run)):
            said = _says(term, ctrl, need, role, 1)
            mark(term['name'], term['weight'], said)
            return part(term['weight'], said)
    # Not for an axis. The reach limits are about competition for the
    # homes near your hand. A band's ceiling keeps a cold-start switch
    # off the thumb. Its floor keeps that switch off a thumb position
    # something urgent may still need.
    #
    # Nothing competes for a lever. There is one pitch axis and it is
    # where it is, so a ceiling here refuses the only candidate.
    if axis is None and REFUSE['out_of_reach'](run):
        return None

    s = 0
    for term in rules['term']:
        if (term.get('stops') or not for_this(term, need)
                or not in_pass(term, shared)):
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

    Three terms are about buttons and nothing else. Without this test
    they leak into an axis: `reach` pays a lever +12 for being far from
    the hand, which is a competition no lever is in, and `spare` pays +4
    for a control with MINUS one spare button, because a lever has none
    and the need wants one.

    Said in the file and not in the condition. A term nobody has thought
    about then applies to both kinds, and its silence says so.
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

    A score is a comparison. An explanation is not. A reader that wants
    the second out of the first reverse-engineers it, and a reader that
    asks `p.points == 200` holds a sentinel nobody dares change.

    So this is written at the moment of the decision, by the code making
    it. That is the only place that does not have to infer. Five things
    decide:

        pinned    you named the control and it was free
        floored   the ordinary pass, reach floor and ceiling both held
        relaxed   nothing legal was left, so the ceiling came off
        shared    a spare button on a control something else owns
        yours     a hand, on the review screen

    A planner that puts a placement here itself, past the allocator, is a
    sixth. Nothing does that now: naming one BUTTON of a control is
    `prefer` and `on` together.

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
        #: [(delta, what it was for)]. Most valuable first is NOT
        #: imposed. The order is the order `score()` applies them, which
        #: is the order the rules are written in and the one a reader can
        #: check.
        self.parts = list(parts)
        #: The reach tier of the control it got, and the worst tier this
        #: urgency was allowed in the pass that placed it. Without both,
        #: "reached past the floor" is a claim with nothing behind it.
        self.tier = tier
        self.ceiling = ceiling
        #: The Placement a hand displaced, where one did. The detail
        #: panel says this out loud. It is recorded at the moment of the
        #: move. Guessed later by comparing `at` with `plan`, it is right
        #: only until something else moves.
        self.instead = instead
        #: Why THIS button of that control. `slots_for` decides it by
        #: three rules. The rest of this record is about the control, and
        #: four binds on a hat share that. Without this field they carry
        #: four copies of one sentence, and that looks like an answer.

    @property
    def overridden(self):
        """Did a person put this here rather than the planner."""
        return self.how == 'yours'

    def __repr__(self):
        return f'<Reason {self.how} {self.points}>'


#: How a placement came about, as a reader wants it said. `floored` is
#: absent on purpose. It is the ordinary case, and a line that announces
#: the ordinary case is a line you learn to skip.
CAME_BY = {
    'relaxed': 'it reached past the floor',
    'shared': 'it shares a control with another function',
    'yours': 'you assigned it',
    # Not scored and not compared. The need named the input, and the map
    # holds one of it.
    'named': 'it asked for this one by name',
}


def ran_against(need, devices, rules=None, usable=None, floor=True):
    """[(points, role, ctrl)] -- every control that could have taken this
    need, best first. What the allocator compared, kept.

    Scored WITHOUT `stayed`. That term pays whichever control the need is
    already on, so a comparison that counts it answers "it is here
    because it is here": every alternative sits 20 below, and the screen
    reports that nothing else fitted. Being where you left it is a
    reason. It is not a reason one CONTROL beat another, so it is said
    separately.

    Recomputed rather than carried. The screen asks for one need at a
    time, and the allocator would have to carry this for all of them,
    through a Layout and through five adapters.

    `floor` has to be the one the placement was made under. The floored
    pass refuses a binding that reached past the floor, so asking with
    the floor on answers that the control it sits on was never a
    candidate.
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

    Both fit. Both are the right shape. Both are on the device it asked
    for. Those terms cancel. What is left is the whole of why one beat
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
    """[str] -- the account of one placement, in the order a reader reads
    it.

    One copy per game is about forty lines each, and every copy reads the
    same fields: which band, whether the floor held, what was pinned,
    what a person wrote down.

    What stays a game's own is what only it knows: Falcon BMS's DX
    number, X4's slot. The game appends those rather than reassembling
    this, and that is the difference between a shared skeleton and a
    sixth copy.

    This degrades where there is no `Reason`. It does not raise. The band
    is a fact about the need rather than about the run that placed it, so
    there is something to say either way.
    """
    n, r = p.need, p.why
    out = [URGENCY_NAME[n.urgency]]
    if reach_said(p.ctrl):
        # Printed every time, and not only for the reflex bands. The
        # floor acts on this, so a disputed placement turns on it.
        out.append(f'reach: {reach_said(p.ctrl)}')
    if r is None:
        return out
    if r.how == 'pinned' and n.prefer:
        out.append(f'pinned to {n.prefer!r}')
    elif r.how in CAME_BY:
        out.append(CAME_BY[r.how])
    # Biggest first. The term that decided it is the one to read first.
    # The order `score()` applies them in follows how the rules are
    # written, not what mattered.
    out += [f'{d:+} {t}'
            for d, t in sorted(r.parts, key=lambda q: -abs(q[0]))]
    return out


def hand_out(slots, role, why):
    """Tell every binding in `slots` where it went and why.

    A payload is whatever a game put there, and the allocator only
    indexes it. So this asks rather than assumes. Anything that knows how
    to be told is told, and anything else is carried as it was.

    Each binding gets its OWN `Reason`, and they say the same thing.
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
#: control before anything is scored. `ACCEPTED` changes no allocation,
#: and it tells the screen you have looked. See `Need.assignment`.
CHOSE, ACCEPTED = 'chose', 'accepted'

#: The third thing you can decide: that this row stays empty. It carries
#: no control, and that is the point. A file that says where a row sits
#: and that you agreed has no way to say "I took this off". Then `x`
#: clears the screen, `s` answers that nothing changed, and the next open
#: proposes the row straight back.
CLEARED = 'cleared'


def assigned_at(pool, want):
    """Where in the pool the control you chose is, or None where it is
    gone.

    Matched on the id and not the label. The map promises that an id
    outlives renaming a control and renumbering its buttons, and the
    label is what the capture wizard lets you retype.

    The role is checked too. One desk carries the same label on both
    devices.
    """
    for j, (role, ctrl) in enumerate(pool):
        if role == want.get('role') and ctrl.id == want.get('control'):
            return j
    return None


def honours_press(need, ctrl, button):
    """Whether the exact button pressed is what this need lands on.

    `slots_for` picks for a need with one binding. On a control that
    clicks it takes the click, and otherwise the first position. That is
    right where nobody said, and wrong the moment somebody presses a
    thing. Press the second detent of a trigger, get the first, and the
    tool has overruled a choice you just made by hand.

    Two exceptions. A need that wants several bindings is asking for the
    whole control, and its own direction order decides, not the corner
    you touched. And a need with `on` has made a claim about the
    hardware: a speedbrake is fore and aft whatever hat it lands on. That
    claim is the lie `on` exists to stop, so it keeps winning.
    """
    return (len(need.bindings) == 1 and not need.on
            and button in ctrl.bindable_buttons)


def put(need, role, ctrl, why, button=None, points: int | None = 0,
        pinned=(), axis=None):
    """The placement: which button takes which binding, and everyone
    told.

    One definition, for three callers: the allocator's passes, the review
    screen's assign, and the pass that honours what you chose. Two copies
    had already drifted, and one of them told the click what it was for.

    `button` is the button actually pressed, where a press decided.

    `pinned` is one button per SLOT, and `None` where nothing was said.
    That is what pressing for one direction of a hat gives, rather than
    pressing for the hat.

    `slots_for` answers in the control's own order, and that is right
    until somebody has pressed. A trim hat whose directions the module
    names in another order comes out scrambled, and the way back is to
    re-take the whole control and get the same order again.
    """
    if need.takes == AXIS:
        # `axis` is the resolved index. A lever is named and not chosen,
        # and whoever named it looked at the device. One slot, because an
        # axis need binds one thing. `OnAxis`, so the index cannot be
        # mistaken for a button number.
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
    # `if v` rather than `is not None`. A payload is a list of Binds, and
    # an empty list means this direction was left alone.
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
        #: [(button index, binding)], plus (push, need.push) where there
        #: is one.
        self.slots = slots
        self.points = points
        #: A `Reason`. Defaulted and not required. A missing one reads as
        #: "nobody said" rather than failing a screen. A game that builds
        #: a Placement itself is what leaves one out.
        self.why = why

    def __iter__(self):
        return iter(self.slots)

    def __repr__(self):
        return f'<Placement {self.need.what!r} -> {self.role}/{self.ctrl.label}>'


class Layout:
    """What a planner worked out: the one shape every adapter returns.

    `build()` is in the adapter contract. Its shape has to be here, or
    five adapters reach five orders of the same values, each defensible
    on its own, and no caller outside one file can rely on any of them.

    The core four are here. Anything a game derives for its own writer,
    such as Falcon BMS's DX numbers or War Thunder's resolved action ids,
    is a function of `placed` and belongs beside that writer. A table
    computed inside `build()` cannot be narrowed afterwards, and
    narrowing is what a reviewer does when it accepts some bindings and
    not others.

        def build():
            devs = devmap.by_role('stick', 'throttle')
            return Layout(devs, *allocate(NEEDS, devs))
    """

    def __init__(self, devices, placed, unplaced, free):
        #: {role: Device}, from `devmap.by_role`.
        self.devices = devices
        #: [Placement], most urgent first, buttons and axes alike. One
        #: list, because an axis placement is a placement. Two lists are
        #: why everything downstream grows two code paths.
        self.placed = list(placed)
        #: The two views a FORMAT needs, where it spells the two kinds of
        #: input differently. DCS has `axisDiffs` and `keyDiffs`. X4 has
        #: `INPUT_SOURCE_JOYAXES` and `INPUT_SOURCE_JOYBUTTONS`. That is
        #: a fact about the file being written, so the split belongs to
        #: the writer. What the split IS belongs here, once.
        self.on_axes = [p for p in self.placed if p.need.takes == AXIS]
        self.on_buttons = [p for p in self.placed
                           if p.need.takes != AXIS]
        #: [Need] that found no home.
        self.unplaced = list(unplaced)
        #: [(role, control)] with every button still spare.
        self.free = list(free)

    def __iter__(self) -> typing.Iterator[typing.Any]:
        """(devices, placed, unplaced, free), so a caller unpacks this
        into four names.

        `Any`, because an iterator has one element type and these four
        are not one type. A checker joins them and then objects to
        whichever name is used for what it is.
        """
        return iter((self.devices, self.placed, self.unplaced, self.free))

    def __repr__(self):
        return (f'<Layout {len(self.placed)} placed '
                f'({len(self.on_axes)} on axes), {len(self.unplaced)} '
                f'unplaced, {len(self.free)} free>')

    def unmeasured(self):
        """(controls with no measured reach, controls) on this desk.

        Worth saying wherever a layout is explained. With none of them
        measured, every control scores the same on reach. The layout is
        real and it is not reach-aware, and nothing else on the screen
        says so.
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
            # Asked here rather than held as a literal. The map can be
            # anywhere, and a command nobody can type is not an answer.
            from core import devmap
            return ('No control on this desk has a measured reach, so '
                    'nothing here knows what is near your hand. Run '
                    f'{devmap.capture_command()}, then press r.')
        return (f'{left} of {every} controls have no measured reach. They '
                'sort below every control that has one.')

    def but(self, placed):
        """The same layout with a different set of placements.

        This is what a reviewer hands a writer. Everything else about the
        plan is unchanged, and only the bindings that were accepted go
        in.
        """
        return Layout(self.devices, placed, self.unplaced, self.free)

    def by_device(self):
        """[(role, [Placement])] -- placements grouped for display, in
        the order a reader expects: the stick first, and inside it by
        urgency.
        """
        out = {}
        for p in self.placed:
            out.setdefault(p.role, []).append(p)
        for group in out.values():
            group.sort(key=lambda p: (p.need.urgency, p.ctrl.label))
        return sorted(out.items())


#: What decides which need is looked at first, in the order it decides.
#: Beside `allocate`'s sort key, because the screen that explains the
#: allocator had this as a paragraph and a paragraph does not move when
#: the key does. Written as a paragraph, it said a pin went first long
#: after what you chose by hand started outranking one. The name breaks
#: every tie a band leaves.
ORDERED_BY = (
    ('what you put there yourself', 'The control leaves the pool.'),
    ('a control you pinned by name', 'It is offered the pin and nothing '
                                     'else.'),
    ('how soon you reach for it', 'The bands above decide.'),
    ('its name', 'The line order of the file decides nothing.'),
)

#: The solver this run uses. `--solver` sets it once at startup.
#:
#: A module-level default, not an argument threaded through seven call
#: sites. It is one decision per run and not a property of any one
#: allocation. `allocate` still takes it explicitly, which is how a test
#: asks for one without touching anything else.
SOLVER = None

#: The overlay this run uses. `--overlay` sets it once at startup. The
#: same argument as `SOLVER` holds: one decision per run, not a property
#: of any one allocation, and `allocate` still takes it explicitly so a
#: test asks for one without touching anything else.
#:
#: Typed loosely. `core.overlay` imports THIS module, so naming `Overlay`
#: here is a cycle. A bare `= None` narrows to `Never` for every caller
#: past the `is None` guard.
OVERLAY: typing.Any = None


def allocate(needs, devices, usable=None, rules=None, solver=None,
             overlay=None, finds=None):
    """(placements, unplaced, free), most urgent first.

    Two scored passes. The first keeps the reach floor: something you do
    on the ramp may not take a control your thumb rests on, however many
    are spare at that moment. The second drops the floor for whatever is
    left, because an unbound engine start is worse than a canopy switch
    under the thumb. By then everything urgent has chosen.

    `usable(role, ctrl)` lets a game veto a control the hardware has and
    the game cannot address. Falcon BMS sees a device's first 32 buttons,
    so the VMAX's last nineteen are real to your hand and invisible to
    the sim.

    `rules` is a game's own scoring merged over the core's. That is how a
    band's limits get replaced for one game, because the same ceiling
    means different things depending on where the needs came from. A
    hand-written list saturates the good controls, so a tight ceiling
    displaces something more urgent. A list cut from the game's own
    vocabulary has room to spare, and there a tight ceiling on `in the
    air` steers sensor and radio switches onto shared finger positions
    instead of whole keyboard buttons.

    `overlay` is what YOU want of the layout, as against what the game
    wants: which device a family belongs on, which control carries the
    shift, which two things your hand works at once. Without one, nothing
    is asked for and every control is judged on reach and shape alone.
    """
    rules = rules or RULES
    overlay = overlay if overlay is not None else OVERLAY
    #: (need, need, what the rule accepts). The rule arrives as a
    #: callable and not as a name to look up later, so nothing below
    #: holds the overlay to ask it a question.
    pairs = overlay.bound(needs) if overlay is not None else []
    who = solver or SOLVER or csolvers.best()
    top = {n: b['takes'][1] for n, b in enumerate(rules['band'])}
    pool = [(role, c) for role, d in sorted(devices.items())
            for c in d.groups(bindable=True)]
    taken, placed = set(), []
    #: Which control each need ended up on, by identity, for the pair
    #: rules. Not read off `placed`. That holds `Placement` objects, and
    #: this question is asked once per candidate, in the hot loop.
    sat = {}

    # Before anything is scored: what YOU put there.
    #
    # This is not a strong opinion. `prefer` below is the strong opinion,
    # and that difference is the point. A pin outranks the ordering and
    # the ranking, and the scoring still has to agree with it: a gate can
    # refuse a pinned control, and a pinky shift pinned to a grip button
    # left it and turned up on the throttle that way.
    #
    # Nothing refuses this. You sat at the desk with the stick in your
    # hand and put the thing where you wanted it. There is no opinion
    # here to overrule.
    #
    # Unwritten, this lasts until `q`. Every mark and every hand-placed
    # binding is then rebuilt from the planner on the next open, and an
    # evening of walking the list comes back purple and in the planner's
    # order.
    # Before that: the needs that are NAMED rather than chosen. An
    # aircraft's pitch axis is the stick's pitch axis on every desk, so
    # there is nothing to compare and nothing to score. The need says
    # `device stick, shape stick, on ('y',)`, and the map holds one of
    # those.
    #
    # This pass takes no control out of play. Two functions on one axis
    # is the normal case and not a conflict: X4 steers with the stick's y
    # and walks with it, Elite flies and drives with the same lever, and
    # War Thunder has an aeroplane and a helicopter on every one. A
    # control's axes do not stop its buttons being free.
    # What you took off, which no pass may hand back. `x` on the review
    # screen writes `how: cleared` and nothing else, so this is the one
    # decision of yours that names no control.
    #
    # Read before any pass. Every pass would otherwise fill the gap it
    # made. The row comes out unplaced, which is what it is.
    empty = {i for i, n in enumerate(needs)
             if (n.assignment or {}).get('how') == CLEARED}
    named, nowhere = [], []
    for i, need in enumerate(needs):
        if need.takes == AXIS and i not in empty:
            named.append(i)
    #: (role, coupling group, context) -> the need sitting there. An axis
    #: is exclusive, and what it is exclusive WITHIN is a context. X4
    #: steers with the stick's y axis and walks with it. Elite flies and
    #: drives with the same lever. War Thunder has an aeroplane and a
    #: helicopter on every one. You never do both at once, so sharing
    #: there is the point and not a clash.
    #:
    #: The group, not the axis. Two axes that travel together are ONE
    #: input: the VMAX's throttle levers move as a pair until you release
    #: the catch, so a function on the second one moves with whatever is
    #: on the first. Counted separately, they put MSFS's prop pitch on
    #: the twin of its own throttle.
    held = {}
    # Best fit first, so the need a lever suits most takes it and the
    # next one takes what is left. Zoom wants a dial that rests at zero
    # and the antenna wants one that stays put, so zoom has the better
    # claim on the one dial that rests at zero. A tie keeps the file's
    # order, which is the only thing here that is not a measurement.
    #
    # Worked out before anything is placed, and the RESULT goes back into
    # the file's order below. The order a pass visits things in has no
    # business reaching the layout: it rewrites every game's profile with
    # the same bindings shuffled.
    def fits_best(i):
        got = axes_for(needs[i], devices, usable=usable, rules=rules)
        return -(got[0][0] or 0) if got else 1
    first = len(placed)
    for i in sorted(named, key=fits_best):
        need = needs[i]
        # A game may NAME the control, and the points then pick the axis
        # within it. The game is asked first and may answer None. Which
        # command is pitch is the module's own vocabulary, and the core
        # cannot read that. Which LEVER pitch goes on is a comparison,
        # and that is not the game's business.
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
            # Quiet where the GAME answered. A search that comes back
            # empty is the game's own decision, and the game says so in
            # its own words. Where the ask was the core's and the desk
            # answers none of it, nothing else says so.
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
        # Nothing free in this context. Share rather than go homeless.
        # War Thunder brakes both wheels off one lever, because the desk
        # has one brake lever. Split across two, they are a worse
        # answer.
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

    #: pool index -> the buttons of it taken by needs that name both a
    #: control and a button. A control is `taken` once every button of it
    #: is spoken for, and that is what lets two needs share one. A
    #: four-way hat carrying four separate commands is how DCS's own
    #: vocabulary names a hat, and a trigger's two stages are two
    #: commands on one control.
    spoken = {}
    chose, orphan = set(), []
    for i, need in enumerate(needs):
        if i in named or i in empty:
            continue
        # Two claims in one shape: a control named AND which of its
        # buttons. Yours is an assignment. A game's is `prefer` with
        # `on`, and that pair is the only way to ask for ONE BUTTON of a
        # control. The scored passes hand over whole controls, so two
        # needs cannot share a trigger there.
        yours = (need.assignment or {}).get('how') == CHOSE
        said = bool(need.prefer) and bool(need.on)
        if not (yours or said):
            continue
        j = (assigned_at(pool, need.assignment) if yours else
             next((k for k, (_r, c) in enumerate(pool)
                   if c.label == need.prefer), None))
        if said and (j is None or not satisfies_on(need, pool[j][1])):
            # Not an error here. The scored passes read the pin again,
            # say so in their own words, and offer the need nothing else.
            #
            # The directions have to be THERE as well as the control.
            # Without that, `slots_for` falls back to press order, and a
            # need that asked for the second stage of a trigger takes the
            # first and says nothing.
            continue
        if j is None:
            # Say it and leave the need empty. Allocating it somewhere
            # else in silence is the one thing this must not do. The
            # reason the choice is written down is that it does not
            # move.
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
            # left empty. This is the game's opinion about where the
            # thing goes and not yours, so the need goes back in the
            # queue and takes what the points give it.
            continue
        if clash:
            # The BUTTONS, not the control. Two things you put by hand on
            # one hat are not a conflict: a four-way carrying four
            # separate commands is how DCS's vocabulary names them. Two
            # things on one button are a conflict.
            #
            # The whole control refused to the second comer gives a hat
            # you filled a direction at a time one direction and three
            # orphans.
            print(f'!! {need.what!r} and something else are both on '
                  f'{need.assignment.get("control")!r} button '
                  f'{sorted(clash)[0]}. The first one keeps it.',
                  file=sys.stderr)
            chose.add(i)
            orphan.append(i)
            continue
        spoken.setdefault(j, set()).update(b for b, _v in here.slots)
        if set(ctrl.bindable_buttons) <= spoken[j]:
            taken.add(j)        # Nothing spare on it now.
        placed.append(here)
        sat[id(need)] = ctrl
        chose.add(i)

    #: A pinned need goes first, before urgency is consulted at all. A
    #: `prefer` that only tips the scales is no use once something more
    #: urgent has taken the control: a pinky shift pinned to the grip
    #: pinky button still loses it to the landing lights, because those
    #: are touched on approach and it is not. An explicit choice has to
    #: outrank the ordering, or it is not a choice.
    #:
    #: This is belt and braces now. `offers` gives a pinned need its pin
    #: and nothing else, and the term stops the scoring. Taking this line
    #: out moves no binding in any of the five games. It stays, because
    #: the other two keys are about SCORING and this one is about the
    #: queue.
    # `what` last, and it is load-bearing. Without it this is not a total
    # order, `sorted` is stable, and every tie falls back to the order the
    # needs sit in the file. The layout is then a function of the file's
    # line order.
    #
    # Moving two lines moves bindings, and the review screen moves them
    # itself: it saves the list back in PLACEMENT order, so every save
    # reshuffles the ties and the next open places them differently. X4
    # came back with four rows purple after a save that changed nothing
    # but the order they were written in.
    order = sorted((i for i in range(len(needs))
                    if i not in chose and i not in named
                    and i not in empty),
                   key=lambda i: (needs[i].prefer is None, needs[i].urgency,
                                  needs[i].what))

    def offers(i, floor):
        """{pool index: points} -- where this need may go, and what each
        place is worth.

        A pinned need is offered its pin and nothing else, so the choice
        is a choice. It is not a nudge the ranking can undo.
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

        Asked against what is already down. That is why this is not a
        gate: `score` sees one control and one need, and a pair rule is a
        claim about two placements.

        A partner nothing has placed yet says nothing. Whichever of the
        two is placed second keeps the rule, and both orders give the same
        answer.
        """
        for one, other, keeps in pairs:
            mine = other if one is need else one if other is need else None
            if mine is None or not sat.get(id(mine)):
                continue
            if not keeps(ctrl, sat[id(mine)]):
                return False
        return True

    #: need -> its index, for the pair rules, which hold Needs.
    which = {id(n): i for i, n in enumerate(needs)}

    def broken(got, wants):
        """The one placement to forbid, or None where the batch keeps
        every pair rule.

        `allowed` above cannot see this. It filters a candidate against
        what is already DOWN, and a batch is solved as one model: both
        halves of a pair are decided at once, and neither is down.

        So the batch is checked afterwards and solved again without the
        offending option. The cheaper half of the pair is the one to
        forbid, because the half that wanted its control less is the half
        to move.
        """
        points = dict(wants)
        for one, other, keeps in pairs:
            a, b = which.get(id(one)), which.get(id(other))
            if a not in got or b not in got:
                continue
            if keeps(pool[got[a]][1], pool[got[b]][1]):
                continue
            # Lower points first, then the later control, so the same
            # inputs forbid the same option every time.
            return min(((a, got[a]), (b, got[b])),
                       key=lambda p: (points[p[0]].get(p[1], 0), -p[1]))
        return None

    def chosen(todo, floor):
        """{need index: pool index} for as many as can be placed.

        One model, rather than one choice per need in turn. Greedy cannot
        undo a choice, so an early urgent need takes the control a later
        need wanted more, and no pass gives it back.
        """
        wants = [(i, offers(i, floor)) for i in todo]
        banned = set()
        got = {}
        # One option forbidden per round, so the pool bounds the walk.
        # Every round either answers or takes a control out of play.
        for _ in range(len(pool) + 1):
            trimmed = [(i, {j: s for j, s in room.items()
                            if (i, j) not in banned})
                       for i, room in wants]
            said = who.best(trimmed, range(len(pool)))
            if said is None:
                # It could not answer. The model ran out of time with
                # nothing feasible. Walking the list is worse than the
                # best answer and much better than none.
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
                # It is pinned and the pin is not free. Say so. Put
                # somewhere else in silence, it looks like success.
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
            # Score the winner a second time, collecting the terms.
            # `score()` is pure, so this describes the call that won. It
            # is not a second opinion. The hot loop above stays a
            # comparison between numbers, and it builds no record per
            # candidate.
            terms = []
            score(ctrl, need, role, floor=floor, usable=usable,
                  rules=rules, parts=terms)
            # The BAND's ceiling, not the lifted one. The relaxed pass
            # raises it, and the raised number recorded here makes a
            # placement that reached past the floor read as one that did
            # not. `how` is what says the floor came off.
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
    # directions AND a press. A rocker nobody claimed has two positions.
    # What is spare is counted per BUTTON and not per control: a need with
    # one binding does not speak for the other three buttons of its
    # hat.
    occupied = {(p.role, b) for p in placed for b, _ in p.slots}
    still = []
    for i in unplaced:
        need = needs[i]
        if need.wanted != 1:
            still.append(i)        # Nothing to share for a whole control.
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
                # These lend no position. A trigger's stages are the gun.
                # A selector's positions are one switch. An encoder's two
                # contacts are one more and less pair. A latch HOLDS
                # whichever position it is in, so a press action shared
                # from one fires for as long as the lever sits there.
                # Bomb release landed on a master-arm latch that way.
                #
                # Their click, where they have one, is a real button and
                # is fair game.
                if c.push is None or (role, c.push) in occupied:
                    continue
                button = c.push
            else:
                button = (c.push if c.push is not None
                          and (role, c.push) not in occupied else spare[0])
            # The same scorer as every other pass, told which pass it
            # is. `scoring.toml` says what that changes: the shape gate
            # comes off and the reward for distance turns around.
            #
            # Computed here instead, it is four numbers in source, with
            # the reach floor and the ceiling checked by hand beside
            # them, and a sum nobody can see the parts of. The parts then
            # have to be rebuilt by hand for the screen, and the two
            # copies have to agree.
            s = score(c, need, role, usable=usable, rules=rules,
                      shared=True, opening=j not in taken)
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
              shared=True, opening=j not in taken)
        why = Reason('shared', points=_s, parts=terms,
                     tier=reach_tier(ctrl),
                     ceiling=top[need.urgency])
        slots = [(button, need.bindings[0])]
        hand_out(slots, role, why)
        placed.append(Placement(need, role, ctrl, slots, _s, why))
        sat[id(need)] = ctrl

    # A need whose chosen control is gone comes back here, and NOT
    # through the share pass above. A spare button somewhere else moves
    # it, and not moving it is what writing the choice down was for. The
    # row waits, empty, for you to say where it goes now.
    still += orphan + nowhere + sorted(empty)

    # Free means every INPUT of it is free, and an axis is an input. It
    # does not mean that no need chose the control.
    #
    # The main stick has no buttons, so all zero of them are spare and it
    # is offered as a free control with pitch, roll and rudder on it. The
    # same holds for both throttle levers and both mini-sticks: five
    # controls on this desk, every one a flight control, offered to a
    # cold-start switch.
    on_axes = {(p.role, b) for p in placed for b, _v in p.slots
               if isinstance(b, OnAxis)}
    free = [(r, c) for j, (r, c) in enumerate(pool)
            if j not in taken
            and not any((r, b) in occupied for b in c.bindable_buttons)
            and not any((r, OnAxis(a.index)) in on_axes
                        for a in axes_of(devices[r], c))]
    return placed, [needs[i] for i in still], free

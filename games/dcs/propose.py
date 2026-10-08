#!/usr/bin/env python3
"""propose.py - lay out one DCS module on the HOTAS

DESCRIPTION
    Propose a binding for every command the module puts on a HOTAS, from
    the shape of the controls in the device map.
    Proposals land in the wizard's results file marked `?` until confirmed.
    --write hands the result to dcs-bind-wizard.py, which owns diff.lua.

FILES
    dcs-bind-wizard.py             device detection and the diff.lua writer
    dcs-bind-wizard-results.json   the bindings, and where the game is
    jobs.toml                      what each command is for, by name
    <device>.diff.lua              written by --write, per aircraft

ENVIRONMENT
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close DCS first: it rewrites Config/Input on exit.
    Aircraft is remembered after the first run; -a picks another.
"""

import argparse
import collections
import datetime
import json
import tomllib
import os
import re
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'There is no shared core at {CORE}.\n'
                     'Set SIM_BIND_WIZARD to the sim-bind-wizard '
                     'checkout.')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core.needs import IN_A_TURN, IN_THE_AIR                # noqa: E402


def wizard():
    """The wizard itself, imported for its harvest -- it is the thing that
    knows how to read a module's commands and profiles."""
    return adapter.from_file('dcswiz',
                             os.path.join(HERE, 'dcs-bind-wizard.py'),
                             argv=['dcs-bind-wizard'])


#: What the module's own prose is asking for. Ordered: first match wins, so
#: the specific phrases sit above the general ones.
SHAPES = [
    (r"\btrigger\b",                            'trigger'),
    (r'\bpaddle\b',                             'paddle'),
    (r'slew|mini-?stick|thumb slew',            'ministick'),
    (r'4-way hat|four-way|\bhat\b',             'hat4'),
    (r'rotary|antenna wheel|\bknob\b',          'dial'),
    (r'2-position|two-position|2-way|two-way',  'hat2'),
    (r'toe brakes|brake lever',                 'axis'),
    (r'spare axis|the throttle lever|its [XY] axis|twist', 'axis'),
]


def wants(cmd, g):
    """(shape, device or None, when you touch it, what it takes).

    The SHAPE is read out of the module's own prose, because that
    sentence is the thing that tells a dial from a hat. Which device it
    belongs on and when you touch it are data in the same table -- a
    sentence about the real jet is not something a scorer can read, and
    asking the factory profiles instead is what this used to do.
    """
    place = (g.get('place') or '').lower()
    ways = cmd.get('ways') or 0
    if LATCH_COMMANDS.search(cmd['name']):
        # the lever is on the grip, so nothing about reach can disqualify it
        return 'latch', 'stick', IN_A_TURN, corneeds.BUTTON
    shape = 'button'
    for pattern, s in SHAPES:
        if re.search(pattern, place):
            shape = s
            break
    # The command's own kind wins over the prose, both ways. "toe brakes. A
    # brake lever on the stick base" is the place for BOTH `Wheel Brake` (an
    # axis) and `Wheel Brake - ON/OFF` (a button), and each wants its own kind
    # of home.
    if cmd['kind'] == 'axis':
        # Keep what the prose said where it named a kind that CARRIES
        # an axis: "the antenna wheel on the throttle. A rotary or an
        # axis" is asking for a dial, and flattening every axis
        # command to a bare `axis` threw that away -- then the points
        # had nothing to go on but "any lever will do".
        if shape not in ('ministick', 'dial', 'lever', 'stick'):
            shape = 'axis'
    elif shape == 'axis':
        shape = 'hat2' if ways > 1 else 'button'
    if shape == 'hat4' and 1 < ways <= 2:
        shape = 'hat2'                  # its siblings say it is a 2-way switch
    return shape, g.get('device'), g.get('band'), (
        corneeds.AXIS if cmd['kind'] == 'axis' else corneeds.BUTTON)


class Need(corneeds.Need):
    """A core need built from a module's own commands rather than by hand.

    `bindings` is the list of DCS command hashes the family covers, which the
    core treats as opaque -- it only ever indexes it.

    `on` is set by `families`, one word per member, read out of the
    module's own prose -- and None for a member whose prose does not say
    which way it points, which a four-member family often has two of.
    It used to be left unset on purpose, because `slots_for` wanted every
    direction to match or fell back to press order for the lot; it fills
    the gaps now, so the core can place a hat's directions itself.
    """

    def __init__(self, what, shape, members, device=None, urgency=IN_THE_AIR,
                 takes=corneeds.BUTTON):
        # A slot is a list of Binds now. DCS has no contexts and no
        # release half, so every slot is exactly one -- `members` is the
        # list of command hashes the family covers.
        #
        # An axis command asks the way every other game's needs file
        # asks: a shape, which axis of it, and where it has to rest.
        # `wants()` reads the first out of the module's prose and
        # `axis_ask` the rest out of the command's own name -- which is
        # the one thing about an axis the core cannot know.
        #
        # `takes` comes from the COMMAND's own kind, passed in: read off
        # the shape word instead, a command whose prose names a dial or a
        # mini-stick stopped being an axis need at all and the Hornet
        # lost its designator, its zoom and its antenna.
        on = rests = prefer = None
        if takes == corneeds.AXIS:
            shape, on, rests, prefer = axis_ask(what, shape)
        super().__init__(what, shape,
                         bindings=[[cactions.Bind(h)] for h in members],
                         device=device, urgency=urgency,
                         takes=takes, rests=rests, prefer=prefer,
                         on=(on,) if on else None,
                         invert=takes == corneeds.AXIS and _inverted(what))
        #: the hashes, in order. The core only ever indexes `bindings`;
        #: this is for the places that still think in DCS's own hashes,
        #: and the order is the order of the slots.
        self.members = list(members)


#: How DCS spells "step the switch along" where the switch has positions
#: of its own. `Cycle` is always that; `Up` and `Down` are it only when
#: some other position is named, because on a two-position switch they ARE
#: the positions (`Landing Gear Control Handle - UP`).
STEPPING = ('up', 'down', 'cycle')


def _tail(name, family):
    """The part of a command name that says WHICH position this is.

    Two spellings, and one module uses both: the Hornet separates the
    position with ` - ` ("FLAP Switch - FULL"), the Su-25T appends it
    ("Landing Gear Up/Down"). Taking the family's own name off the front
    covers either, and `switch_family` has already worked out what the
    family is called -- which is why this needs telling.
    """
    low = name.strip().lower()
    head = (family or '').strip().lower()
    if head and low.startswith(head):
        low = low[len(head):]
    return low.lstrip(' -').strip()


def one_per_switch(chosen, cmds):
    """The same list, with one command per physical switch.

    A three-position switch ships its positions, a command for each
    adjacent PAIR of them (`- RETRACT/OFF`), and a `Cycle` that steps
    through -- four names for one switch. Binding more than one of them
    spends buttons on the same thing, and on a six-position rotary it put
    the flap positions on three and "step the flaps" on the other three.

    Done over the whole list rather than inside `families`, where it used
    to be: `ways` counts a family's DIRECTIONS, so a switch whose
    positions are called EXTEND and RETRACT is not a family at all, and
    its combined form survived every time.
    """
    by_family = {}
    for h in chosen:
        by_family.setdefault(cmds[h].get('family') or h, []).append(h)
    drop = set()
    for fam, members in by_family.items():
        tails = {_tail(cmds[h]['name'], fam): h for h in members}
        named = [t for t in tails if t not in STEPPING and '/' not in t]
        for tail, h in tails.items():
            if '/' in tail and all(p.strip() in tails
                                   for p in tail.split('/')):
                drop.add(h)            # the pair, where both parts are here
            elif tail == 'cycle' and len(tails) > 1:
                drop.add(h)            # the same thing with another word
            elif tail in STEPPING and named:
                drop.add(h)            # a position is named, so this steps
    return [h for h in chosen if h not in drop]


def families(module, cmds, guide, chosen):
    """Group a hat's four commands into one thing to place.

    A four-way hat reaches the wizard as four separate commands; placing them
    one at a time would scatter them across four unrelated buttons.

    `module` is here for the direction words: which way each command of a
    family points is in the module's own prose, and the need carries the
    answer in `on` so that the core puts them in that order.
    """
    check_guide(cmds, guide)
    groups, singles = collections.OrderedDict(), []
    for h in chosen:
        c = cmds[h]
        fam = c.get('family')
        shape, dev, urgency, takes = wants(c, guide[h])
        # Siblings of one physical switch belong together whatever shape they
        # were classified as. Left and right engine cutoff are a pair: split
        # across two devices they are worse than anywhere together, because
        # your hand has to learn two places for one idea.
        # `ways` counts a switch's sibling positions, and the Hornet reports 0
        # for master arm, so the usual test would leave the pair as two
        # unrelated singles -- and they would then land on the lever in
        # whatever order scoring happened to visit them. LATCH_COMMANDS already
        # admits exactly one pair, so the count adds nothing there.
        together = shape == 'latch' or (c.get('ways') or 0) > 1
        if fam and together and shape in ('hat4', 'hat2', 'button', 'latch'):
            key = (fam, shape)
            groups.setdefault(key, {'shape': shape, 'device': dev,
                                    'urgency': urgency, 'members': []})
            groups[key]['members'].append(h)
        else:
            singles.append((h, shape, dev, urgency, takes))
    for g in groups.values():
        if g['shape'] == 'latch':
            # A leftover member goes on the next bindable button in order,
            # and the latch reports its contacts closed-first. Putting SAFE
            # first lands
            # it on the same physical contact that carries SimSafeMasterArm in
            # Falcon BMS, so one check on the ramp settles both sims -- and if
            # it turns out backwards, both swap together.
            g['members'].sort(key=lambda h: 0 if re.search(
                r'safe$', cmds[h]['name'], re.I) else 1)

    def label_for(fam, members):
        """`switch_family` strips the direction words, which sometimes leaves
        nothing useful: the engine cutoff pair comes out called "throttle".
        The names themselves read better."""
        names = [cmds[h]['name'] for h in members]
        head = names[0]
        for n in names[1:]:
            i = 0
            while i < min(len(head), len(n)) and head[i] == n[i]:
                i += 1
            head = head[:i]
        head = head.rstrip(' -(,')
        return head if len(head) >= 4 else fam

    out = []
    for (fam, shape), g in groups.items():
        members = g['members']
        fam = label_for(fam, members)
        if shape == 'button' and len(members) > 1:
            # a pair of buttons that are one switch wants one switch
            shape = 'hat2' if len(members) == 2 else 'hat4'
        out.append(Need(fam, shape, members, device=g['device'],
                        urgency=g['urgency']))
    for h, shape, dev, urgency, takes in singles:
        out.append(Need(cmds[h]['name'], shape, [h], device=dev,
                        urgency=urgency, takes=takes))
    # Not sorted here. `allocate` has its own order and it is a total one
    # -- pinned, then the band, then the name -- and a second ordering in
    # front of it only decided the ties it could not see.
    for need in out:
        need.suits = job_of(need.what)
        if need.takes != corneeds.AXIS:
            # Which way each command points, in the module's words, one
            # per binding -- and None where its prose does not say. The
            # core puts the named ones where they belong and fills the
            # rest in press order.
            #
            # `on` used to be deliberately NOT set, with `lay_out` here
            # matching the directions itself at writing time. So the
            # core answered which button for the screen and this
            # answered it for the writer, and a trim hat could be shown
            # one way round and written another.
            said = tuple(direction_of(module, cmds[h])
                         for h in need.members)
            need.on = said if any(said) else None
    return out


_JOBS = None


def jobs():
    """[(phrase, job)] from `jobs.toml`, in the file's own order.

    Order is load-bearing -- the first phrase that appears in a command's
    name wins -- so this keeps the list flat rather than a dict per job:
    `fov select` has to be read before `select`.

    Checked against the core's table on the way in, the way the overlay
    reader checks a rule name: a job nobody defines is a word no overlay
    can match, so a typo here would cost every command it touches every
    wish in the file, silently.
    """
    global _JOBS
    if _JOBS is None:
        with open(os.path.join(HERE, 'jobs.toml'), 'rb') as f:
            got = tomllib.load(f)
        out = []
        for row in got.get('job', []):
            if row['is'] not in corneeds.JOBS:
                raise SystemExit(
                    f'jobs.toml: {row["is"]!r} is not a job. These are: '
                    + ', '.join(corneeds.JOBS) + '.')
            out += [(phrase.lower(), row['is']) for phrase in row['when']]
        _JOBS = out
    return _JOBS


def job_of(name):
    """What this command is for, or None if no phrase in the table fits.

    None is not a failure: a module nobody has been through yet lays out
    on reach and shape exactly as it did before this existed. `Dcs.__init__`
    says how many went unnamed, because that is the number that tells you
    whether an overlay had anything to work with.
    """
    low = name.lower()
    return next((job for phrase, job in jobs() if phrase in low), None)


def check_guide(cmds, guide):
    """Loud when the module's own table names a device or a band nothing
    knows -- the way `jobs()` is loud about a job.

    Both words come from somewhere else and neither is this module's to
    invent: a device does a job the DESK names, and a band is one of the
    four the core scores in. A role nothing on the desk answers to
    matches no device and quietly costs that command its home; a band
    off the scale orders it against needs it was never compared with.
    """
    roles = set(devmap.load().ROLES_ON_A_DESK)
    bands = range(len(corneeds.URGENCY_NAME))
    for h, g in guide.items():
        if g['band'] is None:
            continue
        what = cmds[h]['name'] if h in cmds else h
        if g['device'] is not None and g['device'] not in roles:
            sys.exit(f'{what!r} is put on a {g["device"]!r}. That is not '
                     'a job a device does. These are: '
                     + ', '.join(sorted(roles)) + '.')
        if g['band'] not in bands:
            sys.exit(f'{what!r} is in band {g["band"]!r}. That is not a '
                     'band. These are: '
                     + ', '.join(corneeds.URGENCY_NAME) + '.')


#: Which axis of which control a flight command belongs on, in the map's
#: own two words: the kind of control, and which of its axes.
#:
#: It used to say `stick-y`, `stick-x` and `twist` -- one word for both --
#: and the map stopped spelling it that way: a stick is ONE control with
#: three axes, not three controls, so a kind per axis said the kind twice.
#: `Device.axes(kind=...)` filters on the control's kind, so all three
#: asked for a kind nothing has and got nothing back. Pitch, roll and
#: rudder -- the three axes the aircraft flies on -- came out as `no axis
#: on this hardware` on a desk with a full stick on it, and the only sign
#: was that line. `games/x4/plan.py` has used `axis_of` since the rename.
#: The module says which way a switch goes in its own words; the map says which
#: way each button points. Joining them is what stops a trim hat coming out
#: scrambled -- both halves were there and the first version zipped them in
#: arbitrary order.
MOVE_TO_DIR = [
    (r'press|depress',                          'push'),
    # sideways first: "INBOARD (towards your left)" contains "towards you",
    # which would otherwise read as aft and scramble the whole hat
    (r'inboard|\bleft\b',                       'left'),
    (r'outboard|\bright\b',                     'right'),
    (r'forward|fwd|away from you|\bpush\b',     'up'),
    (r'\baft\b|towards you\b|\bpull\b|\bback\b',  'down'),
    (r'\bup\b|climb',                           'up'),
    (r'\bdown\b|descend',                       'down'),
]

#: a two-stage trigger names its detents
STAGE_WORDS = [(r'first|1st', 0), (r'second|2nd', 1), (r'third|3rd', 2)]


def direction_of(module, cmd):
    move = module.hat_move(cmd['name'], cmd.get('dir')) or cmd['name']
    for pattern, d in MOVE_TO_DIR:
        if re.search(pattern, move, re.I):
            return d
    return None


def stage_of(cmd):
    for pattern, i in STAGE_WORDS:
        if re.search(pattern, cmd['name'], re.I):
            return i
    return None


#: What an axis command ASKS FOR, read out of its own name. Ordered:
#: first match wins, so the specific phrases sit above the general ones.
#:
#: It used to answer with a resolved axis -- `resolve_axis`, which went
#: looking through the devices itself and carried its own preferences
#: ("steadiest first: something that stays where you leave it"). Those
#: are comparisons over what the map measured, and the scoring table is
#: where comparisons live. What is left here is the only thing the core
#: cannot know: which command IS pitch, in this module's words.
#:
#:   pattern -> (shape, which axis of it, where it must rest)
AXIS_ASK = [
    (r'^pitch',                   ('stick', 'y', 'centred')),
    (r'^roll',                    ('stick', 'x', 'centred')),
    (r'^rudder',                  ('stick', 'z', 'centred')),
    (r'designator|slew',          ('ministick', None, 'centred')),
    (r'^thrust|^throttle$',       ('lever', None, 'mid')),
    (r'brake',                    ('lever', None, 'min')),
    (r'zoom',                     ('dial', None, 'min')),
    (r'\brpm\b|prop(eller)? pitch|mixture|supercharger',
                                  ('lever', None, 'mid')),
]


def axis_ask(name, shape):
    """(shape, on, rests, prefer) for an axis command, from its name.

    `shape` is what the module's prose already said, and it wins: "the
    antenna wheel on the throttle. A rotary or an axis" is asking for a
    dial, and this table is only here for what the prose does NOT say --
    which axis of a stick, and where the thing has to rest.

    `prefer` only for the engine pair: two levers, two engines, and a
    cold start in the Hornet runs them up one at a time. Nothing in the
    hardware says which lever is the left one -- the command's own name
    does, and that is the one thing here that is not a comparison.
    """
    low = name.lower()
    for pattern, (said, on, rests) in AXIS_ASK:
        if not re.search(pattern, low):
            continue
        if shape == 'axis':
            shape = said        # the prose said nothing finer
        if re.search(r'vert', low):
            on = 'y'
        elif on is None and shape == 'ministick':
            on = 'x'
        side = ('right' if 'right' in low else
                'left' if 'left' in low else None)
        prefer = f'{side} throttle lever' if side and shape == 'lever' else None
        return shape, on, rests, prefer
    # Nothing in the name, so whatever the prose said stands and the
    # points pick among what fits. `mid` because an axis nobody named is
    # one you set and leave: that is what gets Radar Elevation Control a
    # home instead of nothing.
    return shape, None, 'mid', None


# WHEN you touch a command decides how good a home it deserves, and it is
# said per row in the wizard's own hint table now -- `band`, in the core's
# four. It was derived here twice over: a map from the module's six themes
# onto the four, and a regex looking for "on the grip" in the sentence that
# describes the real jet, which is a different question and moved the
# symptom every time it was fixed. A table row says it outright.


#: A two-position switch that HOLDS its position deserves a control that also
#: holds one, and this hardware has exactly one: the lever over the trigger.
#: Master arm is the command it was made for -- the guard position becomes the
#: switch position, so you can read the aircraft's state off your own hand
#: without looking into the cockpit.
#:
#: Deliberately narrow. Every other two-position command in a module is happy
#: on a sprung hat, and the trigger lever is the most valuable real estate on
#: the stick; it should not go to the first switch family that asks.
LATCH_COMMANDS = re.compile(r'master arm switch - (arm|safe)$', re.I)


#: Reach tiers, shape substitutions and the scorer all live in the core now.
#: The copies here were the core's minus `prefer`, `suits`, `push`, `usable`
#: and the second pass; see ALLOCATION.md.
reach_tier = corneeds.reach_tier
score = corneeds.score


def results_path():
    return os.path.join(HERE, 'dcs-bind-wizard-results.json')


def load_cfg(module, game_dir=None):
    """The wizard remembers where the game is in the results file; reuse that
    rather than making you pass it again."""
    try:
        with open(results_path(), encoding='utf-8') as f:
            cfg = dict(json.load(f)['_config'])
    except (OSError, KeyError):
        cfg = {}
    if game_dir:
        cfg['game_dir'] = game_dir
    if not cfg.get('game_dir'):
        sys.exit('Pass --game-dir, or run the wizard once so that it '
                 'remembers.')
    return cfg


def candidates(module, cmds, guide):
    """The commands worth placing: the ones the module's own table puts on
    the HOTAS.

    Cold-start switches used to be listed here separately, on the
    argument that no factory profile binds them -- a profile is written
    for a jet that is already running. The table says it now, where the
    rest of the judgement is.
    """
    chosen = [h for _t, items in module.essentials(cmds, guide)
              for h, _n, _k in items]
    # The module's own prose says the combined thrust axis is superseded:
    # "The throttle lever -- both levers if the jet has Thrust Left/Right".
    # A cold start runs the engines up one at a time, so the pair is what
    # you want and binding the combined one as well would have them
    # fighting over the same lever. This used to be a resolver that
    # answered "no axis" for it, which read as a gap rather than as a
    # decision.
    names = {cmds[h]['name'].lower() for h in chosen}
    if {'thrust left', 'thrust right'} <= names:
        chosen = [h for h in chosen if cmds[h]['name'].lower() != 'thrust']
    return one_per_switch(chosen, cmds)


_RULES = None


def _rules():
    """DCS's scoring: the core's, with `scoring.toml` beside this over it.

    Module level because two of `place`'s three callers have no adapter to
    ask -- `reseed` and `seed` -- and all three have to score the same way
    or the screen and the file disagree about the same aircraft.
    """
    global _RULES
    if _RULES is None:
        with open(os.path.join(HERE, 'scoring.toml'), 'rb') as f:
            _RULES = corneeds.merge_rules(corneeds.RULES, tomllib.load(f))
    return _RULES


def name_the_stages(devs, needs, cmds):
    """Which stage of the trigger each command that wants it gets.

    A command can name one ("Gun Trigger - SECOND DETENT") and that is
    the stage it gets -- the Hornet's gun was landing on the first
    detent, which is the one that only runs the camera, because press
    order was all the core had to go on.

    And more than one command can want the trigger: on the Su-25T the
    cannon and the selected weapon both belong there, lighter pull first,
    and letting the first comer take the whole control put the jet's main
    fire command on a hat direction.

    What is DCS's own is the reading: a stage named in a command ("Gun
    Trigger - SECOND DETENT"), and otherwise the name deciding who gets
    the lighter pull. The PLACING is not: the need says which control
    (`prefer`) and which of its buttons (`on`), and the allocator honours
    both. This used to build a `Placement` here with 200 points written
    into it and a `Reason` of its own, take the need out of the list, and
    veto the control for everybody else.
    """
    want = [n for n in needs if n.shape == 'trigger' and len(n.members) == 1]
    if not want:
        return
    spot = next(((r, c) for r, d in sorted(devs.items())
                 for c in d.groups(bindable=True)
                 if c.kind == 'trigger'), None)
    if spot is None:
        return
    ctrl = spot[1]
    # The map's own words for them -- `first`, `second`, `third` -- which
    # is what `on` is matched against.
    stages = [ctrl.direction(b) for b in ctrl.buttons]
    mine, rest = {}, []
    for need in want:
        st = stage_of(cmds[need.members[0]])
        if st is not None and st < len(stages) and stages[st] not in mine:
            mine[stages[st]] = need
        else:
            rest.append(need)
    rest.sort(key=lambda n: n.what)
    for need in rest:
        spare = [s for s in stages if s and s not in mine]
        if not spare:
            break
        mine[spare[0]] = need
    for stage, need in mine.items():
        need.on = (stage,)
        if len(want) > 1:
            # Only where they have to SHARE. One claimant is scored like
            # everything else and `on` is enough to put it on the stage it
            # names; naming the control as well would take it out of the
            # comparison for no reason.
            need.prefer = ctrl.label


def place(module, cmds, guide, chosen, rules=None, needs=None):
    """-> core.needs.Layout.

    The matching is `core.needs.allocate`. What stays here is what the core
    cannot know: which commands form one family, which of them wants an axis,
    and that a trigger's stages are separately named.

    It used to return `[(need, spot, score)], unplaced` -- a fourth shape of
    the same five values, which is the drift `core.needs.Layout` exists to
    stop. The free list, which this threw away, is kept, and that is where
    `--free` comes from.

    The axes go through `allocate` with everything else and are scored
    like everything else. Which command IS pitch is read out of its own
    name in `axis_ask`, because that is the one thing about an axis the
    core cannot know; which LEVER pitch goes on is a comparison, and the
    scoring table makes it.
    """
    devs = devmap.by_role('stick', 'throttle')
    # Given, when a caller has already put what you confirmed onto them.
    needs = (families(module, cmds, guide, chosen)
             if needs is None else needs)
    name_the_stages(devs, needs, cmds)
    placed, still, free = corneeds.allocate(
        needs, devs, rules=rules or _rules())

    return corneeds.Layout(devs, list(placed), still, free)


def rows(layout):
    """[(need, spot, score)] -- the shape the listing and --check read.

    The axes first and then the buttons, which is the order the listing
    has always printed. There used to be a third group in front of them:
    the trigger claims, which `place()` built itself. They are ordinary
    placements now and come through with the rest.

    A claim was recognised by scoring exactly 200 -- a number chosen to
    carry a meaning, which is a number nobody can change and one the
    allocator could hit honestly -- and then by a `Reason` of its own.
    Both are gone with the claiming.
    """
    # Including the axis needs this desk cannot answer. The combined
    # Thrust is deliberately one of them -- the two engines are bound
    # separately -- so a listing that dropped it would be hiding a
    # decision rather than reporting a gap.
    at = {id(p.need): p for p in layout.on_axes}
    axes = []
    for need in [p.need for p in layout.on_axes] + list(layout.unplaced):
        if need.takes != corneeds.AXIS:
            continue
        p = at.get(id(need))
        axes.append((need, (p.role, [layout.devices[p.role].axis(
            p.slots[0][0].index)]) if p else None, None))
    return axes + [(p.need, (p.role, p.ctrl), p.points)
                   for p in layout.on_buttons]


def written(layout):
    """command hash -> (role, button) -- the allocator's own answer.

    The one place it is read off a layout. There used to be two answers
    to which button a command lands on: `slots_for` in the core, which is
    what the review screen draws, and `lay_out` here, which is what the
    writer wrote and what the listing printed. They agreed by
    construction for a need with one command and could differ for a hat.
    """
    return {b.action: (p.role, button)
            for p in layout.on_buttons
            for button, payload in p.slots
            for b in payload}


def propose(module, key, game_dir=None):
    cfg = load_cfg(module, game_dir)
    ac = module.discover_aircraft(cfg)
    if key not in ac:
        sys.exit(f'There is no module called {key}. These are '
                 f'installed: {", ".join(ac)}.')
    cmds = module.harvest_commands(cfg, key, ac[key]['factory_dir'])
    guide = module.build_guide(cmds)
    layout = place(module, cmds, guide, candidates(module, cmds, guide))
    return cmds, guide, layout


def seed(module, cmds, guide, chosen=None, layout=None):
    """{command hash: the same record the capture screen writes}.

    Marked `proposed` so the screen can show what you have not confirmed yet;
    capturing over one drops the mark.

    `layout` is the plan to write down. Give it whenever there IS one --
    the review screen hands back its own, narrowed to what was accepted --
    because working one out again here ignores every decision that screen
    made. Left out, one is worked out, which is what the capture wizard and
    `reseed()` want: neither has a reviewer to ask.
    """
    if layout is None:
        if chosen is None:
            chosen = candidates(module, cmds, guide)
        layout = place(module, cmds, guide, chosen)
    recs = {}
    for p in layout.on_axes:
        name = cmds[p.need.members[0]]['name']
        recs[p.need.members[0]] = {
            'name': name, 'role': p.role, 'type': 'axis',
            'index': p.slots[0][0].index, 'invert': _inverted(name),
            'proposed': True}
    for h, (role, button) in written(layout).items():
        if h in cmds:
            recs[h] = {'name': cmds[h]['name'], 'role': role,
                       'type': 'button', 'index': button, 'proposed': True}
    return recs


def _inverted(name):
    """Pitch wants inverting everywhere: stick back is nose up."""
    return name.split(' - ')[0].strip() == 'Pitch'


def unbound(module, cmds, guide, key):
    """What the module puts on the HOTAS and nothing has taken yet.

    In the list's own order -- the order you learn an aircraft in, by
    name inside each theme. It used to be sorted by how many factory
    profiles bound each one, which is the ranking that left.
    """
    binds = json.load(open(results_path()))['aircraft'].get(key, {})
    return [(name, kind)
            for _t, items in module.essentials(cmds, guide)
            for h, name, kind in items if h not in binds]


def write(module, cfg, aircraft, backup_dir=None):
    """Into the game, through the wizard that knows diff.lua.

    The wizard stays the writer -- it owns the format, and the results file it
    reads is its own. What it should not also own is the *verb*: every other
    planner in the family answers `--write` itself, and this delegating is
    what makes that true for DCS too.
    """
    results = json.load(open(results_path()))
    return module.generate(results, cfg, aircraft, backup_dir)


def audit(module, key, cmds, guide):
    """Bindings that no longer match the hardware.

    An old capture is numbered against the device as it was configured then.
    Reconfigure a VIRPIL and the numbers stay put while the buttons move, so a
    binding can end up on a control that does something else -- or on one the
    firmware reports with nothing behind it.
    """
    binds = json.load(open(results_path()))['aircraft'].get(key, {})
    devs = devmap.by_role('stick', 'throttle')
    out = []

    # two commands on one axis is nearly always a leftover: they drive the same
    # surface from the same lever and fight over it
    by_axis = {}
    for h, r in binds.items():
        if isinstance(r, dict) and r.get('type') == 'axis':
            by_axis.setdefault((r['role'], r['index']), []).append(r)
    for (role, idx), rs in by_axis.items():
        if len(rs) > 1:
            others = ', '.join(x['name'] for x in rs[1:])
            out.append((rs[0]['name'], rs[0],
                        f'shares this axis with {others}'))
        # the same lever cannot need inverting for one command and not another
        if len({bool(x.get('invert')) for x in rs}) > 1:
            out.append((rs[0]['name'], rs[0],
                        'inverted for some commands on this axis, not others'))

    for h, r in binds.items():
        if not isinstance(r, dict) or 'role' not in r:
            continue
        d = devs.get(r['role'])
        if not d:
            continue
        if r['type'] == 'axis':
            if d.axis(r['index']) is None:
                out.append((r['name'], r, 'no such axis on this device'))
            continue
        g = d.group_of(r['index'])
        if g is None:
            out.append((r['name'], r, 'no such button'))
        elif not g.bindable:
            out.append((r['name'], r,
                        f'{g.kind} — {g.label}: nothing is behind it'))
        elif h in cmds:
            shape, _dev, _urg, _takes = wants(cmds[h], guide.get(h, {}))
            if shape and shape != 'axis' and g.kind != shape:
                # a hat direction is a fine home for a plain button; the other
                # way round is what is worth saying
                if shape in ('paddle', 'trigger', 'ministick'):
                    out.append((r['name'], r,
                                f'wants a {shape}, sits on {g.kind} '
                                f'"{g.label}"'
                                + (f' [{g.direction(r["index"])}]'
                                   if g.direction(r['index']) else '')))
    return out


# -------------------------------------------------------------- the adapter --

class Wizard(typing.Protocol):
    """What this proposer calls on `dcs-bind-wizard.py`.

    See the note on `Preset` in games/warthunder/plan.py: this gets the call
    sites checked, not the promise that the script has them.
    """

    def discover_aircraft(self, cfg: dict) -> dict: ...

    def harvest_commands(self, cfg: dict, aircraft_key: str,
                         factory_dir: str) -> dict: ...

    def catalogue(self, cmds: dict) -> list[cactions.Action]: ...

    def build_guide(self, commands: dict) -> dict: ...

    def render_all(self, results: dict, cfg: dict, aircraft: str,
                   bindings: dict | None = ...) -> tuple[dict, list[str]]: ...


@typing.final
class Dcs(adapter.Planner):
    """DCS World, one module at a time.

    A `Planner` like the other five. It used to be a `Proposer` -- a type
    of its own, with its own writer path, its own store and its own review
    screen -- on the argument that a binding confirmed at the stick beats
    one a planner proposed. That is true and it is not a reason for a
    second set of interfaces: the family already draws that line with `+`
    and `?`, writes both, and says so before the keystroke.

    What stays DCS's own is what no other game has. The needs are derived
    from the module's command vocabulary on every run, so they are a
    function of `--aircraft` and there is no needs file to keep them in --
    which is also why the adapters had to become classes, since `NEEDS` as
    a module constant could never mean both the Hornet's and the Su-25T's.
    The `diff.lua` format and naming the devices by DCS's own GUIDs live in
    `dcs-bind-wizard.py`.
    """

    game = 'dcs'
    title = 'DCS World'
    CATALOGUE = 'dcs-actions.json'
    CACHE = {'dcs-actions.json': 'aircraft'}
    #: `-a` is what this has always been typed as, and `./bind dcs plan
    #: -a su-25T` is in the top-level README.
    ALIASES = {'aircraft': ('-a',)}
    SAYS = {'aircraft': 'which module to lay out (default: FA-18C)',
            'game_dir': 'the DCS install, if it is not where the results '
                        'file says'}

    def __init__(self, aircraft='FA-18C', game_dir=None, backup_dir=None):
        self.aircraft = aircraft or 'FA-18C'
        self.backup_dir = backup_dir
        self.subtitle = self.aircraft
        self.module = typing.cast(Wizard,
                                  self.sidecar('dcs-bind-wizard.py'))
        self.cfg = load_cfg(self.module, game_dir)
        # The cache first, the install only if it has nothing for this
        # module. Running a module's default.lua through a Lua interpreter
        # costs a second or two and needs DCS on the machine; cached, this
        # opens on a clone with no game installed -- which is what the other
        # five already offered.
        got = self.cache('dcs-actions.json',
                         build=lambda: {}).get(self.aircraft)
        if got is None:
            ac = self.module.discover_aircraft(self.cfg)
            if self.aircraft not in ac:
                raise SystemExit(
                    f'There is no module called {self.aircraft}. These are '
                    f'installed: {", ".join(sorted(ac))}.')
            got = {'commands': self.module.harvest_commands(
                self.cfg, self.aircraft, ac[self.aircraft]['factory_dir'])}
        self.cmds = got['commands']
        # Built here every time, never cached. The guide is the module's
        # own judgement about its command names -- which device, which
        # band, what to say about it -- and a cached copy would keep an
        # edit to that table out of the next plan.
        self.guide = self.module.build_guide(self.cmds)
        # Where things sit, one file per module: an adapter is built FOR
        # an aircraft, and the Hornet and the Viper are two layouts. Set
        # here rather than declared on the class, because the class does
        # not know which aircraft it is yet.
        self.BINDS = f'dcs-{self.aircraft}-binds.json'
        self._needs = families(
            self.module, self.cmds, self.guide,
            candidates(self.module, self.cmds, self.guide))
        # Where things sit, onto those same needs -- so `NEEDS` is the
        # list the screen walks AND the list the plan is built from, not
        # two lists that happen to agree.
        corneeds.load_assignments(HERE, self.BINDS, self._needs)

    @property
    @typing.override
    def NEEDS(self):
        """Derived from this module's own commands, so it is a property."""
        return self._needs

    @typing.override
    def build(self):
        # The same needs the screen walks, carrying what you confirmed at
        # the stick -- so the `chose` pass takes those controls first and
        # the screen opens green on them rather than rebuilding every mark
        # from the planner.
        got = place(self.module, self.cmds, self.guide,
                    candidates(self.module, self.cmds, self.guide),
                    needs=self._needs)
        # Once per adapter, and `Adapter.answers` says why. In practice
        # `__init__` has already read them onto these same needs, which
        # is where it has to happen: `place` above takes the control you
        # chose before anything is scored.
        self.answers(self._needs)
        return got


    @typing.override
    def catalogue(self):
        # Settled beside `harvest_commands`, which builds these records:
        # what a field is called is a fact about the format. DCS is the one
        # game whose record is richer than the shared one -- `ways`, `dir`
        # and `family` have no room in it and seven places here read them
        # -- so the cache keeps one record rather than two spellings of
        # the same four fields across 2500 of them.
        return self.module.catalogue(self.cmds)


    @typing.override
    def describe(self, placement):
        return [(str(button), self.cmds[b.action]['name'])
                for button, payload in placement.slots
                for b in payload if b.action in self.cmds]

    @typing.override
    def write_layout(self, layout):
        """The game's files, for the layout it is handed.

        The layout and nothing else, like the other five: what the review
        screen kept is what goes into the game, `?` rows included -- the
        box before the keystroke says so, and clearing one with `x` is
        how you say no. This used to read the results file and ignore the
        argument, so anything cleared on the screen came straight back.
        """
        results = json.load(open(results_path()))
        # `seed` the module function: the layout-to-records step DCS
        # already had. `proposed` is the screen's business, not the
        # game's.
        bound = {h: {k: v for k, v in r.items() if k != 'proposed'}
                 for h, r in seed(self.module, self.cmds, self.guide,
                                  layout=layout).items()}
        files, said = self.module.render_all(results, self.cfg,
                                             self.aircraft, bound)
        for line in said:
            print(line)
        return files

    @typing.override
    def save_needs(self, needs):
        """Where things sit, in the family's own file.

        One per module, because an adapter is built for one: the Hornet
        and the Viper are two aircraft and two layouts. There is no
        needs file beside it -- DCS derives its needs from the module's
        vocabulary on every run, so there is no judgement to keep.
        """
        corneeds.save_assignments(self.here, self.BINDS, needs)
        return (f'wrote where {sum(1 for n in needs if n.assignment)} '
                f'things sit to {self.BINDS}')

    @typing.override
    def offers(self):
        """`a` changes which module the screen is of.

        DCS is the one game that lays out a list that depends on an
        argument: the Hornet's commands are not the Su-25T's, so they are
        different needs, a different store and a different kneeboard.
        That is why the wizard had a menu of its own, and it is one key.
        """
        def pick(_rv, tui):
            found = self.module.discover_aircraft(self.cfg)
            keys = sorted(found, key=lambda k: found[k]['display'].lower())
            got = tui.menu('Which module', [found[k]['display'] for k in keys],
                           index=keys.index(self.aircraft)
                           if self.aircraft in keys else 0)
            if got is None or keys[got] == self.aircraft:
                return 'the same module'
            return type(self)(aircraft=keys[got],
                              backup_dir=self.backup_dir)

        # `t` for the type of aircraft: `a` and `A` are the family's,
        # for browsing the vocabulary, and the screen refuses a key it
        # already answers to rather than letting one shadow the other.
        return [('t', 'type', pick)]

    @typing.override
    def sheet_suffix(self):
        """A kneeboard per module, not per game: the Hornet and the Viper
        are two aircraft and two sheets."""
        return f'-{self.aircraft}'

    @typing.override
    def sheet(self, layout):
        """The kneeboard, in the core's shape, out of the PLAN.

        `mark` is `?` where nobody has confirmed it at the stick, which is
        the one thing this page says that the other five do not: half of
        what is bound by the time you read it is yours and half is the
        planner's. It used to be read out of the wizard's own results file
        -- the plan carries it now, because `Need.assignment` says who
        decided and the store is the family's.
        """
        devs = layout.devices
        sh = csheet.Sheet(
            f'Kneeboard — {self.aircraft}',
            # `#` because the column serves axes as well as buttons; the
            # rows say `BTN12` themselves, which is the number DCS shows.
            f'DCS {self.aircraft}', ident='#',
            devices={r: d.product for r, d in devs.items()})
        sh.note('Button numbers',
                'These are the numbers DCS shows. Each one is higher by '
                'one than the number the device map uses.')
        for p in sorted(layout.on_buttons, key=lambda p: (p.role, p.ctrl.label)):
            mine = p.need.assignment or {}
            mark = '' if (mine.get('how') == corneeds.ACCEPTED
                          and mine.get('control') == p.ctrl.id) else '?'
            for button, payload in sorted(p.slots):
                for b in payload:
                    name = self.cmds[b.action]['name']
                    sh.add(csheet.Row(
                        p.role, p.ctrl.label,
                        part=p.ctrl.direction(button) or '',
                        ident=f'BTN{button + 1}', does=name,
                        bindings={'': name}, mark=mark))
        for p in layout.on_axes:
            a = devs[p.role].axis(p.slots[0][0].index)
            g = devs[p.role].axis_group(a.index)
            sh.add_axis(p.role, g.label if g else a.label,
                        f'axis {a.index}',
                        p.need.what + (' (inverted)' if p.need.invert
                                       else ''))
        for role, ctrl in layout.free:
            sh.add_free(role, ctrl.label)
        # In the list's own order: fly it, take off and land, fight with
        # it, and by name inside each. It used to be ordered by how many
        # of the shipped profiles bound each one, with the count off the
        # page because `5 factory profiles` beside a command name is a
        # number you can do nothing with.
        sh.unplaced_note = 'these are on the list, and nothing here fits'
        for name, kind in unbound(self.module, self.cmds,
                                  self.guide, self.aircraft):
            sh.add_unplaced(name, kind)
        return sh

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--audit', action='store_true',
                            help='List the bindings that no longer match '
                                 'the hardware.')
        parser.add_argument('--check', action='store_true',
                            help='Compare the plan with the results '
                                 'file.')

    @typing.override
    def paths(self, args):
        return [('game', self.cfg.get('game_dir', '(not recorded)')),
                ('results', results_path()),
                ('backups', backup.dir_for('dcs', self.backup_dir))]

    @typing.override
    def extra(self, args, layout):
        if args.audit:
            out = []
            for name, r, why in audit(self.module, self.aircraft,
                                      self.cmds, self.guide):
                where = (f'{r["role"]} BTN{r["index"] + 1}'
                         if r['type'] == 'button'
                         else f'{r["role"]} axis {r["index"]}')
                out.append(f'  {self.aircraft:8s} {name[:44]:46s} '
                           f'{where:16s} {why}')
            out.append(f'\n  {len(out)} binding(s) worth a second look')
            return out
        if args.check:
            # The listing and then the comparison: `--check` has always
            # printed both, because the second only means something next to
            # the first.
            return self.show(layout, why=args.why) + self.check(layout)
        return None

    def check(self, layout):
        """The proposal against what is in the results file."""
        have = json.load(open(results_path()))['aircraft'].get(
            self.aircraft, {})
        mine = written(layout)
        out = ['', '--- against what you bound by hand ---']
        same = diff = 0
        for h, v in have.items():
            if not isinstance(v, dict) or v.get('type') != 'button':
                continue
            if h not in mine:
                continue
            got = (v['role'], v['index'])
            if got == mine[h]:
                same += 1
            else:
                diff += 1
                out.append(f'  {v["name"][:40]:42s} you: {got[0]} '
                           f'{got[1]:<3} proposed: {mine[h][0]} {mine[h][1]}')
        out.append(f'\n  {same} identical, {diff} different, '
                   f'{len(mine)} proposed in total')
        return out

    @typing.override
    def show(self, layout, why=False):
        out, unplaced = rows(layout), layout.unplaced
        placed = [(n, p, s) for n, p, s in out if p]
        lines = [f'{self.aircraft}: {len(placed)} controls proposed, '
                 f'{len(unplaced)} unplaced', '']
        # `rows()` hands back the need and where it went, not the
        # placement, and the account of WHY is on the placement.
        held = {id(p.need): p for p in layout.placed}
        spots = written(layout)
        for need, pair, s in out:
            if need.takes == corneeds.AXIS:
                role, axs = pair if pair else (None, [])
                a = axs[0] if axs else None
                name0 = self.cmds[need.members[0]]['name'].lower()
                if a:
                    where = f'{role} axis {a.index} — {a.label}'
                elif name0 == 'thrust':
                    where = ('left unbound — the two engines are bound '
                             'separately')
                else:
                    where = 'no axis on this hardware'
                lines.append(f'  {need.what[:38]:40s} {where}')
                lines.append('')
                continue
            if pair is None:
                continue
            role, c = pair
            lines.append(f'  {need.what[:38]:40s} {role:8s} {c.kind:9s} '
                         f'{c.label}')
            for h in need.members:
                b = spots.get(h, (None, None))[1]
                w = c.direction(b) if b is not None else '?'
                lines.append(f'      {self.cmds[h]["name"][:46]:48s} '
                             f'-> {str(b):>3s} {w}')
            if why:
                p_ = held.get(id(need))
                bits = (corneeds.why_bits(p_) if p_ is not None
                        else [corneeds.URGENCY_NAME[need.urgency]])
                lines.append(f'      wants {need.shape}'
                             + (f', {need.device}' if need.device else '')
                             + '   ' + '   '.join(bits))
                lines.append(f'      '
                             f'{self.guide[need.members[0]]["place"][:74]}')
                if need.shape == 'latch':
                    # the line above is the module's own advice, and we just
                    # went against it on purpose; say so rather than leave it
                    # looking like the proposal missed it
                    lines.append('      OVERRIDDEN: the module is right that '
                                 'this is a panel switch, but the')
                    lines.append('      trigger lever holds its position the '
                                 'way the real one does, so the')
                    lines.append('      guard position IS the switch '
                                 'position.')
            lines.append('')

        if unplaced:
            lines.append(f'{len(unplaced)} found no control:')
            for n in unplaced:
                lines.append(f'  {n.what[:40]:42s} wanted {n.shape}'
                             + (f' on the {n.device}' if n.device else ''))
        return lines


if __name__ == '__main__':
    sys.exit(adapter.run(Dcs))

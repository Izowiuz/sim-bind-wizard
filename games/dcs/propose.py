#!/usr/bin/env python3
"""propose.py - lay out one DCS module on the HOTAS

DESCRIPTION
    Propose a binding for every command the module ships, from the shape of
    the controls in the device map and the factory profiles' ranking.
    Proposals land in the wizard's results file marked `?` until confirmed.
    --write hands the result to dcs-bind-wizard.py, which owns diff.lua.

FILES
    dcs-bind-wizard.py             the capture TUI and the writer
    dcs-bind-wizard-results.json   the bindings, and where the game is
    sheet-template.html            the kneeboard template
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
    raise SystemExit(f'no shared core at {CORE}\n'
                     'set SIM_BIND_WIZARD to the sim-bind-wizard checkout')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH,             # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)


def wizard():
    """The wizard itself, imported for its harvest -- it is the thing that
    knows how to read a module's commands and profiles."""
    return adapter.from_file('dcswiz',
                             os.path.join(HERE, 'dcs-bind-wizard.py'),
                             argv=['dcs-bind-wizard'])


#: What the module's own prose is asking for. Ordered: first match wins, so
#: the specific phrases sit above the general ones.
SHAPES = [
    (r'keyboard is fine',                       None),
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
    """(shape, device or None, must be reachable in flight)."""
    place = (g.get('place') or '').lower()
    ways = cmd.get('ways') or 0
    if LATCH_COMMANDS.search(cmd['name']):
        # the lever is on the grip, so nothing about reach can disqualify it
        return 'latch', 'stick', 0
    shape = None
    for pattern, s in SHAPES:
        if re.search(pattern, place):
            shape = s
            break
    else:
        shape = 'button'
    # The command's own kind wins over the prose, both ways. "toe brakes. A
    # brake lever on the stick base" is the place for BOTH `Wheel Brake` (an
    # axis) and `Wheel Brake - ON/OFF` (a button), and each wants its own kind
    # of home.
    if shape is not None:
        if cmd['kind'] == 'axis':
            shape = 'axis'
        elif shape == 'axis':
            shape = 'hat2' if (cmd.get('ways') or 0) > 1 else 'button'
    if shape == 'hat4' and 1 < ways <= 2:
        shape = 'hat2'                  # its siblings say it is a 2-way switch
    if shape is None:
        return None, None, False

    where = g.get('where') or ''
    dev = ('stick' if 'STICK' in where else
           'throttle' if 'THROTTLE' in where else None)
    urgency = URGENCY.get(g.get('theme'), 3)
    if GRIP_PROSE.search(place):
        urgency = 0
    # "on the throttle" is where it lives on the real jet, not a claim that you
    # must reach it mid-manoeuvre; only fingers and the grip mean that
    # The prose says where a control sits on the real jet; the theme says
    # whether you touch it with a MiG on your tail. Lights are a fingertip
    # switch on the throttle and still have no business on a thumb hat.
    return shape, dev, urgency


class Need(corneeds.Need):
    """A core need built from a module's own commands rather than by hand.

    `bindings` is the list of DCS command hashes the family covers, which the
    core treats as opaque -- it only ever indexes it. `rank` is how many of the
    factory HOTAS profiles bind the family, so a module bought tomorrow ranks
    itself.

    `on` is deliberately NOT set. The core's `slots_for` wants every direction
    to match or it falls back to press order, while `lay_out` below matches per
    member -- and a four-member family often has only two members whose
    direction the module's prose makes legible. So the core picks the control
    and `lay_out` still decides which button each command lands on.
    """

    def __init__(self, what, shape, members, dev=None, urgency=IN_THE_AIR,
                 rank=0):
        # A slot is a list of Binds now. DCS has no contexts and no
        # release half, so every slot is exactly one -- `members` is the
        # list of command hashes the family covers.
        super().__init__(what, shape,
                         bindings=[[cactions.Bind(h)] for h in members],
                         dev=dev, urgency=urgency, rank=rank)
        #: the hashes, in order, for the places that still think in them:
        #: `lay_out` matches each command against the module's own prose.
        self.members = list(members)
        #: a button assigned outside the allocator: a trigger stage or a
        #: borrowed spare position
        self.borrowed = None


def _drop_combined(members, cmds):
    """A switch family often ships its positions AND a command that does both:
    `- UP`, `- DOWN` and `- UP/DOWN`. Binding the pair makes the combined one
    redundant, and it would eat a third slot on a two-position switch.
    """
    tails = {}
    for h in members:
        name = cmds[h]['name']
        tail = name.rsplit(' - ', 1)[-1] if ' - ' in name else name
        tails[tail.strip().lower()] = h
    drop = set()
    for tail, h in tails.items():
        if '/' in tail:
            parts = [p.strip() for p in tail.split('/')]
            if all(p in tails for p in parts):
                drop.add(h)
    return [h for h in members if h not in drop] or members


def families(cmds, guide, chosen):
    """Group a hat's four commands into one thing to place.

    A four-way hat reaches the wizard as four separate commands; placing them
    one at a time would scatter them across four unrelated buttons.
    """
    groups, singles = collections.OrderedDict(), []
    for h in chosen:
        c = cmds[h]
        fam = c.get('family')
        shape, dev, urgency = wants(c, guide[h])
        if shape is None:
            continue
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
            groups.setdefault(key, {'shape': shape, 'dev': dev,
                                    'urgency': urgency, 'members': [],
                                    'votes': 0})
            g = groups[key]
            g['members'].append(h)
            g['votes'] = max(g['votes'], c['votes'])
        else:
            singles.append((h, shape, dev, urgency, c['votes']))
    for g in groups.values():
        if g['shape'] == 'latch':
            # lay_out() zips leftovers onto bindable_buttons in order, and the
            # latch reports its contacts closed-first. Putting SAFE first lands
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
        members = _drop_combined(g['members'], cmds)
        fam = label_for(fam, members)
        if shape == 'button' and len(members) > 1:
            # a pair of buttons that are one switch wants one switch
            shape = 'hat2' if len(members) == 2 else 'hat4'
        out.append(Need(fam, shape, members, dev=g['dev'],
                        urgency=g['urgency'], rank=g['votes']))
    for h, shape, dev, urgency, votes in singles:
        out.append(Need(cmds[h]['name'], shape, [h], dev=dev,
                        urgency=urgency, rank=votes))
    # most urgent first, and only then by how many factory profiles agree
    out.sort(key=lambda x: (x.urgency, -x.rank))
    return out


AXIS_FOR = {'Pitch': 'stick-y', 'Roll': 'stick-x', 'Rudder': 'twist',
            'Thrust': 'throttle-lever'}

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

#: Starting a cold aircraft needs controls no factory profile bothers to bind,
#: because a profile is written for a jet that is already running. They sit
#: below the vote floor and would never reach the essentials on their own.
#: Commands worth placing that no factory profile votes for, so the ranking
#: never surfaces them. Cold-start switches, because a profile author assumes
#: you start hot -- and master arm, because it is a cockpit switch in every
#: profile and a HOTAS switch on this hardware.
COLD_START = [
    r'throttle \((left|right)\).*off\(hold\)',
    r'engine crank switch - (left|right)$',
    r'apu control sw',
    r'master arm switch - (arm|safe)$',
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


def lay_out(module, ctrl, members, cmds, press_only=False, borrowed=None):
    """hash -> button, respecting which way each one points."""
    if borrowed is not None and len(members) == 1:
        return {members[0]: borrowed}
    if press_only and ctrl.push is not None and len(members) == 1:
        return {members[0]: ctrl.push}
    out, left = {}, []
    used = set()
    dirs = list(ctrl.dirs or ctrl.stages or ctrl.positions or [])
    for h in members:
        c = cmds[h]
        want = None
        if ctrl.kind == 'trigger':
            i = stage_of(c)
            if i is not None and i < len(ctrl.buttons):
                want = ctrl.buttons[i]
        else:
            d = direction_of(module, c)
            if d == 'push' and ctrl.push is not None:
                want = ctrl.push
            elif d and d in dirs:
                want = ctrl.buttons[dirs.index(d)]
        if want is not None and want not in used:
            out[h] = want
            used.add(want)
        else:
            left.append(h)
    spare = [b for b in ctrl.bindable_buttons if b not in used]
    for h, b in zip(left, spare):
        out[h] = b
    return out


def resolve_axis(devs, need, cmds):
    """Which axis on which device a flight or slew command belongs to."""
    name = cmds[need.members[0]]['name']
    want = AXIS_FOR.get(name.split(' - ')[0].strip())
    if want == 'stick-x':
        return ('stick', devs['stick'].axes(kind='stick-x'))
    if want == 'stick-y':
        return ('stick', devs['stick'].axes(kind='stick-y'))
    if want == 'twist':
        return ('stick', devs['stick'].axes(kind='twist'))
    low = name.lower()
    # Two levers, two engines. A cold start in the Hornet runs them up one at a
    # time, so the combined Thrust axis is not enough -- and binding it as well
    # would have both fighting for the same engines.
    if low.startswith('thrust'):
        levers = devs['throttle'].axes(kind='lever')
        side = ('right' if 'right' in low else
                'left' if 'left' in low else None)
        if side:
            match = [a for a in levers if side in (a.label or '').lower()]
            return ('throttle', match or levers[:1])
        return ('throttle', [])          # combined: superseded by the pair
    if want == 'throttle-lever':
        return ('throttle', [a for a in devs['throttle'].axes(kind='lever')
                             if 'left' in (a.label or '').lower()])
    if 'designator' in low or 'slew' in low:
        # the clue is in the name: it hangs off the throttle
        g = next(iter(devs['throttle'].groups('ministick')), None)
        if g and len(g.axes) == 2:
            i = 1 if re.search(r'vert', low) else 0
            return ('throttle', [devs['throttle'].axis(g.axes[i])])
    if 'brake' in low:
        return ('stick', [a for a in devs['stick'].axes()
                          if a.safe_for_absolute])
    if 'zoom' in low:
        return ('throttle', [a for a in devs['throttle'].axes(kind='dial')])
    # a warbird flies on three levers: throttle, propeller RPM, mixture
    if re.search(r'\brpm\b|prop(eller)? pitch|mixture|supercharger', low):
        spare = [a for a in devs['throttle'].axes()
                 if a.kind in ('lever', 'slider', 'dial')
                 and 'throttle lever' not in (a.label or '').lower()]
        # steadiest first: something that stays where you leave it
        spare.sort(key=lambda a: (a.kind != 'lever', a.index))
        return ('throttle', spare[:1])
    return (None, [])


#: WHEN you touch a command, from the module's own theme. This is the thing
#: that decides how good a home it deserves -- and the wizard already works it
#: out. The first version read the word "finger" out of a sentence describing
#: where a switch sits on the real jet, which is a different question, and
#: every fix to it moved the symptom somewhere else.

#: This module's six themes onto the core's four urgencies. The scale is the
#: core's; only the mapping is DCS's.
URGENCY = {'fight': IN_A_TURN, 'fly': IN_A_TURN,
           'land': ON_APPROACH,
           'sensors': IN_THE_AIR,
           'cockpit': ON_THE_RAMP, 'other': ON_THE_RAMP}


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


#: When the module says a command sits ON THE GRIP, the aircraft's own
#: designers already answered this question -- your hand is there anyway. That
#: beats the theme, which only says when you touch it.
#:
#: Deliberately narrow: "a fingertip switch on the throttle" describes the
#: throttle body, not the grip, and exterior lights have no business on a thumb
#: hat however fingertip-operated they are.
GRIP_PROSE = re.compile(
    r'on the grip|under your thumb|front of the grip|top of the grip'
    r'|behind the grip|the grip in the real jet', re.I)


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
        sys.exit('pass --game-dir, or run the wizard once so it remembers')
    return cfg


def candidates(module, cmds, guide):
    """The commands worth placing: the module's own essentials, plus the few
    a cold start needs that no factory profile bothers to bind."""
    chosen = [h for _t, items in module.essentials(cmds, guide)
              for h, _n, _k in items]
    for h, c in cmds.items():
        if h in chosen:
            continue
        if any(re.search(p, c['name'], re.I) for p in COLD_START):
            chosen.append(h)
    return chosen


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


def place(module, cmds, guide, chosen, rules=None):
    """-> core.needs.Layout.

    The matching is `core.needs.allocate`. What stays here is what the core
    cannot know: which commands form one family, which of them wants an axis,
    and that a trigger's stages are separately named.

    It used to return `[(need, spot, score)], unplaced` -- a fourth shape of
    the same five values, which is the drift `core.needs.Layout` exists to
    stop. The axis entries go in `Layout.axes`, which is game-shaped by
    contract; the free list, which this threw away, is kept, and that is
    where `--free` comes from.
    """
    devs = devmap.by_role('stick', 'throttle')
    needs = families(cmds, guide, chosen)
    claims, axes = [], []

    # A trigger has stages and more than one command wants it: on the Su-25T
    # the cannon and the selected weapon both belong there, lighter pull first.
    # Letting the first comer take the whole control put the jet's main fire
    # command on a hat direction. The core has no notion of a stage named in a
    # command ("Gun Trigger - SECOND DETENT"), so this is settled first and the
    # control is then vetoed for everybody else.
    claimed = None
    trigger_needs = [n for n in needs if n.shape == 'trigger'
                     and len(n.members) == 1]
    if len(trigger_needs) > 1:
        spot = next(((r, c) for r, d in sorted(devs.items())
                     for c in d.groups(bindable=True)
                     if c.kind == 'trigger'), None)
        if spot:
            role, ctrl = spot
            claimed = ctrl
            free = list(ctrl.buttons)
            named, rest = {}, []
            for n in trigger_needs:
                st = stage_of(cmds[n.members[0]])
                if st is not None and st < len(free) and free[st] not in named:
                    named[free[st]] = n
                else:
                    rest.append(n)
            rest.sort(key=lambda n: -n.rank)
            for n in rest:
                spare = [b for b in free if b not in named]
                if not spare:
                    break
                named[spare[0]] = n
            for b, n in named.items():
                n.borrowed = b
                claims.append(corneeds.Placement(
                    n, role, ctrl,
                    [(b, [cactions.Bind(n.members[0])])], 200,
                    corneeds.Reason('claimed', points=200)))
                needs.remove(n)

    # Axes never go through the allocator, in any game in the family.
    buttons = []
    for need in needs:
        if need.shape == 'axis':
            axes.append((need, resolve_axis(devs, need, cmds)))
        else:
            buttons.append(need)

    placed, still, free = corneeds.allocate(
        buttons, devs, rules=rules or _rules(),
        usable=(lambda r, c: c is not claimed) if claimed else None)

    for pl in placed:
        # `lay_out` still decides which button each command of a family lands
        # on, because it reads directions out of the module's own prose. But
        # where a need has ONE command the core already chose the button --
        # the control's click, or a spare position it borrowed -- and that
        # choice is the authoritative one.
        if len(pl.need.members) == 1 and pl.slots:
            pl.need.borrowed = pl.slots[0][0]
    return corneeds.Layout(devs, claims + list(placed), still, free,
                           axes=axes)


def rows(layout):
    """[(need, spot, score)] -- the shape the listing and --check read.

    The order is the one `place()` appended in before it returned a Layout,
    and the one the listing has always printed: the trigger claims, then the
    axes, then whatever the allocator placed.

    A claim used to be recognised by scoring exactly 200 -- a number chosen
    to carry a meaning, which is a number nobody can change and one the
    allocator could hit honestly. It now says what it is: `place()` writes
    `Reason('claimed')` at the moment it claims.
    """
    def claimed(p):
        return p.why is not None and p.why.how == 'claimed'

    claims = [p for p in layout.placed if claimed(p)]
    rest = [p for p in layout.placed if not claimed(p)]
    return ([(p.need, (p.role, p.ctrl), p.points) for p in claims]
            + [(n, spot, None) for n, spot in layout.axes]
            + [(p.need, (p.role, p.ctrl), p.points) for p in rest])


def propose(module, key, game_dir=None):
    cfg = load_cfg(module, game_dir)
    ac = module.discover_aircraft(cfg)
    if key not in ac:
        sys.exit(f'no such module: {key} (have {", ".join(ac)})')
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
    out = rows(layout)
    recs = {}
    for need, pair, _s in out:
        if not pair:
            continue
        role, what = pair
        if need.shape == 'axis':
            axes = what
            if not axes:
                continue
            name = cmds[need.members[0]]['name']
            recs[need.members[0]] = {
                'name': name, 'role': role, 'type': 'axis',
                'index': axes[0].index, 'invert': _inverted(name),
                'proposed': True}
            continue
        ctrl = what
        spots = lay_out(module, ctrl, need.members, cmds,
                        press_only=len(need.members) == 1
                        and len(ctrl.bindable_buttons) > 1,
                        borrowed=need.borrowed)
        for h, b in spots.items():
            recs[h] = {'name': cmds[h]['name'], 'role': role,
                       'type': 'button', 'index': b, 'proposed': True}
    return recs


def _inverted(name):
    """Pitch wants inverting everywhere: stick back is nose up."""
    return name.split(' - ')[0].strip() == 'Pitch'


#: byte for byte what core/sheet.py has; this sheet still renders itself,
#: because the core template has no `?` for a proposal and no vote-ordered
#: "still unbound" panel.
_esc = csheet.esc


#: Panel order on the sheet. Anything the map has that is not named here
#: follows, alphabetically -- so a captured third device appears rather than
#: raising KeyError, and the stick still comes first.
ROLE_ORDER = ('stick', 'throttle')


def panel_roles(rows):
    known = [r for r in ROLE_ORDER if r in rows]
    return known + sorted(r for r in rows
                          if r != 'axes' and r not in ROLE_ORDER)


def bound_rows(module, key, cmds, guide):
    """What is actually bound, joined with what the hardware map calls it.

    The results file is the source of truth, not the proposal: half of it is
    yours by the time you read a sheet.
    """
    binds = json.load(open(results_path()))['aircraft'].get(key, {})
    devs = devmap.by_role('stick', 'throttle')
    # Keyed off the devices the map actually gave us, not a literal pair: a
    # captured third device -- pedals, a button box -- used to raise KeyError
    # here rather than show up on the sheet.
    rows = {role: [] for role in devs}
    rows['axes'] = []
    for h, r in binds.items():
        if not isinstance(r, dict) or 'role' not in r:
            continue
        d = devs.get(r['role'])
        theme = (guide.get(h) or {}).get('theme', '')
        mark = '?' if r.get('proposed') else ''
        if r['type'] == 'axis':
            a = d.axis(r['index']) if d else None
            g = d.axis_group(r['index']) if d else None
            label = (g.label if g else (a.label if a else f'axis {r["index"]}'))
            rows['axes'].append((r['role'], r['index'], label, r['name'],
                                 ' (inverted)' if r.get('invert') else '', mark))
            continue
        g = d.group_of(r['index']) if d else None
        part = g.direction(r['index']) if g else ''
        label = g.label if g else f'button {r["index"]}'
        rows.setdefault(r['role'], []).append(
            (r['index'], label, part, r['name'], theme, mark))
    for k in rows:
        rows[k].sort()
    return rows, devs


def unbound(module, cmds, guide, key):
    binds = json.load(open(results_path()))['aircraft'].get(key, {})
    out = []
    for _t, items in module.essentials(cmds, guide):
        for h, name, kind in items:
            if h not in binds:
                out.append((name, kind, cmds[h]['votes']))
    out.sort(key=lambda x: -x[2])
    return out


def write_sheet(module, key, cmds, guide, path):
    rows, devs = bound_rows(module, key, cmds, guide)
    L = [f'# Kneeboard — {key}', '',
         'What sits under which finger. Button numbers are the ones DCS shows,',
         'one higher than the OS number the device map uses.', '',
         '**Generated** by `./propose.py -a %s --sheet` from the results file'
         % key,
         'and `sim-device-map`. A `?` is proposed and not yet confirmed.', '']
    for role in panel_roles(rows):
        d = devs.get(role)
        if not rows[role]:
            continue
        L += [f'## {d.product if d else role}', '',
              '| Control | DCS | Command |', '|---|---|---|']
        for idx, label, part, name, theme, mark in rows[role]:
            what = label + (f' — {part}' if part else '')
            L.append(f'| {what} | `BTN{idx + 1}` | {name}'
                     f'{" ?" if mark else ""} |')
        L.append('')
    if rows['axes']:
        L += ['## Axes', '', '| Control | Axis | Command |', '|---|---|---|']
        for role, idx, label, name, inv, mark in rows['axes']:
            L.append(f'| {label} | `{role} {idx}` | {name}{inv}'
                     f'{" ?" if mark else ""} |')
        L.append('')
    left = unbound(module, cmds, guide, key)
    if left:
        L += ['## Still unbound', '',
              'Essentials with no control yet, most-wanted first.', '']
        for name, kind, votes in left:
            L.append(f'- {name} — {kind}, {votes} factory profiles')
        L.append('')
    open(path, 'w', encoding='utf-8').write('\n'.join(L))
    return path, sum(len(rows[k]) for k in rows)


def write_html(module, key, cmds, guide, path):
    import datetime
    rows, devs = bound_rows(module, key, cmds, guide)

    def panel(role):
        d = devs.get(role)
        body = []
        for idx, label, part, name, theme, mark in rows[role]:
            what = _esc(label) + (f' <em>{_esc(part)}</em>' if part else '')
            unsure = ' <em>?</em>' if mark else ''
            body.append(f'<tr><td class="c">{what}</td>'
                        f'<td class="n">{idx + 1}</td>'
                        f'<td>{_esc(name)}{unsure}</td></tr>')
        return (f'<div class="panel"><h2>{_esc(d.product if d else role)}'
                f'<small>DCS button numbers</small></h2><table>'
                f'<tr><th>Control</th><th>BTN</th><th class="a">Command</th>'
                f'</tr>' + ''.join(body) + '</table></div>')

    arows = ''.join(
        f'<tr><td class="c">{_esc(label)}</td>'
        f'<td class="n">{_esc(role[:3])} {idx}</td>'
        f'<td>{_esc(name)}{_esc(inv)}{" <em>?</em>" if mark else ""}</td></tr>'
        for role, idx, label, name, inv, mark in rows['axes'])
    axes_panel = ('<div class="panel"><h2>Axes</h2><table><tr><th>Control</th>'
                  '<th>#</th><th class="a">Command</th></tr>'
                  + arows + '</table></div>')

    left = unbound(module, cmds, guide, key)
    urows = ''.join(
        f'<tr><td class="c">{_esc(n)}</td><td class="n">{v}</td>'
        f'<td class="h">{_esc(k)}</td></tr>' for n, k, v in left[:18])
    unbound_panel = ('<div class="panel"><h2>Still unbound<small>most-wanted'
                     ' first</small></h2><table><tr><th>Command</th>'
                     '<th>Profiles</th><th>Kind</th></tr>'
                     + (urows or '<tr><td colspan="3">nothing</td></tr>')
                     + '</table></div>')

    tpl = open(os.path.join(HERE, 'sheet-template.html'), encoding='utf-8').read()
    n = sum(len(rows[k]) for k in rows)
    out = (tpl.replace('__MODULE__', _esc(key))
              .replace('__PANELS__', ''.join(
                  panel(r) for r in panel_roles(rows)))
              .replace('__AXES__', axes_panel)
              .replace('__UNBOUND__', unbound_panel)
              .replace('__STAMP__', f'generated {datetime.date.today()} '
                                    f'· {n} bindings'))
    open(path, 'w', encoding='utf-8').write(out)
    return path, n


def reseed(module, key, cmds, guide, backup_dir=None, when=None):
    """Throw an aircraft's bindings away and lay it out fresh.

    A results file that has been through several device configurations and two
    generations of this matcher is sediment: an old capture numbered against
    hardware that has since been reconfigured, a combined Thrust axis left
    beside the split pair that replaced it, an inversion nobody meant. Patching
    those one at a time is slower and less certain than starting over, because
    everything the proposal knows is now better than what is there.

    Everything comes out marked `proposed`, so the wizard still asks you to
    confirm it -- this replaces the guesses, not your judgement.
    """
    path = results_path()
    data = json.load(open(path))
    # One folder for the whole --reseed, however many aircraft it walks: the
    # results file is rewritten once per aircraft, and a copy per rewrite would
    # be six backups of six intermediate states of the same run.
    dest, _ = backup.save('dcs', path, into=backup_dir, when=when)

    before = len(data['aircraft'].get(key, {}))
    recs = seed(module, cmds, guide)
    data.setdefault('aircraft', {})[key] = recs
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    return dest, before, len(recs)


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
            shape, _dev, _urg = wants(cmds[h], guide.get(h, {}))
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

    def render_all(self, results: dict, cfg: dict,
                   aircraft: str) -> tuple[dict, list[str]]: ...


@typing.final
class Dcs(adapter.Proposer):
    """DCS World, one module at a time.

    A `Proposer` rather than a `Planner` because its writer reads the capture
    wizard's results file: a binding somebody confirmed at the stick is better
    evidence than one this proposed, and the review screen the other five use
    is the wizard itself.

    It is also why the adapters had to become classes. The needs here are
    derived from the module's own command vocabulary, so they are a function
    of `--aircraft`; `NEEDS` as a module constant could never mean both the
    Hornet's and the Su-25T's, which is why `propose.py` had neither `NEEDS`
    nor `build()` until now.
    """

    game = 'dcs'
    title = 'DCS World'
    CATALOGUE = 'dcs-actions.json'
    CACHE = {'dcs-actions.json': 'aircraft'}
    #: `-a` is what this has always been typed as, and `./bind dcs plan
    #: -a su-25T` is in the top-level README.
    ALIASES = {'aircraft': ('-a',)}

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
                raise SystemExit(f'no such module: {self.aircraft} '
                                 f'(have {", ".join(sorted(ac))})')
            cmds = self.module.harvest_commands(
                self.cfg, self.aircraft, ac[self.aircraft]['factory_dir'])
            got = {'commands': cmds, 'guide': self.module.build_guide(cmds)}
        self.cmds, self.guide = got['commands'], got['guide']
        self._needs = families(self.cmds, self.guide,
                               candidates(self.module, self.cmds, self.guide))

    @property
    @typing.override
    def NEEDS(self):
        """Derived from this module's own commands, so it is a property."""
        return self._needs

    @typing.override
    def build(self):
        return place(self.module, self.cmds, self.guide,
                     candidates(self.module, self.cmds, self.guide))

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
    def seed(self, layout):
        path = results_path()
        data = json.load(open(path))
        # The layout, not a fresh one. Five games hand `write_layout`
        # whatever the reviewer accepted and `Layout.but()` exists to make
        # it; this used to take the same argument and throw it away, so
        # anything cleared on the screen came straight back.
        data.setdefault('aircraft', {})[self.aircraft] = seed(
            self.module, self.cmds, self.guide, layout=layout)
        return {path: json.dumps(data, indent=2)}

    @typing.override
    def write_game(self):
        results = json.load(open(results_path()))
        files, said = self.module.render_all(results, self.cfg, self.aircraft)
        for line in said:
            print(line)
        return files

    @typing.override
    def write_sheets(self, layout, markdown=None, html=None):
        """DCS renders from its own template, not the core's.

        Its placeholders are per-device (`__STICK__`, `__THROTTLE__`) where
        the core's are `__PANELS__`, and the core sheet has no `?` for a
        proposal -- see ARCHITECTURE.md.
        """
        out = []
        if markdown is not None:
            path = markdown or os.path.join(
                HERE, f'KNEEBOARD-{self.aircraft}.md')
            pth, n = write_sheet(self.module, self.aircraft, self.cmds,
                                 self.guide, path)
            out.append(f'wrote {pth}: {n} bindings')
        if html is not None:
            path = html or os.path.join(
                HERE, f'kneeboard-{self.aircraft}.html')
            pth, n = write_html(self.module, self.aircraft, self.cmds,
                                self.guide, path)
            out.append(f'wrote {pth}: {n} bindings')
        for line in out:
            print(line)
        return out

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--reseed', action='store_true',
                            help="discard this module's bindings and lay it "
                                 'out fresh')
        parser.add_argument('--audit', action='store_true',
                            help='list bindings that no longer match the '
                                 'hardware')
        parser.add_argument('--check', action='store_true',
                            help='compare against the results file')

    @typing.override
    def paths(self, args):
        return [('game', self.cfg.get('game_dir', '(not recorded)')),
                ('results', results_path()),
                ('backups', backup.dir_for('dcs', self.backup_dir))]

    @typing.override
    def extra(self, args, layout):
        if args.reseed:
            return self.write_seed(layout) + [
                '  open the wizard and walk the list: c confirms one, '
                'C the section']
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
        mine = {}
        for need, pair, _ in rows(layout):
            if not pair or need.shape == 'axis':
                continue                 # (role, [axis]) has no buttons
            role, c = pair
            for h, b in lay_out(self.module, c, need.members, self.cmds,
                                press_only=len(need.members) == 1
                                and len(c.bindable_buttons) > 1).items():
                mine[h] = (role, b)
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
        for need, pair, s in out:
            if need.shape == 'axis':
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
            spots = lay_out(self.module, c, need.members, self.cmds,
                            press_only=len(need.members) == 1
                            and len(c.bindable_buttons) > 1,
                            borrowed=need.borrowed)
            for h in need.members:
                b = spots.get(h)
                w = c.direction(b) if b is not None else '?'
                lines.append(f'      {self.cmds[h]["name"][:46]:48s} '
                             f'-> {str(b):>3s} {w}')
            if why:
                p_ = held.get(id(need))
                bits = (corneeds.why_bits(p_) if p_ is not None
                        else [corneeds.URGENCY_NAME[need.urgency]])
                lines.append(f'      wants {need.shape}'
                             + (f', {need.dev}' if need.dev else '')
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
                             + (f' on the {n.dev}' if n.dev else ''))
        return lines


if __name__ == '__main__':
    sys.exit(adapter.run(Dcs))

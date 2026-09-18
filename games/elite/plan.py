#!/usr/bin/env python3
"""Lay out Elite Dangerous on the VIRPIL HOTAS and write a .binds preset.

    ./plan.py                 the layout
    ./plan.py --why           and the evidence for each choice
    ./plan.py --free          what stays unbound
    ./plan.py --sheet --html  the kneeboard
    ./plan.py --write         into the game's Bindings folder

harvest.py supplies the vocabulary and the ranking; sim-device-map supplies
the shape of every control; `core.needs.allocate` does the matching. The
writing is `ed-bind-wizard.py`'s own `generate()` -- the layout is handed to it
in the shape its capture TUI produces, so there is one writer and not two.

The two work on different presets by default. The TUI owns whatever you
captured by hand; the plan writes `Izowiuz-PLAN`, so neither overwrites the
other and both can be selected in the game to compare.
"""

import argparse
import collections
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'no shared core at {CORE}\n'
                     'set SIM_BIND_WIZARD to the sim-bind-wizard checkout')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH,             # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)

_spec = importlib.util.spec_from_file_location(
    'edharvest', os.path.join(HERE, 'harvest.py'))
harvest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harvest)

VOCAB = vocab.load(HERE, 'ed-actions.json', key='vocabulary',
                   build=harvest.vocabulary)
RANK = vocab.load(HERE, 'ed-rank.json', key='ranking',
                  build=harvest.ranking)

AXES = set(VOCAB.get('axis', ()))


def vouched():
    """Every function there is evidence the game accepts.

    The shipped presets are not the whole list: `NightVisionToggle` is a real
    ship function, written into a preset and working in game, and it appears in
    none of the thirty. A function bound by hand in the results file has been
    verified against the game itself, which is better evidence than a preset,
    so it counts too.
    """
    out = set(VOCAB.get('button', ())) | AXES
    try:
        import json
        saved = json.load(open(os.path.join(
            HERE, 'ed-bind-wizard-results.json')))
    except OSError:
        return out
    return out | {k for k, v in saved.items()
                  if not k.startswith('_') and v is not None}

#: The preset the plan owns. The game picks a preset in its own control
#: options and records the choice in StartPreset.4.start, which nothing here
#: writes -- so a freshly written preset is selected once, by hand.
PRESET = os.environ.get('ED_PRESET', 'Izowiuz-PLAN')


def wizard():
    """The capture TUI, imported for its writer and its device resolution."""
    spec = importlib.util.spec_from_file_location(
        'edwiz', os.path.join(HERE, 'ed-bind-wizard.py'))
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ['ed-bind-wizard']
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    finally:
        sys.argv = argv
    return mod


def votes(*functions):
    """How many of the shipped HOTAS presets bind any of these."""
    return max((RANK.get(f, {}).get('votes', 0) for f in functions),
               default=0)


#: Elite names an SRV function with a `_Buggy` suffix OR a `Buggy` prefix, and
#: a function with no twin in either form answers in both. This is War
#: Thunder's rule exactly, down to the trap: checking only the suffix made
#: `PitchAxisRaw` look shared when its twin is `BuggyPitchAxis`.
def srv_twin(function):
    """The SRV form of a ship function, if the game has one."""
    allf = vouched()
    for candidate in (f'{function}_Buggy', f'Buggy{function}'):
        if candidate in allf:
            return candidate
    return None


class Need(corneeds.Need):
    """A need whose payload is one function name per context.

    Elite scopes a binding by which function it is, so one control carries the
    ship's meaning and the SRV's without them clashing -- the same shape War
    Thunder's air/heli pair and MSFS's plane/heli/global triple have.
    """

    def __init__(self, what, shape, ship=(), srv=(), push=None, suits=None,
                 urgency=IN_THE_AIR, device=None, prefer=None, on=None,
                 note=''):
        self.ship, self.srv = list(ship), list(srv)
        n = max(len(self.ship), len(self.srv))

        def pad(xs):
            return list(xs) + [None] * (n - len(xs))

        flat = [f for f in self.ship + self.srv if f]
        super().__init__(what, shape,
                         bindings=list(zip(pad(self.ship), pad(self.srv))),
                         push=push, urgency=urgency, suits=suits, dev=device,
                         prefer=prefer, on=on, rank=votes(*flat), note=note)

    @property
    def device(self):
        return self.dev


def twinned(*ship):
    """The SRV forms of these ship functions, positionally, None where absent.

    Written out rather than inlined so a need says what it means: a pair that
    reads `srv=twinned(...)` is claiming the game has a twin, and an absent
    one shows up as a None rather than as a typo nobody notices.
    """
    return [srv_twin(f) if f else None for f in ship]


# --------------------------------------------------------------- the layout --

#: (function, context, role, how to find the axis in the map, invert)
#:
#: The context is declared rather than read off the name. Elite's SRV
#: functions mostly carry `Buggy`, but not all of them: `SteeringAxis`,
#: `DriveSpeedAxis` and `ToggleDriveAssist` are SRV-only and say nothing about
#: it, so guessing from the name reported them as clashing with the ship's
#: roll, throttle and flight assist on the same control -- which is exactly
#: what sharing a control between contexts is FOR.
AXIS_NEEDS = [
    ('RollAxisRaw',       'Ship', 'stick',    ('kind', 'stick-x'),      False),
    ('PitchAxisRaw',      'Ship', 'stick',    ('kind', 'stick-y'),      True),
    ('YawAxisRaw',        'Ship', 'stick',    ('kind', 'twist'),        False),
    ('ThrottleAxis',      'Ship', 'throttle',
     ('label', 'Left throttle lever'), False),
    ('LateralThrustRaw',  'Ship', 'throttle', ('kind', 'mini-stick-x'), False),
    ('VerticalThrustRaw', 'Ship', 'throttle', ('kind', 'mini-stick-y'), False),
    ('BuggyRollAxisRaw',  'SRV',  'stick',    ('kind', 'stick-x'),      False),
    ('BuggyPitchAxis',    'SRV',  'stick',    ('kind', 'stick-y'),      True),
    ('SteeringAxis',      'SRV',  'stick',    ('kind', 'stick-x'),      False),
    ('DriveSpeedAxis',    'SRV',  'throttle',
     ('label', 'Left throttle lever'), False),
    ('CamTranslateXAxis', 'Ship', 'stick',    ('kind', 'mini-stick-x'), False),
    ('CamTranslateYAxis', 'Ship', 'stick',    ('kind', 'mini-stick-y'), False),
]

NEEDS = [
    # --- with something shooting at you
    Need('Primary fire', 'trigger', ship=['PrimaryFire'],
         srv=['BuggyPrimaryFireButton'], suits='fire', urgency=IN_A_TURN,
         device='stick', note='13/13 factory presets, all of them on the stick'),

    Need('Secondary fire', 'button', ship=['SecondaryFire'],
         srv=['BuggySecondaryFireButton'], suits='fire', urgency=IN_A_TURN,
         device='stick'),

    Need('Boost', 'button', ship=['UseBoostJuice'],
         urgency=IN_A_TURN, device='throttle',
         note='13/13, and every split preset puts it on the throttle'),

    Need('Select target', 'button', ship=['SelectTarget'],
         srv=twinned('SelectTarget'), suits='lock', urgency=IN_A_TURN,
         device='stick'),

    Need('Next hostile', 'button', ship=['CycleNextHostileTarget'],
         suits='lock', urgency=IN_A_TURN, device='stick'),

    Need('Highest threat', 'button', ship=['SelectHighestThreat'],
         suits='lock', urgency=IN_A_TURN, device='stick'),

    Need('Power distribution', 'hat4',
         ship=['IncreaseSystemsPower', 'IncreaseWeaponsPower',
               'ResetPowerDistribution', 'IncreaseEnginesPower'],
         srv=twinned('IncreaseSystemsPower', 'IncreaseWeaponsPower',
                     'ResetPowerDistribution', 'IncreaseEnginesPower'),
         on=('up', 'right', 'down', 'left'),
         urgency=IN_A_TURN, device='stick',
         note='four functions at 13/13; pips are the whole of ED combat'),

    Need('Fire group', 'hat2',
         ship=['CycleFireGroupNext', 'CycleFireGroupPrevious'],
         on=('forward', 'back'), urgency=IN_A_TURN, device='stick'),

    Need('Hardpoints', 'button', ship=['DeployHardpointToggle'],
         urgency=IN_A_TURN, device='stick'),

    Need('Chaff', 'button', ship=['FireChaffLauncher'],
         urgency=IN_A_TURN, device='throttle'),

    Need('Heat sink', 'button', ship=['DeployHeatSink'],
         urgency=IN_A_TURN, device='throttle'),

    Need('Shield cell', 'button', ship=['UseShieldCell'],
         urgency=IN_A_TURN, device='throttle'),

    # --- hands busy, but there is time
    Need('Landing gear', 'button', ship=['LandingGearToggle'],
         suits='toggle', urgency=ON_APPROACH, device='throttle',
         note='a toggle, so one button: ED has no separate up and down. '
              '9/13, four of five split presets on the throttle'),

    Need('Cargo scoop', 'button', ship=['ToggleCargoScoop'],
         srv=twinned('ToggleCargoScoop'), urgency=ON_APPROACH,
         device='throttle'),

    Need('Flight assist', 'button', ship=['ToggleFlightAssist'],
         srv=['ToggleDriveAssist'], urgency=ON_APPROACH, device='throttle'),

    Need('Speed zero', 'button', ship=['SetSpeedZero'],
         urgency=ON_APPROACH, device='throttle'),

    Need('Reverse throttle', 'button', ship=['ToggleReverseThrottleInput'],
         srv=['BuggyToggleReverseThrottleInput'], urgency=ON_APPROACH,
         device='throttle'),

    Need('Frame shift', 'button', ship=['HyperSuperCombination'],
         urgency=ON_APPROACH, device='throttle',
         note='supercruise and hyperspace on one button, as the game intends'),

    # --- somewhere in the cruise
    Need('Subsystem', 'hat2',
         ship=['CycleNextSubsystem', 'CyclePreviousSubsystem'],
         on=('forward', 'back'), suits='sensor', urgency=IN_THE_AIR,
         device='stick'),

    Need('Target', 'hat2',
         ship=['CycleNextTarget', 'CyclePreviousTarget'],
         on=('right', 'left'), suits='lock', urgency=IN_THE_AIR,
         device='stick'),

    Need('Radar range', 'hat2',
         ship=['RadarIncreaseRange', 'RadarDecreaseRange'],
         on=('forward', 'back'), suits='sensor', urgency=IN_THE_AIR,
         device='throttle'),

    Need('Head look', 'ministick', ship=[], suits='view',
         urgency=IN_THE_AIR, device='throttle',
         note='binds nothing: it reserves the mini-stick, which the axes '
              'below take, so no button need can claim it'),

    Need('Head look reset', 'button', ship=['HeadLookReset'],
         suits='view', urgency=IN_THE_AIR, device='throttle'),

    Need('Discovery scan', 'button', ship=['ExplorationFSSDiscoveryScan'],
         urgency=IN_THE_AIR, device='throttle', note='13/13'),

    Need('Night vision', 'button', ship=['NightVisionToggle'],
         srv=twinned('NightVisionToggle'), urgency=IN_THE_AIR),

    Need('Spotlight', 'button', ship=['ShipSpotLightToggle'],
         srv=['HeadlightsBuggyButton'], urgency=IN_THE_AIR),

    # What the factory presets actually put on hardware is the panel CYCLE,
    # 13/13 and every split preset on the throttle -- not the four Focus*
    # functions, which are 5/13 and were left on the keyboard by hand. Cycling
    # reaches all four panels from two buttons.
    Need('Panel', 'hat2',
         ship=['CycleNextPanel', 'CyclePreviousPanel'],
         on=('forward', 'back'), urgency=IN_THE_AIR, device='throttle',
         note='13/13, every split preset on the throttle'),

    Need('Panel page', 'hat2',
         ship=['CycleNextPage', 'CyclePreviousPage'],
         on=('right', 'left'), urgency=IN_THE_AIR, device='throttle'),

    # --- canopy open, engine off
    Need('Galaxy map', 'button', ship=['GalaxyMapOpen'],
         srv=twinned('GalaxyMapOpen'), urgency=ON_THE_RAMP),

    Need('System map', 'button', ship=['SystemMapOpen'],
         srv=twinned('SystemMapOpen'), urgency=ON_THE_RAMP),

    # Pinned deliberately. It is destructive and the borrow pass does not
    # honour the reach FLOOR, so left to itself it took a thumb hat direction.
    Need('Eject cargo', 'button', ship=['EjectAllCargo'],
         srv=twinned('EjectAllCargo'), urgency=ON_THE_RAMP,
         prefer='Big red button',
         note='pinned away from the hand: it throws the cargo out'),
]


def unknown():
    """Functions named in NEEDS or AXIS_NEEDS that the game will not accept.

    The vocabulary comes out of the game's own base preset, so a typo or a
    function a patch renamed is an error here rather than a binding that
    silently does nothing.
    """
    allf = vouched()
    bad = []
    for n in NEEDS:
        for slot in n.bindings:
            for f in slot:
                if f and f not in allf:
                    bad.append((n.what, f))
        if n.push and n.push not in allf:
            bad.append((n.what, n.push))
    for f, _ctx, _role, _how, _inv in AXIS_NEEDS:
        if f not in AXES:
            bad.append(('axis', f))
    return bad


def duplicates():
    """Functions named by more than one need.

    Elite has one element per function, so two needs claiming one function
    means the second silently wins whatever the sheet says.
    """
    seen = collections.Counter()
    for n in NEEDS:
        for slot in n.bindings:
            for f in slot:
                if f:
                    seen[f] += 1
    axis = collections.Counter(f for f, *_ in AXIS_NEEDS)
    return ([f for f, c in seen.items() if c > 1]
            + [f for f, c in axis.items() if c > 1])


# ------------------------------------------------------------ the hardware --

def axis_of(devs, role, how):
    kind, value = how
    for a in devs[role].axes():
        if kind == 'kind' and a.kind == value:
            return a
        if kind == 'label' and a.label == value:
            return a
    return None


def axis_plan(devs):
    """[(function, context, role, axis, invert)] -- axes skip allocate()."""
    out = []
    for func, ctx, role, how, invert in AXIS_NEEDS:
        a = axis_of(devs, role, how)
        if a is None:
            print(f'!! no {how[1]!r} axis on the {role} for {func}',
                  file=sys.stderr)
            continue
        out.append((func, ctx, role, a, invert))
    return out


def build():
    devs = devmap.by_role('stick', 'throttle')
    # Needs with no bindings at all are kept, not filtered: a need whose whole
    # job is to reserve a control -- `Head look` over the throttle mini-stick,
    # which the axes below take -- has `wanted == 0` and binds nothing, and
    # dropping it let a button need claim the mini-stick's click.
    placed, unmet, free = corneeds.allocate(list(NEEDS), devs)
    return devs, placed, unmet, free, axis_plan(devs)


# ----------------------------------------------------------------- writing --

def as_results(devs, placed, axes):
    """The plan in the shape `ed-bind-wizard.py`'s generate() consumes.

    `{function: {'role', 'type', 'index', 'sign'}}` plus `_devices`. Going
    through the capture TUI's own writer means one implementation of the
    `.binds` format, and the plan gets its keyboard-fallback handling and its
    deadzone care for free.
    """
    out = {}
    for p in placed:
        for button, payload in p.slots:
            for func in payload:
                if func:
                    out[func] = {'role': p.role, 'type': 'button',
                                 'index': button, 'sign': 1}
    for func, _ctx, role, a, invert in axes:
        out[func] = {'role': role, 'type': 'axis', 'index': a.index,
                     'sign': -1 if invert else 1}
    return out


def write(devs, placed, axes, preset=None, backup_dir=None):
    mod = wizard()
    results = as_results(devs, placed, axes)
    # the captured results file is where the device ids and axis maps live
    import json
    saved = json.load(open(os.path.join(HERE, 'ed-bind-wizard-results.json')))
    results['_devices'] = saved.get('_devices', {})
    cfg = saved.get('_config', {})
    base = cfg.get('base') or mod.DEFAULT_BASE
    bindings = cfg.get('bindings_dir') or mod.DEFAULT_BINDINGS_DIR
    for line in mod.generate(results, base, bindings, preset or PRESET,
                             backup_dir):
        print(line)


# ---------------------------------------------------------------- the sheet --

CTX = ('Ship', 'SRV')


def _sheet():
    devs, placed, unmet, free, axes = build()
    sh = csheet.Sheet(
        'Kneeboard Elite Dangerous', 'Elite Dangerous · VIRPIL',
        ident='Joy', contexts=CTX,
        devices={r: d.product for r, d in devs.items()})

    for p in sorted(placed, key=lambda p: (p.role, p.ctrl.label)):
        for button, payload in p.slots:
            by_ctx = {}
            for ctx, func in zip(CTX, payload):
                if func:
                    by_ctx[ctx] = harvest.readable(func)
            if not by_ctx:
                continue
            sh.add(csheet.Row(
                p.role, p.ctrl.label,
                part=p.ctrl.direction(button) or 'press',
                ident=f'Joy_{button + 1}',
                does=p.need.what, bindings=by_ctx))

    for func, ctx, role, a, invert in axes:
        g = devs[role].axis_group(a.index)
        sh.add_axis(csheet.AxisRow(
            role, g.label if g else a.label,
            ident=f'axis {a.index}',
            does=f'{ctx}: {harvest.readable(func)}'
                 + (' (inverted)' if invert else '')))

    sh.free = [(r, c.label, '', c.reach or '') for r, c in free]
    sh.unplaced = [(n.what, n.shape if isinstance(n.shape, str)
                    else '/'.join(n.shape)) for n in unmet]
    sh.note('Writing it', [
        ('Preset', f'{PRESET} — the capture TUI owns whatever you bound by '
                   'hand, so neither overwrites the other.'),
        ('Selecting it', 'Elite records the active preset in '
                         'StartPreset.4.start, which nothing here writes: '
                         'choose it once in the game\'s control options.'),
        ('Contexts', 'A function name carries its own context — an SRV '
                     'binding is a `_Buggy` suffix or a `Buggy` prefix — so '
                     'one control means both without clashing.'),
        ('Ranking', 'Counted from the 13 HOTAS presets Elite ships, five of '
                    'which name the stick and the throttle separately and so '
                    'say which device a function belongs on.'),
    ])
    return sh


# ------------------------------------------------------------------- output --

def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--why', action='store_true', help='explain every choice')
    p.add_argument('--free', action='store_true', help='only what is unbound')
    p.add_argument('--sheet', action='store_true', help='write KNEEBOARD.md')
    p.add_argument('--html', action='store_true',
                   help='the same in columns, for a second screen')
    p.add_argument('--write', action='store_true',
                   help="into the game's Bindings folder")
    p.add_argument('--preset', help=f'which preset to write (default {PRESET})')
    backup.add_argument(p, 'elite')
    a = p.parse_args()

    bad = unknown()
    if bad:
        for what, func in bad:
            print(f'!! {what}: the game has no function {func}',
                  file=sys.stderr)
        sys.exit('the vocabulary disagrees with NEEDS; run ./harvest.py --json')
    dup = duplicates()
    if dup:
        sys.exit('claimed by more than one need: ' + ', '.join(dup))

    devs, placed, unmet, free, axes = build()

    did = False
    if a.sheet:
        print('wrote %s (%d rows, %d axes)'
              % _sheet().markdown(os.path.join(HERE, 'KNEEBOARD.md')))
        did = True
    if a.html:
        print('wrote %s (%d rows, %d axes)'
              % _sheet().html(os.path.join(HERE, 'kneeboard.html')))
        did = True
    if a.write:
        write(devs, placed, axes, a.preset, a.backup_dir)
        did = True
    if did:
        return

    if a.free:
        for role, c in free:
            print(f'  {role:9} {c.label:34} {c.kind:10} {c.reach or ""}')
        return

    for p_ in sorted(placed, key=lambda p_: (p_.need.urgency, p_.role)):
        n = p_.need
        print(f'  {n.what:22} {p_.role:9} {n.first_shape:9} {p_.ctrl.label}')
        for button, payload in p_.slots:
            part = p_.ctrl.direction(button) or 'press'
            for ctx, func in zip(CTX, payload):
                if func:
                    print(f'      {part:9} Joy_{button + 1:<4} {ctx:5} '
                          f'{harvest.readable(func)}')
        if a.why:
            print(f'      {"":9} [{corneeds.URGENCY_NAME[n.urgency]}]'
                  f'  {n.rank}/13 factory presets'
                  f'{" relaxed" if n.relaxed else ""}'
                  f'{"  " + n.note if n.note else ""}')
    print()
    for func, ctx, role, a_, invert in axes:
        print(f'  {harvest.readable(func):34} {ctx:5} {role:9} '
              f'axis {a_.index} {a_.label}'
              f'{"  inverted" if invert else ""}')
    if unmet:
        print()
        print(f'{len(unmet)} unplaced: '
              + ', '.join(f'{n.what} (wanted {n.first_shape})' for n in unmet))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""plan.py - lay out Elite Dangerous on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write a .binds preset through ed-bind-wizard.py.

FILES
    harvest.py                  the function vocabulary and the ranking
    ed-bind-wizard-results.json device ids and axis maps, from the capture TUI
    <preset>.4.2.binds          written by --write, in the game's Bindings dir
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    ED_PRESET           preset to write (default Izowiuz-PLAN)
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    The plan and the capture TUI write different presets, so neither
    overwrites the other.
    Writing a preset does not select it: choose it once in the game.
"""

import argparse
import collections
import json
import os
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

from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import review as creview                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH,             # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)

harvest = adapter.from_file('edharvest', os.path.join(HERE, 'harvest.py'))

#: The capture wizard's own file: device ids, axis maps, and whatever was
#: confirmed at the stick. The plan reads it and never writes it.
RESULTS = 'ed-bind-wizard-results.json'

#: Filled by `Elite.__init__`, never at import -- see the note in
#: games/falconbms/plan.py. `vouched()` and `votes()` are functions, so they
#: read these only once an adapter exists.
VOCAB, RANK, AXES = {}, {}, set()


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
        with open(os.path.join(HERE, RESULTS), encoding='utf-8') as f:
            saved = json.load(f)
    except OSError:
        return out
    return out | {k for k, v in saved.items()
                  if not k.startswith('_') and v is not None}

#: The preset the plan owns. The game picks a preset in its own control
#: options and records the choice in StartPreset.4.start, which nothing here
#: writes -- so a freshly written preset is selected once, by hand.
PRESET = os.environ.get('ED_PRESET', 'Izowiuz-PLAN')


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

def _needs():
    """The needs, built on demand rather than at import.

    Two things in here read the vocabulary: `rank=votes(*flat)` in
    `Need.__init__`, and `srv=twinned(...)`, which asks whether the
    game has an SRV twin of each function. As a module-level literal
    this ran before any adapter existed to fill VOCAB and RANK, which
    made every need rank 0 and silently dropped every SRV binding --
    and the layout changed with it, because rank feeds the score.

    That is what the abstract NEEDS being a *property* is for: DCS
    derives its needs per aircraft, and this one derives its own from
    the game's vocabulary. Neither can be a constant.
    """
    return [
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


def unknown(needs):
    """Functions named in NEEDS or AXIS_NEEDS that the game will not accept.

    The vocabulary comes out of the game's own base preset, so a typo or a
    function a patch renamed is an error here rather than a binding that
    silently does nothing.
    """
    allf = vouched()
    bad = []
    for n in needs:
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


def duplicates(needs):
    """Functions named by more than one need.

    Elite has one element per function, so two needs claiming one function
    means the second silently wins whatever the sheet says.
    """
    seen = collections.Counter()
    for n in needs:
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


def contents(mod, devs, placed, axes, preset):
    """({path: the preset's whole text}, summary lines). Writes nothing.

    The device ids and the axis maps come out of the captured results file,
    which is the capture wizard's own: the plan lays a layout over what
    somebody already confirmed at the stick.
    """
    results = as_results(devs, placed, axes)
    saved = json.load(open(os.path.join(HERE, RESULTS)))
    results['_devices'] = saved.get('_devices', {})
    cfg = saved.get('_config', {})
    base = cfg.get('base') or mod.DEFAULT_BASE
    bindings = cfg.get('bindings_dir') or mod.DEFAULT_BINDINGS_DIR
    out, text, lines = mod.render(results, base, bindings, preset)
    return {out: text}, lines


# ---------------------------------------------------------------- the review --

def _describe(p):
    """[(part of the control, what it does)] -- a function name carries its own
    context in Elite, so the column says which."""
    out = []
    for button, payload in p.slots:
        part = p.ctrl.direction(button) or 'press'
        for ctx, func in zip(CTX, payload):
            if func:
                out.append((part, f'{ctx}: {harvest.readable(func)}'))
    return out


# ---------------------------------------------------------------- the sheet --

CTX = ('Ship', 'SRV')


def _sheet(layout):
    devs, placed, unmet, free, axes = layout
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

# -------------------------------------------------------------- the adapter --

class Wizard(typing.Protocol):
    """What this planner calls on `ed-bind-wizard.py`.

    See the note on `Preset` in games/warthunder/plan.py: this gets the call
    sites checked, not the promise that the script has them.
    """

    DEFAULT_BASE: str
    DEFAULT_BINDINGS_DIR: str

    def render(self, results: dict, base: str, bindings_dir: str,
               preset_name: str) -> tuple[str, str, list[str]]: ...


@typing.final
class Elite(adapter.Planner):
    """Elite Dangerous, on the VIRPIL pair.

    Two tools on one writer: this lays a layout out, `ed-bind-wizard.py`
    captures bindings off the devices, and both go through the wizard's
    `render()` so there is one implementation of the `.binds` format. They
    write different presets, so neither overwrites the other.
    """

    game = 'elite'
    title = 'Elite Dangerous'
    CACHE = {'ed-actions.json': 'vocabulary', 'ed-rank.json': 'ranking'}


    def __init__(self, preset=None, backup_dir=None):
        self.preset = preset or os.environ.get('ED_PRESET', PRESET)
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {self.preset}'
        VOCAB.update(self.cache('ed-actions.json',
                                build=harvest.vocabulary))
        RANK.update(self.cache('ed-rank.json', build=harvest.ranking))
        AXES.update(VOCAB.get('axis', ()))
        # Elite has one element per function, so a function two needs both
        # claim does not clash -- the second simply wins, silently. The
        # adapter refuses to exist rather than write that.
        self._needs = _needs()
        dup = duplicates(self._needs)
        if dup:
            raise SystemExit('claimed by more than one need: '
                             + ', '.join(dup))

    @property
    @typing.override
    def NEEDS(self):
        """Derived from the game's own vocabulary, so it is a property."""
        return self._needs

    @typing.final
    def wizard(self):
        return typing.cast(Wizard, self.sidecar('ed-bind-wizard.py'))

    @typing.override
    def build(self):
        devs = devmap.by_role('stick', 'throttle')
        # Needs with no bindings at all are kept, not filtered: a need whose
        # whole job is to reserve a control -- `Head look` over the throttle
        # mini-stick, which the axes take -- has `wanted == 0` and binds
        # nothing, and dropping it let a button need claim the click.
        return corneeds.Layout(devs, *corneeds.allocate(list(self.NEEDS),
                                                        devs),
                               axes=axis_plan(devs))

    @typing.override
    def unknown(self):
        return [(what, 'function', func)
                for what, func in unknown(self._needs)]

    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout)

    @typing.override
    def write_layout(self, layout):
        files, said = contents(self.wizard(), layout.devices, layout.placed,
                               layout.axes, self.preset)
        for line in said:
            print(line)
        return files

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--preset',
                            help=f'preset to write (default {self.preset})')

    @typing.override
    def paths(self, args):
        mod = self.wizard()
        saved = json.load(open(os.path.join(HERE, RESULTS)))
        cfg = saved.get('_config', {})
        return [('game', cfg.get('game_dir', '(not recorded)')),
                ('base preset', cfg.get('base') or mod.DEFAULT_BASE),
                ('writes', os.path.join(
                    cfg.get('bindings_dir') or mod.DEFAULT_BINDINGS_DIR,
                    f'{self.preset}.4.2.binds')),
                ('backups', backup.dir_for('elite', self.backup_dir))]

    @typing.override
    def show(self, layout, why=False):
        _devs, placed, unmet, _free, axes = layout
        out = []
        for p_ in sorted(placed, key=lambda p_: (p_.need.urgency, p_.role)):
            n = p_.need
            out.append(f'  {n.what:22} {p_.role:9} {n.first_shape:9} '
                       f'{p_.ctrl.label}')
            for button, payload in p_.slots:
                part = p_.ctrl.direction(button) or 'press'
                for ctx, func in zip(CTX, payload):
                    if func:
                        out.append(f'      {part:9} Joy_{button + 1:<4} '
                                   f'{ctx:5} {harvest.readable(func)}')
            if why:
                out.append(f'      {"":9} '
                           f'[{corneeds.URGENCY_NAME[n.urgency]}]'
                           f'  {n.rank}/13 factory presets'
                           f'{" relaxed" if n.relaxed else ""}'
                           f'{"  " + n.note if n.note else ""}')
        out.append('')
        for func, ctx, role, a_, invert in axes:
            out.append(f'  {harvest.readable(func):34} {ctx:5} {role:9} '
                       f'axis {a_.index} {a_.label}'
                       f'{"  inverted" if invert else ""}')
        if unmet:
            out.append('')
            out.append(f'{len(unmet)} unplaced: '
                       + ', '.join(f'{n.what} (wanted {n.first_shape})'
                                   for n in unmet))
        return out


if __name__ == '__main__':
    sys.exit(adapter.run(Elite))

#!/usr/bin/env python3
"""plan.py - lay out Elite Dangerous on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write a .binds preset through ed-bind-wizard.py.

FILES
    harvest.py                  the function vocabulary
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
from core import review as creview                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH,             # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)

harvest = adapter.from_file('edharvest', os.path.join(HERE, 'harvest.py'))

#: The capture wizard's own file: device ids, axis maps, and whatever was
#: confirmed at the stick. The plan reads it and never writes it.
RESULTS = 'ed-bind-wizard-results.json'

#: Where the judgements live. Source, not cache -- nothing derives them.
#: Deliberately not in `CACHE`: that names what the harvest wrote, and a
#: harvest cannot write a judgement.

#: The catalogue as the harvest wrote it, and the one view of it this file
#: asks for. Filled by `Elite.__init__`, never at import -- see the note
#: in games/falconbms/plan.py: a module that reads a cache on import
#: cannot be told apart from one that is broken, on a clone where nothing
#: is harvested. `known()` is a function for the same reason.
CAT, AXES = [], set()


def known():
    """Every function the game accepts a binding for.

    This used to add whatever the results file held as well, because the
    thirty shipped presets are LAYOUTS and cannot show a function nobody
    bound -- and `NightVisionToggle` is exactly that, a real ship function
    that works in game and appears in none of them.

    But the results file is written by this tool. A function we misspelled
    went in, came back as vocabulary, and then validated against itself in
    `unknown()` -- so the one check meant to catch a typo was the one place
    guaranteed not to.

    The harvest reads the bindings file Elite keeps for itself now, which
    lists every function it knows whether bound or not. The gap is closed
    where it opened: 440 functions, `NightVisionToggle` among them, with
    nothing vouching for anything.
    """
    return {a.id for a in CAT}

#: The preset the plan owns. The game picks a preset in its own control
#: options and records the choice in StartPreset.4.start, which nothing here
#: writes -- so a freshly written preset is selected once, by hand.
PRESET = os.environ.get('ED_PRESET', 'Izowiuz-PLAN')


#: Elite names an SRV function with a `_Buggy` suffix OR a `Buggy` prefix, and
#: a function with no twin in either form answers in both. This is War
#: Thunder's rule exactly, down to the trap: checking only the suffix made
#: `PitchAxisRaw` look shared when its twin is `BuggyPitchAxis`.
def srv_twin(function):
    """The SRV form of a ship function, if the game has one."""
    allf = known()
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

def _needs(described, placed):
    """[Need] -- the hand-written list, read rather than executed.

    This used to BUILD them, and two parts were derived on the way: how
    many of the shipped HOTAS presets bound each function, and whether
    the game has an SRV twin of it (`twinned(...)`). The twin is written
    down now; the count is gone from the whole family -- it ranked other
    people's layouts for other people's hardware.
    """
    out = corneeds.read_needs(vocab.load(HERE, described, key='needs'),
                              make=Need)
    return out


def unknown(needs):
    """Functions named in the needs file that the game will not accept.

    The vocabulary comes out of the game's own base preset, so a typo or a
    function a patch renamed is an error here rather than a binding that
    silently does nothing.
    """
    allf = known()
    bad = []
    for n in needs:
        for slot in n.bindings:
            for f in (b.action for b in slot):
                if f and f not in allf:
                    bad.append((n.what, f))
        if n.push and n.push not in allf:
            bad.append((n.what, n.push))
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
    return [f for f, c in seen.items() if c > 1]


# ------------------------------------------------------------ the hardware --

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
            for func in (b.action for b in payload):
                if func:
                    out[func] = {'role': p.role, 'type': 'button',
                                 'index': button, 'sign': 1}
    for p in axes:
        index = p.slots[0][0].index
        for func in (b.action for b in p.slots[0][1]):
            out[func] = {'role': p.role, 'type': 'axis', 'index': index,
                         'sign': -1 if p.need.invert else 1}
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
        for func in (b.action for b in payload):
            ctx = context_of(func)
            if func:
                out.append((part, f'{ctx}: {harvest.readable(func)}'))
    return out


# ---------------------------------------------------------------- the sheet --

CTX = ('Ship', 'SRV')


#: SRV functions whose names do not say so. `srv_twin` builds the two forms
#: Frontier normally uses -- `X_Buggy` and `BuggyX` -- and everything else
#: follows one of them. These two do not, and no rule will find them:
#: `HeadlightsBuggyButton` is the SRV twin of `ShipSpotLightToggle` and
#: `ToggleDriveAssist` of `ToggleFlightAssist`, and nothing in either pair
#: of names is shared. Read off a written-out list because they were found
#: by somebody who knew the game, which is the only way they can be found.
#: Four, not two. `SteeringAxis` and `DriveSpeedAxis` are the SRV's
#: steering and throttle and are named like neither rule; the axes
#: section declared their context in the row, which is the same list
#: written in a second place, and the rows have moved into the needs.
SRV_BY_HAND = frozenset(('HeadlightsBuggyButton', 'ToggleDriveAssist',
                         'SteeringAxis', 'DriveSpeedAxis'))


def context_of(function):
    """Which of CTX a function answers in, read off the name.

    `srv_twin` builds the two forms the game uses, so recognising one is
    that rule read backwards -- plus the two it cannot reach. The context
    used to be the position in the payload tuple, which meant the core
    could not tell and every screen had to be handed the answer.
    """
    return ('SRV' if function.endswith('_Buggy')
            or function.startswith('Buggy')
            or function in SRV_BY_HAND else 'Ship')


def _sheet(layout):
    devs, placed, unmet, free = (layout.devices, layout.on_buttons,
                                 layout.unplaced, layout.free)
    axes = layout.on_axes
    sh = csheet.Sheet(
        'Kneeboard Elite Dangerous', 'Elite Dangerous · VIRPIL',
        ident='Joy', contexts=CTX,
        devices={r: d.product for r, d in devs.items()})

    for p in sorted(placed, key=lambda p: (p.role, p.ctrl.label)):
        for button, payload in p.slots:
            by_ctx = {}
            for func in (b.action for b in payload):
                ctx = context_of(func)
                if func:
                    by_ctx[ctx] = harvest.readable(func)
            if not by_ctx:
                continue
            sh.add(csheet.Row(
                p.role, p.ctrl.label,
                part=p.ctrl.direction(button) or 'press',
                ident=f'Joy_{button + 1}',
                does=p.need.what, bindings=by_ctx))

    for p in axes:
        a = devs[p.role].axis(p.slots[0][0].index)
        g = devs[p.role].axis_group(a.index)
        for func in (b.action for b in p.slots[0][1]):
            sh.add_axis(p.role, g.label if g else a.label, f'axis {a.index}',
                        harvest.readable(func)
                        + (' (inverted)' if p.need.invert else ''),
                        context_of(func))

    for r, c in free:
        sh.add_free(r, c.label)
    for n in unmet:
        sh.add_unplaced(n.what, n.shape if isinstance(n.shape, str)
                        else '/'.join(n.shape))
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
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'elite-needs.json'
    BINDS = 'elite-binds.json'
    CATALOGUE = 'ed-actions.json'
    CACHE = {'ed-actions.json': 'actions'}


    def __init__(self, preset=None, backup_dir=None):
        self.preset = preset or os.environ.get('ED_PRESET', PRESET)
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {self.preset}'
        CAT[:] = cactions.read(self.cache('ed-actions.json',
                                          build=harvest.action_rows))
        AXES.update(a.id for a in CAT if a.kind == 'axis')
        # Elite has one element per function, so a function two needs both
        # claim does not clash -- the second simply wins, silently. The
        # adapter refuses to exist rather than write that.
        self._needs = _needs(self.NEEDS_FILE, self.BINDS)
        dup = duplicates(self._needs)
        if dup:
            raise SystemExit('More than one need claims these: '
                             + ', '.join(dup) + '.')

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
        self.answers(self.NEEDS)
        return corneeds.Layout(devs, *corneeds.allocate(list(self.NEEDS),
                                                        devs))

    @typing.override
    def unknown(self):
        return [(what, 'function', func)
                for what, func in unknown(self._needs)]

    @typing.override
    def catalogue(self):
        """Every function there is evidence the game accepts.

        A read, not a translation. The harvest writes the record, from
        the bindings file the game keeps for itself -- which names every
        function whether bound or not, so the screen no longer depends on
        what this tool happened to have written down.
        """
        return list(CAT)


    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout)

    @typing.override
    def write_layout(self, layout):
        files, said = contents(self.wizard(), layout.devices, layout.on_buttons,
                               layout.on_axes, self.preset)
        for line in said:
            print(line)
        return files

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--preset',
                            help='Which preset to write. The default is '
                                 f'{self.preset}.')

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
        devs, placed, unmet = (layout.devices, layout.on_buttons,
                               layout.unplaced)
        axes = layout.on_axes
        out = []
        for p_ in sorted(placed, key=lambda p_: (p_.need.urgency, p_.role)):
            n = p_.need
            out.append(f'  {n.what:22} {p_.role:9} {n.first_shape:9} '
                       f'{p_.ctrl.label}')
            for button, payload in p_.slots:
                part = p_.ctrl.direction(button) or 'press'
                for func in (b.action for b in payload):
                    ctx = context_of(func)
                    if func:
                        out.append(f'      {part:9} Joy_{button + 1:<4} '
                                   f'{ctx:5} {harvest.readable(func)}')
            if why:
                out.append('      ' + ' · '.join(corneeds.why_bits(p_)))
        out.append('')
        for p_ in axes:
            a_ = devs[p_.role].axis(p_.slots[0][0].index)
            for func in (b.action for b in p_.slots[0][1]):
                out.append(f'  {harvest.readable(func):34} '
                           f'{context_of(func):5} {p_.role:9} '
                           f'axis {a_.index} {a_.label}'
                           f'{"  inverted" if p_.need.invert else ""}')
        if unmet:
            out.append('')
            out.append(f'{len(unmet)} unplaced: '
                       + ', '.join(f'{n.what} (wanted {n.first_shape})'
                                   for n in unmet))
        return out


if __name__ == '__main__':
    sys.exit(adapter.run(Elite))

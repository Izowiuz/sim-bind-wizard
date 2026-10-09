#!/usr/bin/env python3
"""plan.py - lay out one DCS module on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write one diff.lua per device.

FILES
    harvest.py                     the module's command vocabulary
    <device>.diff.lua              written by --write, per aircraft
    KNEEBOARD-<aircraft>.md        written by --sheet
    kneeboard-<aircraft>.html      written by --html

ENVIRONMENT
    DCS_GAME_DIR        the install, when no Steam library has it
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close DCS first: it rewrites Config/Input on exit.
    One module at a time: -a picks another.
"""

# Declarations, and DCS's diff.lua format. Nothing else. The layout, the
# listing, the kneeboard, the review screen and the walk down the
# placements are the core's.
#
# DCS is the one game with a variant. A module's commands are its own, so
# the aircraft decides which vocabulary, which needs file, which binds
# file and which kneeboard. All of that follows from two declarations:
# `VARIANT` names the constructor parameter, and `variants()` says which
# modules are installed. The core builds the rest.

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

from core import adapter                                    # noqa: E402
from core import game as cgame                              # noqa: E402

harvest = adapter.from_file('dcsharvest', os.path.join(HERE, 'harvest.py'))

#: DCS assigns these to EVERY joystick device it sees. The files are
#: `DefaultAssignments.lua` and `base_joystick_binding.lua`. So a stick
#: and a throttle fight over the same axis, and the write removes these
#: wherever they collide.
DEFAULT_AXIS_KEYS = {'Pitch': 'JOY_Y', 'Roll': 'JOY_X',
                     'Rudder': 'JOY_RZ', 'Thrust': 'JOY_Z'}
DEFAULT_BUTTON_KEYS = {'Weapon Fire': 'JOY_BTN1',
                       'Weapon Change': 'JOY_BTN4',
                       'Cannon': 'JOY_BTN5'}

#: Axis tuning by command name, as (curvature, deadzone). These are Eagle
#: Dynamics' own values, out of their VPC WarBRD profile. Tune them in the
#: game under Axis Tune.
AXIS_FILTERS = {'Pitch': (0.12, 0.03), 'Roll': (0.12, 0.03),
                'Rudder': (0.15, 0.05)}
SLIDER_PREFIX = 'Thrust'       # Thrust, Thrust Left, Thrust Right


def lua(v, indent=1):
    """A value as DCS's own serializer writes it: sorted keys, tab
    indent."""
    pad = '\t' * indent
    if isinstance(v, dict):
        lines = ['{']
        for k in sorted(v):
            key = '[%d]' % k if isinstance(k, int) else '["%s"]' % k
            lines.append('%s%s = %s,' % (pad, key, lua(v[k], indent + 1)))
        lines.append('\t' * (indent - 1) + '}')
        return '\n'.join(lines)
    if isinstance(v, list):
        return lua({i + 1: x for i, x in enumerate(v)}, indent)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, str):
        return '"%s"' % v
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return repr(v)


def make_filter(name, invert):
    curvature, deadzone = AXIS_FILTERS.get(name, (0.0, 0.0))
    return {'curvature': [curvature], 'deadzone': deadzone,
            'hardwareDetent': False, 'hardwareDetentAB': 0,
            'hardwareDetentMax': 0, 'invert': bool(invert),
            'saturationX': 1, 'saturationY': 1,
            'slider': name.startswith(SLIDER_PREFIX)}


def vanilla_filter():
    return make_filter('', False)


def render_diff(diff):
    """One diff dict -> the file's whole text.

    Byte compatible with DCS's own serializer: sorted keys, tab indent,
    and no trailing newline. So a file the game rewrites comes back
    identical.
    """
    body = lua({'axisDiffs': diff.get('axisDiffs', {}),
                'keyDiffs': diff.get('keyDiffs', {})}, 1)
    return 'local diff = %s\nreturn diff' % body


@typing.final
class Dcs(adapter.Planner):
    """DCS World, one module at a time."""

    game = 'dcs'
    title = 'DCS World'
    OVERLAY = 'by-hand'
    MODES = ('',)
    AXES = harvest.AXES
    BUTTON = harvest.BUTTON
    BUTTON_FROM = harvest.BUTTON_FROM
    #: Where the real aircraft keeps it, in the game's own words.
    #: Measured against a hand-written Hornet list: `Throttle Grip` 14 of
    #: 14, and `Stick` 7 of 7.
    DEVICE_BY_CATEGORY = {'Stick': 'stick', 'Throttle Grip': 'throttle',
                          'Throttle Quadrant': 'throttle'}

    #: The few categories that name a job rather than a place in the
    #: cockpit. Most do not: `Instrument Panel` and `Left Console` say
    #: where a switch is, and not what it does.
    JOB_BY_CATEGORY = {'Communications': 'comms', 'VHF Radio': 'comms',
                       'Countermeasures': 'defence', 'Weapons': 'fire',
                       'Autopilot': 'nav', 'Rear Warning Radar': 'sensor',
                       'Engine Control Panel': 'systems',
                       'Fuel Control': 'systems'}

    #: The one game with a variant. `-a` picks it. The core builds the
    #: review screen's key, the sentence that names it, and the
    #: kneeboard's filename out of this and `variants()`.
    VARIANT = 'aircraft'
    ALIASES = {'aircraft': ('-a',)}
    SAYS = {'aircraft': 'which module to lay out (default: FA-18C)'}
    #: The templates, spelled as `harvest.CACHE_TEMPLATE` spells its own.
    #: The contract test that a planner reads what its harvest writes then
    #: has two strings to compare. `__init__` puts the aircraft into
    #: each.
    CATALOGUE = harvest.CACHE_TEMPLATE
    CACHE = {harvest.CACHE_TEMPLATE: 'actions'}
    NEEDS_FILE = 'dcs-<aircraft>-needs.json'
    BINDS = 'dcs-<aircraft>-binds.json'
    PATHS = (('install', 'install_dir'), ('saved games', 'saved_games'),
             ('writes', 'where'))

    def __init__(self, aircraft=None, game_dir=None, backup_dir=None):
        self.aircraft = aircraft or harvest.DEFAULT_AIRCRAFT
        self.backup_dir = backup_dir
        self.cfg = harvest.install(game_dir)
        self.install_dir = self.cfg['game_dir']
        self.saved_games = self.cfg['saved_games']
        # One module, one vocabulary, one list, one store, one kneeboard.
        # The aircraft is the only thing that varies, and the
        # declarations above are templates it fills in.
        self.CATALOGUE = harvest.cache_name(self.aircraft)
        self.CACHE = {self.CATALOGUE: 'actions'}
        self.NEEDS_FILE = type(self).NEEDS_FILE.replace(
            '<aircraft>', self.aircraft)
        self.BINDS = type(self).BINDS.replace('<aircraft>', self.aircraft)
        self.where = os.path.join(
            self.saved_games, 'Config', 'Input',
            harvest.input_id(self.cfg, self.aircraft), 'joystick')
        found = harvest.discover_aircraft(self.cfg).get(self.aircraft, {})
        self.subtitle = f'{found.get("display", self.aircraft)} · VIRPIL'

    @typing.override
    def variants(self):
        """Which modules are installed.

        This is a hook and not a declaration. The answer is read out of
        the game directory.
        """
        return {key: info['display']
                for key, info in harvest.discover_aircraft(self.cfg).items()}

    def _axis_keys(self, device):
        """Which JOY_* axis names this device has.

        A default assignment is removed from a device that could carry it,
        and from no other. The map knows the axes, so nothing reads the
        hardware to answer this.
        """
        return {self.AXES[adapter.HID_AXES.index(a.hid)]
                for a in device.axes() if a.hid in adapter.HID_AXES}

    def _build_diffs(self, rows, layout):
        """{role: {'axisDiffs', 'keyDiffs'}} for the bindings handed over.

        DCS assigns pitch, roll, rudder, thrust, weapon fire, weapon
        change and cannon to EVERY joystick it sees. So a binding that
        lands anywhere other than the default removes that default, from
        this device AND from the other one. The other device otherwise
        goes on answering the same command.
        """
        diffs = {role: {'axisDiffs': {}, 'keyDiffs': {}}
                 for role in layout.devices}

        def other(role):
            return next((r for r in layout.devices if r != role), role)

        for b in rows:
            if not b.slot:
                print(f'!! {b.what}: {b.role} has no DCS key for that '
                      'control.', file=sys.stderr)
                continue
            table = 'axisDiffs' if b.axis else 'keyDiffs'
            entry = diffs[b.role][table].setdefault(b.action,
                                                    {'name': b.what})
            default = (DEFAULT_AXIS_KEYS if b.axis
                       else DEFAULT_BUTTON_KEYS).get(b.what)
            if b.axis:
                filt = make_filter(b.what, b.invert)
                if b.slot == default:
                    if filt != vanilla_filter():
                        entry['changed'] = [{'key': b.slot, 'filter': filt}]
                else:
                    entry['added'] = [{'key': b.slot, 'filter': filt}]
                    if default and default in self._axis_keys(b.device):
                        entry.setdefault('removed', []).append(
                            {'key': default})
                if default and default in self._axis_keys(
                        layout.devices[other(b.role)]):
                    diffs[other(b.role)]['axisDiffs'].setdefault(
                        b.action, {'name': b.what}
                    ).setdefault('removed', []).append({'key': default})
            else:
                if b.slot != default:
                    entry['added'] = [{'key': b.slot}]
                    if default:
                        entry.setdefault('removed', []).append(
                            {'key': default})
                if default:
                    diffs[other(b.role)]['keyDiffs'].setdefault(
                        b.action, {'name': b.what}
                    ).setdefault('removed', []).append({'key': default})

        # Whatever ended up with nothing but a name is not a diff. An
        # axis left at the default says nothing, and DCS reads an empty
        # entry as a change.
        for role in diffs:
            for table in ('axisDiffs', 'keyDiffs'):
                diffs[role][table] = {
                    h: e for h, e in diffs[role][table].items()
                    if set(e) - {'name'}}
        return diffs

    @typing.override
    def write_layout(self, rows, layout):
        """One diff.lua per device, for the bindings it is handed.

        The device's own name is the filename, and the map carries it.
        `game_id('dcs')` is the `Device {GUID}` string DCS writes. Kept in
        a results file instead, somebody fills it in from `dcs.log`, and
        that is a second copy of what the map knows.
        """
        if cgame.running('DCS.exe'):
            raise SystemExit('DCS is running. It rewrites Config/Input when '
                             'it exits. Quit the game first.')
        diffs = self._build_diffs(rows, layout)
        files = {}
        for role, device in layout.devices.items():
            ident = self.device_id(device)
            if not ident or ':' in ident:
                raise SystemExit(
                    f'The device map has no DCS name for the {role} '
                    f'({device.product}). DCS writes it into dcs.log as '
                    '`created [...] with full id [...]`. Put it on the '
                    'device in sim-device-map as its `dcs` game id.')
            files[os.path.join(self.where, f'{ident}.diff.lua')] = \
                render_diff(diffs[role])
        return files


if __name__ == '__main__':
    sys.exit(adapter.run(Dcs))

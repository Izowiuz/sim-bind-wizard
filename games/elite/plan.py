#!/usr/bin/env python3
"""plan.py - lay out Elite Dangerous on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write a .binds preset on top of a base one.

FILES
    harvest.py                     the function vocabulary
    <base>.binds                   read: the keyboard and mouse fallback
    <preset>.4.2.binds             written by --write, in the Bindings dir
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    ED_PRESET           preset to write (default Izowiuz-PLAN)
    ED_DIR              the install, when no Steam library has it
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    The base preset's bindings stay as the keyboard and mouse fallback.
    Writing a preset does not select it: choose it once in the game.
"""

# Declarations, and Elite's `.binds` format. Nothing else. The layout, the
# listing, the kneeboard, the review screen and the walk down the
# placements are the core's.
#
# The base preset is the template, so every function Elite knows is
# already an element with its keyboard binding in place. That is why this
# writer edits a tree rather than building one, and it is the whole of
# what is irreducibly Elite's.

import os
import sys
import typing
import xml.etree.ElementTree as ET

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
from core import game                                       # noqa: E402

harvest = adapter.from_file('edharvest', os.path.join(HERE, 'harvest.py'))

STEAMAPPS = os.path.expanduser('~/.local/share/Steam/steamapps')
DEFAULT_BASE = os.path.join(
    STEAMAPPS, 'common/Elite Dangerous/Products/elite-dangerous-odyssey-64/'
               'ControlSchemes/KeyboardMouseOnly.binds')
DEFAULT_BINDINGS_DIR = os.path.join(
    STEAMAPPS, 'compatdata/359320/pfx/drive_c/users/steamuser/AppData/Local/'
               'Frontier Developments/Elite Dangerous/Options/Bindings')
DEFAULT_PRESET = 'Izowiuz-PLAN'

#: Elite reads pitch the other way round to everything else. Pull the
#: stick towards you and the value goes negative, and negative is nose up.
#: So `Inverted` for these two means the opposite of what it means
#: elsewhere, and what you set on the review screen is combined with this
#: rather than written raw.
#:
#: A fact about the game, found by flying it. That is why it is data
#: here.
PITCH_IS_BACKWARDS = frozenset(('PitchAxisRaw', 'BuggyPitchAxis'))

DEFAULT_DEADZONE = '0.00000000'
#: A ministick drifts more than a flight axis.
AXIS_DEADZONES = {'LateralThrustRaw': '0.10000000',
                  'VerticalThrustRaw': '0.10000000',
                  'BuggyTurretYawAxisRaw': '0.10000000',
                  'BuggyTurretPitchAxisRaw': '0.10000000'}


@typing.final
class Elite(adapter.Planner):
    """Elite Dangerous, on the VIRPIL pair."""

    game = 'elite'
    title = 'Elite Dangerous'
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'elite-needs.json'
    BINDS = 'elite-binds.json'
    CATALOGUE = 'elite-actions.json'
    CACHE = {'elite-actions.json': 'actions'}
    MODES = harvest.MODES
    AXES = harvest.AXES
    BUTTON = harvest.BUTTON
    BUTTON_FROM = harvest.BUTTON_FROM
    #: Elite names a device by its USB pair, as eight hex digits in
    #: capitals.
    DEVICE_ID = 'upper'
    PATHS = (('base preset', 'base'), ('bindings', 'bindings_dir'),
             ('writes', 'where'))
    SAYS = {'preset': 'which preset to write',
            'base': 'the preset whose keyboard bindings stay as a fallback',
            'bindings_dir': 'where the game keeps its presets'}

    def __init__(self, preset=None, base=None, bindings_dir=None,
                 backup_dir=None):
        self.preset = preset or os.environ.get('ED_PRESET', DEFAULT_PRESET)
        self.base = base or DEFAULT_BASE
        self.bindings_dir = bindings_dir or DEFAULT_BINDINGS_DIR
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {self.preset}'
        self.where = os.path.join(self.bindings_dir,
                                  f'{self.preset}.4.2.binds')

    @staticmethod
    def _on_button(el, device, key):
        """Elite's `Primary`, keeping the base preset's keyboard binding.

        The base is a keyboard and mouse layout, and its binding is worth
        keeping. It moves to `Secondary`, so the function still answers at
        the keyboard where the stick is unplugged.
        """
        primary = el.find('Primary')
        secondary = el.find('Secondary')
        if primary is None:
            primary = ET.SubElement(el, 'Primary')
        if secondary is None:
            secondary = ET.SubElement(el, 'Secondary',
                                      Device='{NoDevice}', Key='')
        if (primary.get('Device') not in (None, '{NoDevice}')
                and secondary.get('Device') in (None, '{NoDevice}')):
            secondary.attrib.clear()
            secondary.attrib.update(primary.attrib)
        primary.attrib.clear()
        primary.set('Device', device)
        primary.set('Key', key)

    @staticmethod
    def _on_axis(el, function, device, key, invert):
        binding = el.find('Binding')
        if binding is None:
            binding = ET.SubElement(el, 'Binding')
        binding.attrib.clear()
        binding.set('Device', device)
        binding.set('Key', key)
        inverted = el.find('Inverted')
        if inverted is None:
            inverted = ET.SubElement(el, 'Inverted')
        inverted.set('Value',
                     '1' if invert ^ (function in PITCH_IS_BACKWARDS)
                     else '0')
        deadzone = el.find('Deadzone')
        if deadzone is None:
            deadzone = ET.SubElement(el, 'Deadzone')
        # Leave a deadzone tuned in the game or in the base preset
        # alone.
        if not deadzone.get('Value'):
            deadzone.set('Value',
                         AXIS_DEADZONES.get(function, DEFAULT_DEADZONE))

    @staticmethod
    def _clear(root, ours, keep):
        """Take our devices out of every function the plan no longer
        names.

        A writer removes as well as adds. The base preset is the template,
        so a function is an element whether or not anything sits on it. A
        writer that sets `Primary` and never clears one leaves a binding
        dropped from the needs file answering in the game.

        Our hardware is ours completely, which is the rule in every game
        here. A `Primary` or a `Binding` that names one of our devices is
        one this tool wrote.
        """
        for el in root:
            if el.tag in keep:
                continue
            for part in ('Primary', 'Secondary', 'Binding'):
                found = el.find(part)
                if found is not None and found.get('Device') in ours:
                    found.attrib.clear()
                    found.set('Device', '{NoDevice}')
                    found.set('Key', '')

    @typing.override
    def write_layout(self, rows, layout):
        """Elite's preset, for the bindings it is handed.

        A function the base does not carry is added. That is how the
        functions only the game's own bindings file enumerates get a
        binding.
        """
        if game.running('EliteDangerous64.exe'):
            raise SystemExit('Elite is running. It rewrites its bindings '
                             'when it exits. Quit the game first.')
        if not os.path.exists(self.base):
            raise SystemExit(f'There is no base preset at {self.base}.')
        tree = ET.parse(self.base)
        root = tree.getroot()
        root.set('PresetName', self.preset)
        root.set('MajorVersion', '4')
        root.set('MinorVersion', '2')

        ours = {self.device_id(d) for d in layout.devices.values()}
        self._clear(root, ours, {b.action for b in rows})

        for b in rows:
            if not b.slot:
                print(f'!! {b.what}: {b.role} has no Elite key for that '
                      'control.', file=sys.stderr)
                continue
            el = root.find(b.action)
            if el is None:
                el = ET.SubElement(root, b.action)
            said = self.device_id(b.device)
            if b.axis:
                self._on_axis(el, b.action, said, b.slot, b.invert)
            else:
                self._on_button(el, said, b.slot)

        ET.indent(tree, space='\t')
        return {self.where: ET.tostring(root, encoding='unicode',
                                        xml_declaration=True)}


if __name__ == '__main__':
    sys.exit(adapter.run(Elite))

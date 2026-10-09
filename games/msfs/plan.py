#!/usr/bin/env python3
"""plan.py - lay out MSFS 2024 on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then fill in the profiles MSFS keeps in Steam Cloud.

FILES
    harvest.py          the action vocabulary
    inputprofile_*      written by --write, two per device:
                          with <AircraftInfo/>   flight controls
                          without                camera, ATC, global
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close Steam first: it syncs these files from the cloud.
    An action the profile does not contain is skipped and reported.
"""

# Declarations, and MSFS's profile format. Nothing else. The layout, the
# listing, the kneeboard, the review screen and the walk down the
# placements are the core's.
#
# MSFS keeps two files per device, and the binding carries which one it
# belongs in. So the mode rides on `Bound.mode`. It is a property of the
# binding and not of the action, and no rule over a name will find it.

import glob
import os
import re
import subprocess
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'There is no shared core at {CORE}.\n'
                     'Clone sim-bind-wizard next to this repo, or set '
                     'SIM_BIND_WIZARD.')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import adapter                                    # noqa: E402

harvest = adapter.from_file('msfsharvest', os.path.join(HERE, 'harvest.py'))

REMOTE = os.path.expanduser(
    '~/.local/share/Steam/userdata/*/2537590/remote')


def find_profiles(devices):
    """[(path, role, bucket)] -- bucket is 'flight' or 'global'.

    MSFS keeps two files per device. The one carrying `<AircraftInfo
    CategoryName="..."/>` holds the flying actions, and that is the
    aeroplane AND the helicopter, whatever the label says. The one without
    it holds cameras, radio, and anything that applies whatever you fly.

    Their context sets do not overlap, so every action belongs to exactly
    one of the two.
    """
    pid = {}
    for role, d in devices.items():
        usb = (d.usb or '').split(':')[-1]
        if usb:
            pid[int(usb, 16)] = role
    out = []
    # Digits and nothing else. `inputprofile_*` also matches a
    # `.bak.<stamp>` copy, so a second run binds into its own backups and
    # backs THOSE up again. Backups live outside the folder now, in
    # `core.backup`, and the older copies still sit here.
    for path in sorted(glob.glob(os.path.join(REMOTE, 'inputprofile_*'))):
        if not re.fullmatch(r'inputprofile_\d+', os.path.basename(path)):
            continue
        with open(path, encoding='utf-8') as f:
            raw = f.read(4000)
        m = re.search(r'ProductID="([^"]*)"', raw)
        if not m:
            continue
        role = pid.get(int(m.group(1)))
        if not role:
            continue
        bucket = ('flight' if re.search(r'<AircraftInfo CategoryName=', raw)
                  else 'global')
        out.append((path, role, bucket))
    return out


def unbind_ours(text, keep):
    """Take our joystick out of every action the plan no longer names.

    A writer that only adds and replaces leaves a binding dropped from the
    needs file with its `<Primary>` block, and that binding goes on
    answering in the game.

    Our hardware is ours completely, which is the rule in every game here.
    An MSFS profile belongs to one device, so every joystick binding in it
    is one this program wrote. What the plan does not ask for goes back to
    self-closing, which is what the game ships.
    """
    out, at = [], 0
    for m in re.finditer(r'([ \t]*)<Action ActionName="([^"]+)"([^>]*)>'
                         r'(.*?)</Action>', text, re.S):
        ind, name, attrs, body = m.groups()
        if name in keep or 'Information="Joystick' not in body:
            continue
        out.append(text[at:m.start()])
        out.append(f'{ind}<Action ActionName="{name}"{attrs}/>')
        at = m.end()
    out.append(text[at:])
    return ''.join(out)


def bind_into(text, action, information, code):
    """Put one binding into the profile text and leave the rest alone.

    An unbound action is self-closing. A bound one carries a `<Primary>`
    block. Editing the text rather than reserialising the XML keeps the
    170 KB of formatting MSFS wrote exactly as it was.
    """
    esc = re.escape(action)
    key = f'<KEY Information="{information}">{code}</KEY>'
    for pattern, flags in ((r'([ \t]*)<Action ActionName="%s"([^>]*?)/>', 0),
                           (r'([ \t]*)<Action ActionName="%s"([^>]*)>'
                            r'(?:.*?)</Action>', re.S)):
        m = re.search(pattern % esc, text, flags)
        if not m:
            continue
        ind, attrs = m.group(1), m.group(2)
        block = (f'{ind}<Action ActionName="{action}"{attrs}>\n'
                 f'{ind}\t<Primary>\n{ind}\t\t{key}\n{ind}\t</Primary>\n'
                 f'{ind}</Action>')
        return text[:m.start()] + block + text[m.end():], True
    return text, False


@typing.final
class Msfs(adapter.Planner):
    """MSFS 2024, on the VIRPIL pair."""

    game = 'msfs'
    title = 'MSFS 2024'
    subtitle = 'VIRPIL'
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'msfs-needs.json'
    BINDS = 'msfs-binds.json'
    CATALOGUE = 'msfs-actions.json'
    CACHE = {'msfs-actions.json': 'actions'}
    MODES = harvest.MODES
    AXES = harvest.AXES
    BUTTON = harvest.BUTTON
    BUTTON_FROM = harvest.BUTTON_FROM
    PATHS = (('profiles', 'where'),)

    def __init__(self, backup_dir=None):
        self.backup_dir = backup_dir
        found = sorted(glob.glob(REMOTE))
        self.where = found[0] if found else REMOTE

    @staticmethod
    def _code(slot, axis):
        """The number MSFS stores beside the name it shows.

        A button's code is the index, and the name counts from one. An
        axis has a code of its own, in `AXIS_CODES` beside the name in
        `AXES`.
        """
        if axis:
            at = harvest.AXES.index(slot)
            return harvest.AXIS_CODES[at]
        return int(slot.rsplit(' ', 1)[1]) - 1

    @typing.override
    def write_layout(self, rows, layout):
        """MSFS's profiles, for the bindings it is handed.

        Steam has to be closed. It syncs these files from the cloud, and
        it puts the old ones back over anything written here.
        """
        if subprocess.run(['pgrep', '-x', 'steam'],
                          capture_output=True).returncode == 0:
            raise SystemExit('Steam is running. It syncs these files from '
                             'the cloud, and that would overwrite this '
                             'write. Quit Steam first.')
        found = find_profiles(layout.devices)
        if not found:
            raise SystemExit('There are no MSFS input profiles. Start the '
                             'sim once with the devices plugged in.')
        want = {}
        for b in rows:
            if not b.slot:
                continue
            bucket = 'global' if b.mode == harvest.GLOBAL else 'flight'
            want.setdefault((b.role, bucket), []).append(
                (b.action, b.slot, self._code(b.slot, b.axis)))

        files = {}
        for path, role, bucket in found:
            mine = want.get((role, bucket), [])
            if not mine:
                continue
            with open(path, encoding='utf-8') as f:
                text = f.read()
            # Ours completely. Whatever the plan no longer names loses
            # its binding before the plan's bindings go in.
            text = unbind_ours(text, {a for a, _i, _c in mine})
            for action, info, code in mine:
                text, _ok = bind_into(text, action, info, code)
            files[path] = text
        return files


if __name__ == '__main__':
    sys.exit(adapter.run(Msfs))

#!/usr/bin/env python3
"""plan.py - lay out X4 Foundations on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write the result into X4's own profile.

FILES
    harvest.py          the action vocabulary
    inputmap_3.xml      written by --write, under the Proton prefix
    KNEEBOARD.md        written by --sheet
    kneeboard.html      written by --html

ENVIRONMENT
    X4_PROFILE          profile file to write (default inputmap_3.xml)
    X4_SLOTS            override slot detection, e.g. "stick=2,throttle=3"
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close X4 first: it rewrites these files on exit.
    Every id in the needs file is checked against the vocabulary before
    anything runs.
"""

# Declarations, and X4's profile format. Nothing else. The layout, the
# listing, the kneeboard, the review screen and the walk down the
# placements are the core's, and every game answers the same interface.
#
# X4 works out one thing for itself: which SLOT a device is. A slot is not
# hardware identity. It is a number X4 assigned by enumeration order and
# wrote into one profile, so the device map cannot hold it and
# `Adapter.device_id` cannot answer it.

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

from core import adapter                                    # noqa: E402
from core import game                                       # noqa: E402

harvest = adapter.from_file('x4harvest', os.path.join(HERE, 'harvest.py'))

#: X4 writes the game's own binding changes into `inputmap.xml`, which is
#: the working copy. So a named profile is the only place a generated
#: layout survives an edit in the menu.
DEFAULT_PROFILE = 'inputmap_3.xml'

#: One element per line, self-closing, two spaces in. The attribute order
#: is not fixed in the files X4 writes: `toggle` sits between source and
#: code. So a line is matched by element first and by attribute second.
LINE = re.compile(r'^[ \t]*<(action|state|range)\s+([^>]*?)\s*/>[ \t]*\r?\n',
                  re.M)
ATTR = re.compile(r'(\w+)="([^"]*)"')


def source(slot, axis=False):
    """INPUT_SOURCE_JOYBUTTONS_2 and friends. Slot 1 carries no suffix."""
    stem = 'INPUT_SOURCE_JOYAXES' if axis else 'INPUT_SOURCE_JOYBUTTONS'
    return stem if slot == 1 else f'{stem}_{slot}'


def render(kind, ident, src, code, indent='  '):
    return f'{indent}<{kind} id="{ident}" source="{src}" code="{code}"/>\n'


def rewrite(text, wanted, ours):
    """Replace every binding on our devices with the plan's.

    A writer removes as well as adds. An id dropped from the needs file has
    to stop answering, and a button that carried something else must not
    keep it.

    X4 makes that clean, because `source` names the hardware. Every line
    that points at our slots goes, and the keyboard, mouse, compass and VR
    lines are untouched.

    Matching on the id alone is wrong. Up to three lines share one id:
    `INPUT_ACTION_OPEN_MAP` is a keyboard line AND a joystick line, and
    replacing the element takes the keyboard binding with it.
    """
    keep, last = [], 0
    for m in LINE.finditer(text):
        a = dict(ATTR.findall(m.group(2)))
        if a.get('source') in ours:
            keep.append(text[last:m.start()])
            last = m.end()
    keep.append(text[last:])
    text = ''.join(keep)

    block = ''.join(render(k, i, s, c) for k, i, s, c in wanted)
    close = text.rindex('</inputmap>')
    return text[:close] + block + text[close:]


@typing.final
class X4(adapter.Planner):
    """X4 Foundations, on the VIRPIL pair."""

    game = 'x4'
    title = 'X4 Foundations'
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'x4-needs.json'
    BINDS = 'x4-binds.json'
    CATALOGUE = 'x4-actions.json'
    CACHE = {'x4-actions.json': 'actions'}
    MODES = harvest.MODES
    AXES = harvest.AXES
    BUTTON = harvest.BUTTON
    BUTTON_FROM = harvest.BUTTON_FROM
    BUTTON_NAMES = harvest.BUTTON_NAMES
    PATHS = (('profile', 'where'),)
    SAYS = {'profile': 'which profile file to write',
            'slots': 'which device X4 enumerated as which slot, when it '
                     'has them in another order (X4_SLOTS sets it)'}

    def __init__(self, profile=None, slots=None, backup_dir=None):
        self.profile = profile or os.environ.get('X4_PROFILE',
                                                 DEFAULT_PROFILE)
        self.forced_slots = slots or os.environ.get('X4_SLOTS', '')
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {self.profile}'
        self.where = os.path.join(harvest.profile_dir(), self.profile)

    def _slots(self):
        """{role: X4 slot number}.

        X4 names a device by its position in enumeration order, and it
        keeps no device list in the file. The number is therefore not
        stable, and it means nothing outside the profile that wrote it. It
        is read back off the profile, and `X4_SLOTS` overrides it.

        A third device is in the mix here. The Steam Controller puck
        enumerates as a pad and holds slot 1 in this profile, so the
        VIRPIL pair are slots 2 and 3.
        """
        forced = {}
        for part in filter(None, self.forced_slots.split(',')):
            role, _, num = part.partition('=')
            forced[role.strip()] = int(num)
        if set(forced) >= set(self.ROLES):
            return forced

        profs = harvest.profiles()
        if self.profile not in profs:
            sys.exit(f'{self.profile} is not in the profile folder. These '
                     'are: ' + ', '.join(sorted(profs)) + '.')
        guessed = harvest.slots(profs[self.profile])
        out = dict(forced)
        for slot, info in guessed.items():
            role = info['guess']
            if role in self.ROLES and role not in out:
                out[role] = int(slot.lstrip('_'))
        missing = set(self.ROLES) - set(out)
        if missing:
            sys.exit('Nothing says which X4 slot is the '
                     f'{", ".join(sorted(missing))} in {self.profile}.\n'
                     '  These are the slots it saw: '
                     + ', '.join(f'{s} is the {i["guess"]} '
                                 f'({len(i["axes"])} axes)'
                                 for s, i in sorted(guessed.items()))
                     + '.\n  Say which with X4_SLOTS="stick=2,throttle=3".')
        return out

    @typing.override
    def write_layout(self, rows, layout):
        """X4's profile, for the bindings it is handed.

        Every line whose source is one of our slots is dropped before ours
        go in. That is how a binding cut from the needs file stops
        answering. No signature can state that clause, and
        `tests/test_contract.py` holds it.
        """
        if game.running('X4', 'X4.exe'):
            raise SystemExit('X4 is running. It rewrites these files when '
                             'it exits. Quit the game first.')
        if not os.path.exists(self.where):
            raise SystemExit(f'{self.where} does not exist. Save a profile '
                             'of that name in the game once. X4 then '
                             'creates it.')
        slot = self._slots()
        with open(self.where, encoding='utf-8') as f:
            text = f.read()
        ours = {source(slot[r], axis=a)
                for r in self.ROLES for a in (False, True)}
        # `kind_of` reads `action`, `state` or `range` off the id. That is
        # X4's own convention: the id says which of the three elements it
        # is, in its own prefix.
        wanted = [(harvest.kind_of(b.action), b.action,
                   source(slot[b.role], axis=b.axis), b.slot)
                  for b in rows if b.slot]
        return {self.where: rewrite(text, wanted, ours)}


if __name__ == '__main__':
    sys.exit(adapter.run(X4))

#!/usr/bin/env python3
"""harvest.py - read MSFS's action vocabulary

DESCRIPTION
    Read the profiles MSFS ships and report every bindable action.

FILES
    msfs-actions.json   written: every action, with the contexts it lives in

OPTIONS
    --game-dir PATH     the MSFS install (auto-detected otherwise)
"""

# Read what MSFS can be told to do, from the profiles it ships.
#
# MSFS 2024 accepts about 1700 actions. It ships 551 default profiles
# covering 101 devices, split by aircraft category, and between them they
# name the vocabulary.
#
# One thing comes out:
#
#   msfs-actions.json   every action name seen, with its contexts
#
# It does not belong in version control. It is derived from Asobo's files.
#
# How many profiles bound each action is not read. That is a count of what
# Asobo's authors did with a hundred other devices.
#
#     ./harvest.py                  # find the Steam install
#     ./harvest.py --game-dir PATH

import collections
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions
from core import adapter                                    # noqa: E402

CANDIDATES = [
    '~/.local/share/Steam/steamapps/common/MSFS2024',
    '~/.steam/steam/steamapps/common/MSFS2024',
    '/mnt/*/SteamLibrary/steamapps/common/MSFS2024',
]


def find_game(explicit=None):
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        sys.exit(f'There is no directory at {explicit}.')
    for c in CANDIDATES:
        for p in glob.glob(os.path.expanduser(c)):
            if os.path.isdir(os.path.join(p, 'Packages')):
                return p
    sys.exit('Nothing found MSFS2024. Pass --game-dir.')


def profiles(game_dir):
    """The shipped defaults, as (category, device, tree)."""
    root = os.path.join(game_dir, 'Packages', 'asobo-input-profiles-pc',
                        'InputProfiles', 'Categories')
    for path in sorted(glob.glob(os.path.join(root, '*', '*.xml'))):
        category = os.path.basename(os.path.dirname(path))
        try:
            # The files carry a BOM, and some carry a stray encoding.
            tree = ET.fromstring(open(path, encoding='utf-8-sig').read())
        except ET.ParseError:
            continue
        dev = tree.find('.//Device')
        name = dev.get('DeviceName', '') if dev is not None else ''
        yield category, name, tree, path


USER_PROFILES = os.path.expanduser(
    '~/.local/share/Steam/userdata/*/2537590/remote/inputprofile_*')


def user_actions():
    """Every action the game knows, from the profiles it wrote for you.

    The shipped defaults mention what somebody chose to bind, which is 699
    actions. A profile the sim generates carries all 1710. A missing action
    is a binding the program refuses to write and the game would have
    accepted.
    """
    out = {}
    for path in sorted(glob.glob(USER_PROFILES)):
        if '.bak.' in path:
            continue
        raw = open(path, encoding='utf-8', errors='replace').read()
        ctx = None
        for m in re.finditer(r'<Context ContextName="([^"]*)"|'
                             r'<Action ActionName="([^"]*)"', raw):
            if m.group(1):
                ctx = m.group(1)
            else:
                out.setdefault(m.group(2), set()).add(ctx or '')
    return out


def harvest(game_dir):
    actions = {}                       # name -> {'contexts': set}
    seen_profiles = collections.Counter()

    for category, device, tree, _path in profiles(game_dir):
        seen_profiles[category] += 1
        for ctx in tree.iter('Context'):
            ctx_name = ctx.get('ContextName', '')
            for act in ctx.iter('Action'):
                name = act.get('ActionName')
                if not name:
                    continue
                actions.setdefault(name, {'contexts': set()})
                actions[name]['contexts'].add(ctx_name)
        for axis in tree.iter('Axis'):
            nm = axis.get('AxisName')
            if nm:
                actions.setdefault(f'AXIS:{nm}', {'contexts': {'AXES'}})

    # The shipped profiles name what somebody bound. A profile the sim
    # wrote for this machine names everything.
    for name, ctxs in user_actions().items():
        actions.setdefault(name, {'contexts': set()})
        actions[name]['contexts'] |= ctxs

    return actions, seen_profiles


#: Which file a binding goes into, as the kneeboard's columns. MSFS keeps
#: two profiles per device. The one carrying `<AircraftInfo/>` holds the
#: flying actions. The one without it holds cameras, radio, and whatever
#: applies however you fly.
#:
#: This is a property of the BINDING and not of the action: it is which
#: file somebody put the binding in. So it rides on `actions.Bind.mode`
#: and it is not written onto the action below. No rule over an action
#: name will find it.
#: What MSFS calls each axis, in `adapter.HID_AXES` order, and the code it
#: writes beside the name. Confirmed against the owner's own profiles for
#: X, Y, Z, Rx and Slider. The rest follow the same +0x10 step and want
#: checking in the sim.
#:
#: Two parallel tuples, not pairs. `Adapter.AXES` is the name, and the
#: core indexes it by HID position. The code travels beside it in
#: `AXIS_CODES`, which only the writer reads.
AXES = ('Joystick L-Axis X ', 'Joystick L-Axis Y ', 'Joystick L-Axis Z ',
        'Joystick R-Axis X ', 'Joystick R-Axis Y ', 'Joystick R-Axis Z ',
        'Joystick Slider X ', 'Joystick Slider Y ')
AXIS_CODES = (1026, 1042, 1058, 770, 786, 802, 514, 530)

#: How MSFS spells a button. It shows a number that counts from one and
#: stores a code that counts from zero, so the name is the index plus one
#: and the code is the index.
BUTTON, BUTTON_FROM = 'Joystick Button {n}', 1

PLANE, HELI, GLOBAL = 'plane', 'heli', 'glob'
MODES = (PLANE, HELI, GLOBAL)


def catalogue(actions=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    MSFS marks an axis by putting `AXIS:` in front of the name, so the
    kind and the readable name come out of one string.

    The contexts an action appears in are its `category`. That is what
    they are: the game's own grouping, and what the vocabulary screen
    groups by. They are not its `mode`. See `MODES`.
    """
    actions = actions or {}
    return [cactions.Action(name, name.removeprefix('AXIS:'),
                            kind='axis' if name.startswith('AXIS:')
                            else 'button',
                            category=', '.join(sorted(ctxs)) or None)
            for name, ctxs in sorted(actions.items())]


@typing.final
class MsfsHarvest(adapter.Harvest):
    """MSFS's action vocabulary.

    `msfs-actions.json` carries an "actions" envelope. `core.vocab.save`
    writes the sections it is given, so it cannot emit a bare mapping.

    The cache is derived from the installed game and it is in
    `.gitignore`, so one `--json` run rebuilds it. `games/msfs/plan.py`
    has to know the key, or it reads a cache that is there and shaped
    wrong.
    """

    game = 'msfs'
    files = {'msfs-actions.json': ('actions',)}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--game-dir',
                            help='Where MSFS is installed.')

    @typing.override
    def read(self, args):
        self.where = find_game(args.game_dir)
        actions, counts = harvest(self.where)
        self.counts = counts
        return {'msfs-actions.json': {
            'actions': cactions.dump(catalogue(
                {k: sorted(v['contexts'])
                 for k, v in sorted(actions.items())}))}}

    @typing.override
    def summary(self, data):
        out = [f'game: {self.where}',
               f"{len(data['msfs-actions.json']['actions'])} actions"]
        for c, n in sorted(self.counts.items()):
            out.append(f'  {c:16s} {n:3d} profiles read')
        return out


if __name__ == '__main__':
    sys.exit(MsfsHarvest().main())

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
# MSFS 2024 has ~1700 bindable actions. It ships 551 default profiles covering
# 101 devices, split by aircraft category, and between them they name the
# vocabulary -- which is what this reads them for.
#
# One thing comes out:
#
#   msfs-actions.json   every action name seen, with the contexts it lives in
#
# It does not belong in version control: it is derived from Asobo's files.
#
# How many of those profiles bound each action used to come out too, and the
# plan used it to break ties. It is a count of what Asobo's authors did with
# a hundred other devices, so it is gone from the whole family.
#
#     ./harvest.py                  # auto-detect the Steam install
#     ./harvest.py --game-dir PATH

import argparse
import collections
import glob
import json
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
            # the files carry a BOM and occasional stray encodings
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

    The shipped defaults only mention what somebody chose to bind, which is
    699 of them -- a profile the sim generates carries all 1710. Missing one
    means refusing to write a binding the game would have accepted.
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

    # the shipped profiles name only what someone bound; a profile the sim
    # wrote for this machine names everything
    for name, ctxs in user_actions().items():
        actions.setdefault(name, {'contexts': set()})
        actions[name]['contexts'] |= ctxs

    return actions, seen_profiles


def catalogue(actions=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    MSFS marks an axis by prefixing the name with `AXIS:`, so the kind and
    the readable name come out of the same string.
    """
    actions = actions or {}
    return [cactions.Action(name, name.removeprefix('AXIS:'),
                            kind='axis' if name.startswith('AXIS:')
                            else 'button',
                            mode=', '.join(sorted(ctxs)) or None)
            for name, ctxs in sorted(actions.items())]


def action_rows(actions=None):
    """The section the cache holds."""
    return cactions.dump(catalogue(actions))


@typing.final
class MsfsHarvest(adapter.Harvest):
    """MSFS's action vocabulary.

    `msfs-actions.json` gains an "actions" envelope here. It was the one
    cache in the family whose top level WAS the data, because it was written
    by hand with `json.dump`; `core.vocab.save` writes the sections it is
    given and so can never emit a bare mapping. The cache is derived from
    the installed game and gitignored, so the migration is one `--json` run
    -- but `games/msfs/plan.py` had to learn the key in the same commit, or
    it reads a cache that is there and shaped wrong.
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
            'actions': action_rows({k: sorted(v['contexts'])
                                    for k, v in sorted(actions.items())})}}

    @typing.override
    def summary(self, data):
        out = [f'game: {self.where}',
               f"{len(data['msfs-actions.json']['actions'])} actions"]
        for c, n in sorted(self.counts.items()):
            out.append(f'  {c:16s} {n:3d} profiles read')
        return out


if __name__ == '__main__':
    sys.exit(MsfsHarvest().main())

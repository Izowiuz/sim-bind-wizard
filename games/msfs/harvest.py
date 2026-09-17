#!/usr/bin/env python3
"""Read what a HOTAS is expected to carry, from the profiles MSFS ships.

MSFS 2024 has ~1700 bindable actions and offers no hint where to start. It also
ships 551 default profiles covering 101 devices, split by aircraft category --
which is a far better answer to "what matters" than any list anyone could write
by hand, and the same trick that drives the DCS and War Thunder wizards.

Two things come out:

  msfs-actions.json   every action name seen, with the contexts it lives in
  msfs-rank.json      how many shipped profiles bind each action, per category

Neither belongs in version control: both are derived from Asobo's files.

    ./harvest.py                  # auto-detect the Steam install
    ./harvest.py --game-dir PATH
"""

import argparse
import collections
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

CANDIDATES = [
    '~/.local/share/Steam/steamapps/common/MSFS2024',
    '~/.steam/steam/steamapps/common/MSFS2024',
    '/mnt/*/SteamLibrary/steamapps/common/MSFS2024',
]


def find_game(explicit=None):
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        sys.exit(f'no such directory: {explicit}')
    for c in CANDIDATES:
        for p in glob.glob(os.path.expanduser(c)):
            if os.path.isdir(os.path.join(p, 'Packages')):
                return p
    sys.exit('could not find MSFS2024 -- pass --game-dir')


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
    rank = collections.defaultdict(collections.Counter)   # cat -> Counter
    seen_profiles = collections.Counter()

    for category, device, tree, _path in profiles(game_dir):
        seen_profiles[category] += 1
        bound = set()
        for ctx in tree.iter('Context'):
            ctx_name = ctx.get('ContextName', '')
            for act in ctx.iter('Action'):
                name = act.get('ActionName')
                if not name:
                    continue
                actions.setdefault(name, {'contexts': set()})
                actions[name]['contexts'].add(ctx_name)
                # only a KEY under Primary/Secondary counts as bound
                if act.find('.//KEY') is not None:
                    bound.add(name)
        for axis in tree.iter('Axis'):
            nm = axis.get('AxisName')
            if nm:
                actions.setdefault(f'AXIS:{nm}', {'contexts': {'AXES'}})
        rank[category].update(bound)

    # the shipped profiles name only what someone bound; a profile the sim
    # wrote for this machine names everything
    for name, ctxs in user_actions().items():
        actions.setdefault(name, {'contexts': set()})
        actions[name]['contexts'] |= ctxs

    return actions, rank, seen_profiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir')
    args = ap.parse_args()

    game = find_game(args.game_dir)
    print(f'game: {game}')
    actions, rank, counts = harvest(game)

    a_path = os.path.join(HERE, 'msfs-actions.json')
    json.dump({k: sorted(v['contexts']) for k, v in sorted(actions.items())},
              open(a_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'{os.path.basename(a_path)}: {len(actions)} actions')

    r_path = os.path.join(HERE, 'msfs-rank.json')
    json.dump({'profiles': dict(counts),
               'rank': {c: k.most_common() for c, k in rank.items()}},
              open(r_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    for c, n in sorted(counts.items()):
        top = rank[c].most_common(1)
        print(f'  {c:16s} {n:3d} profiles, {len(rank[c]):4d} actions bound'
              + (f', top: {top[0][0]} ({top[0][1]})' if top else ''))


if __name__ == '__main__':
    main()

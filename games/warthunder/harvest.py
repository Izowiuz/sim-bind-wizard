#!/usr/bin/env python3
"""harvest.py - read War Thunder's action vocabulary

DESCRIPTION
    Unpack the game's archives and report every bindable action and axis
    with its menu name.

FILES
    wt-actions.json        written: every action and axis, with its menu name

OPTIONS
    --game-dir PATH        the War Thunder install (auto-detected otherwise)

NOTES
    plan.py refuses to write an action that is not in the vocabulary: War
    Thunder drops an unknown id in silence.
"""

# Rebuild the game vocabulary this wizard validates against, from the game.
#
# One file comes out, and it does not belong in version control -- it is
# Gaijin's own localisation:
#
#   wt-actions.json      every bindable action and axis, with its menu name.
#                        plan.py refuses to write an action that is not in here,
#                        because War Thunder drops an unknown id in silence.
#
# The joystick profiles the game ships used to be counted as well -- how many
# of them bound each action, decoded out of the binary .blk presets. Those
# profiles are old and lean arcade; they predate countermeasures and radar,
# and what they rank is Gaijin's layout for other hardware. Gone, with the
# .blk decoder that existed for them.
#
# The archives are `VRFx` containers: zstd, with the first and last 16 bytes of
# the compressed body XORed against a fixed key. Inside sits a flat filesystem.
# The preset files are binary .blk, zstd-compressed against a dictionary shipped
# alongside them, with their key names in a nametable shared across the archive.
#
#     ./harvest.py                       # auto-detect the Steam install
#     ./harvest.py --game-dir /path/to/War\ Thunder

import argparse
import csv
import io
import json
import os
import struct
import sys

try:
    import zstandard
except ImportError:
    sys.exit('This needs python-zstandard. Run: pip install zstandard')

import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions
from core import adapter                                    # noqa: E402

CANDIDATES = [
    '~/.local/share/Steam/steamapps/common/War Thunder',
    '~/.steam/steam/steamapps/common/War Thunder',
    '/mnt/*/SteamLibrary/steamapps/common/War Thunder',
    '~/WarThunder',
]

# The first and last 16 bytes of a packed body are obfuscated with these.
KEY1 = bytes.fromhex('55aa55aa0ff00ff055aa55aa48124812')
KEY2 = bytes.fromhex('4812481255aa55aa0ff00ff055aa55aa')


def find_game(explicit=None):
    import glob
    if explicit:
        if os.path.isdir(explicit):
            return explicit
        sys.exit(f'There is no directory at {explicit}.')
    for c in CANDIDATES:
        for p in glob.glob(os.path.expanduser(c)):
            if os.path.isfile(os.path.join(p, 'aces.vromfs.bin')):
                return p
    sys.exit('Nothing found War Thunder. Pass --game-dir.')


def _xor(a, k):
    return bytes(x ^ y for x, y in zip(a, k))


def unpack_vromfs(path):
    """VRFx container -> the bytes of the filesystem inside it."""
    raw = open(path, 'rb').read()
    magic, _plat, orig, pkflags = struct.unpack_from('<4s4sII', raw, 0)
    if magic not in (b'VRFx', b'VRFs'):
        sys.exit(f'{path}: not a vromfs container')
    psize = pkflags & 0x03FFFFFF
    off = 16
    if magic == b'VRFx':
        ext_size = struct.unpack_from('<H', raw, 16)[0]
        off = 16 + ext_size
    body = bytearray(raw[off:off + psize])
    if len(body) >= 16:
        body[:16] = _xor(body[:16], KEY1)
    if len(body) >= 32:
        pos = (len(body) & ~3) - 16
        body[pos:pos + 16] = _xor(body[pos:pos + 16], KEY2)
    d = zstandard.ZstdDecompressor()
    try:
        return d.decompress(bytes(body), max_output_size=orig + 4096)
    except zstandard.ZstdError:
        return d.decompressobj().decompress(bytes(body))


def vfs_files(data):
    """name -> bytes, for everything in an unpacked archive."""
    names_off, names_cnt = struct.unpack_from('<II', data, 0)
    data_off, _ = struct.unpack_from('<II', data, 16)
    out = {}
    for i in range(names_cnt):
        (p,) = struct.unpack_from('<Q', data, names_off + i * 8)
        name = data[p:data.index(b'\x00', p)].decode('utf-8', 'replace')
        off, size, _a, _b = struct.unpack_from('<IIII', data, data_off + i * 16)
        out[name] = data[off:off + size]
    return out


# ----------------------------------------------------------------- harvest --

def harvest(game_dir):
    lang = vfs_files(unpack_vromfs(os.path.join(game_dir, 'lang.vromfs.bin')))
    csv_bytes = lang.get('lang/controls.csv')
    if not csv_bytes:
        sys.exit('lang.vromfs.bin has no lang/controls.csv file.')
    rows = list(csv.reader(io.StringIO(csv_bytes.decode('utf-8', 'replace')),
                           delimiter=';', quotechar='"'))
    head = rows[0]
    i_en, i_pl = head.index('<English>'), head.index('<Polish>')
    actions, controls = {}, {}
    for r in rows[1:]:
        if not r or len(r) <= max(i_en, i_pl):
            continue
        key = r[0]
        if key.startswith('hotkeys/ID_'):
            actions[key.split('/', 1)[1]] = [r[i_en], r[i_pl]]
        elif key.startswith('controls/'):
            controls[key.split('/', 1)[1]] = [r[i_en], r[i_pl]]

    return actions, controls


def is_heli(action):
    """War Thunder is not consistent: most helicopter actions carry
    `_HELICOPTER` as a suffix, but a handful wear it as a prefix
    (`ID_HELICOPTER_TRIM`). Getting this wrong puts two actions on one
    button in the same context and the game drops one of them."""
    return (action.endswith('_HELICOPTER')
            or action.startswith('ID_HELICOPTER'))


def contexts(action, known):
    """Which vehicle contexts an action actually applies to.

    The trap: a twin has to be looked for in BOTH forms. And an action with
    no twin in either form is SHARED -- it applies to helicopters as well
    as aircraft, whatever we meant by putting it there.
    `ID_TRIM_ELEVATOR_MINUS` has no helicopter twin, so it is live in a
    helicopter too.

    `known` is every id there is, because a twin is only absent relative to
    the whole vocabulary -- which is why this lives here, where the whole
    vocabulary is being read anyway.
    """
    if is_heli(action):
        return ('heli',)
    twins = (action + '_HELICOPTER',
             action.replace('ID_', 'ID_HELICOPTER_', 1))
    if any(t in known for t in twins):
        return ('air',)
    return ('air', 'heli')


def catalogue(actions=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    The English half of the localised pair is the name.
    """
    actions = actions or {}
    known = set(actions)
    return [cactions.Action(i, (names[0] if names else i), kind='button',
                            mode='/'.join(contexts(i, known)))
            for i, names in sorted(actions.items())]


def action_rows(actions=None):
    """The section the cache holds."""
    return cactions.dump(catalogue(actions))


@typing.final
class WarThunderHarvest(adapter.Harvest):
    """War Thunder's vocabulary."""

    game = 'warthunder'
    files = {'wt-actions.json': ('actions', 'local', 'controls')}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--game-dir',
                            help='Where War Thunder is installed.')

    @typing.override
    def read(self, args):
        self.where = find_game(args.game_dir)
        actions, controls = harvest(self.where)
        # The record, not the raw localised pairs: the English half is the
        # name, and which contexts an action answers in is a fact about
        # War Thunder's naming that is settled here, where the whole
        # vocabulary is in hand to look for a twin in.
        # The Polish half stays in a section of War Thunder's own: the
        # shared record carries one name, and translating it is a fact
        # about this game's language files, not about actions. Only the
        # half that does not fit -- the English one is already in the
        # record and is not written twice.
        local = {i: names[1] for i, names in actions.items()
                 if len(names) > 1 and names[1]}
        return {'wt-actions.json': {'actions': action_rows(actions),
                                    'local': local,
                                    'controls': controls}}

    @typing.override
    def summary(self, data):
        vocab = data['wt-actions.json']
        return [f'game: {self.where}',
                f"{len(vocab['actions'])} actions, "
                f"{len(vocab['controls'])} axis names"]


if __name__ == '__main__':
    sys.exit(WarThunderHarvest().main())

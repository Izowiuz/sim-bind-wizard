#!/usr/bin/env python3
"""Rebuild the game vocabulary this wizard validates against, from the game.

Two files come out, and neither belongs in version control -- one is Gaijin's
localisation, the other is derived from the presets they ship:

  wt-actions.json      every bindable action and axis, with its menu name.
                       plan.py refuses to write an action that is not in here,
                       because War Thunder drops an unknown id in silence.
  wt-factory-rank.json how many of the joystick profiles the game ships bind
                       each action. Not a verdict -- those profiles are old and
                       lean arcade, they predate countermeasures and radar --
                       but a useful prior on what a HOTAS is expected to carry.

The archives are `VRFx` containers: zstd, with the first and last 16 bytes of
the compressed body XORed against a fixed key. Inside sits a flat filesystem.
The preset files are binary .blk, zstd-compressed against a dictionary shipped
alongside them, with their key names in a nametable shared across the archive.

    ./harvest.py                       # auto-detect the Steam install
    ./harvest.py --game-dir /path/to/War\\ Thunder
"""

import argparse
import csv
import collections
import io
import json
import os
import struct
import sys

try:
    import zstandard
except ImportError:
    sys.exit('needs python-zstandard: pip install zstandard')

HERE = os.path.dirname(os.path.abspath(__file__))

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
        sys.exit(f'no such directory: {explicit}')
    for c in CANDIDATES:
        for p in glob.glob(os.path.expanduser(c)):
            if os.path.isfile(os.path.join(p, 'aces.vromfs.bin')):
                return p
    sys.exit('could not find War Thunder -- pass --game-dir')


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


# ------------------------------------------------------------ binary .blk --

TYPES = {0x01: 'str', 0x02: 'int', 0x03: 'float', 0x09: 'bool'}


def _varint(buf, i):
    shift = res = 0
    while True:
        b = buf[i]
        i += 1
        res |= (b & 0x7f) << shift
        if not b & 0x80:
            return res, i
        shift += 7


def decode_blk(raw, names, dctx):
    """Marker 0x05: zstd against the shared dictionary, names from the shared
    nametable. Returns the root block as nested dicts."""
    if not raw or raw[0] != 0x05:
        return None
    body = dctx.decompressobj().decompress(raw[1:])
    i = 0
    names_count, i = _varint(body, i)
    if names_count:
        return None                      # local nametable: not used by presets
    blocks_count, i = _varint(body, i)
    params_count, i = _varint(body, i)
    params_size, i = _varint(body, i)
    pdata = body[i:i + params_size]
    i += params_size
    praw = body[i:i + params_count * 8]
    i += params_count * 8

    params = []
    for k in range(params_count):
        p = praw[k * 8:k * 8 + 8]
        nid = int.from_bytes(p[0:3], 'little')
        typ, v = p[3], p[4:8]
        if typ == 0x02:
            val = int.from_bytes(v, 'little', signed=True)
        elif typ == 0x03:
            val = struct.unpack('<f', v)[0]
        elif typ == 0x09:
            val = bool(v[0])
        elif typ == 0x01:
            o = int.from_bytes(v, 'little') & 0x7fffffff
            end = pdata.index(b'\x00', o) if o < len(pdata) else o
            val = pdata[o:end].decode('utf-8', 'replace')
        else:
            val = v.hex()
        nm = names[nid].decode('utf-8', 'replace') if nid < len(names) else ''
        params.append((nm, TYPES.get(typ, hex(typ)), val))

    blocks = []
    for _ in range(blocks_count):
        nid, i = _varint(body, i)
        pc, i = _varint(body, i)
        bc, i = _varint(body, i)
        fb = 0
        if bc:
            fb, i = _varint(body, i)
        nm = '' if nid == 0 else (names[nid - 1].decode('utf-8', 'replace')
                                  if nid - 1 < len(names) else '')
        blocks.append((nm, pc, bc, fb))

    cur = [0]
    nodes = []
    for nm, pc, bc, fb in blocks:
        nodes.append({'name': nm, 'params': params[cur[0]:cur[0] + pc],
                      'blocks': []})
        cur[0] += pc
    for bi, (_nm, _pc, bc, fb) in enumerate(blocks):
        nodes[bi]['blocks'] = [nodes[fb + k] for k in range(bc)]
    return nodes[0] if nodes else None


def sub(node, name):
    return next((b for b in node['blocks'] if b['name'] == name), None)


# ----------------------------------------------------------------- harvest --

# profiles for a gamepad, a keyboard or a console pad say nothing about a HOTAS
NOT_HOTAS = ('gamepad', 'xinput', 'dualshock', 'xboxone', 'steamdeck', 'ps4',
             'keyboard', 'empty', 'event', 'vrdevice', 'fragfx', 'hori_hpc',
             'default')


def harvest(game_dir):
    lang = vfs_files(unpack_vromfs(os.path.join(game_dir, 'lang.vromfs.bin')))
    csv_bytes = lang.get('lang/controls.csv')
    if not csv_bytes:
        sys.exit('lang.vromfs.bin has no lang/controls.csv')
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

    aces = vfs_files(unpack_vromfs(os.path.join(game_dir, 'aces.vromfs.bin')))
    nm_raw = next((v for k, v in aces.items() if k.endswith('nm')), None)
    dct_raw = next((v for k, v in aces.items() if k.endswith('.dict')), None)
    rank = collections.Counter()
    n_profiles = 0
    if nm_raw and dct_raw:
        # the nametable is plain zstd; the .blk files need it as a dictionary
        names = zstandard.ZstdDecompressor().decompressobj() \
            .decompress(nm_raw[40:]).split(b'\x00')
        dctx = zstandard.ZstdDecompressor(
            dict_data=zstandard.ZstdCompressionDict(dct_raw))
        for path, raw in aces.items():
            if not path.startswith('config/hotkeys/hotkey.'):
                continue
            if any(g in os.path.basename(path) for g in NOT_HOTAS):
                continue
            try:
                root = decode_blk(raw, names, dctx)
            except Exception:
                continue
            ctl = sub(root, 'controls') if root else None
            if not ctl:
                continue
            hk, ax = sub(ctl, 'hotkeys'), sub(ctl, 'axes')
            seen = set()
            for b in (hk['blocks'] if hk else []):
                if any(n == 'joyButton' for n, _, _ in b['params']):
                    seen.add(b['name'])
            for b in (ax['blocks'] if ax else []):
                if any(n == 'axisId' for n, _, _ in b['params']):
                    seen.add(b['name'])
            if seen:
                n_profiles += 1
                rank.update(seen)
    return actions, controls, rank, n_profiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game-dir', help='where War Thunder is installed')
    args = ap.parse_args()

    game = find_game(args.game_dir)
    print(f'game: {game}')
    actions, controls, rank, n = harvest(game)

    a_path = os.path.join(HERE, 'wt-actions.json')
    json.dump({'actions': actions, 'controls': controls},
              open(a_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(f'{a_path}: {len(actions)} actions, {len(controls)} axis names')

    if n:
        r_path = os.path.join(HERE, 'wt-factory-rank.json')
        acts = [(k, v) for k, v in rank.most_common() if k.startswith('ID_')]
        axes = [(k, v) for k, v in rank.most_common() if not k.startswith('ID_')]
        json.dump({'n': n, 'actions': acts, 'axes': axes},
                  open(r_path, 'w', encoding='utf-8'), ensure_ascii=False,
                  indent=0)
        print(f'{r_path}: {n} factory joystick profiles')
    else:
        print('no factory profiles decoded -- the ranking was left alone',
              file=sys.stderr)


if __name__ == '__main__':
    main()

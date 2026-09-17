#!/usr/bin/env python3
"""Read what X4 Foundations can be told to do, and how it names our devices.

X4 is the friendliest target of the family. Its bindings live in plain XML in
the Proton prefix, one file per named profile, and every binding is one line:

    <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
            source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>

Three element types, and the difference matters when deciding what a control
should carry:

    <action>  fires once on press          280 of them
    <state>   true while held              113
    <range>   an axis                       34

`source` names the device by SLOT -- `JOYBUTTONS`, `_2`, `_3` -- and `code` is
LOCAL to that device. No global numbering to undo, unlike War Thunder and BMS.

Two things this cannot tell us, and one of them still needs measuring:

- Which slot is which device. There is no device list anywhere in the config,
  so the slots follow enumeration order. `slots()` infers it from an existing
  profile instead: the slot carrying THROTTLE on RX is the throttle, the slot
  whose codes are all Xbox names is a gamepad.
- What `INPUT_XBUTTON_17` is in terms of the button index the device map uses.
  X4 mixes Xbox names with bare numbers and it is not established whether they
  share one numbering. NOT GUESSED HERE -- see `CODES` below.
"""

import argparse
import collections
import os
import re
import sys

#: Steam appid, and where the game keeps its profiles inside the prefix.
APPID = '392160'
PROFILE_DIR = ('drive_c/users/steamuser/Documents/Egosoft/X4')

ROW = re.compile(r'<(action|state|range)\s+id="([^"]+)"\s+'
                 r'source="([^"]+)"\s+code="([^"]+)"\s*/>')
HEADER = re.compile(r'<inputmap\s+version="(\d+)"(?:\s+id="(\d+)")?'
                    r'(?:\s+name="([^"]*)")?')

#: button index -> X4 code. DELIBERATELY EMPTY.
#:
#: X4 writes `INPUT_XBUTTON_A` for some buttons and `INPUT_XBUTTON_17` for
#: others, and whether those are one numbering or two is not established. The
#: way to find out is to bind one known button in the game's own menu and read
#: the code back out of the file -- `./harvest.py --watch` does exactly that.
#: Filling this in from a plausible-looking XInput order would be a guess, and
#: guessing what a control physically is has already cost this project two
#: wrong layouts.
CODES = {}


def profile_dir():
    """Where X4 keeps its per-player profiles, under the Steam user id."""
    if os.environ.get('X4_DIR'):
        return os.environ['X4_DIR']
    base = os.path.expanduser(
        f'~/.local/share/Steam/steamapps/compatdata/{APPID}/pfx/{PROFILE_DIR}')
    if not os.path.isdir(base):
        sys.exit(f'no X4 profiles under {base} — set X4_DIR')
    players = [os.path.join(base, d) for d in sorted(os.listdir(base))
               if os.path.isdir(os.path.join(base, d))]
    if not players:
        sys.exit(f'{base} has no player directory yet — run X4 once')
    return players[-1]


def profiles(path=None):
    """{filename: (version, id, name, [(kind, id, source, code)])}."""
    path = path or profile_dir()
    out = {}
    for name in sorted(os.listdir(path)):
        if not re.fullmatch(r'inputmap(_\d+)?\.xml', name):
            continue
        txt = open(os.path.join(path, name), encoding='utf-8',
                   errors='replace').read()
        h = HEADER.search(txt)
        out[name] = {
            'version': h.group(1) if h else '?',
            'id': h.group(2) if h else None,
            # the working copy carries no name= at all, only the saved
            # profiles do, so an absent group is the default one
            'name': (h.group(3) if h else None) or '(default)',
            'rows': ROW.findall(txt),
        }
    return out


def vocabulary(profs=None):
    """{kind: {id}} -- everything X4 will accept a binding for.

    The default profile ships every action with its stock binding, so it is
    the vocabulary as well as a layout; the named profiles can only add.
    """
    profs = profs or profiles()
    vocab = collections.defaultdict(set)
    for p in profs.values():
        for kind, ident, _src, _code in p['rows']:
            vocab[kind].add(ident)
    return {k: sorted(v) for k, v in vocab.items()}


def readable(ident):
    """`INPUT_ACTION_TOGGLE_TRAVEL_MODE` -> `Toggle travel mode`.

    X4's ids are self-describing, so there is no language file to crack -- a
    rare mercy after War Thunder's zstd archives and BMS's shared dictionary.
    """
    for prefix in ('INPUT_ACTION_', 'INPUT_STATE_', 'INPUT_RANGE_'):
        if ident.startswith(prefix):
            ident = ident[len(prefix):]
            break
    return ident.replace('_', ' ').capitalize()


AXIS_CODE = re.compile(r'INPUT_JOYAXIS_(\w+)$')
XBOX_NAME = re.compile(r'INPUT_XBUTTON_([A-Z_]+)$')


def slots(prof):
    """Work out which device slot is which, from what a profile already binds.

    It has to be ONE profile: a slot number only means something inside the
    profile that wrote it, and reading all four together blends a
    gamepad-era layout with the VIRPIL one into nonsense -- which is what
    the first version did, calling two different slots the throttle.

    Evidence, in this order:
      * a slot whose button codes are ALL Xbox names and which offers RZ is
        a gamepad. Checked FIRST, because a gamepad binds throttle to a
        trigger and would otherwise look like a throttle;
      * the slot with THROTTLE on an axis is the throttle;
      * the remaining joystick slot is the stick.
    """
    seen = collections.defaultdict(lambda: {'axes': set(), 'codes': set(),
                                            'ids': set()})
    for p in (prof,):
        for kind, ident, src, code in p['rows']:
            if 'JOY' not in src:
                continue
            slot = src.replace('INPUT_SOURCE_JOYBUTTONS', '') \
                      .replace('INPUT_SOURCE_JOYAXES', '') or '_1'
            s = seen[slot]
            s['ids'].add(ident)
            m = AXIS_CODE.match(code)
            if m:
                s['axes'].add(m.group(1))
            else:
                s['codes'].add(code)
    out = {}
    for slot, s in seen.items():
        named = sum(1 for c in s['codes'] if XBOX_NAME.match(c))
        guess = 'unknown'
        if s['codes'] and named == len(s['codes']) and 'RZ' in s['axes']:
            guess = 'gamepad'
        elif any('THROTTLE' in i for i in s['ids']):
            guess = 'throttle'
        out[slot] = {'axes': sorted(s['axes']), 'named': named,
                     'numeric': len(s['codes']) - named, 'guess': guess}
    left = [k for k, v in out.items() if v['guess'] == 'unknown']
    if len(left) == 1:
        out[left[0]]['guess'] = 'stick'
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vocab', action='store_true',
                    help='what X4 will accept a binding for')
    ap.add_argument('--grep', metavar='WORD',
                    help='vocabulary entries matching a word')
    a = ap.parse_args()

    path = profile_dir()
    profs = profiles(path)
    print(f'{path}\n')
    for name, p in profs.items():
        joy = sum(1 for k, i, s, c in p['rows'] if 'JOY' in s)
        print(f'  {name:<16} v{p["version"]:<4} {p["name"]:<20} '
              f'{len(p["rows"]):>4} bindings, {joy} on a joystick')

    v = vocabulary(profs)
    print(f'\nvocabulary  ' + ', '.join(f'{len(ids)} {k}' for k, ids in v.items()))

    for name, prof in profs.items():
        sl = slots(prof)
        if not sl:
            continue
        print(f'\ndevice slots in {name} ({prof["name"]})')
        for slot, st in sorted(sl.items()):
            print(f'  JOY{slot:<4} {st["guess"]:<9} '
                  f'axes {",".join(st["axes"]) or "-":<22}'
                  f' codes: {st["named"]} named / {st["numeric"]} numeric')

    if not CODES:
        print('\n!! CODES is empty: which button index each INPUT_XBUTTON_* means')
        print('   has not been measured. Bind one known button in X4 and read')
        print('   it back before trusting any layout this repo writes.')

    if a.grep:
        print()
        for kind, ids in v.items():
            for i in ids:
                if a.grep.lower() in i.lower():
                    print(f'  {kind:<7} {i:<52} {readable(i)}')
    elif a.vocab:
        for kind, ids in v.items():
            print(f'\n== {kind} ({len(ids)})')
            for i in ids:
                print(f'   {i:<54} {readable(i)}')


if __name__ == '__main__':
    main()

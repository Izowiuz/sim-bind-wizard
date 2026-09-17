#!/usr/bin/env python3
"""Read Elite Dangerous: every function it accepts a binding for, and how many
of the HOTAS presets it ships bind each one.

    ./harvest.py              what it found
    ./harvest.py --vocab      every function, by kind
    ./harvest.py --grep word  functions matching a word
    ./harvest.py --json       cache it, the way the other games do

In: the shipped `.binds` presets under `ControlSchemes/`. Out: two JSON files
next to this script -- the vocabulary and the ranking.

The vocabulary is `KeyboardMouseOnly.binds`, which carries every function as an
element whether or not it is bound: 311 buttons, 58 axes and 68 settings that
are not bindings at all (`MouseSensitivity`, deadzones, `YawToRollMode`).

The ranking is the other presets. Fifteen of the thirty are real HOTAS
profiles, and five of those -- the X55, X56, Warthog, T16000M and G940 -- name
the stick and the throttle as separate devices, so they say which device a
function belongs on as well as how much it matters.
"""

import argparse
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import game                                       # noqa: E402
from core import vocab                                      # noqa: E402

APPID = '359320'
INSTALL = 'Elite Dangerous'
SCHEMES = ('Products', 'elite-dangerous-odyssey-64', 'ControlSchemes')

#: the preset that carries every function whether bound or not
BASE = 'KeyboardMouseOnly.binds'

#: Presets whose device is a keyboard, a mouse, a gamepad or a VR controller.
#: Counting them would rank a gamepad's layout, which is a different machine.
NOT_HOTAS = re.compile(
    r'keyboard|mouse|blackwidow|controlpad|consolex360|ps3|playstation|'
    r'dualshock|oculus|gamepad|xb360|empty', re.I)

#: What the device name in a shipped preset says the device IS.
THROTTLE = re.compile(r'throttle', re.I)
PEDALS = re.compile(r'pedal', re.I)


def schemes_dir(path=None):
    """Where the shipped presets live."""
    if path:
        return path
    if os.environ.get('ED_DIR'):
        return os.path.join(os.environ['ED_DIR'], *SCHEMES)
    install = game.install_dir(INSTALL)
    if not install:
        sys.exit(f'{INSTALL} is not installed in any Steam library; '
                 'set ED_DIR to its folder')
    out = os.path.join(install, *SCHEMES)
    if not os.path.isdir(out):
        sys.exit(f'no ControlSchemes at {out}')
    return out


def presets(path=None):
    """{filename: Root element} for every shipped preset."""
    path = schemes_dir(path)
    out = {}
    for name in sorted(os.listdir(path)):
        if not name.endswith('.binds'):
            continue
        try:
            out[name] = ET.parse(os.path.join(path, name)).getroot()
        except ET.ParseError:
            continue
    return out


def vocabulary(path=None):
    """{kind: [function names]} -- kind is 'button' or 'axis'.

    The union across every shipped preset, not just the base one. The base
    carries the most (369 bindable), but the others name 24 it does not:
    `Humanoid*` on-foot functions, the FSS camera buttons, the store camera's
    stepped forms. Missing one makes a planner unable to name it.

    A function with no children is a setting rather than a binding and is left
    out: `MouseSensitivity` and `YawToRollMode` are numbers in the same file.

    Even the union is not the whole truth. `NightVisionToggle` is a real ship
    function, accepted in a written preset and working in game, and it appears
    in none of the thirty. A planner should treat a function bound and
    verified by hand as vouched for too.
    """
    out = collections.defaultdict(set)
    for root in presets(path).values():
        for fn in root:
            tags = {c.tag for c in fn}
            if 'Binding' in tags:
                out['axis'].add(fn.tag)
            elif 'Primary' in tags:
                out['button'].add(fn.tag)
    if not out:
        sys.exit('no presets found -- the vocabulary comes from them')
    # a function seen as both is an axis: the axis form is the richer one
    out['button'] -= out['axis']
    return {k: sorted(v) for k, v in out.items()}


def role_of(device):
    """Which of our roles a shipped preset's device name corresponds to."""
    if PEDALS.search(device):
        return 'pedals'
    if THROTTLE.search(device):
        return 'throttle'
    return 'stick'


def hotas(path=None):
    """{filename: Root} for the presets that are HOTAS rather than pad."""
    return {n: r for n, r in presets(path).items()
            if n != BASE and not NOT_HOTAS.search(n)}


def ranking(path=None):
    """{function: {'votes': n, 'where': {role: n}}}.

    `votes` is how many HOTAS presets put the function on hardware at all --
    the same measure the other games in the family use, and the only one here
    that is counted rather than judged. `where` only fills in from the five
    presets that name the stick and the throttle separately; the rest describe
    one device and cannot say.
    """
    out = {}
    for name, root in hotas(path).items():
        devices = set()
        for fn in root:
            for c in fn:
                d = c.get('Device')
                if d and d not in ('{NoDevice}', '', 'Keyboard', 'Mouse'):
                    devices.add(d)
        split = len({role_of(d) for d in devices}) > 1
        seen = set()
        for fn in root:
            for c in fn:
                d = c.get('Device')
                if not d or d in ('{NoDevice}', '', 'Keyboard', 'Mouse'):
                    continue
                rec = out.setdefault(fn.tag, {'votes': 0, 'where': {}})
                if fn.tag not in seen:
                    rec['votes'] += 1
                    seen.add(fn.tag)
                if split:
                    role = role_of(d)
                    rec['where'][role] = rec['where'].get(role, 0) + 1
    return out


_WORDS = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')

#: Words in a function name that are names rather than prose. Without these a
#: flat lower-casing turns UI_Up into "Ui up" and FSSRadioTuning into
#: "Fs sradio tuning".
ACRONYMS = {'UI', 'FSD', 'FSS', 'SRV', 'HMD', 'ESC', 'AFM', 'ADS', 'GUI',
            'DSS', 'POI', 'SLF', 'FA'}


def readable(name):
    """`LandingGearToggle` -> `Landing gear toggle`.

    The element names are the only human text Elite gives; there is no
    localisation file to read, unlike War Thunder's `controls.csv`.
    """
    words = [w for part in name.split('_')
             for w in _WORDS.sub(' ', part).split()]
    if not words:
        return name
    out = [w if w.upper() in ACRONYMS else w.lower() for w in words]
    if out[0].upper() not in ACRONYMS:
        out[0] = out[0].capitalize()
    return ' '.join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('--vocab', action='store_true',
                   help='every function, by kind')
    p.add_argument('--grep', metavar='WORD', help='functions matching a word')
    p.add_argument('--json', action='store_true', help='write the cache')
    p.add_argument('--schemes-dir', help='override the ControlSchemes lookup')
    a = p.parse_args()

    path = a.schemes_dir
    v = vocabulary(path)
    rank = ranking(path)
    profiles = hotas(path)

    if a.grep:
        for kind in ('button', 'axis'):
            for f in v.get(kind, ()):
                if a.grep.lower() in f.lower():
                    r = rank.get(f, {})
                    print(f'  {kind:7} {f:38} {r.get("votes", 0):2}/'
                          f'{len(profiles)}  {r.get("where") or ""}')
        return

    if a.vocab:
        for kind in ('button', 'axis'):
            print(f'--- {kind} ({len(v.get(kind, ()))})')
            for f in v.get(kind, ()):
                print(f'  {f}')
        return

    print(schemes_dir(path))
    print()
    print(f'vocabulary  {len(v.get("button", ()))} button, '
          f'{len(v.get("axis", ()))} axis')
    print(f'ranking     {len(rank)} functions, from '
          f'{len(profiles)} HOTAS presets')
    print()
    split = [n for n, r in profiles.items()
             if len({role_of(c.get('Device'))
                     for fn in r for c in fn
                     if c.get('Device') not in (None, '{NoDevice}', '',
                                                'Keyboard', 'Mouse')}) > 1]
    print(f'of those, {len(split)} name the stick and throttle separately:')
    for n in sorted(split):
        print(f'  {n}')
    print()
    print('most bound')
    for f, r in sorted(rank.items(), key=lambda x: -x[1]['votes'])[:18]:
        kind = 'axis' if f in v.get('axis', ()) else 'button'
        where = ' '.join(f'{k} {n}' for k, n in sorted(r['where'].items()))
        print(f'  {readable(f)[:36]:38} {kind:7} {r["votes"]:2}/'
              f'{len(profiles)}  {where}')

    if a.json:
        print()
        vocab.save(HERE, 'ed-actions.json', vocabulary=v)
        vocab.save(HERE, 'ed-rank.json', ranking=rank,
                   profiles=sorted(profiles))


if __name__ == '__main__':
    main()

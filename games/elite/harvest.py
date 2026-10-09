#!/usr/bin/env python3
"""harvest.py - read Elite's function vocabulary

DESCRIPTION
    Read the control schemes Elite ships and report every bindable
    function.

FILES
    elite-actions.json     written by --json: every function

OPTIONS
    --schemes-dir PATH  the ControlSchemes directory
"""

# Read Elite Dangerous: every function it accepts a binding for.
#
#     ./harvest.py              what it found
#     ./harvest.py --vocab      every function, by kind
#     ./harvest.py --grep word  functions matching a word
#     ./harvest.py --json       cache it, the way the other games do
#
# In: the shipped `.binds` presets under `ControlSchemes/`. Out: one JSON
# file beside this script, holding the vocabulary.
#
# `KeyboardMouseOnly.binds` is the vocabulary. It carries every function
# as an element whether or not it is bound: 311 buttons, 58 axes, and 68
# settings that are not bindings at all. `MouseSensitivity`, the deadzones
# and `YawToRollMode` are among the settings.
#
# What the other presets bound is not read. That is a layout Frontier
# wrote for a Warthog, and not a fact about Elite.

import os
import re
import sys
import typing
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import game                                       # noqa: E402
from core import adapter                                    # noqa: E402

APPID = '359320'
INSTALL = 'Elite Dangerous'
SCHEMES = ('Products', 'elite-dangerous-odyssey-64', 'ControlSchemes')

#: Where the game writes its OWN bindings, inside the Proton prefix. The
#: shipped presets are thirty layouts. This is the file Elite maintains,
#: and it lists every function it knows, with the binding left empty where
#: there is none. Finding the prefix is `core/game.py`'s job.
BINDINGS_PARTS = ('users', 'steamuser', 'AppData', 'Local',
                  'Frontier Developments', 'Elite Dangerous', 'Options',
                  'Bindings')

#: Only the file the GAME keeps. Never every `.binds` in that folder: this
#: program writes its own preset in there too, and a typo of ours read
#: back out enters the vocabulary and then validates itself.
WRITTEN = re.compile(r'Custom(\.[\d.]+)?\.binds$')


def schemes_dir(path=None):
    """Where the shipped presets live."""
    if path:
        return path
    if os.environ.get('ED_DIR'):
        return os.path.join(os.environ['ED_DIR'], *SCHEMES)
    install = game.install_dir(INSTALL)
    if not install:
        sys.exit(f'{INSTALL} is not installed in any Steam library. Set '
                 'ED_DIR to its folder.')
    out = os.path.join(install, *SCHEMES)
    if not os.path.isdir(out):
        sys.exit(f'There is no ControlSchemes folder at {out}.')
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


def functions_in(root):
    """{'button': {name}, 'axis': {name}} for one parsed .binds tree.

    A function with no child element is a setting and not a binding, and it
    is left out. `MouseSensitivity` and `YawToRollMode` are numbers in the
    same file, and the file the game writes holds 92 of them.
    """
    out = {'button': set(), 'axis': set()}
    for fn in root:
        tags = {c.tag for c in fn}
        if 'Binding' in tags:
            out['axis'].add(fn.tag)
        elif 'Primary' in tags:
            out['button'].add(fn.tag)
    return out


def merge(seen):
    """{kind: [name]} from several `functions_in` answers."""
    button, axis = set(), set()
    for one in seen:
        button |= one['button']
        axis |= one['axis']
    # A function seen as both is an axis. The axis form is the richer
    # one.
    return {'axis': sorted(axis), 'button': sorted(button - axis)}


def written(path=None):
    """[Root] for the bindings file the GAME keeps, where there is one.

    An absent one is not an error. On a machine where Elite has never run
    there is nothing to read, and the presets still give a vocabulary. It
    is a narrower one, and a harvest that refuses over it is worse than
    one that says what it got.
    """
    where = path or game.in_prefix(APPID, *BINDINGS_PARTS)
    if not where or not os.path.isdir(where):
        return []
    out = []
    for name in sorted(os.listdir(where)):
        if not WRITTEN.match(name):
            continue
        try:
            out.append(ET.parse(os.path.join(where, name)).getroot())
        except ET.ParseError:
            continue
    return out


def vocabulary(path=None, also=None):
    """{kind: [function names]} -- kind is 'button' or 'axis'.

    Two sources. Neither one is whole.

    The shipped presets are thirty LAYOUTS. Their union names 393
    functions. The base carries the most, and the others add 24 it does
    not: the `Humanoid` on-foot functions, the FSS camera buttons, and the
    store camera's stepped forms.

    That is still not everything. `NightVisionToggle` is a real ship
    function. It is accepted in a written preset and it works in the game,
    and it appears in none of the thirty.

    The file Elite writes for itself carries it, with 46 others the
    presets never mention: the Galnet audio controls, the humanoid emote
    slots, and the placement-camera axes. MSFS needs the same trick for
    the same reason. Read the source that ENUMERATES, not the one that
    binds.
    """
    seen = [functions_in(r) for r in presets(path).values()]
    if not seen:
        sys.exit('There are no presets. The vocabulary comes from '
                 'them.')
    seen += [functions_in(r) for r in (written() if also is None else also)]
    return merge(seen)


_WORDS = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')

#: Words in a function name that are names rather than prose. Without
#: these, a flat lowering turns `UI_Up` into "Ui up" and `FSSRadioTuning`
#: into "Fs sradio tuning".
ACRONYMS = {'UI', 'FSD', 'FSS', 'SRV', 'HMD', 'ESC', 'AFM', 'ADS', 'GUI',
            'DSS', 'POI', 'SLF', 'FA'}


def readable(name):
    """`LandingGearToggle` -> `Landing gear toggle`.

    The element names are the only text for a person Elite gives. There is
    no localisation file to read, as War Thunder has in `controls.csv`.
    """
    words = [w for part in name.split('_')
             for w in _WORDS.sub(' ', part).split()]
    if not words:
        return name
    out = [w if w.upper() in ACRONYMS else w.lower() for w in words]
    if out[0].upper() not in ACRONYMS:
        out[0] = out[0].capitalize()
    return ' '.join(out)


#: Which context a function answers in, as the kneeboard's columns. Elite
#: scopes a binding by which function it is, and not by a mode flag. So
#: one control carries the ship's meaning and the SRV's without a
#: clash.
SHIP, SRV = 'Ship', 'SRV'
MODES = (SHIP, SRV)

#: What Elite calls each axis, in `adapter.HID_AXES` order. Slider and
#: Dial land on its two extra axes. That is the report descriptor's order,
#: and X4, DCS and Falcon BMS need the same rule.
#:
#: The planner declares this. Nothing here turns a HID name into a key,
#: because the core does that for every game in one place.
AXES = ('Joy_XAxis', 'Joy_YAxis', 'Joy_ZAxis', 'Joy_RXAxis', 'Joy_RYAxis',
        'Joy_RZAxis', 'Joy_UAxis', 'Joy_VAxis')

#: How Elite spells a button, as `Adapter.BUTTON` takes it.
BUTTON, BUTTON_FROM = 'Joy_{n}', 1


#: SRV functions whose names do not say so. Elite spells an SRV function
#: `X_Buggy` or `BuggyX`, and the rest follow one of those two.
#:
#: These four follow neither, and no rule over the name will find them.
#: `HeadlightsBuggyButton` is the SRV twin of `ShipSpotLightToggle`, and
#: `ToggleDriveAssist` is the twin of `ToggleFlightAssist`. Neither pair
#: of names shares a word. `SteeringAxis` and `DriveSpeedAxis` are the
#: SRV's steering and throttle.
#:
#: Written out, because somebody who knows the game found them. That is
#: the only way to find them.
SRV_BY_HAND = frozenset(('HeadlightsBuggyButton', 'ToggleDriveAssist',
                         'SteeringAxis', 'DriveSpeedAxis'))


def mode_of(name):
    """Which of `MODES` a function answers in, read off the name.

    The suffix AND the prefix. The suffix alone makes `PitchAxisRaw` look
    shared, and its twin is `BuggyPitchAxis`.

    Read here, so nothing above this file knows the rule. The context
    travels as data on the action. In the planner instead, it is one of
    six private mechanisms for one idea.
    """
    if (name.endswith('_Buggy') or name.startswith('Buggy')
            or name in SRV_BY_HAND):
        return SRV
    return SHIP


def catalogue(voc=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    Built here, because everything it needs is read here anyway. The kinds
    come out of the same parse, `readable` turns Elite's CamelCase into
    words, and `mode_of` reads the context off the same name.
    """
    voc = vocabulary() if voc is None else voc
    axes = set(voc.get('axis', ()))
    return [cactions.Action(fn, readable(fn),
                            kind='axis' if fn in axes else 'button',
                            mode=mode_of(fn))
            for fn in sorted(axes | set(voc.get('button', ())))]


@typing.final
class EliteHarvest(adapter.Harvest):
    """Elite's function vocabulary."""

    game = 'elite'
    files = {'elite-actions.json': ('actions',)}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--vocab', action='store_true',
                            help='List every function, by kind.')
        parser.add_argument('--grep', metavar='WORD',
                            help='List the functions that match a word.')
        parser.add_argument('--schemes-dir',
                            help='Where the ControlSchemes folder is.')

    @typing.override
    def read(self, args):
        self.args = args
        path = args.schemes_dir
        self.where = schemes_dir(path)
        self.v = vocabulary(path)
        return {'elite-actions.json':
                {'actions': cactions.dump(catalogue(self.v))}}

    @typing.override
    def summary(self, data):
        """What to print. `--grep` and `--vocab` narrow it. They do not
        cancel the write.

        A harvest that returns before it reads `--json` makes
        `./harvest.py --vocab --json` print and write nothing, while
        another that checks `--json` first writes. The order lives in
        `core.adapter`, and there is one of it.
        """
        v = self.v
        if self.args.grep:
            return [f'  {kind:7} {f}'
                    for kind in ('button', 'axis')
                    for f in v.get(kind, ())
                    if self.args.grep.lower() in f.lower()]

        if self.args.vocab:
            out = []
            for kind in ('button', 'axis'):
                out.append(f'--- {kind} ({len(v.get(kind, ()))})')
                out += [f'  {f}' for f in v.get(kind, ())]
            return out

        return [str(self.where), '',
                f'vocabulary  {len(v.get("button", ()))} button, '
                f'{len(v.get("axis", ()))} axis']


if __name__ == '__main__':
    sys.exit(EliteHarvest().main())

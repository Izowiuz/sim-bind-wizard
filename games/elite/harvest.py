#!/usr/bin/env python3
"""harvest.py - read Elite's function vocabulary

DESCRIPTION
    Read the control schemes Elite ships and report every bindable
    function.

FILES
    ed-actions.json     written by --json: every function

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
# In: the shipped `.binds` presets under `ControlSchemes/`. Out: one JSON file
# next to this script -- the vocabulary.
#
# The vocabulary is `KeyboardMouseOnly.binds`, which carries every function as an
# element whether or not it is bound: 311 buttons, 58 axes and 68 settings that
# are not bindings at all (`MouseSensitivity`, deadzones, `YawToRollMode`).
#
# The other presets used to be counted as well -- how many of the fifteen
# HOTAS ones bound each function, and which device they put it on. That is
# a layout Frontier wrote for a Warthog, not a fact about Elite, and
# nothing reads it any more.

import argparse
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
from core import vocab                                      # noqa: E402

APPID = '359320'
INSTALL = 'Elite Dangerous'
SCHEMES = ('Products', 'elite-dangerous-odyssey-64', 'ControlSchemes')

#: Where the game writes its OWN bindings, inside the Proton prefix. The
#: shipped presets are thirty layouts; this is the file Elite maintains, and
#: it lists every function it knows with the binding left empty where there
#: is none. Finding the prefix is `core/game.py`'s job.
BINDINGS_PARTS = ('users', 'steamuser', 'AppData', 'Local',
                  'Frontier Developments', 'Elite Dangerous', 'Options',
                  'Bindings')

#: Only the file the GAME keeps, never every `.binds` in that folder: this
#: wizard writes its own preset in there too, and reading that back would
#: let a typo of ours enter the vocabulary and then validate itself.
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

    A function with no children is a setting rather than a binding and is
    left out: `MouseSensitivity` and `YawToRollMode` are numbers in the same
    file, and the file the game writes holds 92 of them.
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
    # a function seen as both is an axis: the axis form is the richer one
    return {'axis': sorted(axis), 'button': sorted(button - axis)}


def written(path=None):
    """[Root] for the bindings file the GAME keeps, if there is one.

    Absent is not an error: on a machine where Elite has never been run
    there is nothing to read, and the presets still give a vocabulary --
    a narrower one, but a harvest that refuses because of it is worse than
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

    Two sources, because neither is the whole truth.

    The shipped presets are thirty LAYOUTS. Their union names 393 functions
    -- the base carries the most, and the others add 24 it does not:
    `Humanoid*` on-foot functions, the FSS camera buttons, the store
    camera's stepped forms.

    It is still not everything. `NightVisionToggle` is a real ship function,
    accepted in a written preset and working in game, and it appears in none
    of the thirty. The file Elite writes for itself carries it, along with
    46 others the presets never mention -- the Galnet audio controls, the
    humanoid emote slots, the placement-camera axes. That is the same trick
    MSFS already uses for the same reason: read the source that ENUMERATES,
    not the one that merely binds.
    """
    seen = [functions_in(r) for r in presets(path).values()]
    if not seen:
        sys.exit('There are no presets. The vocabulary comes from '
                 'them.')
    seen += [functions_in(r) for r in (written() if also is None else also)]
    return merge(seen)


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


def catalogue(voc=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    Built here because everything it needs is read here anyway: the kinds
    come from the same parse, and `readable` turns Elite's CamelCase into
    words.
    """
    voc = vocabulary() if voc is None else voc
    axes = set(voc.get('axis', ()))
    return [cactions.Action(fn, readable(fn),
                            kind='axis' if fn in axes else 'button')
            for fn in sorted(axes | set(voc.get('button', ())))]


def action_rows(voc=None):
    """The section the cache holds."""
    return cactions.dump(catalogue(voc))


@typing.final
class EliteHarvest(adapter.Harvest):
    """Elite's function vocabulary."""

    game = 'elite'
    files = {'ed-actions.json': ('actions',)}

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
        return {'ed-actions.json': {'actions': action_rows(self.v)}}

    @typing.override
    def summary(self, data):
        """What to print. `--grep` and `--vocab` narrow it; they do not
        cancel the write.

        They used to `return` before `--json` was consulted, so
        `./harvest.py --vocab --json` printed and wrote nothing -- while X4,
        which checked `--json` first, wrote. Two adapters, the same two
        flags, opposite meanings. The order lives in `core.adapter` now and
        there is only one of it.
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

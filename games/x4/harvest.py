#!/usr/bin/env python3
"""harvest.py - read X4's action vocabulary

DESCRIPTION
    Parse the bindings X4 keeps in its Proton prefix and report what the game
    can be told to do. With no arguments, print a summary.

FILES
    inputmap*.xml       read, under the prefix
    x4-actions.json     written by --json

NOTES
    plan.py reparses the XML when this cache is missing, so --json is
    optional here and required for every other game in the repo.
"""

# Read what X4 Foundations can be told to do, and how it names our devices.
#
# X4 is the friendliest target of the family. Its bindings live in plain XML in
# the Proton prefix, one file per named profile, and every binding is one line:
#
#     <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
#             source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>
#
# Three element types, and the difference matters when deciding what a control
# should carry:
#
#     <action>  fires once on press          229 distinct ids
#     <state>   true while held              101
#     <range>   an axis                       29
#
# `source` names the device by SLOT -- `JOYBUTTONS`, `_2`, `_3` -- and `code` is
# LOCAL to that device. No global numbering to undo, unlike War Thunder and BMS.
#
# Two things this cannot tell us, and one of them still needs measuring:
#
# - Which slot is which device. There is no device list anywhere in the config,
#   so the slots follow enumeration order. `slots()` infers it from an existing
#   profile instead: the slot carrying THROTTLE on RX is the throttle, the slot
#   whose codes are all Xbox names is a gamepad.
# - What `INPUT_XBUTTON_17` is in terms of the button index the device map uses.
#   X4 mixes Xbox names with bare numbers and it is not established whether they
#   share one numbering. NOT GUESSED HERE -- see `CODES` below.

import argparse
import collections
import html
import os
import re
import sys
import typing

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..'))
from core import actions as cactions                        # noqa: E402
from core import game                                       # noqa: E402
from core import adapter                                    # noqa: E402
from core import vocab                                      # noqa: E402

#: Steam appid, and where inside the prefix X4 keeps its profiles. Finding the
#: prefix itself is core/game.py's job -- it searches every Steam library,
#: which matters because compatdata lives next to the library a game is
#: installed in, not always the first one.
APPID = '392160'
PROFILE_PARTS = ('users', 'steamuser', 'Documents', 'Egosoft', 'X4')

#: The three kinds X4 names in the id itself, and the prefixes that say so.
#: `readable()` strips exactly these, which is the same fact read the other
#: way round -- so it is kept here, once, rather than beside each reader.
#: `INPUT_SOURCE_` is deliberately not among them: that says where a binding
#: comes FROM, not what is being bound.
ACTION, STATE, RANGE = 'action', 'state', 'range'
PREFIX = {ACTION: 'INPUT_ACTION_', STATE: 'INPUT_STATE_',
          RANGE: 'INPUT_RANGE_'}

#: An id anywhere in a block of bytes. X4 ships no list of what it accepts --
#: its four `inputmap*.xml` are LAYOUTS, and three of the four are the
#: player's own saved profiles, so reading them tells you what somebody once
#: chose rather than what the game allows. The executable carries the names.
ID_IN_BYTES = re.compile(rb'INPUT_(?:ACTION|STATE|RANGE)_[A-Z0-9_]+')

#: Attributes are not always in the same order and not always just the three.
#: `toggle="1"` sits BETWEEN source and code on a latching <state>, and `sgn`
#: sits after code on a VR axis used as a button. Matching them positionally
#: lost 3-18 rows a file, and two ids entirely -- INPUT_STATE_MATCH_SPEED and
#: INPUT_STATE_MAP_PAN_TO_ROTATE were absent from the vocabulary although
#: match speed is bound on the throttle. Match the element, then the
#: attributes.
ROW = re.compile(r'<(action|state|range)\s+([^>]*?)\s*/>')
ATTR = re.compile(r'(\w+)="([^"]*)"')
HEADER = re.compile(r'<inputmap\s+version="(\d+)"(?:\s+id="(\d+)")?'
                    r'(?:\s+name="([^"]*)")?')

#: How a button index in the device map becomes an X4 `code`.
#:
#: MEASURED 2026-09-17, by binding three isolated buttons on the WarBRD in the
#: game's own menu and reading the file back:
#:
#:     js 12  ->  INPUT_XBUTTON_13
#:     js 30  ->  INPUT_XBUTTON_31
#:     js  6  ->  INPUT_XBUTTON_BACK
#:
#: So the number is the index PLUS ONE -- two independent points agree -- and
#: names share that same numbering rather than living in a second one: BACK
#: occupies the position that would otherwise read `_7`.
#:
#: The trigger could not be used for this. It is cumulative, so reaching the
#: second detent means passing through the first, and X4 closes the binding
#: dialog on the first input it catches.
OFFSET = 1

#: Positions 1..11 always come out as an Xbox name, 12 upward as a bare number.
#:
#: MEASURED: a bare number is NOT accepted where a name belongs -- OPEN_MAP was
#: moved from `BACK` to `_7`, and X4 parsed the file, failed to recognise it and
#: left the binding blank in its own menu. So the table below is needed; there
#: is no way to sidestep it with numbers.
#:
#: CONFIRMED: js 9 came back `RIGHT_THUMB`, which is where the order below
#: puts it. Two measured points inside the named range, two in the numeric one.
#:
#: The chain that got there, kept because it is the method rather than the
#: answer:
#:   * `BACK` is position 7 (measured, js 6);
#:   * no `_1` through `_11` appears anywhere in four profile files, while
#:     `_12` and `_13` do -- so everything up to 11 is named;
#:   * fifteen names appear in those files, four of which are `DPAD_*`
#:     directions belonging to a POV rather than a button position, leaving
#:     exactly eleven -- the same count;
#:   * those eleven in DirectInput's usual order for an Xbox pad put `BACK`
#:     seventh, which is where it was measured.
#:
#: Every observation fitted and the prediction held on the next measurement,
#: so the table stands. Note what could NOT be used to get here: the trigger is
#: cumulative, so reaching a deeper detent means passing through the shallower
#: ones, and X4 closes its binding dialog on the first input it catches.
NAMES = ('A', 'B', 'X', 'Y', 'LEFT_SHOULDER', 'RIGHT_SHOULDER', 'BACK',
         'START', 'LEFT_THUMB', 'RIGHT_THUMB', 'BIGBUTTON')

#: Settled 2026-09-17 by the js 9 = RIGHT_THUMB prediction holding.
NAMES_INFERRED = False


def code(index):
    """The X4 `code` for a button index in the device map."""
    if index < len(NAMES):
        return f'INPUT_XBUTTON_{NAMES[index]}'
    return f'INPUT_XBUTTON_{index + OFFSET}'


def index_of(code_str):
    """The button index an X4 code refers to, or None if it is neither."""
    m = re.fullmatch(r'INPUT_XBUTTON_(\d+)', code_str)
    if m:
        return int(m.group(1)) - OFFSET
    m = re.fullmatch(r'INPUT_XBUTTON_([A-Z_]+)', code_str)
    if m and m.group(1) in NAMES:
        return NAMES.index(m.group(1))
    return None


def profile_dir():
    """Where X4 keeps its per-player profiles, under the Steam user id."""
    if os.environ.get('X4_DIR'):
        return os.environ['X4_DIR']
    base = game.in_prefix(APPID, *PROFILE_PARTS)
    if base is None:
        sys.exit(f'no X4 profile directory in the prefix for appid {APPID} — '
                 'run the game once, or set X4_DIR')
    players = [os.path.join(base, d) for d in sorted(os.listdir(base))
               if os.path.isdir(os.path.join(base, d))]
    if not players:
        sys.exit(f'{base} has no player directory yet — run X4 once')
    return players[-1]


def rows(txt):
    """[(kind, id, source, code)] for every binding in a profile's text.

    Attributes beyond those four are read and dropped here; a writer that
    needs `toggle` or `sgn` parses the line itself.
    """
    out = []
    for kind, attrs in ROW.findall(txt):
        a = dict(ATTR.findall(attrs))
        if 'id' in a and 'source' in a and 'code' in a:
            out.append((kind, a['id'], a['source'], a['code']))
    return out


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
            # The working copy carries no name= at all, only the saved
            # profiles do, so an absent group is the default one. The
            # attribute is captured raw, so &amp; arrives still escaped.
            'name': html.unescape((h.group(3) if h else None)
                                  or '(default)'),
            'rows': rows(txt),
        }
    return out


def kind_of(ident):
    """`action`, `state` or `range`, read off the id.

    X4's ids carry it, so it never had to travel in a payload beside them.
    It is a property of the action, not of binding it.
    """
    for kind, prefix in PREFIX.items():
        if ident.startswith(prefix):
            return kind
    return ACTION


def ids_in(blob):
    """{id} -- every action id in a block of bytes."""
    return {m.group(0).decode('ascii') for m in ID_IN_BYTES.finditer(blob)}


def binary(path=None):
    """The game executable, or None. It holds the names of the actions.

    Not an error when it is absent: the profiles still give a vocabulary,
    just a narrower one, and a harvest that refuses to run because a Steam
    library moved is worse than one that says what it got.
    """
    if path:
        return path if os.path.exists(path) else None
    where = os.environ.get('X4_GAME_DIR') or game.install_dir('X4 Foundations')
    if not where:
        return None
    exe = os.path.join(where, 'X4.exe')
    return exe if os.path.exists(exe) else None


def vocabulary(profs=None, extra=None):
    """{kind: [id]} -- everything X4 will accept a binding for.

    Two sources, unioned, because neither is the whole truth.

    The profiles are layouts. The shipped default binds 337 ids and the
    three saved ones 314-338, and three of those four are the player's own
    -- so what they carry is a record of past choices. Nine ids they DO
    carry are absent from the executable (the mouse, VR and cutscene ones,
    which the UI assembles rather than names), so they cannot be dropped.

    The executable names 447, of which 97 no profile binds at all --
    `INPUT_ACTION_DEPLOY_SATELLITE`, `DEPLOY_MINE`, `DEPLOY_NAVBEACON` and
    the rest. Those are real, bindable, and exactly the kind of thing a
    HOTAS wants; they were invisible because nobody had bound them yet.

    `extra` is that second source as a set of bare ids -- `kind_of` reads
    their kind off the id, which is X4's own convention and not a guess.
    Left out, the executable is read; an empty one means none, the same
    distinction `profs` makes. A caller asking for nothing must not be
    handed everything.
    """
    # `is None`, not falsy: an empty mapping means "no profiles", and
    # going off to read the install instead would make a caller that asked
    # for nothing get everything.
    profs = profiles() if profs is None else profs
    if extra is None:
        exe = binary()
        extra = ids_in(open(exe, 'rb').read()) if exe else ()
    vocab = collections.defaultdict(set)
    for p in profs.values():
        for kind, ident, _src, _code in p['rows']:
            vocab[kind].add(ident)
    for ident in extra:
        vocab[kind_of(ident)].add(ident)
    return {k: sorted(v) for k, v in sorted(vocab.items())}


#: Words in an id that are names rather than prose.
ACRONYMS = {'FP', 'VR', 'SETA', 'HUD', 'AI', 'UI', 'NPC', 'LOD', 'MK1', 'MK2',
            'MK3', 'MK4'}


def readable(ident):
    """`INPUT_ACTION_TOGGLE_TRAVEL_MODE` -> `Toggle travel mode`.

    X4's ids are self-describing, so there is no language file to crack -- a
    rare mercy after War Thunder's zstd archives and BMS's shared dictionary.
    """
    for prefix in ('INPUT_ACTION_', 'INPUT_STATE_', 'INPUT_RANGE_'):
        if ident.startswith(prefix):
            ident = ident[len(prefix):]
            break
    # A flat .capitalize() turned FP_YAW into "Fp yaw". The ids carry a few
    # acronyms and they are the ones that mean something.
    words = ident.split('_')
    out = [w if w in ACRONYMS else w.lower() for w in words]
    if out[0] not in ACRONYMS:
        out[0] = out[0].capitalize()
    return ' '.join(out)


def context_of(ident):
    """Which context an id answers in, read off the id itself.

    X4 has no mode flag on a binding: `MAP_*` ids answer only in the map and
    `FP_*` only on foot, which is what lets one control carry three
    meanings. Kept beside `kind_of` and `readable` because all three are the
    same fact -- X4 says what an action IS in its name.
    """
    if '_MAP_' in ident:
        return 'Map'
    if '_FP_' in ident:
        return 'On foot'
    return 'Ship'


def catalogue(voc=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    Built here rather than in `plan.py` because everything it needs is
    already known here: `readable`, `kind_of` and `context_of` all read
    X4's own naming, and the alternative is translating on the way out of
    the cache instead of on the way in.

    `range` is X4's word for an axis; `action` and `state` are both buttons
    to anything outside this file, and the three-way kind stays recoverable
    from the id for the writer that needs it.

    No `rank`: X4's four profiles each bind 314-338 of the 456, and three
    of the four are the player's own saved layouts, so counting them
    separates nothing. A derived stand-in would be read as a fact.
    """
    voc = vocabulary() if voc is None else voc
    return [cactions.Action(i, readable(i),
                            kind='axis' if k == RANGE else 'button',
                            mode=context_of(i))
            for k, ids in sorted(voc.items()) for i in ids]


def action_rows(voc=None):
    """The section the cache holds, for a planner rebuilding on the spot."""
    return cactions.dump(catalogue(voc))


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


@typing.final
class X4Harvest(adapter.Harvest):
    """X4's action vocabulary, its device slots and its profile names.

    The cache is optional here -- reparsing four 46 KB XML files is free,
    where War Thunder unpacks zstd archives -- but `--json` means the same
    thing in every game, so a planner never has to know the difference.
    """

    game = 'x4'
    files = {'x4-actions.json': ('actions', 'slots', 'profiles')}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--vocab', action='store_true',
                            help='what X4 will accept a binding for')
        parser.add_argument('--grep', metavar='WORD',
                            help='vocabulary entries matching a word')

    @typing.override
    def read(self, args):
        self.args = args
        self.where = profile_dir()
        self.profs = profiles(self.where)
        self.exe = binary()
        self.v = vocabulary(self.profs)
        # `slots()` ran twice for every profile: once for the display and
        # once for the cache. Once is enough, and the two can no longer
        # disagree.
        self.slots = {n: slots(pr) for n, pr in self.profs.items()}
        return {'x4-actions.json': {
            'actions': action_rows(self.v),
            'slots': self.slots,
            'profiles': {n: pr['name'] for n, pr in self.profs.items()}}}

    @typing.override
    def summary(self, data):
        out = [f'{self.where}', '']
        for name, p in self.profs.items():
            joy = sum(1 for k, i, s, c in p['rows'] if 'JOY' in s)
            out.append(f'  {name:<16} v{p["version"]:<4} {p["name"]:<20} '
                       f'{len(p["rows"]):>4} bindings, {joy} on a joystick')
        out.append('')
        out.append('vocabulary  '
                   + ', '.join(f'{len(ids)} {k}'
                               for k, ids in self.v.items())
                   + ('' if self.exe else
                      '  (no X4.exe found -- profiles only, which is what '
                      'somebody already bound rather than what X4 accepts)'))
        for name, sl in self.slots.items():
            if not sl:
                continue
            out.append('')
            out.append(f'device slots in {name} '
                       f'({self.profs[name]["name"]})')
            for slot, st in sorted(sl.items()):
                out.append(f'  JOY{slot:<4} {st["guess"]:<9} '
                           f'axes {",".join(st["axes"]) or "-":<22}'
                           f' codes: {st["named"]} named / '
                           f'{st["numeric"]} numeric')
        out += ['', 'button codes']
        for i in (0, 6, 9, 10, 11, 12, 30):
            tag = '  <- measured' if i in (6, 12, 30) else ''
            out.append(f'  js {i:<3} {code(i)}{tag}')
        if NAMES_INFERRED:
            out.append('  !! the eleven names rest on one measured point '
                       '(js 6 = BACK).')
            out.append('     One more bind settles it: js 9 should be '
                       'RIGHT_THUMB.')
        else:
            out.append('  names confirmed: js 6 = BACK and js 9 = '
                       'RIGHT_THUMB both held')

        if self.args.grep:
            out.append('')
            for kind, ids in self.v.items():
                for i in ids:
                    if self.args.grep.lower() in i.lower():
                        out.append(f'  {kind:<7} {i:<52} {readable(i)}')
        elif self.args.vocab:
            for kind, ids in self.v.items():
                out += ['', f'== {kind} ({len(ids)})']
                out += [f'   {i:<54} {readable(i)}' for i in ids]
        return out


if __name__ == '__main__':
    sys.exit(X4Harvest().main())

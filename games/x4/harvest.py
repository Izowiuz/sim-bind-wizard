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

# X4 keeps its bindings in plain XML in the Proton prefix, one file per
# named profile. One binding is one line:
#
#     <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
#             source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>
#
# Three element types. The difference decides what a control carries:
#
#     <action>  fires once on press          229 distinct ids
#     <state>   true while held              101
#     <range>   an axis                       29
#
# `source` names the device by SLOT, as `JOYBUTTONS`, `_2` or `_3`. `code`
# is LOCAL to that device, so there is no global numbering to undo.
#
# Two things the files do not say:
#
# - Which slot is which device. The configuration holds no device list, so
#   the slots follow enumeration order. `slots()` reads it back off an
#   existing profile: the slot carrying THROTTLE on RX is the throttle,
#   and the slot whose codes are all Xbox names is a gamepad.
# - What `INPUT_XBUTTON_17` is in the device map's button numbering. X4
#   mixes Xbox names with bare numbers. Measured, not guessed. See the
#   `OFFSET` and `NAMES` notes below.

import collections
import html
import os
import re
import sys
import typing

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..'))
from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import game                                       # noqa: E402

#: The Steam appid, and where inside the prefix X4 keeps its profiles.
#: Finding the prefix is `core/game.py`'s job. It searches every Steam
#: library, because `compatdata` sits next to the library a game is
#: installed in.
APPID = '392160'
PROFILE_PARTS = ('users', 'steamuser', 'Documents', 'Egosoft', 'X4')

#: The three kinds X4 names in the id itself, and the prefixes that say
#: so. `readable()` strips these, which is the same fact read the other way
#: round, so it is kept here once.
#:
#: `INPUT_SOURCE_` is not among them. That says where a binding comes
#: FROM, and not what is being bound.
ACTION, STATE, RANGE = 'action', 'state', 'range'
PREFIX = {ACTION: 'INPUT_ACTION_', STATE: 'INPUT_STATE_',
          RANGE: 'INPUT_RANGE_'}

#: An id anywhere in a block of bytes. X4 ships no list of what it
#: accepts. Its four `inputmap*.xml` are LAYOUTS, and three of the four
#: are the player's own saved profiles, so they say what somebody once
#: chose. The executable carries the names.
ID_IN_BYTES = re.compile(rb'INPUT_(?:ACTION|STATE|RANGE)_[A-Z0-9_]+')

#: The attributes are not always in the same order, and not always only
#: three. `toggle="1"` sits BETWEEN source and code on a latching
#: `<state>`. `sgn` sits after code on a VR axis used as a button.
#:
#: Matched positionally, that loses 3 to 18 rows a file, and two ids
#: entirely: `INPUT_STATE_MATCH_SPEED` and `INPUT_STATE_MAP_PAN_TO_ROTATE`
#: go missing from the vocabulary while match speed is bound on the
#: throttle. Match the element first and the attributes second.
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
#: So the number is the index PLUS ONE, and two independent points agree.
#: The names share that same numbering. They do not live in a second one:
#: `BACK` occupies the position that would otherwise read `_7`.
#:
#: The trigger could not be used for this. It is cumulative, so reaching the
#: second detent means passing through the first, and X4 closes the binding
#: dialog on the first input it catches.
OFFSET = 1

#: Positions 1..11 always come out as an Xbox name, 12 upward as a bare number.
#:
#: MEASURED: a bare number is NOT accepted where a name belongs.
#: `OPEN_MAP` moved from `BACK` to `_7`. X4 parsed the file, failed to
#: recognise the code, and left the binding blank in its own menu. So the
#: table below is necessary. Numbers do not sidestep it.
#:
#: CONFIRMED: js 9 came back `RIGHT_THUMB`, which is where the order below
#: puts it. Two measured points inside the named range, two in the numeric one.
#:
#: The chain that got there, kept because it is the method:
#:   * `BACK` is position 7, measured at js 6.
#:   * No `_1` to `_11` appears in four profile files, and `_12` and `_13`
#:     do. So everything up to 11 is named.
#:   * Fifteen names appear in those files. Four are `DPAD_*` directions,
#:     which belong to a POV rather than to a button position. That leaves
#:     exactly eleven, which is the same count.
#:   * Those eleven in DirectInput's usual order for an Xbox pad put
#:     `BACK` seventh, which is where it was measured.
#:
#: Every observation fitted and the prediction held on the next measurement,
#: so the table stands.
NAMES = ('A', 'B', 'X', 'Y', 'LEFT_SHOULDER', 'RIGHT_SHOULDER', 'BACK',
         'START', 'LEFT_THUMB', 'RIGHT_THUMB', 'BIGBUTTON')

#: Settled 2026-09-17 by the js 9 = RIGHT_THUMB prediction holding.
NAMES_INFERRED = False

#: Words in an id that are names rather than prose.
ACRONYMS = {'FP', 'VR', 'SETA', 'HUD', 'AI', 'UI', 'NPC', 'LOD', 'MK1', 'MK2',
            'MK3', 'MK4'}

#: Which context an id answers in, as the kneeboard's columns. X4 puts no
#: mode flag on a binding. A `MAP_` id answers in the map only and an
#: `FP_` id on foot only, and that is what lets one control carry three
#: meanings.
SHIP, MAP, ON_FOOT = 'Ship', 'Map', 'On foot'
MODES = (SHIP, MAP, ON_FOOT)


#: The eleven named positions, and the pattern for the rest, as
#: `Adapter.BUTTON_NAMES` and `Adapter.BUTTON` take them. The planner
#: declares these. Nothing here turns an index into a code, because the
#: core does that for every game in one place.
BUTTON_NAMES = tuple(f'INPUT_XBUTTON_{n}' for n in NAMES)
BUTTON, BUTTON_FROM = 'INPUT_XBUTTON_{n}', OFFSET

#: What X4 calls each axis, in `adapter.HID_AXES` order. Slider and Dial
#: land on its two sliders. That is the report descriptor's order, and
#: Elite, DCS and Falcon BMS need the same rule.
AXES = tuple(f'INPUT_JOYAXIS_{n}' for n in
             ('X', 'Y', 'Z', 'RX', 'RY', 'RZ', 'SLIDER1', 'SLIDER2'))


def profile_dir():
    """Where X4 keeps its per-player profiles, under the Steam user id."""
    if os.environ.get('X4_DIR'):
        return os.environ['X4_DIR']
    base = game.in_prefix(APPID, *PROFILE_PARTS)
    if base is None:
        sys.exit('The prefix for appid '
                 f'{APPID} has no X4 profile directory. Run the game once, '
                 'or set X4_DIR.')
    players = [os.path.join(base, d) for d in sorted(os.listdir(base))
               if os.path.isdir(os.path.join(base, d))]
    if not players:
        sys.exit(f'{base} has no player directory yet. Run X4 once.')
    return players[-1]


def rows(txt):
    """[(kind, id, source, code)] for every binding in a profile's text.

    An attribute beyond those four is read and dropped here. A writer that
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
            # The working copy carries no `name=`. Only a saved profile
            # does, so an absent group is the default one. The attribute
            # is captured raw, so `&amp;` arrives still escaped.
            'name': html.unescape((h.group(3) if h else None)
                                  or '(default)'),
            'rows': rows(txt),
        }
    return out


def kind_of(ident):
    """`action`, `state` or `range`, read off the id.

    X4's ids carry the kind, so it never travels in a payload beside them.
    It is a property of the action and not of binding it.
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

    An absent one is not an error. The profiles still give a vocabulary,
    and it is a narrower one. A harvest that refuses to run because a
    Steam library moved is worse than one that says what it got.
    """
    if path:
        return path if os.path.exists(path) else None
    where = os.environ.get('X4_GAME_DIR') or game.install_dir('X4 Foundations')
    if not where:
        return None
    exe = os.path.join(where, 'X4.exe')
    return exe if os.path.exists(exe) else None


def vocabulary(profs=None, extra=None):
    """{kind: [id]} -- everything X4 accepts a binding for.

    Two sources, unioned. Neither one is whole.

    The profiles are layouts. The shipped default binds 337 ids and the
    three saved ones bind 314 to 338, and three of the four are the
    player's own. So they hold a record of past choices. Nine ids they DO
    carry are absent from the executable: the mouse, VR and cutscene ones,
    which the UI assembles rather than names. So the profiles cannot be
    dropped.

    The executable names 447 ids. No profile binds 97 of them, including
    `INPUT_ACTION_DEPLOY_SATELLITE`, `DEPLOY_MINE` and `DEPLOY_NAVBEACON`.
    Those are real and bindable, and they are the kind of thing a HOTAS
    wants.

    `extra` is that second source, as a set of bare ids. `kind_of` reads
    the kind off the id, which is X4's own convention.

    Left out, `extra` reads the executable. An empty one means none, which
    is the distinction `profs` makes as well. A caller that asks for
    nothing must not be handed everything.
    """
    # `is None`, not falsy. An empty mapping means "no profiles", and
    # reading the install instead hands a caller that asked for nothing
    # everything.
    profs = profiles() if profs is None else profs
    if extra is None:
        exe = binary()
        extra = ids_in(open(exe, 'rb').read()) if exe else ()
    found = collections.defaultdict(set)
    for p in profs.values():
        for kind, ident, _src, _code in p['rows']:
            found[kind].add(ident)
    for ident in extra:
        found[kind_of(ident)].add(ident)
    return {k: sorted(v) for k, v in sorted(found.items())}


def readable(ident):
    """`INPUT_ACTION_TOGGLE_TRAVEL_MODE` -> `Toggle travel mode`.

    X4's ids describe themselves, so there is no language file to crack.
    War Thunder keeps zstd archives and Falcon BMS a shared dictionary.
    """
    for prefix in PREFIX.values():
        if ident.startswith(prefix):
            ident = ident[len(prefix):]
            break
    # A flat `.capitalize()` turns `FP_YAW` into "Fp yaw". The ids carry a
    # few acronyms, and those are the words that mean something.
    words = ident.split('_')
    out = [w if w in ACRONYMS else w.lower() for w in words]
    if out[0] not in ACRONYMS:
        out[0] = out[0].capitalize()
    return ' '.join(out)


def mode_of(ident):
    """Which of `MODES` an id answers in, read off the id itself.

    Kept beside `kind_of` and `readable`, because all three read the same
    fact: X4 says what an action IS in its name.

    It is written onto the `Action` here, so nothing above this file knows
    the rule. The context a binding answers in travels as data.
    """
    if '_MAP_' in ident:
        return MAP
    if '_FP_' in ident:
        return ON_FOOT
    return SHIP


def catalogue(voc=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    Built here, where everything it needs is known. `readable`, `kind_of`
    and `mode_of` all read X4's own naming. The cache then holds the
    finished record, and `Adapter.catalogue` reads it.

    `range` is X4's word for an axis. `action` and `state` are both
    buttons to anything outside this file, and the writer that needs the
    three-way kind reads it off the id.
    """
    voc = vocabulary() if voc is None else voc
    return [cactions.Action(i, readable(i),
                            kind='axis' if k == RANGE else 'button',
                            mode=mode_of(i))
            for k, ids in sorted(voc.items()) for i in ids]


AXIS_IN_CODE = re.compile(r'INPUT_JOYAXIS_(\w+)$')
XBOX_NAME = re.compile(r'INPUT_XBUTTON_([A-Z_]+)$')


def slots(prof):
    """Which device slot is which, read off what a profile already binds.

    ONE profile. A slot number means something inside the profile that
    wrote it and nowhere else, so all four read together blend a
    gamepad-era layout with the VIRPIL one and call two different slots
    the throttle.

    The evidence, in this order:
      * A slot whose button codes are ALL Xbox names and which offers RZ
        is a gamepad. Checked FIRST, because a gamepad binds throttle to
        a trigger and otherwise looks like a throttle.
      * The slot with THROTTLE on an axis is the throttle.
      * The remaining joystick slot is the stick.
    """
    seen = collections.defaultdict(lambda: {'axes': set(), 'codes': set(),
                                            'ids': set()})
    for kind, ident, src, got in prof['rows']:
        if 'JOY' not in src:
            continue
        slot = src.replace('INPUT_SOURCE_JOYBUTTONS', '') \
                  .replace('INPUT_SOURCE_JOYAXES', '') or '_1'
        s = seen[slot]
        s['ids'].add(ident)
        m = AXIS_IN_CODE.match(got)
        if m:
            s['axes'].add(m.group(1))
        else:
            s['codes'].add(got)
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

    The cache is optional here. Reparsing four 46 KB XML files is free,
    where War Thunder unpacks zstd archives. `--json` still means the same
    thing in every game, so a planner does not know the difference.
    """

    game = 'x4'
    files = {'x4-actions.json': ('actions', 'slots', 'profiles')}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--vocab', action='store_true',
                            help='List what X4 accepts a binding for.')
        parser.add_argument('--grep', metavar='WORD',
                            help='List the entries that match a word.')

    @typing.override
    def read(self, args):
        self.args = args
        self.where = profile_dir()
        self.profs = profiles(self.where)
        self.exe = binary()
        self.v = vocabulary(self.profs)
        # Once per profile. Called for the display and again for the
        # cache, `slots()` runs twice and the two answers can differ.
        self.slots = {n: slots(pr) for n, pr in self.profs.items()}
        return {'x4-actions.json': {
            'actions': cactions.dump(catalogue(self.v)),
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
                      '  There is no X4.exe, so this is the profiles '
                      'only. A profile is what somebody already bound, '
                      'not what X4 accepts.'))
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
            said = (BUTTON_NAMES[i] if i < len(BUTTON_NAMES)
                    else BUTTON.format(n=i + BUTTON_FROM))
            out.append(f'  js {i:<3} {said}{tag}')
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

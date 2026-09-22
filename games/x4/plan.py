#!/usr/bin/env python3
"""plan.py - lay out X4 Foundations on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write the result into X4's own profile.

FILES
    harvest.py          the action vocabulary
    inputmap_3.xml      written by --write, under the Proton prefix
    KNEEBOARD.md        written by --sheet
    kneeboard.html      written by --html

ENVIRONMENT
    X4_PROFILE          profile file to write (default inputmap_3.xml)
    X4_SLOTS            override slot detection, e.g. "stick=2,throttle=3"
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close X4 first: it rewrites these files on exit.
    Every id in NEEDS is checked against the vocabulary before anything runs.
"""

# X4 ships no factory HOTAS profiles to count, unlike BMS, War Thunder, MSFS
# and DCS, so there is no ranking to read off the game. NEEDS below is seeded
# from the bindings already in inputmap_3.xml -- a record of what was worth
# binding by hand -- and ordered by urgency alone.

import argparse
import os
import re
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'no shared core at {CORE}\n'
                     'set SIM_BIND_WIZARD to the sim-bind-wizard checkout')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import game                                       # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import review as creview                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH,             # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)

harvest = adapter.from_file('x4harvest', os.path.join(HERE, 'harvest.py'))

#: The profile the plan owns when nothing says otherwise. X4 writes the
#: game's own binding changes into `inputmap.xml`, the working copy, so a
#: named profile is the only place a generated layout survives being edited
#: in the menu.
DEFAULT_PROFILE = 'inputmap_3.xml'

#: sim-device-map's HID axis names to X4's. The first six are DirectInput's own
#: and pass straight through; Slider and Dial become SLIDER1 and SLIDER2 in
#: report-descriptor order, the same rule Falcon BMS needs.
#:
#: Confirmed against the bindings already in the file: the throttle's Rx is its
#: left lever and carries INPUT_RANGE_THROTTLE there, and the stick's X/Y/Z
#: carry STEERING_PRIMARY/PITCH/SECONDARY.
AXIS_CODE = {'X': 'X', 'Y': 'Y', 'Z': 'Z', 'Rx': 'RX', 'Ry': 'RY',
             'Rz': 'RZ', 'Slider': 'SLIDER1', 'Dial': 'SLIDER2'}

#: X4's three binding elements. `action` fires once on press, `state` is true
#: while held, `range` is an axis. Taken from the harvest rather than spelled
#: again: it is where `readable`, `kind_of` and `context_of` all live, and
#: they are one fact -- X4 says what an action IS in its name.
ACTION, STATE, RANGE = harvest.ACTION, harvest.STATE, harvest.RANGE
kind_of = harvest.kind_of
context_of = harvest.context_of


def A(name):
    return 'INPUT_ACTION_' + name


def S(name):
    return 'INPUT_STATE_' + name


class Need(corneeds.Need):
    """A need whose slots carry X4 ids.

    X4 scopes a binding by which id it is rather than by a mode flag: MAP_*
    ids only answer in the map, FP_* only on foot, everything else in
    flight. So one physical button carries up to three ids and they never
    collide, and `context_of` reads which is which off the name -- the
    slot needs no room for it.
    """

    @property
    def device(self):
        return self.dev


# --------------------------------------------------------------- the layout --

#: Axes are resolved by what the device map says a control IS, never by index.
#: (X4 id, role, how to find it)
AXIS_NEEDS = [
    ('INPUT_RANGE_STEERING_PRIMARY',   'stick',    ('kind', 'stick-x')),
    ('INPUT_RANGE_STEERING_PITCH',     'stick',    ('kind', 'stick-y')),
    ('INPUT_RANGE_STEERING_SECONDARY', 'stick',    ('kind', 'twist')),
    ('INPUT_RANGE_STRAFE_LEFT_RIGHT',  'stick',    ('kind', 'mini-stick-x')),
    ('INPUT_RANGE_STRAFE_UP_DOWN',     'stick',    ('kind', 'mini-stick-y')),
    ('INPUT_RANGE_THROTTLE',           'throttle', ('label', 'Left throttle lever')),
    ('INPUT_RANGE_MAP_ZOOM_IN',        'throttle', ('label', 'Side lever')),
    ('INPUT_RANGE_MAP_PAN_LEFT_RIGHT', 'throttle', ('kind', 'mini-stick-x')),
    ('INPUT_RANGE_MAP_PAN_UP_DOWN',    'throttle', ('kind', 'mini-stick-y')),
    ('INPUT_RANGE_FP_YAW',             'stick',    ('kind', 'mini-stick-x')),
    ('INPUT_RANGE_FP_PITCH',           'stick',    ('kind', 'mini-stick-y')),
    ('INPUT_RANGE_FP_WALK',            'stick',    ('kind', 'stick-y')),
    ('INPUT_RANGE_FP_STRAFE',          'stick',    ('kind', 'stick-x')),
]

#: Where the judgements live. Which band a thing is in, what shape it wants,
#: which device it belongs on, what somebody wrote about it -- 373 of them
#: across the family, and nothing derives any of them.
#:
#: Source, not cache. They were a Python literal until now, which meant
#: changing one meant editing code; they are still the same 32 decisions,
#: kept in the repo, and now readable by something other than an editor.
#: Deliberately not in `CACHE`: that names what the harvest wrote, and a
#: harvest cannot write a judgement.


def needs(filename):
    """[Need] -- the hand-written list, read rather than executed."""
    return corneeds.read_needs(vocab.load(HERE, filename, key='needs'),
                               make=Need)



def unknown(needs, catalogue):
    """Ids in NEEDS or AXIS_NEEDS that the game will not accept a binding for.

    The catalogue is read from the game's own files, so a typo or an id
    dropped by a patch shows up here rather than as a binding that silently
    does nothing.
    """
    known = cactions.by_id(catalogue)
    bad = []
    for n in needs:
        for slot in n.bindings:
            for ident in (b.action for b in slot):
                if ident not in known:
                    bad.append((n.what, kind_of(ident), ident))
        if n.push is not None:
            ident = n.push.action
            if ident not in known:
                bad.append((n.what, kind_of(ident), ident))
    for ident, _role, _how in AXIS_NEEDS:
        a = known.get(ident)
        if a is None or a.kind != 'axis':
            bad.append(('axis', RANGE, ident))
    return bad


# ------------------------------------------------------------ the hardware --

def axis_of(devs, role, how):
    """The axis a need names, by what the map says it is."""
    kind, value = how
    for a in devs[role].axes():
        if kind == 'kind' and a.kind == value:
            return a
        if kind == 'label' and a.label == value:
            return a
    return None


def axis_plan(devs):
    """[(x4 id, role, axis)] -- axes never go through the allocator."""
    out = []
    for ident, role, how in AXIS_NEEDS:
        a = axis_of(devs, role, how)
        if a is None:
            print(f'!! no {how[1]!r} axis on the {role} for {ident}',
                  file=sys.stderr)
            continue
        if a.hid not in AXIS_CODE:
            print(f'!! {role} axis {a.hid!r} has no X4 code', file=sys.stderr)
            continue
        out.append((ident, role, a))
    return out


def slots(devs, profile):
    """{role: X4 slot number}.

    X4 names a device by its position in enumeration order and keeps no device
    list in the file, so the number is not stable and means nothing outside the
    profile that wrote it. It is read back from the profile rather than
    assumed, and `X4_SLOTS` overrides it.

    A third device is in the mix: the Steam Controller puck enumerates as a
    pad and holds slot 1 in this profile, which is why the VIRPIL pair are
    slots 2 and 3 rather than 1 and 2.
    """
    forced = {}
    for part in filter(None, os.environ.get('X4_SLOTS', '').split(',')):
        role, _, num = part.partition('=')
        forced[role.strip()] = int(num)
    if set(forced) >= set(devs):
        return forced

    profs = harvest.profiles()
    name = profile
    if name not in profs:
        sys.exit(f'{name} is not in the profile folder; have '
                 + ', '.join(sorted(profs)))
    guessed = harvest.slots(profs[name])
    out = dict(forced)
    for slot, info in guessed.items():
        role = info['guess']
        if role in devs and role not in out:
            out[role] = int(slot.lstrip('_'))
    missing = set(devs) - set(out)
    if missing:
        sys.exit(f'cannot tell which X4 slot is the '
                 f'{", ".join(sorted(missing))} in {name}.\n'
                 '  slots seen: '
                 + '; '.join(f'{s} -> {i["guess"]} '
                             f'({len(i["axes"])} axes)'
                             for s, i in sorted(guessed.items()))
                 + '\n  set it with X4_SLOTS="stick=2,throttle=3"')
    return out


def source(slot, axis=False):
    """INPUT_SOURCE_JOYBUTTONS_2 and friends. Slot 1 carries no suffix."""
    stem = 'INPUT_SOURCE_JOYAXES' if axis else 'INPUT_SOURCE_JOYBUTTONS'
    return stem if slot == 1 else f'{stem}_{slot}'


# ----------------------------------------------------------------- writing --

#: One element per line, self-closing, two spaces in. Attribute order is not
#: fixed in the files X4 writes -- `toggle` sits between source and code -- so
#: lines are matched by element and then by attribute.
LINE = re.compile(r'^[ \t]*<(action|state|range)\s+([^>]*?)\s*/>[ \t]*\r?\n',
                  re.M)
ATTR = re.compile(r'(\w+)="([^"]*)"')


def render(kind, ident, src, code, indent='  '):
    return f'{indent}<{kind} id="{ident}" source="{src}" code="{code}"/>\n'


def lines_for(devs, placed, axes, slot):
    """[(kind, id, source, code)] -- every line the plan wants written.

    Placement.slots is already [(button index, payload)] with the control's
    click appended, so the button arithmetic is the core's, not repeated here.
    """
    out = []
    for p in placed:
        src = source(slot[p.role])
        for button, payload in p.slots:
            code = harvest.code(button)
            for ident in (b.action for b in payload):
                out.append((kind_of(ident), ident, src, code))
    for ident, role, a in axes:
        out.append((RANGE, ident, source(slot[role], axis=True),
                    'INPUT_JOYAXIS_' + AXIS_CODE[a.hid]))
    return out


def rewrite(text, wanted, ours):
    """Replace every binding on our devices with the plan's.

    A writer has to remove as well as add: an id dropped from NEEDS must stop
    answering, and a button that used to carry something else must not keep it.
    X4 makes that clean, because `source` names the hardware -- so every line
    pointing at our slots goes, and keyboard, mouse, compass and VR lines are
    never touched.

    Matching on the id alone would be wrong: up to three lines share one id
    (INPUT_ACTION_OPEN_MAP is a keyboard line AND a joystick line), and
    replacing the element would take the keyboard binding with it.
    """
    dropped = []
    keep = []
    last = 0
    for m in LINE.finditer(text):
        a = dict(ATTR.findall(m.group(2)))
        if a.get('source') in ours:
            dropped.append((m.group(1), a.get('id'), a.get('source')))
            keep.append(text[last:m.start()])
            last = m.end()
    keep.append(text[last:])
    text = ''.join(keep)

    block = ''.join(render(k, i, s, c) for k, i, s, c in wanted)
    close = text.rindex('</inputmap>')
    return text[:close] + block + text[close:], dropped


def profile_path(name):
    return os.path.join(harvest.profile_dir(), name)


def contents(devs, placed, axes, profile):
    """(path, the profile's whole new text, what went in, what came out).

    Computes and returns; `core.adapter` does the backing up and the writing.
    Every line whose source is one of our slots is dropped before ours go in,
    which is how a binding cut from `NEEDS` stops answering -- the clause no
    signature can state, and the one `tests/test_formats.py` holds.
    """
    if game.running('X4', 'X4.exe'):
        raise SystemExit('X4 is running -- it rewrites these files on exit. '
                         'Quit the game first.')
    slot = slots(devs, profile)
    path = profile_path(profile)
    if not os.path.exists(path):
        raise SystemExit(f'{path} does not exist -- save a profile of that '
                         'name in the game once so X4 creates it.')
    text = open(path, encoding='utf-8').read()

    ours = set()
    for role in devs:
        ours.add(source(slot[role]))
        ours.add(source(slot[role], axis=True))

    wanted = lines_for(devs, placed, axes, slot)
    new, dropped = rewrite(text, wanted, ours)
    return path, new, wanted, dropped, slot


# ---------------------------------------------------------------- the sheet --

CTX = ('Ship', 'Map', 'On foot')


def _sheet(layout, profile):
    devs, placed, unmet, free, axes = layout
    slot = slots(devs, profile)
    sh = csheet.Sheet(
        'Kneeboard X4', 'X4 Foundations · VIRPIL',
        ident='Code', contexts=CTX,
        devices={r: d.product for r, d in devs.items()})

    for p in sorted(placed, key=lambda p: (p.role, p.ctrl.label)):
        cells = {}
        for button, payload in p.slots:
            by_ctx = cells.setdefault(button, {})
            for ident in (b.action for b in payload):
                by_ctx.setdefault(context_of(ident), []).append(
                    harvest.readable(ident))
        for button, by_ctx in sorted(cells.items()):
            sh.add(csheet.Row(
                p.role, p.ctrl.label,
                part=p.ctrl.direction(button) or 'press',
                ident=harvest.code(button).replace('INPUT_XBUTTON_', ''),
                does=p.need.what, bindings=by_ctx))

    # One physical axis carries up to three ids, one per context, and
    # AxisRow has no bindings dict -- so the context goes in `does` or the
    # sheet shows the same lever three times with no way to tell them apart.
    for ident, role, a in axes:
        g = devs[role].axis_group(a.index)
        sh.add_axis(csheet.AxisRow(
            role, g.label if g else a.label,
            ident=AXIS_CODE[a.hid],
            does=f'{context_of(ident)}: {harvest.readable(ident)}'))

    sh.free = [(r, c.label, '', c.reach or '') for r, c in free]
    sh.unplaced = [(n.what, n.shape if isinstance(n.shape, str)
                    else '/'.join(n.shape)) for n in unmet]
    sh.note('Writing it', [
        ('Profile', f'{profile} — X4 puts menu edits in inputmap.xml, so '
                    'a named profile is the only place this survives.'),
        ('Slots', ', '.join(f'{r} = {s}' for r, s in sorted(slot.items()))
                  + '. Enumeration order, not stable: re-read after '
                    'plugging something in.'),
        ('Contexts', 'X4 scopes a binding by which id it is — MAP_* answers '
                     'only in the map, FP_* only on foot — so one button '
                     'carries three without clashing.'),
    ])
    return sh


# ---------------------------------------------------------------- the review --

def _describe(p):
    """[(which part of the control, what it does)] for the review pane.

    X4 scopes a binding by which id it is, so one button carries up to three
    meanings and each wants its context named -- the same reason `_sheet()`
    puts the context in the axis row's `does`.
    """
    out = []
    for button, payload in p.slots:
        part = p.ctrl.direction(button) or 'press'
        for ident in (b.action for b in payload):
            out.append((part,
                        f'{context_of(ident)}: {harvest.readable(ident)}'))
    return out


# -------------------------------------------------------------- the adapter --

@typing.final
class X4(adapter.Planner):
    """X4 Foundations, on the VIRPIL pair."""

    game = 'x4'
    title = 'X4 Foundations'
    BINDS = 'x4-binds.json'
    CATALOGUE = 'x4-actions.json'
    CACHE = {'x4-actions.json': 'actions'}


    @property
    @typing.override
    def NEEDS(self) -> list:
        """The literal stays at module scope -- it is most of this file, and
        moving it into the class body would bury every other change.

        A property rather than a class attribute because pyright rejects the
        second as an override of an abstract property, and because two of the
        six derive their needs and could never be a constant anyway.
        """
        return self._needs

    def __init__(self, profile=None, slots=None, backup_dir=None):
        self.profile = profile or os.environ.get('X4_PROFILE',
                                                 DEFAULT_PROFILE)
        self.forced_slots = slots or os.environ.get('X4_SLOTS', '')
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {self.profile}'
        # Reparsing four 46 KB XML files costs nothing, so the cache is
        # optional -- this is the game core/vocab.py's `build=` was written
        # for. It is read here rather than at import, so that importing this
        # module defines classes and reads nothing: the contract test then
        # tells a clone with no cache from an adapter that is broken.
        self.rows = self.cache('x4-actions.json',
                               build=harvest.action_rows)
        self._needs = needs(self.BINDS)

    @typing.override
    def build(self):
        devs = devmap.by_role('stick', 'throttle')
        return corneeds.Layout(devs, *corneeds.allocate(self.NEEDS, devs),
                               axes=axis_plan(devs))

    @typing.override
    def unknown(self):
        return unknown(self.NEEDS, self.catalogue())

    @typing.override
    def catalogue(self):
        # A read, not a translation. The harvest writes the record; what
        # `range` means and which context an id answers in are facts about
        # X4's naming, and they are settled where that naming is parsed.
        return cactions.read(self.rows)


    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout, self.profile)

    @typing.override
    def write_layout(self, layout):
        path, new, wanted, dropped, slot = contents(
            layout.devices, layout.placed, layout.axes, self.profile)
        print(f'  removed {len(dropped)}, wrote {len(wanted)} on slots '
              + ', '.join(f'{r}={slot[r]}'
                          for r in sorted(layout.devices)))
        # The whole path, not the basename: the profile sits six directories
        # into a Proton prefix, and "inputmap_3.xml" says neither which of
        # the three X4 keeps nor that it is the one under compatdata.
        print(f'  {path}')
        return {path: new}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--profile',
                            help=f'profile to write (default {self.profile})')

    @typing.override
    def paths(self, args):
        return [('profile dir', harvest.profile_dir()),
                ('writes', profile_path(self.profile)),
                ('backups', backup.dir_for('x4', self.backup_dir))]

    @typing.override
    def show(self, layout, why=False):
        devs, placed, unmet, _free, axes = layout
        slot = slots(devs, self.profile)
        out = [f'{self.profile}  '
               + '  '.join(f'{r} = slot {s}'
                           for r, s in sorted(slot.items())), '']
        for p_ in sorted(placed, key=lambda p_: (p_.need.urgency, p_.role)):
            n = p_.need
            out.append(f'  {n.what:24} {p_.role:9} {n.first_shape:9} '
                       f'{p_.ctrl.label}')
            for button, payload in p_.slots:
                part = p_.ctrl.direction(button) or 'press'
                for ident in (b.action for b in payload):
                    code = harvest.code(button).replace(
                        'INPUT_XBUTTON_', '')
                    out.append(f'      {part:9} {code:14} '
                               f'{context_of(ident):8} '
                               f'{harvest.readable(ident)}')
            if why:
                out.append('      ' + ' · '.join(corneeds.why_bits(p_)))
                if n.note:
                    out.append(f'      {n.note}')
        out.append('')
        for ident, role, a in axes:
            out.append(f'  {harvest.readable(ident):28} {role:9} '
                       f'{AXIS_CODE[a.hid]:8} {a.label}')
        if unmet:
            out.append('')
            out.append(f'{len(unmet)} unplaced: '
                       + ', '.join(f'{n.what} (wanted {n.first_shape})'
                                   for n in unmet))
        return out


if __name__ == '__main__':
    sys.exit(adapter.run(X4))

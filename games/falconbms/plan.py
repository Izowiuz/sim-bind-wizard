#!/usr/bin/env python3
"""plan.py - lay out Falcon BMS on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then write BMS's key file. --write-axes writes the axis defaults too.

FILES
    harvest.py                  the callback vocabulary and the vendor ranking
    BMS - Full.key              the shipped key file --write builds on
    BMS - VIRPIL.key            written by --write
    DeviceDefaults.txt          written by --write-axes
    axismapping.dat             moved aside by --write-axes, so BMS rebuilds it
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    BMS_DIR             the BMS install (--bms-dir overrides)
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Config files are latin-1 and CRLF; both are preserved.
    Select the key file in BMS Setup -> Controllers, or in the Launcher.
    --write-axes is untested; see README.
"""

import argparse
import os
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
#: the shared core. Sibling directory by default; SIM_BIND_WIZARD overrides it.
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'no shared core at {CORE}\n'
                     'clone sim-bind-wizard next to this repo, '
                     'or set SIM_BIND_WIZARD')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import needs as corneeds
from core import review as creview
from core import vocab
from core import sheet as csheet                          # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH, IN_THE_AIR,  # noqa: E402,F401
                        ON_THE_RAMP)
import harvest                                              # noqa: E402

#: Filled by `FalconBms.__init__`, never at import. Importing this module
#: has to define classes and read nothing, so that a clone with no harvested
#: cache is told apart from an adapter that is broken. `Need.votes` is a
#: property and `dx_offsets()` a function, so both read these only after an
#: adapter exists to fill them.
#: The catalogue as the harvest wrote it, keyed by callback. Filled when
#: an adapter is constructed, never at import.
CAT, ACTIONS, DEVICES, VOTES = [], {}, [], {}

DX_PER_DEVICE = 32
#: g_nHotasPinkyShiftMagnitude. We do not use the shifted layer -- see README --
#: but the writer has to know the number to keep out of its way.
SHIFT = 256





def _binds(calls):
    """BMS's own `calls` shape, as lists of Binds.

    A call is one callback, or a `(press, release)` pair for a switch that
    has to be told what to do when you let go -- the MRM/SRM override is
    the only one, twice. That is one binding with two halves rather than
    two actions, which is what `Bind.edge` is for.
    """
    out = []
    for c in calls:
        if not c:
            out.append([])
        elif isinstance(c, tuple):
            press, release = c
            out.append([cactions.Bind(press)]
                       + ([cactions.Bind(release, edge=cactions.RELEASE)]
                          if release else []))
        else:
            out.append([cactions.Bind(c)])
    return out


class Need(corneeds.Need):
    """The core's Need plus the one thing only BMS has: a second layer.

    Holding the pinky adds `g_nHotasPinkyShiftMagnitude` to the DX number, so
    every addressable button is worth two. Nothing else in the family works
    this way, so it stays here rather than in the core.
    """

    #: BMS alone puts some bindings on a shifted layer -- held pinky plus
    #: the button -- which is a second ledger over the same controls. It
    #: travels beside the judgements because no rule over a callback name
    #: finds it.
    shift = False

    @property
    def calls(self):
        return self.bindings

    def callbacks(self):
        out = [b.action for slot in self.bindings for b in slot]
        if self.push:
            out.extend(b.action for b in self.push)
        return out

    @property
    def votes(self):
        """How many of the 22 vendor profiles bind any part of this control."""
        got = [VOTES.get(c, 0) for c in self.callbacks()]
        return max(got) if got else 0


# The jet's own controls, most-urgent first. Urgency is the DCS wizard's scale:
# 0 you touch with a MiG on your tail, 1 on approach, 2 somewhere in the air,
# 3 on the ramp with the canopy open.
#: Where the judgements live. Which band a thing is in, what shape it wants,
#: which device it belongs on, what somebody wrote about it -- and nothing
#: derives any of it.
#:
#: Source, not cache. They were a Python literal until now, so changing one
#: meant editing code. Deliberately not in `CACHE`: that names what the
#: harvest wrote, and a harvest cannot write a judgement.


def needs(filename):
    """[Need] -- the hand-written list, read rather than executed."""
    return corneeds.read_needs(vocab.load(HERE, filename, key='needs'),
                               also=('shift',), make=Need)



#: in-game axis, which device, and how to find it in the map
AXIS_NEEDS = [
    ('AXIS_ROLL',       'stick',    'kind', 'stick-x'),
    ('AXIS_PITCH',      'stick',    'kind', 'stick-y'),
    ('AXIS_YAW',        'stick',    'kind', 'twist'),
    ('AXIS_THROTTLE',   'throttle', 'label', 'left throttle lever'),
    ('AXIS_BRAKE_LEFT', 'stick',    'kind', 'lever'),
    ('AXIS_ANT_ELEV',   'throttle', 'label', 'side lever'),
    ('AXIS_CURSOR_X',   'throttle', 'kind', 'mini-stick-x'),
    ('AXIS_CURSOR_Y',   'throttle', 'kind', 'mini-stick-y'),
    ('AXIS_FOV',        'throttle', 'kind', 'dial'),
]

AXIS_NOTE = {
    'AXIS_THROTTLE': 'the F-16 has one engine, so the right lever stays free',
    'AXIS_BRAKE_LEFT': 'BMS works both brakes off this one when no right brake '
                       'axis is set, which is what we want from a single lever',
    'AXIS_ANT_ELEV': 'a lever you set and leave, which is how the real knob works',
    'AXIS_FOV': 'the same dial carries zoom in DCS and War Thunder. It rests '
                'centred rather than at zero, so the view starts part-zoomed — '
                'the price of the same hand doing the same thing in all three',
}


# ------------------------------------------------------------------ matching

def addressable(ctrl):
    """Whether BMS can see this control at all.

    Every device gets exactly 32 DX numbers -- the setup guide says "this is by
    design and cannot be altered" -- and they are the device's first 32
    buttons. The VMAX has 51, so its last 19 are invisible to BMS however real
    they are to your hand: the T2 rocker's lower contact, T3 to T5, the APU
    button, both encoders and the whole mode selector.

    This is not a budget the shifted layer can rescue. Shifting adds 256 to the
    DX NUMBER, not to the physical button, so a button with no number to begin
    with gains nothing."""
    btns = ctrl.bindable_buttons
    return not btns or max(btns) < DX_PER_DEVICE


def devices():
    return devmap.by_role('stick', 'throttle')


def usable(role, ctrl):
    """The core's veto hook: BMS cannot see past a device's 32nd button."""
    return addressable(ctrl)


def assign(needs):
    """(devices, placements, unplaced, free) using the shared allocator.

    Two calls rather than one, because the shifted layer runs over the SAME
    controls again and so needs its own ledger. The core gives that for free:
    a separate `allocate` has a separate `taken`, and the one control it must
    not reuse -- whatever carries the shift itself, since holding a button
    cannot also mean pressing it -- is excluded through the veto hook.
    """
    devs = devices()
    plain = [n for n in needs if not n.shift]
    shifted = [n for n in needs if n.shift]

    placed, unmet, free = corneeds.allocate(plain, devs, usable=usable)

    if shifted:
        holder = next((p.ctrl for p in placed
                       if 'SimHotasPinkyShift' in p.need.callbacks()), None)
        if holder is None:
            sys.exit('needs want the shifted layer but nothing carries '
                     'SimHotasPinkyShift -- add it to NEEDS')
        more, unmet2, spare = corneeds.allocate(
            shifted, devs,
            usable=lambda r, c: usable(r, c) and c is not holder)
        placed += more
        unmet += unmet2
        # Intersected, not replaced. Each `allocate` reports what ITS OWN
        # pass left over, so the shifted one calls the whole plain layer
        # free -- and taking its answer offered 24 occupied controls,
        # the main trigger among them, to anything looking for a home.
        still = {(r, id(c)) for r, c in spare}
        free = [(r, c) for r, c in free if (r, id(c)) in still]
    return devs, placed, unmet, free


def unreachable():
    """Controls BMS cannot address, with the DX numbers they would have had."""
    out = []
    for role, d in devmap.by_role().items():
        for c in d.groups(bindable=True):
            if not addressable(c):
                out.append((role, c))
    return out


# ------------------------------------------------------------------ numbering

def dx_offsets():
    """BMS numbers DX buttons in one flat space, 32 per device, and
    DeviceSorting.txt fixes the order. So the sorting file IS the offset table,
    and the map's own USB ids are what line the two up."""
    by_usb = {d['usb']: d for d in DEVICES}
    out = {}
    for role, dev in devices().items():
        entry = next((by_usb[i['usb'].lower()] for i in dev.identities
                      if i.get('usb', '').lower() in by_usb), None)
        if entry is None:
            sys.exit(f'{dev.product} is not in the game\'s DeviceSorting.txt — '
                     'plug it in and start BMS once, then re-run ./harvest.py')
        out[role] = entry['dx_offset']
    return out


def dinput_axis(dev, axis):
    """The DirectInput name BMS wants for one of our axes.

    HID Slider, Dial and Wheel all land on DirectInput's two slider axes, in
    descriptor order -- which is why this counts through the fingerprint rather
    than reading `hid` on its own. The VMAX has both a Slider and a Dial, so
    getting this wrong swaps zoom and the brake."""
    name = axis.hid
    if name in ('X', 'Y', 'Z'):
        return name
    if name in ('Rx', 'Ry', 'Rz'):
        return name.upper()
    if name in ('Slider', 'Dial', 'Wheel'):
        order = [h for h in dev.fingerprint.get('hid', [])
                 if h in ('Slider', 'Dial', 'Wheel')]
        try:
            return f'SLIDER{order.index(name)}'
        except ValueError:
            return 'SLIDER0'
    return None


def find_axis(dev, how, what):
    if how == 'kind':
        return next((a for a in dev.axes() if a.kind == what), None)
    return next((a for a in dev.axes()
                 if what in (a.label or '').lower()), None)


def axis_plan(devs):
    """[(name, role, axis, dinput index)] -- the axes BMS will be told about."""
    axes = []
    for name, role, how, what in AXIS_NEEDS:
        dev = devs[role]
        a = find_axis(dev, how, what)
        if a is None:
            continue
        di = dinput_axis(dev, a)
        if di:
            axes.append((name, role, a, di))
    return axes


def dx_binds(placed):
    """Ready-to-write DX lines for the placements given.

    This was computed inside `build()`, which meant the key file could only be
    written from the whole plan. It takes `placed` so a reviewer who accepted
    some bindings and not others has something to hand it.
    """
    off = dx_offsets()
    binds, seen = [], {}
    for p in placed:
        for local, payload in p.slots:
            if not payload:
                continue
            dx = off[p.role] + local + (SHIFT if p.need.shift else 0)
            press = next((b.action for b in payload
                          if b.edge == cactions.PRESS), None)
            release = next((b.action for b in payload
                            if b.edge == cactions.RELEASE), None)
            where = f'{p.ctrl.label} — {p.ctrl.direction(local) or "press"}'
            if dx in seen:
                print(f'!! DX {dx} wanted by {seen[dx]} and {p.need.what}',
                      file=sys.stderr)
            seen[dx] = p.need.what
            binds.append({'need': p.need, 'role': p.role, 'ctrl': p.ctrl,
                          'local': local, 'dx': dx, 'press': press,
                          'release': release, 'where': where})
    return binds


# ------------------------------------------------------------------- writing

def _flat(text):
    """Key files are latin-1, and BMS's own parser is happier still with plain
    ASCII. Our comments carry em dashes out of the device map, so flatten
    them rather than hand the game a byte it cannot read."""
    swaps = {'\u2014': '-', '\u2013': '-', '\u2018': "'", '\u2019': "'",
             '\u201c': '"', '\u201d': '"', '\u2026': '...'}
    for a, b in swaps.items():
        text = text.replace(a, b)
    return text.encode('ascii', 'replace').decode('ascii')


def dx_lines(binds):
    """The block appended to the key file.

    Two syntaxes, and the difference matters: `-1` in the sound field is an
    ordinary button, `-2` opts into the press/release form, where `0` is the
    press edge and `0x42` the release. Nothing here writes a `-3` POV line --
    VIRPIL firmware reports no HID hat usages at all, so every one of our hats
    is a set of plain buttons."""
    out = ['',
           '#################################################################',
           '###',
           '### VIRPIL layout, written by falconbms-bind-wizard.',
           '### Do not hand-edit: regenerate with ./plan.py --write.',
           '###',
           '### DX numbering follows User/Config/DeviceSorting.txt.',
           '### The pinky-shifted layer (DX +256) is deliberately unused --',
           '### there are 83 buttons here and 22-button sticks are what the',
           '### shift layer was invented for.',
           '###',
           '#################################################################',
           '']
    last = None
    for b in sorted(binds, key=lambda b: b['dx']):
        if b['role'] != last:
            last = b['role']
            out.append('')
            out.append('SimDoNothing -1 0 0XFFFFFFFF 0 0 0 -2 '
                       f'"========= {last.upper()} ========="')
            out.append('')
        out.append(_flat(f'# DX{b["dx"]}  {b["where"]}  ({b["need"].what})'))
        if b['release']:
            out.append(f'{b["press"]} {b["dx"]} -2 -2 0 0x0 -1')
            out.append(f'{b["release"]} {b["dx"]} -2 -2 0x42 0x0 -1')
        else:
            out.append(f'{b["press"]} {b["dx"]} -1 -2 0 0x0 -1')
        out.append('')
    return '\n'.join(out)


def read_keeping(path):
    """Read a BMS config file as text, and report how it ends its lines.

    Every file in User/Config is CRLF, and writing one back as LF rewrites all
    of it. That is how a one-line change turns into a diff the size of the file
    and how a backup stops being useful for telling what we actually did --
    the same mistake this family of tools already made once, on War Thunder's
    machine.blk."""
    raw = path.read_bytes().decode('latin-1')
    nl = '\r\n' if '\r\n' in raw else '\n'
    return raw.replace('\r\n', '\n'), nl


KEYFILE_OUT = 'BMS - VIRPIL.key'


def key_file(bms, placed):
    """(path, the key file's whole new text, lines to print).

    Built from the shipped Full one, so every keyboard binding and every
    comment in it survives; only the DX block is ours.

    It used to take `placed=None` and call `build()` for itself when nobody
    passed any -- which meant a reviewer who cleared half the plan and pressed
    `w` got all of it written anyway. There is no such argument now: the
    placements are the only thing this is given.
    """
    src = bms / 'User' / 'Config' / 'BMS - Full.key'
    dst = bms / 'User' / 'Config' / KEYFILE_OUT
    binds = dx_binds(placed)
    body, nl = read_keeping(src)
    # the first line's description names the file inside BMS's own UI
    body = body.replace('"BMS - Full"', f'"{KEYFILE_OUT[:-4]}"', 1)
    text = body.rstrip('\n') + '\n' + dx_lines(binds) + '\n'
    return dst, text.replace('\n', nl), [
        f'           {len(binds)} DX bindings',
        '',
        'Pick it in the Alternative Launcher (falcon-bms launcher) under',
        f'Keyfile, or in BMS Setup -> Controllers: "{KEYFILE_OUT[:-4]}".']


AXIS_HEADER = '# ---- VIRPIL, written by falconbms-bind-wizard ----'


def _strip_stub(txt, guid, product):
    """BMS writes its own commented placeholder for a device it does not know:

        # R-VPC Stick WarBRD-D
        #GUID = {43E83344-...}
        # Now please add the axismappings for this controller here and ...

    which is the game telling us in its own words that this file is the way in.
    Drop the stub before writing the real block, so the device appears once."""
    out, lines = [], txt.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().lstrip('#').strip().startswith('GUID') \
                and guid in lines[i]:
            if out and product in out[-1]:
                out.pop()
            i += 1
            while i < len(lines) and (lines[i].startswith('#')
                                      or not lines[i].strip()):
                if 'please add the axismappings' not in lines[i]:
                    break
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return '\n'.join(out)


def axis_files(bms, axes):
    """({path: contents}, lines to print) for the axis half of a write.

    `DeviceDefaults.txt` gets our block; the binary mapping is handed back as
    MOVE, because BMS rebuilds it from the defaults only when it is GONE --
    renaming it in place left the game's own config folder full of
    `.dat.<stamp>.bak`, in a directory the game reads.
    """
    cfg = bms / 'User' / 'Config'
    defaults = cfg / 'DeviceDefaults.txt'
    devs = devices()
    said = []

    per = {}
    for name, role, a, di in axes:
        per.setdefault(role, []).append((name, di, a))

    block = ['', AXIS_HEADER]
    for role, items in sorted(per.items()):
        dev = devs[role]
        pid, vid = dev.usb.split(':')
        block.append('')
        block.append(f'# {dev.product}')
        block.append(f'GUID = {{{vid.upper()}{pid.upper()}'
                     '-0000-0000-0000-504944564944}')
        for name, di, a in items:
            block.append(f'{name} = {di}')
    block.append('')

    txt, nl = read_keeping(defaults)
    if AXIS_HEADER in txt:
        txt = txt[:txt.index(AXIS_HEADER)].rstrip('\n')
        said.append('replaced the previous VIRPIL block')
    for role, items in per.items():
        dev = devs[role]
        pid, vid = dev.usb.split(':')
        guid = f'{vid.upper()}{pid.upper()}-0000-0000-0000-504944564944'
        before = txt
        txt = _strip_stub(txt, guid, dev.product)
        if txt != before:
            said.append(f'removed    the game\'s own stub for {dev.product}')

    body = txt.rstrip('\n') + '\n' + '\n'.join(block) + '\n'
    #: {path: Text or str, or MOVE for a file that must be gone} -- the
    #: writer contract in core/adapter.py, and MOVE is None, so the value
    #: type has to be spelled out or the first entry decides it.
    files: dict = {defaults: adapter.Text(body.replace('\n', nl),
                                          encoding='latin-1')}
    for name in ('axismapping.dat', 'axismapping_tmp.dat'):
        if (cfg / name).exists():
            files[cfg / name] = adapter.MOVE

    said += ['',
             'BMS should rebuild the binary from the defaults on next start.',
             'If it does not, set these nine by hand in the Launcher — the '
             'plan', 'above says exactly which physical axis each one is.']
    return files, said


# --------------------------------------------------------------- the review

def _describe(p):
    """[(DX number, callback)] -- what BMS will actually be told."""
    out = []
    for b in dx_binds([p]):
        what = b['press']
        if b['release']:
            what = f'{what}  (release: {b["release"]})'
        out.append((f'DX{b["dx"]}', what))
    return out


# -------------------------------------------------------------------- output

def wrap(text, width, indent):
    out, line = [], ''
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    if line:
        out.append(line)
    return f'\n{indent}'.join(out)


def show(layout, why=False, free_only=False):
    _devs, placed, unmet, free, axes = layout
    out = []
    binds = dx_binds(placed)
    off = dx_offsets()

    if not free_only:
        out.append('AXES')
        for name, role, a, di in axes:
            out.append(f'  {name:<16} {role:<9} {di:<8} {a.label}')
            note = AXIS_NOTE.get(name)
            if why and note:
                out.append(f'{"":<19}{wrap(note, 56, " " * 19)}')
        out.append("")

        by_need = {}
        for b in binds:
            by_need.setdefault(id(b['need']), []).append(b)
        out.append('BUTTONS')
        # The placement itself, not just four fields off it: the account
        # of WHY it is here is a property of the placement, and unpacking
        # it away left `show` reassembling one from the pieces.
        for p_ in placed:
            need, role, ctrl = p_.need, p_.role, p_.ctrl
            mine = by_need.get(id(need), [])
            if not mine:
                out.append(f'  {need.what}')
                out.append(f'!!    {ctrl.label} was chosen but carries nothing — '
                      'a bug in slots_for')
                continue
            out.append(f'  {need.what}')
            out.append(f'{"":<4}{ctrl.label}  ({role}, {ctrl.reach})')
            for b in sorted(mine, key=lambda b: b['dx']):
                d = ctrl.direction(b['local']) or 'press'
                extra = f'   / release: {b["release"]}' if b['release'] else ''
                out.append(f'      DX{b["dx"]:<4} {d:<8} {b["press"]}{extra}')
            if why:
                out.append('      why    '
                           + '; '.join(corneeds.why_bits(p_, out_of=22)))
                if need.dev and need.dev != role:
                    # BMS's own: the only game that calls a wrong device a
                    # compromise rather than a minus fifty.
                    out.append(f'             COMPROMISE: belongs on the '
                               f'{need.dev}, nothing of that shape was '
                               f'left there')
                if need.note:
                    out.append(f'{"":<13}{wrap(need.note, 60, " " * 13)}')
            out.append("")

        if unmet:
            out.append('NOT PLACED')
            for n in unmet:
                out.append(f'  {n.what:<28} wanted a {n.shape}')
            out.append("")

    out.append('STILL FREE')
    for role, c in free:
        n = len(c.bindable_buttons)
        dx = ', '.join(f'DX{off[role] + b}' for b in c.bindable_buttons)
        out.append(f'  {c.label:<28} {c.kind:<10} {role:<9} {n} button(s)  {dx}')
    return out


def audit(layout):
    """Which callbacks the vendors put on hardware and we did not."""
    out = []
    binds = dx_binds(layout.placed)
    mine = set()
    for b in binds:
        mine.add(b['press'])
        if b['release']:
            mine.add(b['release'])

    bad = [c for c in sorted(mine) if c not in ACTIONS]
    if bad:
        out.append('NOT IN THE KEY FILE — these would be silently ignored:')
        for c in bad:
            out.append(f'  {c}')
        out.append("")

    missed = [(cb, n) for cb, n in sorted(VOTES.items(), key=lambda x: -x[1])
              if cb not in mine and n >= 8]
    mfd = [c for c, _ in missed if 'OSB' in c or 'BRT' in c]
    out.append(f'placed {len(mine)} callbacks')
    out.append(f'ranked but not placed: {len(missed)}'
          f'  ({len(mfd)} of them MFD buttons, which need an MFD panel)')
    for cb, n in missed:
        if cb in mfd:
            continue
        a = ACTIONS.get(cb)
        desc = a.name if a is not None else '(gone from the key file)'
        out.append(f'  {n:>3}  {cb:<28} {desc[:52]}')
    return out


#: What to look at once, on the ramp, because it could not be settled offline.
#: Kept here rather than in the template so it sits next to the thing it
#: describes and cannot quietly go stale.
RAMP_CHECKS = [
    ('Master arm', 'it is on the trigger lever, so the guard position IS the '
                   'switch position. Which of the two contacts is the closed '
                   'lever was never measured — if the jet arms with the lever '
                   'down, swap the two names in NEEDS and regenerate.'),
    ('Trim', 'BMS names trim after the wheel, not the nose: '
             '<code>AFElevatorTrimUp</code> is nose DOWN.'),
    ('DOGFIGHT switch', 'hold it forward for MRM, back for dogfight, let go '
                        'and it should cancel. The cancel is the release edge '
                        '— no other sim of the four can express it.'),
]

#: Where our hardware and the jet disagree. The interesting half of the layout.
COMPROMISES = [
    ('Roll trim', 'the F-16 grip has four hats and the WarBRD has three, so '
                  'TMS, DMS and CMS take them and trim gets the encoder: '
                  'pitch only. Roll trim stays on the keyboard.'),
    ('Eject', 'not bound. Twenty of the twenty-two vendor profiles hide it on '
              'the pinky-shifted layer; we do not use that layer, and no button '
              'here is awkward enough to be safe.'),
    ('Zoom', 'on the dial, which rests centred rather than at zero — so the '
             'view may start part-zoomed. The price of the same dial carrying '
             'zoom in DCS and War Thunder too.'),
    ('Axis direction', 'not ours to set. <code>DeviceDefaults.txt</code> says '
                       '<i>which</i> physical axis, never <i>which way</i> — so '
                       'walk the four Advanced Options tabs, move each control, '
                       'watch its value bar and hit <b>Reverse</b> where it runs '
                       'backwards. Pitch almost certainly needs it.'),
    ('SET AB', 'on the Controllers page: left-click sets the afterburner '
               'detent, right-click the idle detent. Without the first there is '
               'no afterburner. <b>CENTER</b>, stick released, zeroes pitch and '
               'roll.'),
    ('A missing axis', 'is usually assigned already — BMS allows one physical '
                       'axis per in-game axis, so an axis in use vanishes from '
                       'every other dropdown. Check all four tabs before '
                       'concluding a device is dead.'),
]
def _sheet(layout):
    """Everything a kneeboard needs, in the core's shape.

    BMS has one aircraft, so there is one unnamed context and the callback
    reads as a second line under the plain-English name. War Thunder passes
    ('Air', 'Helicopter') to the same builder and gets a column each.
    """
    _devs, placed, unmet, free, axes = layout
    binds = dx_binds(placed)
    devs = devices()
    off = dx_offsets()

    sh = csheet.Sheet(
        'Kneeboard Falcon BMS', 'Falcon BMS · F-16C · VIRPIL',
        ident='DX',
        devices={r: f'{d.product}  (DX {off[r]}–{off[r] + 31})'
                 for r, d in devs.items()})

    for name, role, a_, di in axes:
        g = devs[role].axis_group(a_.index)
        sh.add_axis(csheet.AxisRow(role, g.label if g else a_.label,
                                   ident=di, does=name))

    for b in sorted(binds, key=lambda x: x['dx']):
        sh.add(csheet.Row(
            b['role'], b['ctrl'].label,
            part=b['ctrl'].direction(b['local']) or 'press',
            ident=str(b['dx']), does=b['need'].what,
            bindings={'': b['press']}, edge=b['release'] or ''))

    sh.note('Check on the ramp', RAMP_CHECKS)
    sh.note('Where the hardware and the jet disagree', COMPROMISES)
    sh.note('Picking it up',
            'falcon-bms launcher → Keyfile → "BMS - VIRPIL". '
            'Regenerate with ./plan.py --write; never hand-edit.')
    sh.unplaced = [(n.what, n.shape if isinstance(n.shape, str)
                    else '/'.join(n.shape)) for n in unmet]
    sh.free = [(role, c.label,
                ', '.join(str(off[role] + x) for x in c.bindable_buttons),
                c.reach) for role, c in free]
    return sh


# -------------------------------------------------------------- the adapter --

@typing.final
class FalconBms(adapter.Planner):
    """Falcon BMS 4.38, F-16C, on the VIRPIL pair."""

    game = 'falconbms'
    title = 'Falcon BMS'
    BINDS = 'falconbms-binds.json'
    EXTRA = ('shift',)
    CATALOGUE = 'bms-actions.json'
    CACHE = {'bms-actions.json': ('actions', 'devices'),
             'bms-rank.json': 'votes'}
    #: BMS's own word for the install predates the family's. Both spellings
    #: reach the same constructor parameter rather than one of them being
    #: laundered through os.environ, which is what used to happen.
    ALIASES = {'game_dir': ('--bms-dir',)}


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

    def __init__(self, game_dir=None, backup_dir=None):
        if game_dir:
            os.environ['BMS_DIR'] = game_dir
        self.bms = harvest.bms_dir()
        self.backup_dir = backup_dir
        self.subtitle = f'VIRPIL · {KEYFILE_OUT}'
        CAT[:] = cactions.read(self.cache('bms-actions.json',
                                          key='actions'))
        ACTIONS.update(cactions.by_id(CAT))
        DEVICES[:] = self.cache('bms-actions.json', key='devices')
        VOTES.update(self.cache('bms-rank.json'))
        self._needs = needs(self.BINDS)

    @typing.override
    def build(self):
        devs, placed, unmet, free = assign(self.NEEDS)
        return corneeds.Layout(devs, placed, unmet, free,
                               axes=axis_plan(devs))

    @typing.override
    def catalogue(self):
        # A read, not a translation: which of BMS's two panel names is
        # the category, and what a callback is called, are settled in the
        # run that parses the key file.
        return list(CAT)


    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout)

    @typing.override
    def show(self, layout, why=False):
        return show(layout, why=why)

    @typing.override
    def free(self, layout):
        return show(layout, free_only=True)

    @typing.override
    def write_layout(self, layout):
        """The key file and the axis defaults, in one run.

        BMS needed two writes for one layout: `--write` did the key file and
        `--write-axes` the rest, and `./bind bms write` passed both to hide
        it. One layout is one write now, and `--write-axes` remains for the
        axis half on its own.
        """
        dst, text, said = key_file(self.bms, layout.placed)
        files, more = axis_files(self.bms, layout.axes)
        files[dst] = adapter.Text(text, encoding='latin-1')
        for line in said + more:
            print(line)
        return files

    @typing.override
    def extra(self, args, layout):
        if args.audit:
            return audit(layout)
        if args.write_axes:
            files, said = axis_files(self.bms, layout.axes)
            return said + self.lay_down(files)
        return None

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--audit', action='store_true',
                            help='list ranked callbacks left unplaced')
        parser.add_argument('--write-axes', action='store_true',
                            help='write only the axis defaults')

    @typing.override
    def paths(self, args):
        cfg = self.bms / 'User' / 'Config'
        return [('game', str(self.bms)),
                ('writes', str(cfg / KEYFILE_OUT)),
                ('and', str(cfg / 'DeviceDefaults.txt')),
                ('backups', backup.dir_for('falconbms', self.backup_dir))]


if __name__ == '__main__':
    sys.exit(adapter.run(FalconBms))

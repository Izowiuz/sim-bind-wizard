#!/usr/bin/env python3
"""Lay the real F-16 HOTAS onto the hardware we actually have.

This one is different from its three siblings, and the difference is the whole
point. In DCS, War Thunder and MSFS the wizard has to *invent* a layout: the
sims have hundreds of aircraft and no opinion about where anything goes, so the
needs are stated as shapes and matched against whatever fits.

BMS has one aircraft, and the F-16's HOTAS is prescriptive. Its designers
already decided that target management is a four-way hat under your thumb and
that the speedbrake is a fore/aft switch on the throttle. Twenty-two vendor
profiles in `Hotas/Archive` agree with each other to a degree nothing in the
other three sims comes close to. So the needs below are not a guess -- they are
the real jet's own controls, and `--why` prints how many of those profiles back
each one.

What still has to be worked out is which of OUR controls plays each part, and
that is what sim-device-map is for.

    ./plan.py                 # the layout
    ./plan.py --why           # and the evidence for each choice
    ./plan.py --free          # what is still unbound
    ./plan.py --audit         # ranked callbacks we did not place
    ./plan.py --sheet         # write KNEEBOARD.md
    ./plan.py --write         # write the key file into the game
    ./plan.py --write-axes    # and the axis defaults (see the README caveat)
"""

import argparse
import os
import shutil
import sys
from datetime import datetime

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

from core import devmap                                     # noqa: E402
from core import needs as corneeds
from core import vocab
from core import sheet as csheet                          # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH, IN_THE_AIR,  # noqa: E402,F401
                        ON_THE_RAMP)
import harvest                                              # noqa: E402

DX_PER_DEVICE = 32
#: g_nHotasPinkyShiftMagnitude. We do not use the shifted layer -- see README --
#: but the writer has to know the number to keep out of its way.
SHIFT = 256



ACTIONS = vocab.load(HERE, 'bms-actions.json', key='actions')
DEVICES = vocab.load(HERE, 'bms-actions.json', key='devices')
VOTES = dict(vocab.load(HERE, 'bms-rank.json', key='votes'))


class Need(corneeds.Need):
    """The core's Need plus the one thing only BMS has: a second layer.

    Holding the pinky adds `g_nHotasPinkyShiftMagnitude` to the DX number, so
    every addressable button is worth two. Nothing else in the family works
    this way, so it stays here rather than in the core.
    """

    def __init__(self, what, shape, calls=(), shift=False, **kw):
        super().__init__(what, shape, bindings=calls, **kw)
        self.shift = shift

    @property
    def calls(self):
        return self.bindings

    def callbacks(self):
        out = []
        for c in list(self.bindings) + ([self.push] if self.push else []):
            if isinstance(c, tuple):
                out.extend(x for x in c if x)
            elif c:
                out.append(c)
        return out

    @property
    def votes(self):
        """How many of the 22 vendor profiles bind any part of this control."""
        got = [VOTES.get(c, 0) for c in self.callbacks()]
        return max(got) if got else 0


# The jet's own controls, most-urgent first. Urgency is the DCS wizard's scale:
# 0 you touch with a MiG on your tail, 1 on approach, 2 somewhere in the air,
# 3 on the ramp with the canopy open.
NEEDS = [
    # ------------------------------------------------------------- the grip
    Need('Trigger', 'trigger',
         ['SimTriggerFirstDetent', 'SimTriggerSecondDetent'],
         dev='stick', urgency=0, suits='fire',
         note='cumulative: the light pull starts the gun camera and the AVTR, '
              'pulling through it fires. The third detent stays free'),

    Need('Weapon release (Pickle)', 'button', ['SimPickle'],
         dev='stick', urgency=0, suits='fire',
         note='everything you drop or shoot comes off here'),

    Need('TMS — target management', 'hat4',
         ['SimTMSUp', 'SimTMSRight', 'SimTMSDown', 'SimTMSLeft'],
         dev='stick', urgency=0, suits='sensor',
         note='up locks what the cursor is over, down breaks the lock'),

    Need('DMS — display management', 'hat4',
         ['SimDMSUp', 'SimDMSRight', 'SimDMSDown', 'SimDMSLeft'],
         dev='stick', urgency=0, suits='sensor',
         note='picks the SOI — which MFD or the HUD the cursor is driving'),

    Need('CMS — countermeasures', 'hat4',
         ['SimCMSUp', 'SimCMSRight', 'SimCMSDown', 'SimCMSLeft'],
         dev='stick', urgency=0, suits='reflex',
         note='up runs the CMDS programme: this is chaff and flares'),

    Need('Paddle — AP / trim disconnect', 'paddle', ['SimAPOverride'],
         dev='stick', urgency=0, suits='reflex',
         note='hold it to override the autopilot and the trim'),

    Need('NWS / AR DISC / MSL STEP', 'button', ['SimMissileStep'],
         dev='stick', urgency=0, suits='reflex',
         note='one button, three jobs depending on what the jet is doing: '
              'nosewheel steering on the ground, missile step in the air'),

    # The F-16 grip has FOUR hats -- TMS, DMS, CMS and trim -- and the WarBRD
    # has three. Target, display and countermeasure management all outrank
    # trim in a fight, so trim takes the encoder: pitch, which is the one you
    # actually use (tanking, and hands-off level flight), plus reset on the
    # click. Roll trim stays on the keyboard. This is the single place where
    # the hardware is short of the jet, and it is a deliberate choice.
    Need('Trim — pitch', 'encoder',
         ['AFElevatorTrimDown', 'AFElevatorTrimUp'], push='AFResetTrim',
         dev='stick', urgency=0, suits='trim',
         note='BMS names these after the trim wheel, not the nose: '
              '"Trim Up" is nose DOWN. Roll trim is not on the HOTAS — '
              'three hats on the grip, four on the jet'),

    Need('Master arm', 'latch', ['SimSafeMasterArm', 'SimArmMasterArm'],
         dev='stick', urgency=2, suits='state',
         note='the lever over the trigger, so the guard position IS the switch '
              'position. CHECK THIS ON THE RAMP: which of the two contacts is '
              'the closed lever was never measured — if the jet arms with the '
              'lever down, swap the two names in NEEDS'),

    # ----------------------------------------------------------- the throttle
    Need('Radar cursor (slew)', 'ministick', [], push='SimCursorEnable',
         dev='throttle', urgency=0, suits='view',
         note='the axes drive the cursor, the press is Cursor Enable'),

    Need('COMMS switch', 'hat4',
         ['SimTransmitCom1', 'SimCommsSwitchRight',
          'SimTransmitCom2', 'SimCommsSwitchLeft'],
         dev='throttle', urgency=0, suits='reflex',
         note='up UHF, down VHF, left and right work the IFF'),

    Need('SPD BRAKE switch', 'hat2', ['AFBrakesIn', 'AFBrakesOut'],
         on=('forward', 'back'), dev='throttle', urgency=0, suits='reflex',
         note='forward closes, back opens — the way the real switch moves'),

    Need('DOGFIGHT / MRM override', 'hat2',
         [('SimSelectMRMOverride', 'SimDeselectOverride'),
          ('SimSelectSRMOverride', 'SimDeselectOverride')],
         on=('forward', 'back'), dev='throttle', urgency=0, suits='reflex',
         note='spring-loaded in the real jet: hold it forward for MRM, back '
              'for dogfight, let go and it cancels. That last part is the '
              'release edge, which no other sim of the four can express'),

    Need('MAN RANGE knob — UNCAGE', 'button', ['SimToggleMissileCage'],
         dev='throttle', urgency=0, suits='reflex',
         note='uncages the seeker so a heater growls at what you point it at'),

    Need('Radar cursor zero', 'button', ['SimRadarCursorZero'],
         dev='throttle', urgency=0,
         note='puts the cursor back under the nose when you have lost it — '
              'which happens while slewing, so it has to be under the thumb'),

    # ------------------------------------------------------------ in the air
    Need('MAN RANGE knob', 'encoder', ['SimRangeKnobDown', 'SimRangeKnobUp'],
         dev='throttle', urgency=2, suits='trim', shift=True),

    Need('Radar gain', 'encoder', ['SimRadarGainDown', 'SimRadarGainUp'],
         dev='throttle', urgency=2, suits='trim', shift=True),

    Need('ICP — master mode', 'hat2', ['SimICPAA', 'SimICPAG'], urgency=2,
         note='air-to-air and air-to-ground; NAV is the way back out'),

    Need('ICP — NAV mode', 'button', ['SimICPNav'], urgency=2),

    Need('IFF MASTER knob', 'selector',
         ['SimIFFMasterOff', 'SimIFFMasterStby', 'SimIFFMasterLow',
          'SimIFFMasterNorm', 'SimIFFMasterEmerg'],
         dev='throttle', urgency=2, suits='state', shift=True,
         note='five positions in the jet and five on the selector, and the '
              'knob holds its state the same way — the one control here that '
              'matches its cockpit original exactly'),

    # BMS gives every device 32 DX numbers and no more, so the 83 buttons on
    # this pair are only 64 BMS can see. The shifted layer is the only way to
    # fit the rest -- which is what 22 of 22 vendor profiles were saying by
    # binding this callback first. A short press still works as an ordinary
    # pinky press; held past 200 ms it shifts every device at once.
    Need('DX shift (pinky)', 'button', ['SimHotasPinkyShift'],
         dev='stick', urgency=2, suits='occasional',
         # Pinned by hand. Scoring rates this and a throttle keyboard button as
         # equivalent -- both need letting go of the grip -- but this is a
         # button you HOLD while pressing another, and if that other one is on
         # the throttle too you run out of hand.
         prefer='Grip pinky button',
         note='hold it to reach the second layer. Everything on that layer is '
              'something you do on the ground, so a button you have to regrip '
              'for is the right home'),

    Need('Recentre head tracking', 'button', ['RecenterTrackIR'], urgency=2),

    Need('Look closer', 'button', ['FOVToggle'], urgency=2,
         note='a step zoom on top of the analogue one on the dial'),

    Need('Slap switch (ECM)', 'button', ['SimSlapSwitch'], urgency=2),

    Need('Laser arm', 'button', ['SimLaserArmToggle'], urgency=2),

    # ------------------------------------------------------------ on approach
    # The vendors mostly bind AFGearToggle and SimCATSwitch, because a Warthog
    # has no spare two-position switches. We have five rockers, so the switch
    # position and the aircraft agree even after an alt-tab or a reload -- a
    # toggle only ever knows what it did last.
    Need('Landing gear', 'hat2', ['AFGearUp', 'AFGearDown'],
         on=('up', 'down'), urgency=1, suits='stepped-pair', shift=True),

    Need('Parking brake', 'hat2',
         ['SimParkingBrakeUp', 'SimParkingBrakeDown'],
         on=('up', 'down'), urgency=1, suits='stepped-pair', shift=True),

    Need('Landing / taxi lights', 'button', ['SimLandingLightCycle'],
         urgency=1,
         note='LANDING / OFF / TAXI is three positions, and cycling costs one '
              'button where matching it costs a rocker the two-position '
              'switches want more'),

    # ------------------------------------------------------------- on the ramp
    Need('JFS — engine start', 'hat2', ['SimJfsStartUp', 'SimJfsStartDown'],
         on=('up', 'down'), urgency=3, suits='stepped-pair',
         note='START 1 is the one the cold start wants'),

    Need('Throttle idle detent', 'hat2',
         ['SimThrottleIdleDetentForward', 'SimThrottleIdleDetentBack'],
         on=('up', 'down'), urgency=3, suits='stepped-pair',
         note='forward brings the throttle round the detent to IDLE for the '
              'start, back is cutoff. Nothing else in the jet does this'),

    Need('Stores config (CAT I / III)', 'button', ['SimCATSwitch'], urgency=3),
    Need('Air refuelling door', 'button', ['SimFuelDoorToggle'], urgency=3),
    Need('Canopy', 'button', ['AFCanopyToggle'], urgency=3),
    Need('AVTR', 'button', ['SimAVTRToggle'], urgency=3),
    Need('Night vision', 'button', ['ToggleNVGMode'], urgency=3),
    Need('Visor', 'button', ['SimVisorToggle'], urgency=3),

    # SimEject is not here on purpose. Twenty of the twenty-two vendor profiles
    # put it on the SHIFTED layer, which is how you make a control hard to hit
    # by accident. We do not use the shifted layer, and there is no button on
    # either device awkward enough to be safe, so eject stays on the keyboard.
]


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


def assign():
    """(devices, placements, unplaced, free) using the shared allocator.

    Two calls rather than one, because the shifted layer runs over the SAME
    controls again and so needs its own ledger. The core gives that for free:
    a separate `allocate` has a separate `taken`, and the one control it must
    not reuse -- whatever carries the shift itself, since holding a button
    cannot also mean pressing it -- is excluded through the veto hook.
    """
    devs = devices()
    plain = [n for n in NEEDS if not n.shift]
    shifted = [n for n in NEEDS if n.shift]

    placed, unmet, free = corneeds.allocate(plain, devs, usable=usable)

    if shifted:
        holder = next((p.ctrl for p in placed
                       if 'SimHotasPinkyShift' in p.need.callbacks()), None)
        if holder is None:
            sys.exit('needs want the shifted layer but nothing carries '
                     'SimHotasPinkyShift -- add it to NEEDS')
        more, unmet2, free = corneeds.allocate(
            shifted, devs,
            usable=lambda r, c: usable(r, c) and c is not holder)
        placed += more
        unmet += unmet2
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


def build():
    """(axes, binds, placed, unmet, free) -- binds are ready-to-write DX lines."""
    devs, placed, unmet, free = assign()
    off = dx_offsets()

    axes = []
    for name, role, how, what in AXIS_NEEDS:
        dev = devs[role]
        a = find_axis(dev, how, what)
        if a is None:
            continue
        di = dinput_axis(dev, a)
        if di:
            axes.append((name, role, a, di))

    binds, seen = [], {}
    for p in placed:
        for local, call in p.slots:
            if not call:
                continue
            dx = off[p.role] + local + (SHIFT if p.need.shift else 0)
            press, release = call if isinstance(call, tuple) else (call, None)
            where = f'{p.ctrl.label} — {p.ctrl.direction(local) or "press"}'
            if dx in seen:
                print(f'!! DX {dx} wanted by {seen[dx]} and {p.need.what}',
                      file=sys.stderr)
            seen[dx] = p.need.what
            binds.append({'need': p.need, 'role': p.role, 'ctrl': p.ctrl,
                          'local': local, 'dx': dx, 'press': press,
                          'release': release, 'where': where})
    return axes, binds, placed, unmet, free


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


def write_keeping(path, text, nl):
    path.write_bytes(text.replace('\n', nl).encode('latin-1'))


KEYFILE_OUT = 'BMS - VIRPIL.key'


def write_key(bms):
    """Build our key file from the shipped Full one, so every keyboard binding
    and every comment in it survives; only the DX block is ours."""
    src = bms / 'User' / 'Config' / 'BMS - Full.key'
    dst = bms / 'User' / 'Config' / KEYFILE_OUT
    _axes, binds, _p, _u, _f = build()
    body, nl = read_keeping(src)
    # the first line's description names the file inside BMS's own UI
    body = body.replace('"BMS - Full"', f'"{KEYFILE_OUT[:-4]}"', 1)
    if dst.exists():
        bak = dst.with_suffix(f'.key.{datetime.now():%Y%m%d-%H%M%S}.bak')
        shutil.copy2(dst, bak)
        print(f'backed up  {bak.name}')
    write_keeping(dst, body.rstrip('\n') + '\n' + dx_lines(binds) + '\n', nl)
    print(f'wrote      {dst}')
    print(f'           {len(binds)} DX bindings')
    print()
    print('Pick it in the Alternative Launcher (falcon-bms launcher) under')
    print(f'Keyfile, or in BMS Setup -> Controllers: "{KEYFILE_OUT[:-4]}".')
    return dst


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


def write_axes(bms):
    """Write our devices into DeviceDefaults.txt and move the binary mapping out
    of the way so BMS rebuilds it from them."""
    cfg = bms / 'User' / 'Config'
    defaults = cfg / 'DeviceDefaults.txt'
    axes, _b, _p, _u, _f = build()
    devs = devices()

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
        print('replaced the previous VIRPIL block')
    for role, items in per.items():
        dev = devs[role]
        pid, vid = dev.usb.split(':')
        guid = f'{vid.upper()}{pid.upper()}-0000-0000-0000-504944564944'
        before = txt
        txt = _strip_stub(txt, guid, dev.product)
        if txt != before:
            print(f'removed    the game\'s own stub for {dev.product}')
    shutil.copy2(defaults, defaults.with_suffix(
        f'.txt.{datetime.now():%Y%m%d-%H%M%S}.bak'))
    write_keeping(defaults, txt.rstrip('\n') + '\n' + '\n'.join(block) + '\n',
                  nl)
    print(f'wrote      {defaults}')

    for name in ('axismapping.dat', 'axismapping_tmp.dat'):
        p = cfg / name
        if p.exists():
            moved = p.with_suffix(f'.dat.{datetime.now():%Y%m%d-%H%M%S}.bak')
            shutil.move(p, moved)
            print(f'moved away {name} -> {moved.name}')
    print()
    print('BMS should rebuild the binary from the defaults on next start.')
    print('If it does not, set these nine by hand in the Launcher — the plan')
    print('above says exactly which physical axis each one is.')


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


def show(why=False, free_only=False):
    axes, binds, placed, unmet, free = build()
    off = dx_offsets()

    if not free_only:
        print('AXES')
        for name, role, a, di in axes:
            print(f'  {name:<16} {role:<9} {di:<8} {a.label}')
            note = AXIS_NOTE.get(name)
            if why and note:
                print(f'{"":<19}{wrap(note, 56, " " * 19)}')
        print()

        by_need = {}
        for b in binds:
            by_need.setdefault(id(b['need']), []).append(b)
        print('BUTTONS')
        for need, role, ctrl, s in ((p.need, p.role, p.ctrl, p.points)
                                    for p in placed):
            mine = by_need.get(id(need), [])
            if not mine:
                print(f'  {need.what}')
                print(f'!!    {ctrl.label} was chosen but carries nothing — '
                      'a bug in slots_for')
                continue
            print(f'  {need.what}')
            print(f'{"":<4}{ctrl.label}  ({role}, {ctrl.reach})')
            for b in sorted(mine, key=lambda b: b['dx']):
                d = ctrl.direction(b['local']) or 'press'
                extra = f'   / release: {b["release"]}' if b['release'] else ''
                print(f'      DX{b["dx"]:<4} {d:<8} {b["press"]}{extra}')
            if why:
                print(f'      why    {need.votes}/22 vendor profiles bind this; '
                      f'wants a {need.shape}, score {s}')
                if need.dev and need.dev != role:
                    print(f'             COMPROMISE: belongs on the {need.dev}, '
                          f'nothing of that shape was left there')
                if need.relaxed:
                    print('             took a control better than its urgency '
                          'earns, because nothing plainer was left')
                if need.note:
                    print(f'{"":<13}{wrap(need.note, 60, " " * 13)}')
            print()

        if unmet:
            print('NOT PLACED')
            for n in unmet:
                print(f'  {n.what:<28} wanted a {n.shape}')
            print()

    print('STILL FREE')
    for role, c in free:
        n = len(c.bindable_buttons)
        dx = ', '.join(f'DX{off[role] + b}' for b in c.bindable_buttons)
        print(f'  {c.label:<28} {c.kind:<10} {role:<9} {n} button(s)  {dx}')


def audit():
    """Which callbacks the vendors put on hardware and we did not."""
    _a, binds, _p, _u, _f = build()
    mine = set()
    for b in binds:
        mine.add(b['press'])
        if b['release']:
            mine.add(b['release'])

    bad = [c for c in sorted(mine) if c not in ACTIONS]
    if bad:
        print('NOT IN THE KEY FILE — these would be silently ignored:')
        for c in bad:
            print(f'  {c}')
        print()

    missed = [(cb, n) for cb, n in sorted(VOTES.items(), key=lambda x: -x[1])
              if cb not in mine and n >= 8]
    mfd = [c for c, _ in missed if 'OSB' in c or 'BRT' in c]
    print(f'placed {len(mine)} callbacks')
    print(f'ranked but not placed: {len(missed)}'
          f'  ({len(mfd)} of them MFD buttons, which need an MFD panel)')
    for cb, n in missed:
        if cb in mfd:
            continue
        a = ACTIONS.get(cb, {})
        print(f'  {n:>3}  {cb:<28} {a.get("desc", "(gone from the key file)")[:52]}')


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


def _sheet():
    """Everything a kneeboard needs, in the core's shape.

    BMS has one aircraft, so there is one unnamed context and the callback
    reads as a second line under the plain-English name. War Thunder passes
    ('Air', 'Helicopter') to the same builder and gets a column each.
    """
    axes, binds, placed, unmet, free = build()
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


def sheet(path):
    return _sheet().markdown(path)


def html_sheet(path):
    return _sheet().html(path)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--why', action='store_true', help='explain every choice')
    p.add_argument('--free', action='store_true', help='only what is unbound')
    p.add_argument('--audit', action='store_true',
                   help='ranked callbacks we did not place')
    p.add_argument('--sheet', action='store_true', help='write KNEEBOARD.md')
    p.add_argument('--html', action='store_true',
                   help='write kneeboard.html — the same thing in columns,'
                        ' for a second screen')
    p.add_argument('--write', action='store_true', help='write the key file')
    p.add_argument('--write-axes', action='store_true',
                   help='write the axis defaults (untested, see README)')
    p.add_argument('--bms-dir', help='override the BMS install')
    a = p.parse_args()

    if a.bms_dir:
        os.environ['BMS_DIR'] = a.bms_dir
    bms = harvest.bms_dir()

    did = False
    if a.audit:
        audit()
        did = True
    if a.sheet:
        path, nb, na = sheet(os.path.join(HERE, 'KNEEBOARD.md'))
        print(f'wrote {path}: {nb} bindings, {na} axes')
        did = True
    if a.html:
        path, nb, na = html_sheet(os.path.join(HERE, 'kneeboard.html'))
        print(f'wrote {path}: {nb} bindings, {na} axes')
        did = True
    if a.write:
        write_key(bms)
        did = True
    if a.write_axes:
        write_axes(bms)
        did = True
    if not did:
        show(why=a.why, free_only=a.free)


if __name__ == '__main__':
    main()

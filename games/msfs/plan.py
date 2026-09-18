#!/usr/bin/env python3
"""plan.py - lay out MSFS 2024 on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then fill in the profiles MSFS keeps in Steam Cloud.

FILES
    harvest.py          the action vocabulary and the factory ranking
    inputprofile_*      written by --write, two per device:
                          with <AircraftInfo/>   flight controls
                          without                camera, ATC, global
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close Steam first: it syncs these files from the cloud.
    An action the profile does not contain is skipped and reported.
"""

import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'no shared core at {CORE}\n'
                     'clone sim-bind-wizard next to this repo, '
                     'or set SIM_BIND_WIZARD')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import backup                                     # noqa: E402
from core import devmap                                     # noqa: E402
from core import review as creview                          # noqa: E402
from core import needs as corneeds
from core import vocab
from core import sheet as csheet                          # noqa: E402
from core.needs import IN_A_TURN, ON_APPROACH, ON_THE_RAMP  # noqa: E402,F401

REMOTE = os.path.expanduser(
    '~/.local/share/Steam/userdata/*/2537590/remote')

#: HID axis kind -> what MSFS calls it, and the code it writes.
#: Confirmed against the owner's own profiles for X, Y, Z, Rx and Slider;
#: the rest follow the same +0x10 step and want checking in the sim.
AXIS_CODE = {
    'X':      ('Joystick L-Axis X ', 1026),
    'Y':      ('Joystick L-Axis Y ', 1042),
    'Z':      ('Joystick L-Axis Z ', 1058),
    'Rx':     ('Joystick R-Axis X ', 770),
    'Ry':     ('Joystick R-Axis Y ', 786),
    'Rz':     ('Joystick R-Axis Z ', 802),
    'Slider': ('Joystick Slider X ', 514),
    'Dial':   ('Joystick Slider Y ', 530),
}


def button_code(index):
    """MSFS shows one-based numbers and stores zero-based codes."""
    return f'Joystick Button {index + 1}', index



ACTIONS = vocab.load(HERE, 'msfs-actions.json')
RANK = vocab.load(HERE, 'msfs-rank.json')


class Need(corneeds.Need):
    """The core's Need, carrying three payloads per slot instead of one.

    MSFS keeps two files per device and splits its vocabulary three ways: an
    action for aeroplanes, one for helicopters, and one that is global. The
    core does not care -- `bindings` is opaque to it -- so each slot holds the
    triple and `bindings_for` unpacks it.

    Urgency is the core's four-step scale now. MSFS had three of its own
    ("in the air / circuit work / on stand"), whose reach tables happened to
    match the core's 0, 1 and 3 exactly, so the only change is the name.
    """

    def __init__(self, what, shape, plane=(), heli=(), glob_=(), push=None,
                 suits=None, urgency=ON_APPROACH, device=None, note=''):
        self.plane, self.heli, self.glob = list(plane), list(heli), list(glob_)
        n = max(len(self.plane), len(self.heli), len(self.glob))

        def pad(xs):
            return list(xs) + [None] * (n - len(xs))

        super().__init__(what, shape,
                         bindings=list(zip(pad(self.plane), pad(self.heli),
                                           pad(self.glob))),
                         push=push, urgency=urgency, suits=suits, dev=device,
                         note=note)

    @property
    def device(self):
        return self.dev


NEEDS = [
    Need('Flight axes', 'axis',
         plane=['KEY_AXIS_AILERONS_SET', 'KEY_AXIS_ELEVATOR_SET',
                'KEY_AXIS_RUDDER_SET'],
         heli=['KEY_AXIS_CYCLIC_LATERAL_SET',
               'KEY_AXIS_CYCLIC_LONGITUDINAL_SET', 'KEY_AXIS_TAIL_ROTOR_SET'],
         urgency=IN_A_TURN),
    Need('Power axis', 'axis', plane=['KEY_THROTTLE_AXIS_SET_EX1'],
         heli=['KEY_AXIS_COLLECTIVE_SET'], urgency=IN_A_TURN),
    Need('Brakes', 'axis', plane=['KEY_BRAKES'], heli=['KEY_BRAKES'],
         urgency=ON_APPROACH),

    Need('Trim', 'hat4',
         plane=['KEY_ELEV_TRIM_UP', 'KEY_AILERON_TRIM_RIGHT',
                'KEY_ELEV_TRIM_DN', 'KEY_AILERON_TRIM_LEFT'],
         heli=['KEY_ROTOR_LONGITUDINAL_TRIM_INC', 'KEY_ROTOR_LATERAL_TRIM_INC',
               'KEY_ROTOR_LONGITUDINAL_TRIM_DEC', 'KEY_ROTOR_LATERAL_TRIM_DEC'],
         push=None, suits='trim', urgency=IN_A_TURN, device='stick',
         note='the single most-bound thing after the flight axes'),
    Need('Views', 'hat4',
         glob_=['KEY_COCKPIT_QUICKVIEW3', 'KEY_CHASE_QUICKVIEW2',
                'KEY_COCKPIT_QUICKVIEW4', 'KEY_CHASE_QUICKVIEW4'],
         push='KEY_VIEW_MODE', suits='view', urgency=IN_A_TURN, device='stick'),
    Need('Look around', 'ministick', glob_=[], suits='view', urgency=IN_A_TURN,
         device='throttle',
         note='head movement wants the axes, not a hat. It carries no button '
              'payload at all -- it exists to RESERVE the mini-stick so a '
              'button need cannot take it, and it says throttle because the '
              'left hand is the one that is free while you are flying. The '
              'old scorer put it there by accident; now it is asked for'),

    Need('Flaps', 'hat2', plane=['KEY_FLAPS_DECR', 'KEY_FLAPS_INCR'],
         suits='stepped-pair', urgency=ON_APPROACH),
    Need('Gear', ('hat2', 'switch2'), plane=['KEY_GEAR_TOGGLE', 'KEY_GEAR_TOGGLE'],
         heli=['KEY_GEAR_TOGGLE', 'KEY_GEAR_TOGGLE'], suits='toggle', urgency=ON_APPROACH),
    Need('Spoilers', 'hat2', plane=['KEY_SPOILERS_DEC', 'KEY_SPOILERS_INC'],
         suits='stepped-pair', urgency=ON_APPROACH),
    Need('Parking brake', 'button', plane=['KEY_PARKING_BRAKES'],
         heli=['KEY_PARKING_BRAKES'], suits='toggle', urgency=ON_THE_RAMP),

    Need('Radio reply', 'button', glob_=['KEY_SR_COM_QUICK_REPLY'],
         suits='occasional', urgency=IN_A_TURN,
         note='the most-bound global action in the factory profiles'),
    Need('Radio panel', 'button', glob_=['KEY_MENU_SR_COM_PANEL_OPEN'],
         suits='occasional', urgency=ON_APPROACH),
    Need('Cockpit cycle', 'hat2',
         glob_=['KEY_COCKPIT_BACKCYCLE', 'KEY_COCKPIT_CYCLE'],
         suits='view', urgency=ON_APPROACH),
    Need('Pilot view', 'hat2',
         glob_=['KEY_CYCLE_PILOTVIEW_BACK', 'KEY_CYCLE_PILOTVIEW_NEXT'],
         suits='view', urgency=ON_APPROACH),
    Need('Smart camera', 'button', glob_=['KEY_TOGGLE_SMART_CAMERA'],
         suits='view', urgency=ON_APPROACH),

    Need('Rotor trim reset', 'button', heli=['KEY_ROTOR_TRIM_RESET'],
         suits='trim', urgency=IN_A_TURN),
    Need('Rotor brake', 'button', heli=['KEY_ROTOR_BRAKE_TOGGLE'],
         suits='toggle', urgency=ON_THE_RAMP),
    Need('Engine start', 'button', plane=['KEY_ENGINE_AUTO_START'],
         heli=['KEY_ENGINE_AUTO_START'], suits='occasional', urgency=ON_THE_RAMP),
    Need('Prop pitch', 'axis', plane=['KEY_PROP_PITCH_AXIS_SET_EX1'],
         urgency=ON_THE_RAMP),
    Need('Vertical speed', 'axis', plane=['KEY_AXIS_VERTICAL_SPEED_SET'],
         urgency=ON_THE_RAMP,
         note='a dial that rests centred is a SELECTOR, not a lever: it suits '
              'dialling a value in -- VS, heading bug -- where a slider resting '
              'at zero suits an axis where zero means off'),
]

def rank_of(action):
    for cat in ('Airplane', 'Helicopter', 'Transversal'):
        n = dict(RANK['rank'].get(cat, [])).get(action)
        if n:
            return cat, n
    return '', 0


def axis_plan(devs):
    """[(context, action, role, axis)] for the axis-shaped needs."""
    stick, thr = devs['stick'], devs['throttle']
    out = []

    def by_kind(d, kind):
        got = d.axes(kind=kind)
        return got[0] if got else None

    roll, pitch, yaw = (by_kind(stick, 'stick-x'), by_kind(stick, 'stick-y'),
                        by_kind(stick, 'twist'))
    lever = next((a for a in thr.axes(kind='lever')
                  if 'left' in (a.label or '').lower()),
                 next(iter(thr.axes(kind='lever')), None))
    brake = next((a for a in stick.axes()
                  if a.kind in ('slider', 'lever') and a.safe_for_absolute), None)
    # a dial is for dialling a value, not for a lever's job: keep it out of
    # the prop-pitch search and give it the vertical speed selector instead
    prop = next((a for a in thr.axes()
                 if a.kind in ('slider', 'lever')
                 and a is not lever and a.safe_for_absolute), None)
    dial = next(iter(thr.axes(kind='dial')), None)
    for ctx, trio in (('plane', ('KEY_AXIS_AILERONS_SET', 'KEY_AXIS_ELEVATOR_SET',
                                 'KEY_AXIS_RUDDER_SET')),
                      ('heli', ('KEY_AXIS_CYCLIC_LATERAL_SET',
                                'KEY_AXIS_CYCLIC_LONGITUDINAL_SET',
                                'KEY_AXIS_TAIL_ROTOR_SET'))):
        for action, ax in zip(trio, (roll, pitch, yaw)):
            if ax:
                out.append((ctx, action, 'stick', ax))
    if lever:
        out.append(('plane', 'KEY_THROTTLE_AXIS_SET_EX1', 'throttle', lever))
        out.append(('heli', 'KEY_AXIS_COLLECTIVE_SET', 'throttle', lever))
    if brake:
        out.append(('plane', 'KEY_BRAKES', 'stick', brake))
        out.append(('heli', 'KEY_BRAKES', 'stick', brake))
    if prop:
        out.append(('plane', 'KEY_PROP_PITCH_AXIS_SET_EX1', 'throttle', prop))
    if dial:
        out.append(('plane', 'KEY_AXIS_VERTICAL_SPEED_SET', 'throttle', dial))
    ms = next(iter(thr.groups('ministick')), None)
    if ms and len(ms.axes) == 2:
        for action, i in (('KEY_AXIS_PAN_HEADING', 0), ('KEY_AXIS_PAN_PITCH', 1)):
            if action in ACTIONS:
                out.append(('glob', action, 'throttle', thr.axis(ms.axes[i])))
    return out


def build():
    devs = devmap.by_role('stick', 'throttle')
    flat = [n for n in NEEDS if n.first_shape != 'axis']
    return corneeds.Layout(devs, *corneeds.allocate(flat, devs),
                           axes=axis_plan(devs))


def find_profiles(devs):
    """[(path, role, bucket)] -- bucket is 'flight' or 'global'.

    MSFS keeps two files per device. The one carrying
    <AircraftInfo CategoryName="..."/> holds the flying actions -- aeroplane
    AND helicopter, despite the label -- and the one without holds cameras,
    radio and anything that applies whatever you are flying. Their context sets
    do not overlap, so every action belongs to exactly one of them.
    """
    pid = {}
    for role, d in devs.items():
        usb = (d.usb or '').split(':')[-1]
        if usb:
            pid[int(usb, 16)] = role
    out = []
    # `inputprofile_*` also matched the .bak.<stamp> copies write() used to
    # leave behind, so a second run bound into its own backups and backed
    # THOSE up again -- the .bak.X.bak.Y files in the remote folder are the
    # proof. Backups live outside the folder now (core.backup), but the ones
    # from before that still sit here, so the filter stays: MSFS names the
    # real profiles with digits and nothing else.
    for path in sorted(glob.glob(os.path.join(REMOTE, 'inputprofile_*'))):
        if not re.fullmatch(r'inputprofile_\d+', os.path.basename(path)):
            continue
        raw = open(path, encoding='utf-8').read(4000)
        m = re.search(r'ProductID="([^"]*)"', raw)
        if not m:
            continue
        role = pid.get(int(m.group(1)))
        if not role:
            continue
        bucket = ('flight' if re.search(r'<AircraftInfo CategoryName=', raw)
                  else 'global')
        out.append((path, role, bucket))
    return out


def bind_into(text, action, information, code):
    """Put one binding into the profile text, leaving the rest untouched.

    An unbound action is self-closing; a bound one carries a <Primary> block.
    Editing the text rather than reserialising the XML keeps the 170 KB of
    formatting MSFS wrote exactly as it was.
    """
    esc = re.escape(action)
    key = f'<KEY Information="{information}">{code}</KEY>'

    m = re.search(r'([ \t]*)<Action ActionName="%s"([^>]*?)/>' % esc, text)
    if m:
        ind, attrs = m.group(1), m.group(2)
        block = (f'{ind}<Action ActionName="{action}"{attrs}>\n'
                 f'{ind}\t<Primary>\n{ind}\t\t{key}\n{ind}\t</Primary>\n'
                 f'{ind}</Action>')
        return text[:m.start()] + block + text[m.end():], True

    m = re.search(r'([ \t]*)<Action ActionName="%s"([^>]*)>(.*?)</Action>'
                  % esc, text, re.S)
    if m:
        ind, attrs = m.group(1), m.group(2)
        block = (f'{ind}<Action ActionName="{action}"{attrs}>\n'
                 f'{ind}\t<Primary>\n{ind}\t\t{key}\n{ind}\t</Primary>\n'
                 f'{ind}</Action>')
        return text[:m.start()] + block + text[m.end():], True
    return text, False


def bindings_for(devs, placed, axes):
    """{(role, bucket): [(action, information, code)]}"""
    out = {}
    def add(role, bucket, action, info, code):
        out.setdefault((role, bucket), []).append((action, info, code))

    for p in placed:
        need, role, c = p.need, p.role, p.ctrl
        order = list(c.buttons) or ([c.push] if c.push is not None else [])
        for ctx, ids in (('flight', need.plane), ('flight', need.heli),
                         ('global', need.glob)):
            for i, action in enumerate(ids):
                if i >= len(order):
                    break
                info, code = button_code(order[i])
                add(role, ctx, action, info, code)
        if need.push and c.push is not None:
            info, code = button_code(c.push)
            add(role, 'global', need.push, info, code)

    for ctx, action, role, ax in axes:
        pair = AXIS_CODE.get(ax.hid)
        if not pair:
            continue
        add(role, 'global' if ctx == 'glob' else 'flight', action, *pair)
    return out


def write(devs, placed, axes, backup_dir=None):
    if os.popen('pgrep -x steam').read().strip():
        sys.exit('Steam is running -- it syncs these files from the cloud and '
                 'would overwrite the write. Quit Steam first.')
    profiles = find_profiles(devs)
    if not profiles:
        sys.exit('found no MSFS input profiles -- has the sim seen the devices?')

    dest, _ = backup.save('msfs', *(p for p, _r, _b in profiles),
                          into=backup_dir)
    print(f'  backed up to {dest}')

    # Named once, because four profiles under one 70-character Steam userdata
    # path would be four lines of the same directory.
    print(f'  writing into {os.path.dirname(profiles[0][0])}')

    plan = bindings_for(devs, placed, axes)
    total = missing = 0
    for path, role, bucket in profiles:
        want = plan.get((role, bucket), [])
        if not want:
            continue
        text = open(path, encoding='utf-8').read()
        done = 0
        for action, info, code in want:
            text, ok = bind_into(text, action, info, code)
            done += ok
            missing += not ok
        open(path, 'w', encoding='utf-8').write(text)
        total += done
        print(f'  {os.path.basename(path)}  {role:8s} {bucket:6s} '
              f'{done}/{len(want)} written')
    if missing:
        print(f'  {missing} action(s) not present in their profile -- skipped')
    return total


def _describe(p):
    """[(button code, what it does)] -- MSFS splits its vocabulary three ways
    and the same button often carries a different action in each."""
    need, c = p.need, p.ctrl
    out = []
    for ctx, ids in (('plane', need.plane), ('heli', need.heli),
                     ('glob', need.glob)):
        for i, action in enumerate(ids):
            if i >= len(c.bindable_buttons):
                break
            b = c.buttons[i] if i < len(c.buttons) else c.push
            out.append((f'{ctx} {button_code(b)[0]}', action))
    if need.push and c.push is not None:
        out.append((f'glob {button_code(c.push)[0]}', need.push))
    return out


def tui(args):
    def write_kept(kept):
        n = write(kept.devices, kept.placed, kept.axes, args.backup_dir)
        return [f'{n} binding(s) written']

    found = find_profiles(devmap.by_role('stick', 'throttle'))
    creview.run(build(), 'MSFS 2024', 'VIRPIL',
                describe=_describe, write=write_kept,
                paths=[('profiles', os.path.dirname(found[0][0]) if found
                        else '(none found)')]
                      + [(f'  {role} {bucket}', os.path.basename(path))
                         for path, role, bucket in found]
                      + [('backups',
                          backup.dir_for('msfs', args.backup_dir))])


def _sheet():
    """The kneeboard, in the core's shape.

    Three contexts, one column each: MSFS splits its vocabulary between
    aeroplanes, helicopters and a global layer, and the same button often
    carries a different action in each.

    It used to live in a separate `sheet.py` that read the live profiles and
    marked every binding `kept`, `moved from X` or `new` against the earliest
    backup. That went: the interesting question is what the layout IS, and the
    diff cost a second reader of the game's files that could disagree with the
    planner about what is bound.
    """
    devs, placed, unmet, free, axes = build()
    CTX = {'plane': 'Aeroplane', 'heli': 'Helicopter', 'glob': 'Global'}

    sh = csheet.Sheet('Kneeboard MSFS 2024',
                      'Microsoft Flight Simulator 2024 · VIRPIL',
                      ident='Button', contexts=tuple(CTX.values()),
                      devices={r: d.product for r, d in devs.items()})

    for p in placed:
        need, role, c = p.need, p.role, p.ctrl
        order = list(c.buttons) or ([c.push] if c.push is not None else [])
        cells = {}
        for ctx, ids in (('plane', need.plane), ('heli', need.heli),
                         ('glob', need.glob)):
            for i, action in enumerate(ids):
                if i >= len(order):
                    break
                cells.setdefault(order[i], {}).setdefault(CTX[ctx], []).append(action)
        if need.push and c.push is not None:
            cells.setdefault(c.push, {}).setdefault('Global', []).append(need.push)
        for btn, by_ctx in sorted(cells.items()):
            info, _code = button_code(btn)
            sh.add(csheet.Row(role, c.label,
                              part=c.direction(btn) or 'press',
                              ident=info.replace('Joystick Button ', '#'),
                              does=need.what, bindings=by_ctx))

    for ctx, action, role, ax in axes:
        pair = AXIS_CODE.get(ax.hid)
        g = devs[role].axis_group(ax.index)
        sh.add_axis(csheet.AxisRow(role, g.label if g else ax.label,
                                   ident=(pair[0] if pair else ax.hid),
                                   does=action))

    sh.unplaced = [(n.what, n.shape if isinstance(n.shape, str)
                    else '/'.join(n.shape)) for n in unmet]
    sh.note('Writing it', 'Close Steam first -- it syncs these files from the '
                          'cloud and will overwrite what we write. '
                          './plan.py --write')
    return sh


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--why', action='store_true',
                    help='print why each control was chosen')
    ap.add_argument('--free', action='store_true',
                    help='list controls left unbound')
    ap.add_argument('--sheet', action='store_true',
                    help='write KNEEBOARD.md')
    ap.add_argument('--html', action='store_true',
                    help='write kneeboard.html')
    ap.add_argument('--write', action='store_true',
                    help='write the whole layout into the game')
    ap.add_argument('--tui', action='store_true',
                    help='review the layout, write what you keep')
    backup.add_argument(ap, 'msfs')
    args = ap.parse_args()
    devs, placed, unmet, free, axes = build()

    # Both, when both are asked for -- see the same fix in War Thunder.
    did = False
    if args.sheet:
        path, nb, na = _sheet().markdown(os.path.join(HERE, 'KNEEBOARD.md'))
        print(f'wrote {path}: {nb} bindings, {na} axes')
        did = True
    if args.html:
        path, nb, na = _sheet().html(os.path.join(HERE, 'kneeboard.html'))
        print(f'wrote {path}: {nb} bindings, {na} axes')
        did = True
    if did:
        return
    if args.tui:
        tui(args)
        return
    if args.write:
        n = write(devs, placed, axes, args.backup_dir)
        print(f'  {n} bindings written')
        return

    if args.free:
        for role, c in free:
            print(f'  {role:9} {c.label:34} {c.kind:10} {c.reach or ""}')
        return

    print(f'{len(placed)} controls, {len(axes)} axis bindings\n')
    for p in placed:
        need, role, c, s = p.need, p.role, p.ctrl, p.points
        print(f'  {need.what:20s} {role:8s} {c.kind:9s} {c.label}')
        for ctx, ids in (('plane', need.plane), ('heli', need.heli),
                         ('glob', need.glob)):
            for i, a in enumerate(ids):
                if i < len(c.bindable_buttons):
                    b = c.buttons[i] if i < len(c.buttons) else c.push
                    d = c.direction(b) or ''
                    print(f'      {ctx:5s} {a:44s} -> {button_code(b)[0]}'
                          f'{"  " + d if d else ""}')
        if need.push and c.push is not None:
            print(f'      glob  {need.push:44s} -> {button_code(c.push)[0]}  push')
        if args.why:
            cat, n = rank_of((need.plane or need.heli or need.glob or [''])[0])
            if n:
                print(f'      {n} of the factory {cat} profiles bind this')
            if need.note:
                print(f'      {need.note}')
        print()
    print('AXES')
    for ctx, action, role, ax in axes:
        print(f'  {ctx:5s} {action:44s} {role:8s} {AXIS_CODE.get(ax.hid, ("?",))[0]}'
              f'  ({ax.label})')
    if unmet:
        print(f'\n{len(unmet)} unplaced: ' + ', '.join(n.what for n in unmet))


if __name__ == '__main__':
    main()

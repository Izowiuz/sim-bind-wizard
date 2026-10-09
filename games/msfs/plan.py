#!/usr/bin/env python3
"""plan.py - lay out MSFS 2024 on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map, then fill in the profiles MSFS keeps in Steam Cloud.

FILES
    harvest.py          the action vocabulary
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
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'There is no shared core at {CORE}.\n'
                     'Clone sim-bind-wizard next to this repo, or set '
                     'SIM_BIND_WIZARD.')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
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

#: Where the judgements live. Which band a thing is in, what shape it wants,
#: which device it belongs on, what somebody wrote about it -- and nothing
#: derives any of it.
#:
#: Source, not cache. They were a Python literal until now, so changing one
#: meant editing code. Deliberately not in `CACHE`: that names what the
#: harvest wrote, and a harvest cannot write a judgement.


def needs(described, placed):
    """[Need] -- the hand-written list, read rather than executed."""
    out = corneeds.read_needs(vocab.load(HERE, described, key='needs'),
                              make=Need)
    return out


def axis_rows(devs, axes):
    """[(context, action, role, axis)] -- the four fields every reader of
    an axis placement here wants, in one place rather than three."""
    out = []
    for p in axes:
        a = devs[p.role].axis(p.slots[0][0].index)
        for b in p.slots[0][1]:
            out.append((b.mode or 'plane', b.action, p.role, a))
    return out


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
        with open(path, encoding='utf-8') as f:
            raw = f.read(4000)
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


def unbind_ours(text, keep):
    """Take our joystick out of every action the plan no longer names.

    `bind_into` only ever added or replaced, so a binding dropped from
    `NEEDS` kept its <Primary> block and went on answering in the game --
    "can add and change but never remove", the same hole War Thunder's
    hotkeys block had and x4's profile had before them.

    Our hardware is ours completely, which is the rule in every other game
    here: an MSFS profile belongs to one device, so every joystick binding in
    it is one this tool wrote. What the plan does not ask for goes back to
    self-closing, which is what the game ships.
    """
    out, at = [], 0
    for m in re.finditer(r'([ \t]*)<Action ActionName="([^"]+)"([^>]*)>'
                         r'(.*?)</Action>', text, re.S):
        ind, name, attrs, body = m.groups()
        if name in keep or 'Information="Joystick' not in body:
            continue
        out.append(text[at:m.start()])
        out.append(f'{ind}<Action ActionName="{name}"{attrs}/>')
        at = m.end()
    out.append(text[at:])
    return ''.join(out)


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

    # From `slots`, never from the control: the core decides which button
    # each binding lands on -- including putting a lone one on the click --
    # and re-deriving the order here disagreed with it and threw away any
    # button chosen by hand in the review.
    for p in placed:
        for button, payload in p.slots:
            info, code = button_code(button)
            for b in payload:
                add(p.role, 'global' if b.mode == 'glob' else 'flight',
                    b.action, info, code)

    for ctx, action, role, ax in axis_rows(devs, axes):
        pair = AXIS_CODE.get(ax.hid)
        if not pair:
            continue
        add(role, 'global' if ctx == 'glob' else 'flight', action, *pair)
    return out


def contents(devs, placed, axes):
    """({path: the profile's whole new text}, lines saying what went where).

    Computes and returns; `core.adapter` backs up and writes. Steam has to be
    closed either way: it syncs these files from the cloud and would put the
    old ones back over anything written here.
    """
    if os.popen('pgrep -x steam').read().strip():
        raise SystemExit('Steam is running. It syncs these files from the '
                         'cloud, and that would overwrite this write. Quit '
                         'Steam first.')
    profiles = find_profiles(devs)
    if not profiles:
        raise SystemExit('There are no MSFS input profiles. Start the sim '
                         'once with the devices plugged in.')

    # Named once, because four profiles under one 70-character Steam userdata
    # path would be four lines of the same directory.
    out = [f'  writing into {os.path.dirname(profiles[0][0])}']
    plan = bindings_for(devs, placed, axes)
    files, missing = {}, 0
    for path, role, bucket in profiles:
        want = plan.get((role, bucket), [])
        if not want:
            continue
        with open(path, encoding='utf-8') as f:
            text = f.read()
        # Ours completely: whatever the plan no longer names loses its
        # binding before the plan's go in.
        text = unbind_ours(text, {a for a, _i, _c in want})
        done = 0
        for action, info, code in want:
            text, ok = bind_into(text, action, info, code)
            done += ok
            missing += not ok
        files[path] = text
        out.append(f'  {os.path.basename(path)}  {role:8s} {bucket:6s} '
                   f'{done}/{len(want)} written')
    if missing:
        out.append(f'  {missing} action(s) not present in their profile '
                   '-- skipped')
    return files, out


def _describe(p):
    """[(button code, what it does)] -- MSFS splits its vocabulary three ways
    and the same button often carries a different action in each."""
    out = []
    for button, payload in p.slots:
        for b in payload:
            out.append((f'{b.mode} {button_code(button)[0]}', b.action))
    return out


def _sheet(layout):
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
    devs, placed, unmet, free = (layout.devices, layout.on_buttons,
                                 layout.unplaced, layout.free)
    axes = layout.on_axes
    CTX = {'plane': 'Aeroplane', 'heli': 'Helicopter', 'glob': 'Global'}

    sh = csheet.Sheet('Kneeboard MSFS 2024',
                      'Microsoft Flight Simulator 2024 · VIRPIL',
                      ident='Button', contexts=tuple(CTX.values()),
                      devices={r: d.product for r, d in devs.items()})

    for p in placed:
        role, c = p.role, p.ctrl
        cells = {}
        for button, payload in p.slots:
            for b in payload:
                (cells.setdefault(button, {})
                      .setdefault(CTX[b.mode], []).append(b.action))
        # The push is in `slots` already -- the allocator appends it --
        # so it needs no second pass here.
        for btn, by_ctx in sorted(cells.items()):
            info, _code = button_code(btn)
            sh.add(csheet.Row(role, c.label,
                              part=c.direction(btn) or 'press',
                              ident=info.replace('Joystick Button ', '#'),
                              does=p.need.what, bindings=by_ctx))

    for ctx, action, role, ax in axis_rows(devs, axes):
        pair = AXIS_CODE.get(ax.hid)
        g = devs[role].axis_group(ax.index)
        sh.add_axis(role, g.label if g else ax.label,
                    pair[0] if pair else ax.hid, action,
                    #  is the sheet's own spelling for the
                    # unnamed context, which is what no context is.
                    CTX.get(ctx, ctx) or '')

    for n in unmet:
        sh.add_unplaced(n.what, n.shape if isinstance(n.shape, str)
                        else '/'.join(n.shape))
    return sh


# -------------------------------------------------------------- the adapter --

@typing.final
class Msfs(adapter.Planner):
    """MSFS 2024, on the VIRPIL pair."""

    game = 'msfs'
    title = 'MSFS 2024'
    subtitle = 'VIRPIL'
    #: Neither cache carries an envelope: `msfs-actions.json` IS the action
    #: map at its top level. Both keys are None until the harvest moves to
    #: core.vocab.save, which is when they gain one.
    #: `msfs-actions.json` gained its "actions" envelope when the harvest
    #: moved to core.vocab.save. A working copy harvested before that has a
    #: cache with no envelope, and core.vocab raises Stale for it rather
    #: than KeyError: run ./bind-wizard.py msfs harvest.
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'msfs-needs.json'
    BINDS = 'msfs-binds.json'
    CATALOGUE = 'msfs-actions.json'
    CACHE = {'msfs-actions.json': 'actions'}


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

    def __init__(self, backup_dir=None):
        self.backup_dir = backup_dir
        # Read here rather than at import, so that importing this module
        # defines classes and reads nothing.
        self.cat = cactions.read(self.cache('msfs-actions.json'))
        self.by_id = cactions.by_id(self.cat)
        self._needs = needs(self.NEEDS_FILE, self.BINDS)

    @typing.override
    def build(self):
        devs = devmap.by_role('stick', 'throttle')
        self.answers(self.NEEDS)
        return corneeds.Layout(devs, *corneeds.allocate(self.NEEDS, devs))

    @typing.override
    def catalogue(self):
        # A read, not a translation: the `AXIS:` prefix and the
        # per-category vote count are both settled in the run that parses
        # the profiles.
        return list(self.cat)


    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout)

    @typing.override
    def write_layout(self, layout):
        files, said = contents(layout.devices, layout.on_buttons,
                               layout.on_axes)
        for line in said:
            print(line)
        return files

    @typing.override
    def paths(self, args):
        found = find_profiles(devmap.by_role('stick', 'throttle'))
        return ([('profiles', os.path.dirname(found[0][0]) if found
                  else '(none found)')]
                + [(f'  {role} {bucket}', os.path.basename(path))
                   for path, role, bucket in found]
                + [('backups', backup.dir_for('msfs', self.backup_dir))])

    @typing.override
    def show(self, layout, why=False):
        devs, placed, unmet = (layout.devices, layout.on_buttons,
                               layout.unplaced)
        axes = layout.on_axes
        out = [f'{len(placed)} controls, {len(axes)} axis bindings', '']
        for p in placed:
            need, role, c = p.need, p.role, p.ctrl
            out.append(f'  {need.what:20s} {role:8s} {c.kind:9s} {c.label}')
            for button, payload in p.slots:
                d = c.direction(button) or ''
                for b in payload:
                    out.append(f'      {b.mode:5s} {b.action:44s} -> '
                               f'{button_code(button)[0]}'
                               f'{"  " + d if d else ""}')
            if why:
                out.append('      ' + ' · '.join(corneeds.why_bits(p)))
            out.append('')
        out.append('AXES')
        for ctx, action, role, ax in axis_rows(devs, axes):
            out.append(f'  {ctx:5s} {action:44s} {role:8s} '
                       f'{AXIS_CODE.get(ax.hid, ("?",))[0]}  ({ax.label})')
        if unmet:
            out.append('')
            out.append(f'{len(unmet)} unplaced: '
                       + ', '.join(n.what for n in unmet))
        return out


if __name__ == '__main__':
    sys.exit(adapter.run(Msfs))

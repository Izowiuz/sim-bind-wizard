#!/usr/bin/env python3
"""plan.py - lay out War Thunder on the HOTAS

DESCRIPTION
    Match what a pilot must be able to do against the controls in the device
    map. --write hands the result to wt-bind-preset.py, which owns machine.blk.

FILES
    harvest.py          the action vocabulary
    wt-bind-preset.py   the writer; it also has --dry-run, --render, --restore
    machine.blk         written by --write, one per account under Saves/
    KNEEBOARD.md, kneeboard.html   written by --sheet and --html

ENVIRONMENT
    SIM_DEVICE_MAP      where sim-device-map is checked out
    SIM_BIND_BACKUPS    where copies of replaced files go

NOTES
    Close War Thunder first: it rewrites machine.blk on exit.
    Air and helicopter are separate contexts, so one control carries both.
"""

import argparse
import importlib.util
import os
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
#: the shared hardware map. Sibling directory by default; SIM_DEVICE_MAP
#: overrides it, for a clone that does not sit next to this one.
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
from core import devmap                                     # noqa: E402
from core import backup
from core import needs as corneeds
from core import review as creview
from core import vocab
from core import sheet as csheet                          # noqa: E402
from core.needs import (IN_A_TURN, ON_APPROACH, IN_THE_AIR,  # noqa: E402,F401
                        ON_THE_RAMP)

#: The harvest is imported for the naming rules it owns, the way x4's
#: planner does. Importing it defines functions and reads nothing.
harvest = adapter.from_file('wtharvest', os.path.join(HERE, 'harvest.py'))


#: The catalogue as the harvest wrote it, and the view of it this file asks
#: for. Filled by `WarThunder.__init__`, never at import -- see the note in
#: games/falconbms/plan.py.
CAT, BY_ID = [], {}

#: War Thunder's naming convention, kept in the harvest where the whole
#: vocabulary is parsed: a twin is only ABSENT relative to the whole of it.
is_heli = harvest.is_heli


def contexts(action):
    """Which vehicle contexts an action actually applies to."""
    return harvest.contexts(action, BY_ID)


class Need(corneeds.Need):
    """The core's Need with two payloads per slot: aircraft and helicopter.

    War Thunder names most helicopter actions with an `_HELICOPTER` suffix and
    a few with an `ID_HELICOPTER_` prefix, and an action with no twin in either
    form applies to BOTH -- which is why the pair travels together in one slot
    rather than being placed twice. `contexts()` is the only thing that knows
    the naming rule.

    `reflex` is gone. It said "not on a control you must let go of", which is
    what `urgency=IN_A_TURN` says, and saying it twice let the two drift: the
    old scorer had a ceiling and no floor, so anything rare would happily take
    a thumb button and the list had to be hand-sorted around it.
    """

# Ordered by what you lose first if it is missing. The matcher works down the
# list, so the earliest needs get the best control that fits them.
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


# name in WT, the control kind it belongs on, and which of its axes


#: Extra deadzone for a named axis, overriding the rule in build().
#
# The stick twist is the rudder, and in War Thunder that is a problem no other
# sim of the four has. Hauling the stick back while rolling rotates the
# forearm, so yaw creeps in on its own -- and WT is the one that wants reflex
# shooting, which is when it happens. DCS and MSFS are flown deliberately and
# never showed it, so this stays local to this repo rather than becoming a
# device-map fact.
#
# Only `rudder` widens. `helicopter_pedals` is the SAME physical axis but not
# the same kind of control: heli yaw is held continuously and a wide dead patch
# makes a hover harder, where a plane's rudder is tapped.
#
# WT's own `nonlinearity: 2.5` already softens the centre, so the felt dead
# region is wider than the number. The other half of this -- capping authority
# with `rudderMultiplier` -- lives OUTSIDE the controls{} block that
# wt-bind-preset.py rewrites, so it is a slider in the game's own UI, not ours.
#
# A stopgap: VIRPIL pedals are on order. Delete this when they arrive.
AXIS_DEADZONE = {'rudder': 0.10}

#: Axis properties the plan wants to OWN, overriding whatever the game's own
#: axis wizard left in the file. Everything not named here is still preserved,
#: because that wizard knows about calibration and we do not.
#
# zoom kMul: the dial is not sprung -- it stays where you leave it, and it was
# measured resting at 27535 of 32767, deep in the top of its travel. `kMul: 2`
# doubles the gain, so the output is already clamped at full zoom across the
# whole upper half of the dial. Nothing happens until you wind back past the
# middle, which is exactly the "I have to turn it a long way before it lets go"
# that shows up when the sight view sets its own zoom. At 1 the whole dial maps
# to the whole range with no plateau.
AXIS_PROPS = {
    'zoom': {'kMul': 1.0},
}


def devices():
    return devmap.by_role('stick', 'throttle')


def deadzones(name, a):
    """The properties wt-bind-preset writes beside an axis.

    Computed, not judged: a ministick needs more slack than a lever, and
    a lever none at all. `AXIS_DEADZONE` overrides where somebody has an
    opinion about one.
    """
    dead = AXIS_DEADZONE.get(name)
    if dead is None:
        dead = 0.06 if a.kind == 'ministick' else (
            0 if a.kind == 'lever' else 0.02)
    props = {'innerDeadzone': dead}
    props.update(AXIS_PROPS.get(name, {}))
    return props


def axis_rows(devs, axes):
    """[(name, role, axis index, invert, props)] -- what the preset writes.

    One shape, computed here: `wt-bind-preset.py` used to reach into the
    plan objects for five fields, which is the only reason that script
    knew what a Placement was.
    """
    out = []
    for p in axes:
        idx = p.slots[0][0].index
        a = devs[p.role].axis(idx)
        for name in (b.action for b in p.slots[0][1]):
            out.append((name, p.role, idx, p.need.invert,
                        deadzones(name, a)))
    return out


def button_table(placed):
    """[(role, local index, action, where)] for the placements given.

    Computed inside `build()` before, which tied the preset writer to the
    whole plan; it takes `placed` so a reviewer can hand it a subset. The
    clash check below is per-context and has to run over whatever set is
    actually going to be written, which is the other reason it moved here.
    """
    buttons, emitted = [], set()
    for p in placed:
        for local, binds in p.slots:
            for action in (b.action for b in binds):
                key = (p.role, local, action)
                if key in emitted:      # shared actions sit in both lists
                    continue
                emitted.add(key)
                buttons.append((p.role, local, action,
                                f'{p.ctrl.label} — '
                                f'{p.ctrl.direction(local) or "press"}'))

    seen = {}
    for role, idx, action, _w in buttons:
        for ctx in contexts(action):
            key = (role, idx, ctx)
            if key in seen and seen[key] != action:
                print(f'!! {role} button {idx} ({ctx}): '
                      f'{seen[key]} and {action}', file=sys.stderr)
            seen[key] = action
    return buttons


def wt_offsets():
    """War Thunder numbers buttons and axes globally across devices, in the
    order they appear in machine.blk. The sheet has to print the number you
    will actually see in the menu, not the local one."""
    import glob
    import re
    out = {}
    for path in glob.glob(os.path.expanduser(
            '~/.config/WarThunder/Saves/last/production/machine.blk')):
        txt = open(path, encoding='utf-8', errors='replace').read()
        m = re.search(r'deviceMapping\{(.*?)\n    \}', txt, re.S)
        if not m:
            continue
        for blk in re.findall(r'joystick\{(.*?)\}', m.group(1), re.S):
            d = dict(re.findall(r'(\w+):[a-z]=("?[^"\n]*"?)', blk))
            name = d.get('name', '').strip('"').lower()
            role = 'throttle' if 'throttle' in name else 'stick'
            out[role] = (int(d.get('axesOffset', 0)),
                         int(d.get('buttonsOffset', 0)))
    return out or {'throttle': (0, 0), 'stick': (7, 51)}


def en(action):
    a = BY_ID.get(action)
    return a.name if a is not None else action


def _describe(p):
    """[(which part, what it does)] -- War Thunder keeps air and helicopter as
    separate contexts, so one control carries one of each without clashing."""
    out = []
    for local, binds in p.slots:
        part = p.ctrl.direction(local) or 'press'
        for b in binds:
            ctx = 'Heli' if is_heli(b.action) else 'Air'
            out.append((part, f'{ctx}: {en(b.action)}'))
    return out


def _sheet(layout):
    """The kneeboard, in the core's shape.

    Two contexts here, so each gets a column: one button doing different
    things in an aeroplane and a helicopter is the thing you most need to see
    at a glance, and it is why the context list is part of the contract rather
    than something each game solves again.
    """
    placed, unmet, free = layout.on_buttons, layout.unplaced, layout.free
    axes = layout.on_axes
    buttons = button_table(placed)
    off = wt_offsets()
    devs = devices()

    sh = csheet.Sheet('Kneeboard War Thunder',
                      'War Thunder · air simulator + helicopters · VIRPIL',
                      ident='WT', contexts=('Air', 'Helicopter'),
                      devices={r: f'{d.product}  '
                                  f'(buttons {off[r][1]}–'
                                  f'{off[r][1] + d.n_buttons - 1})'
                               for r, d in devs.items()})

    per = {}
    for role, idx, action, _where in buttons:
        cell = per.setdefault((role, idx), {'Air': [], 'Helicopter': []})
        for ctx in contexts(action):
            key = 'Helicopter' if ctx == 'heli' else 'Air'
            if en(action) not in cell[key]:
                cell[key].append(en(action))
    for (role, idx), cell in sorted(per.items(), key=lambda x: (x[0][0], x[0][1])):
        d = devs[role]
        g = d.group_of(idx)
        sh.add(csheet.Row(role, g.label if g else f'button {idx}',
                          part=(g.direction(idx) if g else ''),
                          ident=str(off[role][1] + idx),
                          bindings=cell))

    seen = {}
    for name, role, idx, invert, _props in axis_rows(devs, axes):
        cell = seen.setdefault((role, idx), {'Air': [], 'Helicopter': [],
                                             'inv': invert})
        cell['Helicopter' if name.startswith('helicopter_')
             else 'Air'].append(name)
    for (role, idx), cell in sorted(seen.items()):
        d = devs[role]
        a_, g = d.axis(idx), d.axis_group(idx)
        label = g.label if g else d.axis_label(idx)
        if cell['inv']:
            label += ' (inverted)'
        for ctx in ('Air', 'Helicopter'):
            for name in cell[ctx]:
                sh.add_axis(role, label, str(off[role][0] + idx), name, ctx)

    sh.note('Check in flight', [
        ('Elevator trim', 'Forward on the hat must drop the nose, as it '
                          'does in DCS and BMS. War Thunder names the steps '
                          'by sign, "Positive" and "Negative", and nothing '
                          'here settles which sign is which.'),
        ('Zoom', 'The dial does not return to the centre, so the view can '
                 'start part-zoomed.'),
        ('View mini-stick', 'Your head must go where your thumb goes.'),
    ])
    sh.note('Undo', 'Close the game. Then run ./wt-bind-preset.py '
                    '--restore.')
    for n in unmet:
        sh.add_unplaced(n.what, n.shape if isinstance(n.shape, str)
                        else '/'.join(n.shape))
    for role, c in free:
        sh.add_free(role, c.label,
                    ', '.join(str(off[role][1] + x)
                              for x in c.bindable_buttons))
    return sh


# -------------------------------------------------------------- the adapter --

class Preset(typing.Protocol):
    """What this planner calls on `wt-bind-preset.py`.

    A sidecar is loaded by path, so its name is not importable and everything
    across that seam is `Any` -- a typo in a function name or a swapped
    argument reaches the game before anything notices. Naming the surface
    here gets those checked at the call site.

    What it does NOT check is that the script really has these: a `cast` is
    a promise, not a proof, and pyright cannot verify one against a module it
    was never able to import. That half stays an AttributeError, which is at
    least loud.
    """

    GAME_DIR: str
    SAVES: str

    def targets_under(self, saves: str) -> list[str]: ...

    def compose(self, layout, targets: list[str],
                say=...) -> tuple[list[str], dict, dict]: ...

    def blk_with(self, target: str, block: list[str]) -> str: ...


@typing.final
class WarThunder(adapter.Planner):
    """War Thunder, air simulator and helicopters, on the VIRPIL pair."""

    game = 'warthunder'
    title = 'War Thunder'
    subtitle = 'air simulator + helicopters · VIRPIL'
    OVERLAY = 'by-hand'
    NEEDS_FILE = 'warthunder-needs.json'
    BINDS = 'warthunder-binds.json'
    CATALOGUE = 'wt-actions.json'
    SAYS = {'game_dir': 'the War Thunder install',
            'saves': 'where its config lives, if not beside the install'}
    CACHE = {'wt-actions.json': 'actions'}


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

    def __init__(self, game_dir=None, saves=None, backup_dir=None):
        self.backup_dir = backup_dir
        CAT[:] = cactions.read(self.cache('wt-actions.json'))
        BY_ID.update(cactions.by_id(CAT))
        self._needs = needs(self.NEEDS_FILE, self.BINDS)

        # The writer owns machine.blk and where the install is; these were
        # module constants in it with no override at all.
        self.writer = typing.cast(Preset,
                                  self.sidecar('wt-bind-preset.py'))
        if game_dir:
            self.writer.GAME_DIR = game_dir
        if saves:
            self.writer.SAVES = saves

    @typing.override
    def build(self):
        devs = devmap.by_role('stick', 'throttle')
        self.answers(self.NEEDS)
        return corneeds.Layout(devs, *corneeds.allocate(self.NEEDS, devs))

    @typing.override
    def catalogue(self):
        # A read, not a translation: the harvest settles the name and the
        # context in the run that parses the archives.
        return list(CAT)


    @typing.override
    def describe(self, placement):
        return _describe(placement)

    @typing.override
    def sheet(self, layout):
        return _sheet(layout)

    @typing.override
    def write_layout(self, layout):
        """Every machine.blk of the account, from one composed block.

        The script that owns the format still composes it; what it no longer
        does is open anything. It used to call `plan.build()` for itself when
        nobody handed it a layout, which is the clause this contract has been
        asking for since it was written.
        """
        targets = self.writer.targets_under(self.writer.SAVES)
        block, _dev, _names = self.writer.compose(layout, targets)
        return {t: self.writer.blk_with(t, block) for t in targets}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--unused', dest='free', action='store_true',
                            help='List the controls that stay unbound.')

    @typing.override
    def paths(self, args):
        return [('game', self.writer.GAME_DIR),
                ('saves', self.writer.SAVES),
                ('backups', backup.dir_for('warthunder', self.backup_dir))]

    @typing.override
    def show(self, layout, why=False):
        placed, unmet, free = (layout.on_buttons, layout.unplaced,
                               layout.free)
        axes = layout.on_axes
        buttons = button_table(placed)
        out = [f'{len(placed)} needs matched, {len(buttons)} bindings, '
               f'{len(axes)} axes', '']
        for p_ in placed:
            need, role, c = p_.need, p_.role, p_.ctrl
            used = [b for b, _v in p_.slots]
            where = c.direction(used[0]) if len(used) == 1 else ''
            out.append(f'  {need.what:24s} {role:8s} {c.kind:9s} '
                       f'{str(used):18s} {c.label}'
                       + (f' — {where}' if where else ''))
            if why:
                out.append('      ' + ', '.join(corneeds.why_bits(p_)))
                out.append('')

        if unmet:
            out.append('')
            out.append(f'{len(unmet)} needs found no control:')
            for n in unmet:
                # Guarded, like the placed branch above and like every
                # other listing in the family: 27 of the 28 needs carry a
                # string, and `'/'.join('button')` is `b/u/t/t/o/n`.
                #
                # The `reflex` clause that used to follow read a field that
                # was taken off `Need` -- "reflex is gone" -- and had sat
                # here unrun because nothing ever goes unplaced.
                shape = (n.shape if isinstance(n.shape, str)
                         else '/'.join(n.shape))
                out.append(f'  {n.what:24s} wanted {shape}'
                           + (f', {n.suits}' if n.suits else ''))
        if free:
            out += [''] + self.free(layout)
        return out

    @typing.override
    def says_button(self, role, index):
        """War Thunder numbers globally across devices, in the order they
        appear in machine.blk -- so the number you see in its menu is not
        the map's."""
        return str(wt_offsets()[role][1] + index)


if __name__ == '__main__':
    sys.exit(adapter.run(WarThunder))

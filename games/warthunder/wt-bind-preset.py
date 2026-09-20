#!/usr/bin/env python3
"""wt-bind-preset.py - write War Thunder's control preset

DESCRIPTION
    Resolve plan.py's layout onto War Thunder's global numbering and write the
    controls{} block of machine.blk. Every other block is left byte-identical.
    `./bind wt write` calls this through plan.py --write.

FILES
    ~/.config/WarThunder/Saves/*/production/machine.blk   written, one per
                                                          account
NOTES
    Close War Thunder first: it rewrites machine.blk on exit.
    Copies of what is replaced go to <repo>/backups/warthunder/<stamp>/.
"""

# Generate a full HOTAS control preset for War Thunder (native Linux client).
#
# The plan is not written here. plan.py reads sim-device-map, which knows the
# shape of every control on the hardware -- which buttons are one hat, which
# trigger stages are cumulative, what you can reach without letting go -- and
# matches each thing a pilot needs to a shape that suits it. This file only
# resolves that onto War Thunder's global numbering and writes the file.
#
# Targets air Simulator Battles + helicopters on a VIRPIL VMAX Prime throttle
# (js0) + VPC Stick WarBRD-D (js1).  Writes the `controls{}` block of
# Saves/<uid>/production/machine.blk, which is the file the game actually reads;
# every other block in that file is left byte-identical.
#
# War Thunder numbers joystick axes and buttons GLOBALLY across devices, in the
# order the devices appear in machine.blk's deviceMapping:
#
#     throttle  axes 0..6    buttons 0..50    (axesOffset 0,  buttonsOffset 0)
#     stick     axes 0..5    buttons 0..31    (axesOffset 7,  buttonsOffset 51)
#
# so  WT axisId = axesOffset + local axis  and  WT joyButton = buttonsOffset +
# local button.  The PLAN below is written in local (device, index) terms and
# resolved against the deviceMapping that the game itself recorded, so it stays
# correct if the offsets ever change.
#
# Usage:  ./wt-bind-preset.py [--dry-run] [--restore]

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if not os.path.isdir(CORE):
    raise SystemExit(f'no shared core at {CORE}\n'
                     'set SIM_BIND_WIZARD to the sim-bind-wizard checkout')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import backup                                     # noqa: E402

HOME = os.path.expanduser('~')
SAVES = os.path.join(HOME, '.config/WarThunder/Saves')
GAME_DIR = os.path.join(HOME, '.local/share/Steam/steamapps/common/War Thunder')
ACTIONS_JSON = os.path.join(HERE, 'wt-actions.json')

THR, STK = 'throttle', 'stick'

# --------------------------------------------------------------------------
# The plan.  (device, local index) -> action id.
# Air and helicopter actions are separate contexts in War Thunder, so the same
# physical control carries one of each without conflicting.
# --------------------------------------------------------------------------

#: Filled in by plan.py from sim-device-map: the hardware describes its own
#: shapes, and plan.py matches each need to one. Nothing about this device is
#: written down here any more.
AXES, BUTTONS = [], []

HELI_SUFFIX = '_HELICOPTER'


# --------------------------------------------------------------------------
# Minimal .blk reader/writer.  Only what machine.blk actually uses: nested
# blocks `name{ ... }` and typed scalars `name:t=value`.  Order is preserved,
# and only the blocks we rewrite are re-serialised.
# --------------------------------------------------------------------------

SCALAR_RE = re.compile(r'^(\w+):(\w+)=(.*)$')


def parse_block(lines, i, indent):
    """Return (items, next_index).  items: list of ('blk', name, items) or
    ('val', name, type, raw_value)."""
    items = []
    while i < len(lines):
        s = lines[i].strip()
        if s == '' or s.startswith('//'):
            i += 1
            continue
        if s == '}':
            return items, i + 1
        m = SCALAR_RE.match(s)
        if m:
            items.append(('val', m.group(1), m.group(2), m.group(3)))
            i += 1
            continue
        if s.endswith('{}'):
            items.append(('blk', s[:-2], []))
            i += 1
            continue
        if s.endswith('{'):
            sub, i = parse_block(lines, i + 1, indent + 1)
            items.append(('blk', s[:-1], sub))
            continue
        raise ValueError(f'blk parse error at line {i + 1}: {lines[i]!r}')
    return items, i


def dump_block(items, indent):
    """Serialise back in the game's own style: blocks separated by a blank
    line, scalars packed together, two-space indent."""
    pad = '  ' * indent
    out = []
    prev_was_block = False
    for it in items:
        if it[0] == 'val':
            if prev_was_block:
                out.append('')
            out.append(f'{pad}{it[1]}:{it[2]}={it[3]}')
            prev_was_block = False
        else:
            _, name, sub = it
            if out:
                out.append('')
            if not sub:
                out.append(f'{pad}{name}{{}}')
            else:
                out.append(f'{pad}{name}{{')
                out.extend(dump_block(sub, indent + 1))
                out.append(f'{pad}}}')
            prev_was_block = True
    return out


def find_sub(items, name):
    for it in items:
        if it[0] == 'blk' and it[1] == name:
            return it[2]
    return None


def num(x):
    """Format a number the way the game does: ints bare, floats trimmed."""
    if isinstance(x, int) or (isinstance(x, float) and x == int(x)):
        return ('i', str(int(x)))
    return ('r', repr(round(x, 6)).rstrip('0').rstrip('.'))


# --------------------------------------------------------------------------

def read_blk(path):
    """Read a .blk preserving its line ending -- the game writes CRLF and we
    only ever want the controls{} block to show up in a diff."""
    text = open(path, encoding='utf-8', newline='').read()
    eol = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n'), eol


def write_blk(path, lines, eol):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(eol.join(lines))


def extract_controls(text):
    """Locate the `  controls{` block and return (start, end, parsed items)."""
    m = re.search(r'^  controls\{$', text, re.M)
    if not m:
        sys.exit('error: no controls{} block in machine.blk')
    lines = text.split('\n')
    start = text[:m.start()].count('\n')
    items, end = parse_block(lines, start + 1, 2)
    return start, end, items


def device_offsets(controls):
    dm = find_sub(controls, 'deviceMapping')
    if dm is None:
        sys.exit('error: no deviceMapping in machine.blk -- start War Thunder '
                 'once with both devices plugged in, then re-run')
    devs = []
    for kind, name, sub in [i for i in dm if i[0] == 'blk']:
        if name != 'joystick':
            continue
        d = {k: v for _, k, _, v in [x for x in sub if x[0] == 'val']}
        devs.append({
            'name': d.get('name', '').strip('"'),
            'axes_off': int(d.get('axesOffset', 0)),
            'btn_off': int(d.get('buttonsOffset', 0)),
            'axes': int(d.get('axesCount', 0)),
            'buttons': int(d.get('buttonsCount', 0)),
            'connected': d.get('connected') == 'yes',
        })
    roles = {}
    for d in devs:
        low = d['name'].lower()
        if 'throttle' in low:
            roles[THR] = d
        elif 'stick' in low or 'warbrd' in low:
            roles[STK] = d
    missing = {THR, STK} - set(roles)
    if missing:
        sys.exit(f'error: could not find {", ".join(sorted(missing))} in '
                 f'deviceMapping (saw: {[d["name"] for d in devs]})')
    return roles


def targets_under(saves):
    """Every machine.blk of this install. They move together.

    One account's worth of the same layout: writing half of them, or
    restoring half, is a state the game was never in.
    """
    found = [p for p in (
        os.path.join(saves, 'last/production/machine.blk'),
        *[os.path.join(saves, d, 'production/machine.blk')
          for d in sorted(os.listdir(saves)) if d.isdigit()],
    ) if os.path.isfile(p)]
    if not found:
        raise SystemExit(f'error: no machine.blk under {saves}')
    return found


def blk_with(target, block):
    """`target`'s whole text, with its controls{} block replaced by this one.

    Only that block is ours. Everything else in machine.blk comes back byte
    for byte, including the file's own line ending -- the per-axis
    multipliers that are a slider in the game's own UI live out there.
    """
    txt, eol = read_blk(target)
    s, e, _ = extract_controls(txt)
    lines = txt.split('\n')
    return eol.join(lines[:s] + block + lines[e:])


def compose(layout, targets, say=print):
    """(the new controls{} block, device offsets, the game's action names).

    Everything `main()` used to do between reading the vocabulary and having
    the block ready, and nothing else: no argparse, no writing. `plan.py`
    asks for this and hands the result to `core.adapter`, which owns the
    backing up and the writing for every game in the family.

    War Thunder was the likeliest to keep writing for itself, being the one
    whose writer is a separate script -- so it is the one where the split
    matters most.
    """
    global AXES, BUTTONS
    import plan
    AXES[:] = layout.axes
    BUTTONS[:] = plan.button_table(layout.placed)

    lang = json.load(open(ACTIONS_JSON, encoding='utf-8'))
    known_actions, known_axes = lang['actions'], lang['controls']

    text, _eol = read_blk(targets[0])
    start, end, controls = extract_controls(text)
    dev = device_offsets(targets and controls)

    for role, d in dev.items():
        say(f'{role:9s} {d["name"]}')
        say(f'          axes {d["axes_off"]}..{d["axes_off"] + d["axes"] - 1}'
              f'   buttons {d["btn_off"]}..{d["btn_off"] + d["buttons"] - 1}'
              f'   connected={d["connected"]}')

    # ---- validate the plan against the game's own vocabulary -------------
    problems = []
    for name, *_ in AXES:
        if name not in known_axes:
            problems.append(f'unknown axis name: {name}')
    for role, idx, action, _ in BUTTONS:
        if action not in known_actions:
            problems.append(f'unknown action id: {action}')
        if idx >= dev[role]['buttons']:
            problems.append(f'{role} has no button {idx}')
    for name, role, idx, *_ in AXES:
        if idx >= dev[role]['axes']:
            problems.append(f'{role} has no axis {idx}')
    if problems:
        for p in sorted(set(problems)):
            say(f'  !! {p}')
        sys.exit('refusing to write: the plan does not match this install')

    # ---- conflicts: one physical button, two actions in one context ------
    def contexts(action):
        # Most helicopter actions suffix _HELICOPTER, a few prefix it -- and
        # the twin has to be looked for in BOTH forms. Looking only for the
        # suffix made `ID_TRIM` ("Trim aircraft") look like a shared action,
        # when its twin is `ID_HELICOPTER_TRIM` ("Trim helicopter"), and this
        # checker then reported a clash that does not exist. Same prefix /
        # suffix inconsistency as in plan.is_heli(), one layer further down.
        if action.endswith(HELI_SUFFIX) or action.startswith('ID_HELICOPTER'):
            return ['heli']
        twins = (action + HELI_SUFFIX,
                 action.replace('ID_', 'ID_HELICOPTER_', 1))
        if any(t in known_actions for t in twins):
            return ['air']          # the game has a separate heli twin
        return ['air', 'heli']      # no twin: the action applies to both

    seen = {}
    for role, idx, action, _ in BUTTONS:
        for c in contexts(action):
            key = (role, idx, c)
            if key in seen and seen[key] != action:
                # same action twice (a two-position switch) is intentional
                say(f'  ?? {role} button {idx} ({c}): '
                      f'{seen[key]} and {action}')
            seen[key] = action

    # ---- build the new hotkeys block -------------------------------------
    hotkeys = find_sub(controls, 'hotkeys')
    if hotkeys is None:
        sys.exit('error: no hotkeys block')

    by_action = {}
    order = []
    for kind, name, sub in [i for i in hotkeys if i[0] == 'blk']:
        by_action.setdefault(name, [])
        if name not in order:
            order.append(name)
        by_action[name].append(sub)

    # The joystick half of this block belongs to the plan: strip EVERY
    # joyButton and put back only what the plan asks for.
    #
    # Stripping only the PLANNED actions meant the plan could add and change
    # but never remove. Drop something from NEEDS and its old button stayed
    # live in the game, invisibly fighting whatever took its place -- which is
    # exactly what happened when the bomb sight and the helicopter trim reset
    # were taken off their hats and stayed bound anyway.
    #
    # Keyboard and mouse bindings are left alone. They are the game's business,
    # not the plan's.
    planned = {a for _, _, a, _ in BUTTONS}
    dropped = []
    for action in list(by_action):
        kept = [b for b in by_action[action]
                if not any(x[0] == 'val' and x[1] == 'joyButton' for x in b)]
        if len(kept) != len(by_action[action]) and action not in planned:
            dropped.append(action)
        by_action[action] = kept
    for action in planned:
        # An action the plan introduces may never have appeared in this file --
        # ID_TRIM_RESET had no binding of any kind -- so it needs its list
        # creating, not just its place in the order. Rebuilding this loop last
        # time dropped that and any brand-new action raised a KeyError.
        by_action.setdefault(action, [])
        if action not in order:
            order.append(action)
    if dropped:
        say('  -- joystick bindings cleared (nothing in the plan wants them):')
        for a in sorted(dropped):
            say(f'       {a}   {lang["actions"].get(a, [a])[0]}')

    for role, idx, action, _ in BUTTONS:
        wt = dev[role]['btn_off'] + idx
        by_action[action].append([('val', 'joyButton', 'i', str(wt))])

    # the leftover junk from fiddling in the UI: axis range helpers bound to a
    # joystick button do nothing useful and eat a button
    for name in list(by_action):
        if name.endswith(('_rangeMax', '_rangeMin')):
            by_action[name] = [b for b in by_action[name]
                               if not any(x[0] == 'val' and x[1] == 'joyButton'
                                          for x in b)]

    new_hotkeys = []
    for action in sorted(order):
        for b in by_action.get(action, []) or []:
            new_hotkeys.append(('blk', action, b))
        if not by_action.get(action):
            new_hotkeys.append(('blk', action, []))

    # ---- build the new axes block ----------------------------------------
    axes = find_sub(controls, 'axes') or []
    existing = {name: sub for k, name, sub in
                [i for i in axes if i[0] == 'blk']}

    for name, role, idx, inverse, props in AXES:
        wt = dev[role]['axes_off'] + idx
        old = {k: (t, v) for _, k, t, v in
               [x for x in existing.get(name, []) if x[0] == 'val']}
        new = []
        new.append(('val', 'axisId', 'i', str(wt)))
        t, v = num(props.get('innerDeadzone', 0.02))
        new.append(('val', 'innerDeadzone', t, v))
        # Keep the calibration the game's own axis wizard wrote -- unless the
        # plan asks for a value, in which case the plan wins and says so.
        for k in ('kAdd', 'kMul', 'nonlinearity', 'relative'):
            if k in props:
                v = props[k]
                if isinstance(v, bool):
                    new.append(('val', k, 'b', 'yes' if v else 'no'))
                else:
                    t, sv = num(v)
                    # keep the type the game itself used for this property --
                    # num() makes a whole number an int, and writing kMul:i=1
                    # where the game writes kMul:r=1 is a needless difference
                    if k in old and old[k][0] in ('r', 'i'):
                        t = old[k][0]
                        if t == 'r' and '.' not in sv:
                            sv += '.0'
                    new.append(('val', k, t, sv))
                if k in old and old[k][1] != new[-1][3]:
                    say(f'  -- {name}.{k}: {old[k][1]} -> {new[-1][3]}')
            elif k in old:
                new.append(('val', k, old[k][0], old[k][1]))
        if inverse:
            new.append(('val', 'inverse', 'b', 'yes'))
        existing[name] = new

    # The same "can add and change but never remove" hole the hotkeys block had,
    # one level down: an axis the plan stops naming kept its old axisId, so
    # dropping trim_elevator from AXIS_NEEDS left the right throttle lever still
    # trimming the aircraft. Clear the id from any axis pointing at OUR devices
    # that the plan no longer asks for -- and only ours, so a mouse axis or
    # anything set by hand on a third device is left alone.
    ours = []
    for role in dev:
        off = dev[role]['axes_off']
        ours.append((off, off + dev[role]['axes']))
    planned_axes = {name for name, _r, _i, _inv, _p in AXES}
    freed = []
    for name, sub in existing.items():
        if name in planned_axes:
            continue
        aid = next((int(v) for k, kk, _t, v in
                    [x for x in sub if x[0] == 'val'] if kk == 'axisId'), None)
        if aid is None or not any(lo <= aid < hi for lo, hi in ours):
            continue
        existing[name] = [x for x in sub
                          if not (x[0] == 'val' and x[1] == 'axisId')]
        freed.append(name)
    if freed:
        say('  -- axes released (the plan no longer wants them): '
              + ', '.join(sorted(freed)))

    new_axes = [('blk', n, existing[n]) for n in sorted(existing)]

    # ---- splice ----------------------------------------------------------
    rebuilt = []
    for it in controls:
        if it[0] == 'blk' and it[1] == 'hotkeys':
            rebuilt.append(('blk', 'hotkeys', new_hotkeys))
        elif it[0] == 'blk' and it[1] == 'axes':
            rebuilt.append(('blk', 'axes', new_axes))
        else:
            rebuilt.append(it)

    body = dump_block(rebuilt, 2)
    block = ['  controls{'] + body + ['  }']

    n_btn = len({(r, i) for r, i, _, _ in BUTTONS})
    say(f'\nplan: {len(planned)} actions across {n_btn} physical buttons, '
        f'{len(AXES)} axis assignments')
    return block, dev, known_actions


def main(argv=None, layout=None):
    """Write the preset. `layout` is a plan somebody else already narrowed --
    what the review screen hands over when only some bindings were kept --
    and without it the whole plan is computed here as before."""
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true',
                    help='print the plan and the resolved ids, write nothing')
    ap.add_argument('--restore', action='store_true',
                    help='put the files of a backup back')
    ap.add_argument('--restore-from', metavar='STAMP',
                    help='which backup --restore uses (default the newest)')
    ap.add_argument('--why', action='store_true',
                    help='print why each control was chosen, then exit')
    ap.add_argument('--render', metavar='PATH',
                    help='write the resulting machine.blk to PATH for review '
                         'instead of touching the real one')
    backup.add_argument(ap, 'warthunder')
    args = ap.parse_args(argv)

    import plan
    global AXES, BUTTONS
    lay = plan.build() if layout is None else layout
    AXES[:] = lay.axes
    BUTTONS[:] = plan.button_table(lay.placed)
    if args.why:
        os.execv(sys.executable, [sys.executable,
                                  os.path.join(os.path.dirname(
                                      os.path.abspath(__file__)), 'plan.py'),
                                  '--why'])

    # War Thunder rewrites machine.blk on exit -- never edit it underneath a
    # running game.
    try:
        running = subprocess.run(['pgrep', '-f', f'{GAME_DIR}/linux64/'],
                                 capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        running = ''
    if running and not (args.dry_run or args.render):
        sys.exit('error: War Thunder is running -- quit the game first, it '
                 'overwrites machine.blk on exit')

    targets = targets_under(SAVES)

    if args.restore:
        # Every machine.blk of a run goes back together: they are one account's
        # worth of the same layout, and restoring half of them is a state the
        # game was never in.
        src, done = backup.restore('warthunder', args.restore_from,
                                   args.backup_dir)
        for path in done:
            print(f'  restored {path}')
        print(f'  from {src}')
        return

    # This script's own entry point still needs a plan when nobody handed
    # it one -- that is what `./wt-bind-preset.py` with no arguments means.
    # It asks the adapter for it rather than a module-level `build()`, which
    # no longer exists: the needs and the install are the adapter's.
    import plan
    lay = plan.WarThunder().build() if layout is None else layout
    block, dev, known_actions = compose(lay, targets)

    if args.dry_run:
        for role, idx, action, where in BUTTONS:
            wt = dev[role]['btn_off'] + idx
            en = known_actions[action][0]
            pl = known_actions[action][1]
            print(f'  {role:8s} btn {idx:2d} -> WT {wt:3d}  {action:46s} '
                  f'{where:24s} {pl or en}')
        for name, role, idx, inv, _ in AXES:
            wt = dev[role]['axes_off'] + idx
            print(f'  {role:8s} axis {idx} -> WT {wt:2d}  {name:26s}'
                  f'{"  (inverted)" if inv else ""}')
        return

    if args.render:
        with open(args.render, 'w', encoding='utf-8', newline='') as f:
            f.write(blk_with(targets[0], block))
        print(f'  rendered {args.render} (nothing else was touched)')
        return

    dest, _ = backup.save('warthunder', *targets, into=args.backup_dir)
    print(f'  backed up to {dest}')
    for t in targets:
        with open(t, 'w', encoding='utf-8', newline='') as f:
            f.write(blk_with(t, block))
        print(f'  wrote {t}')


if __name__ == '__main__':
    main()

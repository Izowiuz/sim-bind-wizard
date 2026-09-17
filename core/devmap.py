"""Find and load the shared hardware map.

Every wizard in the family opened with the same twenty lines: work out where
sim-device-map is, fail with a useful message if it is missing, put it on the
path. Four copies, four chances to drift.
"""

import os
import sys

#: Sibling directory by default; SIM_DEVICE_MAP overrides it, for a clone that
#: does not sit next to this one.
DEFAULT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                 'sim-device-map'))


def load():
    """The devicemap module, or exit saying where it should have been."""
    path = os.environ.get('SIM_DEVICE_MAP') or DEFAULT
    if not os.path.isdir(path):
        sys.exit(f'no device map at {path}\n'
                 'clone sim-device-map next to this repo, or set SIM_DEVICE_MAP')
    if path not in sys.path:
        sys.path.insert(0, path)
    import devicemap
    return devicemap


def by_role(*required, pick=None):
    """{'stick': Device, 'throttle': Device, ...} keyed by the map's own `kind`.

    Keying on kind is what lets hardware change without touching any game's
    code: capture a new stick, it lands in the map as `kind = "stick"`, and
    every planner picks it up. Matching inside the map is by USB id and
    fingerprint, never by name, so a firmware update that renames the device
    does not lose it.

    Two devices of the same kind used to mean the last one loaded silently won.
    Now a CONNECTED device wins, and if that still does not decide it the
    ambiguity is reported rather than guessed -- picking the wrong stick would
    produce a layout that looks right and binds the wrong hardware.

    Override explicitly with `pick={'stick': 'slug'}` or the environment:

        SIM_DEVICE_ROLES="stick=vpc-stick-warbrd-d" ./plan.py
    """
    dm = load()
    forced = dict(pick or {})
    for part in filter(None, os.environ.get('SIM_DEVICE_ROLES', '').split(',')):
        role, _, slug = part.partition('=')
        forced.setdefault(role.strip(), slug.strip())

    by_kind = {}
    for d in dm.load_all():
        by_kind.setdefault(d.kind, []).append(d)

    live = set()
    try:
        live = {m.device.slug for m in dm.find_connected() if m.device}
    except OSError:
        pass                            # no /dev/input access; fall back to files

    out = {}
    for kind, devs in by_kind.items():
        if kind in forced:
            hit = next((d for d in devs if d.slug == forced[kind]), None)
            if hit is None:
                sys.exit(f'no {kind} called {forced[kind]!r} in the map; have '
                         + ', '.join(d.slug for d in devs))
            out[kind] = hit
            continue
        if len(devs) == 1:
            out[kind] = devs[0]
            continue
        plugged = [d for d in devs if d.slug in live]
        if len(plugged) == 1:
            out[kind] = plugged[0]
            continue
        if kind in required:
            sys.exit(
                f'the map has {len(devs)} devices of kind {kind!r} and '
                f'{len(plugged)} of them are plugged in, so which one this '
                'layout is for cannot be decided here.\n  candidates: '
                + ', '.join(d.slug for d in devs)
                + f'\n  choose with SIM_DEVICE_ROLES="{kind}=<slug>"')
        out[kind] = (plugged or devs)[0]

    missing = set(required) - set(out)
    if missing:
        sys.exit(f'device map has no {", ".join(sorted(missing))} — '
                 'capture one with sim-device-map/capture.py')
    return out

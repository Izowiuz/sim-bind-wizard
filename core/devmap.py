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


def by_role(*required):
    """{'stick': Device, 'throttle': Device, ...} keyed by what the map calls
    the device's kind, exiting if something named here is not captured yet."""
    dm = load()
    out = {d.kind: d for d in dm.load_all()}
    missing = set(required) - set(out)
    if missing:
        sys.exit(f'device map has no {", ".join(sorted(missing))} — '
                 'capture one with sim-device-map/capture.py')
    return out

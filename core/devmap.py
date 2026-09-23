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


def by_role(*required, desk=None):
    """{'stick': Device, 'throttle': Device, ...} as the desk says it is.

    Keying on the role is what lets hardware change without touching any
    game's code: put a new stick on the desk and every planner picks it
    up. Which device that is comes from the profile in the map, not from
    what happens to be plugged in.

    This used to guess. It bucketed the captures by `kind`, preferred a
    connected one, and where that still did not decide it fell through to
    `(plugged or devs)[0]` -- the last one loaded silently won. Two
    override channels existed to paper over it. A desk answers the
    question outright, so all of that is gone and the only thing left to
    say is which desk:

        SIM_DEVICE_PROFILE=Biurko ./plan.py

    `desk` names it in code, for a test or a caller that already knows.
    """
    dm = load()
    try:
        rig = dm.profile(desk)
    except SystemExit as e:
        # The map's own message names the desks and the environment
        # variable. This adds the flag, which is the spelling anybody
        # running a planner has in front of them.
        raise SystemExit(f'{e}\n  or: --desk <name>') from None
    if rig is None:
        sys.exit('no desk on file, so where your hardware sits is not'
                 ' written down anywhere.\n  make one with'
                 ' sim-device-map/capture.py')
    out = {}
    for dev in dm.load_all(rig=rig):
        if rig.entry(dev.slug) is not None:
            out[dev.role] = dev
    missing = set(required) - set(out)
    if missing:
        sys.exit(_nothing_to_bind(rig, out, missing))
    return out


def _nothing_to_bind(rig, have, missing):
    """Why this desk cannot answer, said about the desk and nothing else.

    Never about what you own. A desk with nothing on it is a desk nobody
    has filled in -- the hardware may be plugged in right now -- and
    `you have no stick` is a claim this has no way of making.
    """
    if not have:
        return (f'{rig.name} has nothing on it, so nothing here knows what'
                ' to bind.\n'
                '  say what is on it:  sim-device-map/capture.py\n'
                '  or work at another desk:  --desk <name>')
    return (f'{rig.name} does not say which of its devices does the job of'
            f' {", ".join(sorted(missing))}.\n'
            f'  it names: {", ".join(sorted(have))}\n'
            '  change what it says:  sim-device-map/capture.py\n'
            '  or work at another desk:  --desk <name>')


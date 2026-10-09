"""Find and load the shared hardware map.

Three things happen here. This module finds `sim-device-map`, reports a
missing one, and puts it on the path. Then it answers which device does
which job at one desk.
"""

import os
import sys

#: The sibling directory. SIM_DEVICE_MAP overrides it, for a clone that
#: does not sit next to this one.
DEFAULT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                 'sim-device-map'))


def where():
    """The map's own directory, wherever it is."""
    return os.environ.get('SIM_DEVICE_MAP') or DEFAULT


def capture_command():
    """How to run the capture tool, as a reader types it.

    The path, not the bare name. The tool is a command once `bin` is on
    your PATH. A message that says `devicemap` to somebody who has not
    done that names nothing they can run.
    """
    return os.path.join(where(), 'bin', 'devicemap')


def load():
    """The devicemap module, or exit naming where it should have been."""
    path = where()
    if not os.path.isdir(path):
        sys.exit(f'There is no device map at {path}.\n'
                 'Clone sim-device-map next to this repo, or set '
                 'SIM_DEVICE_MAP.')
    if path not in sys.path:
        sys.path.insert(0, path)
    import devicemap
    # The first moment both the rules and the map exist. `core.needs`
    # cannot check this at import, because it loads on a clone with no map
    # at all. A shape the rules name and the map has never heard of
    # matches nothing, and it matches nothing silently.
    from core import needs
    needs.check_rules(needs.RULES, devicemap)
    return devicemap


def by_role(*required, desk=None):
    """{'stick': Device, 'throttle': Device, ...} as the desk says it is.

    The key is the role. That is what lets hardware change with no edit to
    a game's code: put a new stick on the desk and every planner picks it
    up.

    The desk says which device does which job. What happens to be plugged
    in does not.

        SIM_DEVICE_PROFILE=Biurko ./plan.py

    `desk` names it in code, for a test or a caller that already knows.
    """
    dm = load()
    try:
        rig = dm.profile(desk)
    except SystemExit as e:
        # The map's own message names the desks and the environment
        # variable. This adds the flag, which is the spelling in front of
        # anybody running a planner.
        raise SystemExit(f'{e}\n  Or name one: --desk <name>') from None
    if rig is None:
        # `profile()` returns None in two states: nothing is on file, and
        # several are on file with nothing to say which. The two need
        # different answers, because each one names a different fix.
        have = dm.load_profiles()
        if have:
            sys.exit('More than one desk is on file: '
                     + ', '.join(p.name for p in have)
                     + '.\n  Name one: --desk <name>')
        sys.exit('No desk is on file. Nothing says where your hardware '
                 f'sits.\n  Make a desk: {capture_command()}')
    out = {}
    for dev in dm.load_all(rig=rig):
        if rig.entry(dev.slug) is not None:
            out[dev.role] = dev
    missing = set(required) - set(out)
    if missing:
        sys.exit(_nothing_to_bind(rig, out, missing))
    return out


def _nothing_to_bind(rig, have, missing):
    """Why this desk cannot answer, said about the desk only.

    Never about what you own. A desk with nothing on it is a desk nobody
    has filled in. The hardware can be plugged in at that moment, so
    `you have no stick` is a claim this cannot make.
    """
    if not have:
        return (f'{rig.name} has nothing on it, so nothing here knows what'
                ' to bind.\n'
                f'  Say what is on it: {capture_command()}\n'
                '  or work at another desk:  --desk <name>')
    return (f'{rig.name} does not say which of its devices does the job of'
            f' {", ".join(sorted(missing))}.\n'
            f'  it names: {", ".join(sorted(have))}\n'
            f'  Change what it says: {capture_command()}\n'
            '  or work at another desk:  --desk <name>')

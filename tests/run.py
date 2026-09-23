#!/usr/bin/env python3
"""Every test in this directory.

    ./tests/run.py              all of them
    ./tests/run.py needs backup only these
    ./tests/run.py -v           and say what each one was

Stdlib `unittest` and nothing else, because the rest of the repo takes no
dependencies either and a test suite you have to install something to run is a
test suite that stops being run.

`sim-device-map` has to be findable -- the fake hardware is built out of its
classes on purpose (see fake.py) -- so a missing map is reported as the one
thing wrong rather than as thirty broken imports.

The tests that run a real planner need a desk named, because the map will
not guess which one you are at and neither will this. Whichever is first on
file is used, unless SIM_DEVICE_PROFILE already says otherwise: the tests
are about a planner returning a layout, not about which desk it was for.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for path in (REPO, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    verbose = any(a in ('-v', '--verbose') for a in sys.argv[1:])

    from core import devmap
    try:
        dm = devmap.load()
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2
    if not os.environ.get('SIM_DEVICE_PROFILE'):
        on_file = dm.load_profiles()
        if on_file:
            os.environ['SIM_DEVICE_PROFILE'] = on_file[0].name

    loader = unittest.TestLoader()
    if args:
        suite = unittest.TestSuite(
            loader.loadTestsFromName(a if a.startswith('test_')
                                     else f'test_{a}') for a in args)
    else:
        suite = loader.discover(HERE, pattern='test_*.py', top_level_dir=HERE)

    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())

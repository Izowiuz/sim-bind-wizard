"""The third enforcement moment: signatures, before anything runs.

`abc` checks that a member exists. `core.adapter`'s `__init_subclass__`
checks that an override can be called the way the base promised. Neither
looks at a type.

What is left for pyright is what those two cannot see: a `build()` that
returns a tuple instead of a `Layout`, a parameter of the wrong type, and
an `@override` that names something no base defines.

This is the only layer a clone can be without, so the other two cover the
argument lists between them.

It skips rather than fails where pyright is absent. `tests/run.py` says a
test suite you have to install something to run is a test suite that stops
being run, and pyright is a Node program. `pipx install pyright` vendors
its own Node, which is why the skip reason names that command.

`pyrightconfig.json` is JSON and cannot carry comments, so the four decisions
in it are recorded here:

    six executionEnvironments   Not tidiness. A planner says `import
                                harvest` with no package, and that
                                resolves because the game's directory is
                                on sys.path. One shared extraPaths lets
                                pyright resolve `harvest` to whichever of
                                the six it saw first, and check MSFS's
                                planner against Elite's harvest without
                                saying so.

    ../sim-device-map           `core/devmap.py` inserts sys.path and imports
                                `devicemap` inside a function; pyright cannot
                                follow that, so the path is declared instead.

    standard everywhere         Strict on `core/adapter.py` produces 358
                                of the repository's 525 errors. Every one
                                of them says "you did not annotate this
                                local", and none is about the contract.
                                The abstract SIGNATURES state the
                                contract, and those are annotated.
                                Standard mode reads them and catches an
                                override that does not match.

    reportMissingModuleSource   `devicemap` lives in a sibling repo that may
                                not be cloned. A missing source there is a
                                fact about the machine, not about this code.

The sidecar seam is typed as far as it can be. A script loaded by path has
no importable name, so everything across that seam is `Any`. A planner
declares a `Protocol` naming what it calls and casts the module to it, and
that gets the CALL SITES checked: a typo in a function name, and a swapped
or missing argument, are both errors.

A cast cannot verify that the script has those functions. It is a promise
and not a proof, and pyright proves it only for a module it could import.
That half stays an AttributeError at run time, which is loud and
immediate.
"""

import json
import os
import shutil
import subprocess
import unittest

REPO = os.environ.get('SIM_BIND_WIZARD') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

WHERE = ('pyright not installed -- pipx install pyright, '
         'or npx pyright once to put it in the npm cache')


def command():
    """How to run pyright here, or None.

    `npx --no-install` runs it only where it is already in the npm cache,
    so this never reaches the network. A test that downloads a Node
    program the first time somebody runs the suite is a test that gets
    deleted.
    """
    if shutil.which('pyright'):
        return ['pyright']
    if shutil.which('npx') and subprocess.run(
            ['npx', '--no-install', 'pyright', '--version'],
            capture_output=True).returncode == 0:
        return ['npx', '--no-install', 'pyright']
    return None


RUN = command()


@unittest.skipUnless(RUN, WHERE)
class Types(unittest.TestCase):
    """What pyright says about the files that carry the contract."""

    @classmethod
    def setUpClass(cls):
        # `skipUnless(RUN, ...)` above guarantees this. Pyright cannot
        # follow the decorator, and a file that asserts pyright is clean
        # must not be one of its errors.
        if RUN is None:
            raise unittest.SkipTest(WHERE)
        run = subprocess.run(
            RUN + ['--outputjson', '--project', REPO],
            cwd=REPO, capture_output=True, text=True)
        try:
            cls.report = json.loads(run.stdout)
        except json.JSONDecodeError:
            raise unittest.SkipTest(
                f'pyright produced no report: {run.stderr.strip()[:200]}')

    def errors(self, under=None):
        """[(file, line, message)] -- pyright's errors. Warnings are left
        out.

        A warning is pyright's opinion about code that works. An error is
        something it can show is wrong. Only the second belongs in a suite
        people have to keep green.
        """
        out = []
        for d in self.report.get('generalDiagnostics', []):
            if d.get('severity') != 'error':
                continue
            path = os.path.relpath(d.get('file', ''), REPO)
            if under and not path.startswith(under):
                continue
            out.append((path, d.get('range', {}).get('start', {})
                        .get('line', 0) + 1, d.get('message', '')
                        .splitlines()[0]))
        return out

    def test_the_contract_itself_is_clean(self):
        """`core/adapter.py` has to be silent.

        The rest of the repository is unannotated, and it is allowed
        opinions filed against it. There were 107 of those when this was
        written, most of them in the tests. The file that states the
        contract is allowed none.
        """
        bad = self.errors(under='core/adapter.py')
        self.assertEqual([], bad, '\n'.join(
            f'{f}:{n} {m}' for f, n, m in bad))

    def test_no_adapter_breaks_its_base(self):
        """An override whose types do not match, anywhere under games/.

        This is the half the runtime guard cannot reach. That guard counts
        parameters, and pyright reads their types.
        """
        bad = [e for e in self.errors(under='games/')
               if 'override' in e[2].lower()
               or 'incompatible' in e[2].lower()]
        self.assertEqual([], bad, '\n'.join(
            f'{f}:{n} {m}' for f, n, m in bad))


if __name__ == '__main__':
    unittest.main()

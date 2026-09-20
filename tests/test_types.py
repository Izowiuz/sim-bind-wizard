"""The third enforcement moment: signatures, before anything runs.

`abc` checks that a member exists, `core.adapter`'s `__init_subclass__` checks
that an override can be called the way the base promised, and neither looks at
a type. What is left for pyright is what those two cannot see: a `build()`
that returns a tuple instead of a `Layout` -- the exact drift `core.needs`
records five adapters falling into -- a parameter of the wrong type, and an
`@override` naming something no base defines.

This is the only layer that can be missing from a clone, which is why the
other two cover arity between them rather than leaving it here.

Why it skips rather than fails when pyright is absent: `tests/run.py` says a
test suite you have to install something to run is a test suite that stops
being run. Pyright is a Node program, so requiring it would break that for
everyone without npm. `pipx install pyright` vendors its own Node, which is
why that is the line in the skip reason.

`pyrightconfig.json` is JSON and cannot carry comments, so the four decisions
in it are recorded here:

    six executionEnvironments   Not tidiness. `games/falconbms/plan.py` says
                                `import harvest` with no package, which
                                resolves only because the game's directory is
                                on sys.path. One shared extraPaths would let
                                pyright resolve `harvest` to whichever of the
                                six it saw first and check MSFS's planner
                                against Elite's harvest without saying so.

    ../sim-device-map           `core/devmap.py` inserts sys.path and imports
                                `devicemap` inside a function; pyright cannot
                                follow that, so the path is declared instead.

    standard everywhere         Strict was set on `core/adapter.py` at first,
                                on the reasoning that the file which IS the
                                contract deserves the strictest check. Run,
                                it produced 358 of the repo's 525 errors --
                                every one of them "you did not annotate this
                                local", none about the contract. What states
                                the contract is the abstract SIGNATURES, and
                                those are annotated; standard mode reads them
                                and catches an override that does not match.

    reportMissingModuleSource   `devicemap` lives in a sibling repo that may
                                not be cloned. A missing source there is a
                                fact about the machine, not about this code.

The sidecar seam is typed, as far as it can be. `wt-bind-preset.py`,
`ed-bind-wizard.py` and `dcs-bind-wizard.py` are loaded by path, so their
names are not importable and everything across that seam used to be `Any`.
Each planner now declares a `Protocol` naming what it calls and casts the
module to it, which gets the CALL SITES checked -- a typo in a function name
and a swapped or missing argument are both errors now, and neither was
visible to anything before.

What a cast cannot do is verify the script really has those functions: it is
a promise, not a proof, and pyright can only prove it for a module it could
import. That half stays an AttributeError at run time, which is at least
loud and immediate.
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

    `npx --no-install` runs it only if it is already in the npm cache, so
    this never reaches the network: a test that downloads a Node program the
    first time somebody runs the suite is a test that gets deleted.
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
        # `skipUnless(RUN, ...)` above already guarantees this, but the
        # decorator is not something pyright can follow -- and a file that
        # asserts pyright is clean has no business being one of its errors.
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
        """[(file, line, message)] -- pyright's errors, warnings left out.

        A warning is pyright's opinion about code that works; an error is
        something it can show is wrong. Only the second belongs in a suite
        that people have to keep green.
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
        """`core/adapter.py` must be silent.

        The rest of the repo is unannotated and is allowed to have opinions
        filed against it -- 107 of them at the time of writing, most in the
        tests. The file that states the contract is not allowed any.
        """
        bad = self.errors(under='core/adapter.py')
        self.assertEqual([], bad, '\n'.join(
            f'{f}:{n} {m}' for f, n, m in bad))

    def test_no_adapter_breaks_its_base(self):
        """An override whose types do not match, anywhere under games/.

        This is the half of Liskov the runtime guard cannot reach: it counts
        parameters and pyright reads them.
        """
        bad = [e for e in self.errors(under='games/')
               if 'override' in e[2].lower()
               or 'incompatible' in e[2].lower()]
        self.assertEqual([], bad, '\n'.join(
            f'{f}:{n} {m}' for f, n, m in bad))


if __name__ == '__main__':
    unittest.main()

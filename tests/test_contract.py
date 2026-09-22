"""The adapter contract, checked rather than described.

`ARCHITECTURE.md` used to carry the contract as prose and a paragraph
recording which adapters did not meet it. A document cannot fail, so the debt
sat there across releases. Everything here is what that paragraph used to say,
in a form that goes red.

Three properties this file is built around, and each cost something to get:

**It runs on a clone with nothing installed.** No device map, no harvested
cache, no game. `core.adapter` is imported for its classes and an adapter
module is imported for its class definitions, and neither reads data any
more -- the `vocab.load` calls that used to sit at module scope moved into
`__init__`. So a failure here is a failure of the contract rather than a fact
about what happens to be on this machine.

**Absent data and broken data are not the same answer.** A missing cache is
a skip, because nobody has run the harvest here and that is honest. A cache
that is present and the wrong shape is a failure, because either a working
copy is stale or a harvest and a planner disagree about a section name. Both
used to arrive as the same bare `SystemExit`, and `tests/test_formats.py`
turned both into a skip -- which is how a violated contract could look exactly
like an unharvested clone.

**A missing member is caught before any of that.** `abc` raises from
`ABCMeta.__call__`, strictly before `__init__` runs, so an incomplete class
fails even on a machine that has never seen the game.
"""

import inspect
import os
import re
import subprocess
import sys
import tempfile
import unittest

#: Deliberately not `import fake`: that loads the device map at import, and
#: the point of this file is that it says something on a clone which has none.
REPO = os.environ.get('SIM_BIND_WIZARD') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402


#: Games with no `Adapter` subclass yet, and why. The debt lives in code the
#: suite reads, the way `bind`'s own `GAPS` does, so it cannot quietly stop
#: being true the way a paragraph can. Empty this and the entry goes.
#: Empty. It held every game once; the last entry was DCS, whose needs are a
#: function of the aircraft and so could never be a module-level constant --
#: which is the reason the adapters became classes.
PENDING = {}

#: The six headings a game's README carries, in this order. They are a
#: contract clause because `measured` and `still a guess` being separate is
#: what tells a reader which claims are load-bearing.
HEADINGS = ('Where it lives', 'How to run it', 'The format',
            'Measured', 'Still a guess', 'Gotchas')

#: What `Adapter.parser()` gives every game, so `bind` may rely on it.
COMMON = ('--why', '--free', '--sheet', '--html', '--tui', '--write',
          '--backup-dir')


def bind():
    """The front door, imported. It has no `.py`, hence the loader."""
    return adapter.from_file('bindscript', os.path.join(REPO, 'bind'))


def reaches(fn, name, mod, seen=None):
    """Does `fn` name that global or attribute, directly or one call away?

    `name in fn.__code__.co_names` is a fact about the compiled function -- a
    LOAD_GLOBAL or a LOAD_ATTR -- so a docstring or a comment mentioning
    `build()` does not trip it, which a grep over the source would. It cannot
    see through `getattr` or a dispatch dict; no adapter uses either to reach
    a method, and if one ever does this stops being able to tell.
    """
    seen = seen if seen is not None else set()
    if fn in seen or not hasattr(fn, '__code__'):
        return False
    seen.add(fn)
    if name in fn.__code__.co_names:
        return True
    for called in fn.__code__.co_names:
        helper = getattr(mod, called, None)
        if inspect.isfunction(helper) and helper.__module__ == mod.__name__:
            if reaches(helper, name, mod, seen):
                return True
    return False


def live(game):
    """The one concrete Adapter subclass a game's planner defines.

    Raises `unittest.SkipTest` only for the two things that are facts about
    this machine: a cache nobody has built, and a device map nobody has
    cloned. Everything else is allowed to fail.
    """
    if game in PENDING:
        raise unittest.SkipTest(f'{game}: {PENDING[game]}')
    script = adapter.planner(game)
    found = adapter.adapters(game)
    if len(found) == 1:
        return found[0]
    if not found:
        # An incomplete subclass is abstract, so `adapters()` filtered it
        # out. Say which member is missing rather than that nothing was
        # found -- `abc` already knows, and its message is the better one.
        mod = adapter.load(game, script)
        for v in vars(mod).values():
            if (inspect.isclass(v) and issubclass(v, adapter.Adapter)
                    and v.__module__ == mod.__name__
                    and getattr(v, '__abstractmethods__', None)):
                raise AssertionError(
                    f'{game}/{script}: {v.__name__} leaves '
                    + ', '.join(sorted(v.__abstractmethods__))
                    + ' unimplemented')
    raise AssertionError(
        f'{game}/{script} defines {len(found)} concrete Adapter '
        f'subclasses, wanted exactly one: {[c.__name__ for c in found]}')


def built(cls):
    """An instance, or a skip if this machine lacks what it reads."""
    try:
        return cls()
    except vocab.Missing as e:
        raise unittest.SkipTest(str(e).splitlines()[-1])
    except SystemExit as e:
        # core.devmap exits when sim-device-map is not beside the repo.
        # vocab.Stale is a SystemExit too and is deliberately NOT caught.
        if isinstance(e, vocab.Stale):
            raise
        raise unittest.SkipTest(f'not on this machine: {e}')


class Readmes(unittest.TestCase):
    """Every game documents itself under the same six headings.

    Checkable on any clone, with nothing installed, which is why it is the
    one clause that was true for all six before any of this started.
    """

    def test_every_game_carries_the_six_headings_in_order(self):
        for game in adapter.games():
            path = os.path.join(REPO, 'games', game, 'README.md')
            with self.subTest(game=game):
                self.assertTrue(os.path.exists(path), path)
                with open(path, encoding='utf-8') as f:
                    found = re.findall(r'^## (.+)$', f.read(), re.M)
                self.assertEqual(list(HEADINGS), found)


class Shape(unittest.TestCase):
    """What every planner defines, whatever the game."""

    def test_each_game_defines_exactly_one_adapter(self):
        for game in adapter.games():
            with self.subTest(game=game):
                live(game)

    def test_needs_is_a_list_of_needs(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                self.assertIsInstance(obj.NEEDS, list)
                self.assertTrue(obj.NEEDS, 'a planner with no needs')
                for need in obj.NEEDS:
                    self.assertIsInstance(need, corneeds.Need)

    def test_build_returns_a_layout(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                self.assertIsInstance(obj.build(), corneeds.Layout)

    def test_every_planner_answers_every_common_flag(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                flags = {s for a in obj.parser()._actions
                         for s in a.option_strings}
                for flag in COMMON:
                    self.assertIn(flag, flags)


class TheWriterTakesWhatItIsGiven(unittest.TestCase):
    """A writer may not go and fetch a plan of its own.

    The review screen's entire job is to write some of a plan and not the
    rest, so a writer that calls `build()` silently undoes the reviewer's
    decisions -- it writes everything, including what was cleared. Two of them
    did exactly that, and one still took `placed=None` as a signal to.

    Not expressible as a signature, and Python has no `private` to stop the
    call, so this reads the compiled function instead. That is as close to
    the compiler's job as this gets.
    """

    def test_no_writer_reaches_build(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                mod = sys.modules[cls.__module__]
                writer = getattr(cls, 'write_layout', None) \
                    or getattr(cls, 'seed')
                self.assertFalse(
                    reaches(writer, 'build', mod),
                    f'{cls.__name__}: the writer reaches build() -- it must '
                    'take the placements it is handed')


class NothingIsLeftBehind(unittest.TestCase):
    """A writer may not leave a stray in the game's own directory.

    `core.backup`'s docstring records four of the six carrying a scar from
    it: a `.bak` beside the original is a file the game can find, and MSFS
    went one better by globbing its own backups back in as profiles.

    Structural now, as far as it goes -- a writer returns contents and has no
    file handle to leave anything with. What is left is the case where a
    writer delegates to a script of its own, which War Thunder and DCS both
    do, and that is what this holds. `lay_down` takes its reference point
    before the writer runs, so a file that appeared DURING it is caught;
    comparing directory listings afterwards would not, because by then the
    stray is already in the "before".
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.game = os.path.join(self.tmp, 'game')
        os.makedirs(self.game)
        self.target = os.path.join(self.game, 'profile.cfg')
        with open(self.target, 'w') as f:
            f.write('OLD\n')

    def writer(self, stray=False):
        target = self.target
        backups = os.path.join(self.tmp, 'backups')

        class Toy(adapter.Planner):
            game = 'toy'
            title = 'Toy'

            def __init__(self):
                self.backup_dir = backups
            # A property, not a class attribute: pyright rejects the second
            # as an override of an abstract property, and a fixture that
            # breaks the rule it is testing is not much of a fixture.
            @property
            def NEEDS(self): return ['one']
            def build(self): return corneeds.Layout({}, [], [], [])
            def catalogue(self): return []

            def describe(self, placement): return []
            def show(self, layout, why=False): return []
            def sheet(self, layout):
                return csheet.Sheet('Toy', '', devices={})
            def write_layout(self, layout):
                if stray:
                    with open(target + '.bak', 'w') as f:
                        f.write('oops')
                return {target: 'NEW\n'}

        return Toy()

    def test_a_clean_write_lays_down_what_it_declared(self):
        said = self.writer().write_all(None)
        with open(self.target) as f:
            self.assertEqual('NEW\n', f.read())
        self.assertTrue(any('profile.cfg' in ln for ln in said))

    def test_the_copy_goes_through_core_backup(self):
        """Nothing obliged a writer to back up before; the base calls it."""
        self.writer().write_all(None)
        kept = [f for _r, _d, fs in os.walk(os.path.join(self.tmp, 'backups'))
                for f in fs]
        self.assertIn('profile.cfg', kept)
        self.assertIn('MANIFEST', kept)

    def test_a_stray_in_the_game_directory_stops_the_write(self):
        with self.assertRaises(RuntimeError) as caught:
            self.writer(stray=True).write_all(None)
        self.assertIn('profile.cfg.bak', str(caught.exception))
        self.assertIn('core.backup', str(caught.exception))


class TheCacheBothSidesName(unittest.TestCase):
    """A harvest and a planner have to mean the same sections.

    They disagreed silently before: the planner exited saying a file was
    missing when the file was there under another key, and the only way to
    find out was to run the game.
    """

    def test_every_key_a_planner_loads_is_one_the_harvest_writes(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                where = os.path.join(REPO, 'games', game, 'harvest.py')
                if not os.path.exists(where):
                    # DCS harvests inside its capture wizard, which is what
                    # `bind`'s own GAPS says. A game with no harvest file has
                    # no cache for a planner to disagree with.
                    self.assertEqual({}, cls.CACHE,
                                     f'{game} loads a cache but has no '
                                     'harvest.py to write it')
                    self.skipTest(f'{game}: harvest is inside the wizard')
                harvests = [v for v in vars(adapter.load(game, 'harvest.py')
                                            ).values()
                            if inspect.isclass(v)
                            and issubclass(v, adapter.Harvest)
                            and not inspect.isabstract(v)]
                if not harvests:
                    self.skipTest(f'{game}: harvest not converted yet')
                written = {f: set(s) for f, s in harvests[0].files.items()}
                for filename, key in cls.CACHE.items():
                    self.assertIn(filename, written)
                    # One file may hold several sections -- BMS's does.
                    wanted = key if isinstance(key, tuple) else (key,)
                    for one in wanted:
                        if one is not None:
                            self.assertIn(one, written[filename])


class TheFrontDoorTellsTheTruth(unittest.TestCase):
    """`bind`'s table says which game answers which verb, and nothing kept
    it honest.

    Availability is decided purely by a key being present in a literal dict,
    and `GAPS` -- the prose explaining a missing verb -- is never consulted
    for it, so the two could contradict each other with nobody the wiser.
    `bind`'s own docstring states a clause ("Every planner owns --write")
    that has never been checked against an adapter.
    """

    def setUp(self):
        self.bind = bind()

    def test_the_verb_table_names_no_game_that_is_gone(self):
        """The game list is read off the filesystem now, so that half cannot
        drift. The verb rows are still written out, and a row for a folder
        somebody deleted would print nothing and say nothing."""
        self.assertEqual([], sorted(set(self.bind.VERB_ROWS)
                                    - set(adapter.games())))

    def test_every_game_is_titled_by_its_own_readme(self):
        for game, title in self.bind.TITLES.items():
            with self.subTest(game=game):
                path = os.path.join(REPO, 'games', game, 'README.md')
                with open(path, encoding='utf-8') as f:
                    self.assertEqual(f'# {title}', f.readline().strip())

    def test_a_verb_the_table_offers_is_a_flag_the_adapter_has(self):
        verbs = {'why': '--why', 'free': '--free', 'sheet': '--sheet',
                 'tui': '--tui', 'write': '--write'}
        for game, spec in self.bind.GAMES.items():
            with self.subTest(game=game):
                obj = built(live(game))
                flags = {s for a in obj.parser()._actions
                         for s in a.option_strings}
                for verb, flag in verbs.items():
                    if verb in spec:
                        self.assertIn(flag, flags, f'{game} {verb}')

    def test_a_verb_the_table_withholds_says_why(self):
        for game in self.bind.GAMES:
            for verb in self.bind.VERBS:
                if verb == 'plan' or verb in self.bind.GAMES[game]:
                    continue
                with self.subTest(game=game, verb=verb):
                    self.assertIn((game, verb), self.bind.GAPS,
                                  'a gap with no reason reads as an omission')

    def test_no_reason_is_given_for_a_verb_that_is_offered(self):
        for (game, verb), why in self.bind.GAPS.items():
            with self.subTest(game=game, verb=verb):
                self.assertNotIn(verb, self.bind.GAMES[game],
                                 f'GAPS says "{why}" but the table offers it')


class TheJudgementsHaveAHome(unittest.TestCase):
    """Where a game keeps what somebody decided, and how it gets back.

    A judgement is not derived from anything: delete it and it is gone.
    So a screen that lets you make one has to be able to write it down,
    and until it could, promoting an action lasted until you pressed `q`.
    """

    def planners(self):
        return [(g, live(g)) for g in adapter.games()]

    def test_a_game_with_a_hand_written_list_says_where_it_lives(self):
        for game, cls in self.planners():
            with self.subTest(game=game):
                if not cls.BINDS:
                    # DCS derives its needs from the aircraft, so there is
                    # no list of judgements to keep. `bind`'s own GAPS
                    # says the same about its review screen.
                    continue
                where = os.path.join(REPO, 'games', game, cls.BINDS)
                self.assertTrue(os.path.exists(where),
                                f'{game} names {cls.BINDS} and it is not there')

    def test_a_field_a_game_keeps_of_its_own_is_named(self):
        # BMS marks a need as living on the shifted layer and nobody else
        # has the idea. A generic bag would be the opaque payload this
        # contract replaced, so the game says which field travels.
        for game, cls in self.planners():
            with self.subTest(game=game):
                self.assertIsInstance(cls.EXTRA, tuple)


class DroppingTheCache(unittest.TestCase):
    """The one destructive thing the screen can do, held to its blast
    radius.

    A harvest is re-runnable: delete what it wrote and one command brings
    it back. A judgement is not -- delete it and it is gone. They sit in
    the same directory, named alike, and the button that removes the first
    must not be able to reach the second.

    It is not a matter of being careful. `CACHE` names what the harvest
    wrote and `BINDS` is deliberately not in it, so the list this walks
    cannot contain the judgements however the walk is written.
    """

    def test_it_never_names_the_judgements(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                if not cls.BINDS:
                    continue
                self.assertNotIn(cls.BINDS, cls.CACHE,
                                 f'{game} would delete its own judgements')

    def test_what_it_would_remove_is_what_a_harvest_writes(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                where = os.path.join(REPO, 'games', game, 'harvest.py')
                if not os.path.exists(where):
                    continue
                harvests = [v for v in vars(adapter.load(game, 'harvest.py')
                                            ).values()
                            if inspect.isclass(v)
                            and issubclass(v, adapter.Harvest)
                            and not inspect.isabstract(v)]
                if not harvests:
                    continue
                for name in cls.CACHE:
                    self.assertIn(name, harvests[0].files,
                                  f'{game} would delete {name}, which its '
                                  'harvest does not write back')


class EveryPayloadIsASlot(unittest.TestCase):
    """A control's click is a button like the others, and carries a slot
    like the others.

    `Need.push` never agreed with itself: War Thunder put a list of Binds
    there, MSFS a bare Bind, BMS a bare callback string. Every writer that
    walks `p.slots` then had to ask what it was holding -- five
    `isinstance` branches across two games, one of them commented "the
    push, a bare callback".

    Nothing was wrong with any of them on their own. They could not be
    written down together, which is what a contract is for.
    """

    def needs(self, game):
        return built(live(game)).NEEDS

    def test_a_slot_is_a_list_of_binds(self):
        for game in adapter.games():
            with self.subTest(game=game):
                for n in self.needs(game):
                    for slot in n.bindings:
                        self.assertIsInstance(slot, list, n.what)
                        for b in slot:
                            self.assertIsInstance(b, cactions.Bind, n.what)

    def test_a_click_is_a_slot_too(self):
        for game in adapter.games():
            with self.subTest(game=game):
                for n in self.needs(game):
                    if n.push is None:
                        continue
                    self.assertIsInstance(n.push, list, f'{game} {n.what}')
                    for b in n.push:
                        self.assertIsInstance(b, cactions.Bind, n.what)


class EveryGameHasACatalogue(unittest.TestCase):
    """The vocabulary, in one shape, from all six.

    What it does NOT assert is that a game has categories, modes or ranks:
    four of the six have no categories and X4 counts nothing, and a test
    demanding them would push somebody into deriving one.
    """

    def catalogue(self, game):
        return built(live(game)).catalogue()

    def test_it_is_not_empty(self):
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertTrue(self.catalogue(game))

    def test_every_id_appears_once(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cat = self.catalogue(game)
                self.assertEqual(len(cat), len({a.id for a in cat}))

    def test_every_action_is_a_button_or_an_axis(self):
        for game in adapter.games():
            with self.subTest(game=game):
                kinds = {a.kind for a in self.catalogue(game)}
                self.assertLessEqual(kinds, {'button', 'axis'})

    def test_nothing_carries_an_empty_name(self):
        # A blank row is unusable, and the fallback to the id exists so it
        # cannot happen however thin a cache is.
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertTrue(all(a.name for a in self.catalogue(game)))

    def test_it_holds_what_the_hand_written_list_binds(self):
        # The point of the whole thing: the curated list is a slice of the
        # catalogue. A miss means the translation dropped a section of the
        # cache, which is exactly the bug this shape is meant to end.
        for game in ('x4', 'elite', 'warthunder'):
            with self.subTest(game=game):
                obj = built(live(game))
                known = {a.id for a in obj.catalogue()}
                named = {x for n in obj.NEEDS for slot in n.bindings
                         for x in (slot if isinstance(slot, tuple)
                                   else (slot,))
                         if isinstance(x, str) and x}
                self.assertEqual(set(), named - known)


class TheDefaultVerb(unittest.TestCase):
    """`./bind x4` with no verb opens the screen.

    It printed the plan, which is the thing you read once to see whether
    the allocator got it right. The screen is the thing you come back to.
    """

    def setUp(self):
        self.bind = bind()

    def test_a_bare_game_opens_the_review(self):
        self.assertEqual('tui', self.bind.default_verb('x4'))

    def test_a_game_with_no_review_falls_back_to_the_plan(self):
        # DCS has none: its capture wizard already is one, which `GAPS`
        # says in those words. Falling through to an error would make the
        # shortest command in the family fail for one of six games.
        self.assertNotIn('tui', self.bind.GAMES['dcs'])
        self.assertEqual('plan', self.bind.default_verb('dcs'))

    def test_every_game_has_a_default_it_can_run(self):
        for game in self.bind.GAMES:
            with self.subTest(game=game):
                self.assertIn(self.bind.default_verb(game),
                              self.bind.GAMES[game])


class RunDirectly(unittest.TestCase):
    """Every script the README offers as runnable on its own, run on its own.

    Nothing else here starts one as `__main__`. `adapter.load` imports the
    module and never reaches its `main()`, and the front door is checked as
    a verb table -- so a script calling something the core has since moved
    is invisible to the whole suite.

    That is not hypothetical. `build()` went from a function in
    `games/warthunder/plan.py` to a method on `WarThunder`, and
    `wt-bind-preset.py` kept calling `plan.build()`: the script was dead on
    the first line that needed a plan, `./bind wt write` was fine because it
    hands the writer a layout, and 168 tests stayed green. A type checker
    found it months later; this is what should have.

    `test_no_writer_reaches_build` is the opposite rule and they do not
    overlap. A *writer* may never fetch a plan of its own, because the
    review screen's whole job is to write some of one. A script started on
    its own has nobody to be handed a plan by, and must.

    The two capture wizards are not run here: both open curses and read
    `/dev/input`, so there is no read-only way to start one. Only their
    import is covered, which is all `harvest.wizard()` and
    `propose.wizard()` ever do with them.
    """

    def ran(self, game, script, *args):
        """The script, in its own interpreter, from its own directory --
        which is how the README says to run it."""
        where = os.path.join(REPO, 'games', game)
        return subprocess.run([sys.executable, script, *args],
                              cwd=where, capture_output=True, text=True,
                              timeout=300)

    def test_a_planner_runs_as_its_own_script(self):
        for game in adapter.games():
            with self.subTest(game=game):
                # The same skip the rest of this file takes on a bare
                # clone: no harvest, or no device map, is a fact about this
                # machine and not about the code.
                built(live(game))
                done = self.ran(game, adapter.planner(game), '--why')
                self.assertEqual(0, done.returncode,
                                 done.stderr.strip()[-500:])

    def test_the_sidecar_that_owns_a_format_runs_as_its_own_script(self):
        # War Thunder's, because it is the one that broke. It is also the
        # only one of the three with a verb that writes nothing: the other
        # two own their format from inside a capture wizard.
        built(live('warthunder'))
        done = self.ran('warthunder', 'wt-bind-preset.py', '--dry-run')
        self.assertEqual(0, done.returncode, done.stderr.strip()[-500:])

    def test_a_capture_wizard_still_imports(self):
        for game, script in (('dcs', 'dcs-bind-wizard.py'),
                             ('elite', 'ed-bind-wizard.py')):
            with self.subTest(game=game):
                adapter.from_file(f'{game}_wizard_under_test',
                                  os.path.join(REPO, 'games', game, script),
                                  argv=[script])


if __name__ == '__main__':
    unittest.main()

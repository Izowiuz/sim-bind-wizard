"""The adapter contract, checked rather than described.

A document cannot fail, so a contract carried as prose carries its debt
across releases. Everything here is that prose in a form that goes red.

Three properties this file is built around, and each one cost something.

**It runs on a clone with nothing installed.** No device map, no harvested
cache, no game. `core.adapter` is imported for its classes and an adapter
module for its class definitions, and neither reads data: a `vocab.load`
call belongs in `__init__` and not at module scope. So a failure here is a
failure of the contract, and not a fact about this machine.

**Absent data and broken data are not the same answer.** A missing cache
is a skip, because nobody has run the harvest here and that is honest. A
cache that is present and the wrong shape is a failure, because a working
copy is stale or a harvest and a planner disagree about a section name.
Both arriving as the same bare `SystemExit`, a violated contract looks
like an unharvested clone.

**A missing member is caught before any of that.** `abc` raises from
`ABCMeta.__call__`, before `__init__` runs, so an incomplete class fails
on a machine that has never seen the game.
"""

import inspect
import json
import io
import os
import re
import subprocess
import sys
import tempfile
import typing
import unittest
from unittest import mock

#: Not `import fake`. That loads the device map at import, and the point
#: of this file is that it says something on a clone with no map.
REPO = os.environ.get('SIM_BIND_WIZARD') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core import actions as cactions                        # noqa: E402
from core import adapter
from core import guess as cguess                                    # noqa: E402
from core import needs as corneeds                          # noqa: E402
from core import sheet as csheet                            # noqa: E402
from core import vocab                                      # noqa: E402


#: Games with no `Adapter` subclass yet, and why. The debt lives in code
#: the suite reads, so it cannot quietly stop being true the way a
#: paragraph can.
#:
#: Empty. It held every game once. The last entry was DCS, whose needs are
#: a function of the aircraft and so could never be a module-level
#: constant. That is why the adapters are classes.
PENDING = {}

#: What `Adapter.parser()` gives every game, so `bind-wizard.py` may rely on
#: it.
COMMON = ('--why', '--free', '--sheet', '--html', '--tui', '--write',
          '--backup-dir')


def bind():
    """The front door, imported. It has no `.py`, hence the loader."""
    return adapter.from_file('bindscript',
                             os.path.join(REPO, 'bind-wizard.py'))


def reaches(fn, name, mod, seen=None):
    """Does `fn` name that global or attribute, directly or one call away?

    `name in fn.__code__.co_names` is a fact about the compiled function.
    It is a LOAD_GLOBAL or a LOAD_ATTR, so a docstring or a comment that
    mentions `build()` does not trip it. A grep over the source does.

    It cannot see through `getattr` or a dispatch dict. No adapter uses
    either to reach a method, and one that does stops being visible
    here.
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

    Raises `unittest.SkipTest` for the two things that are facts about
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
        # out. Say which member is missing, rather than that nothing was
        # found. `abc` knows, and its message is the better one.
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
    """An instance, or a skip where this machine lacks what it reads."""
    try:
        return cls()
    except vocab.Missing as e:
        raise unittest.SkipTest(str(e).splitlines()[-1])
    except SystemExit as e:
        # `core.devmap` exits where sim-device-map is not beside the
        # repository. `vocab.Stale` is a SystemExit too, and it is NOT
        # caught here.
        if isinstance(e, vocab.Stale):
            raise
        raise unittest.SkipTest(f'not on this machine: {e}')


class TheInterfaceStaysSmall(unittest.TestCase):
    """What a game may supply, counted.

    A hook is an invitation. `says_slot` as a hook is four games writing
    the same body over the same eight-name axis table with a different
    spelling. `paths` as a hook is six games writing `getattr`.
    `arguments` as a hook is six games adding a flag the constructor
    declares.

    A declaration cannot be written four ways, because there is nowhere in
    it to put code. So the count is the clause. Anything a game would
    IMPLEMENT the same way as another game is a declaration, and what is
    left is its own format.
    """

    def hooks(self, cls):
        """Every member of `cls` a subclass is allowed to override."""
        out = []
        for name, member in vars(cls).items():
            if name.startswith('_'):
                continue
            fn = member.fget if isinstance(member, property) else member
            if not (inspect.isfunction(fn) or isinstance(member, property)):
                continue
            if name in cls.__abstractmethods__:
                continue
            if not getattr(fn, '__final__', False):
                out.append(name)
        return sorted(out)

    def test_a_game_supplies_its_format_and_nothing_else(self):
        self.assertEqual(['read', 'summary'],
                         sorted(adapter.Harvest.__abstractmethods__))
        self.assertEqual(['write_layout'],
                         sorted(adapter.Planner.__abstractmethods__))

    def test_there_is_one_hook_on_each_side(self):
        # `Harvest.arguments`. A harvest has no constructor to read flags
        # off, and a declaration carrying argparse's types is an argument
        # spec in data.
        self.assertEqual(['arguments'], self.hooks(adapter.Harvest))
        # One on `Adapter`. Which variants are INSTALLED is read out of
        # the game directory, so it cannot be declared.
        #
        # A second hook that asks which actions you already had bound
        # opens the game's files again to learn what the harvest just
        # read. That belongs in the cache, like everything else a harvest
        # finds out.
        self.assertEqual(['variants'], self.hooks(adapter.Adapter))
        self.assertEqual([], self.hooks(adapter.Planner))

    def test_no_game_adds_a_method_of_its_own(self):
        """A game is declarations plus its writer.

        Public members, because a private helper of a format writer is
        that writer's business. What a game may not do is offer a method
        the interface does not declare. Such a method makes a caller
        upstairs know which game it is holding.
        """
        allowed = {'write_layout', 'variants'}
        for game in adapter.games():
            with self.subTest(game=game):
                (cls,) = adapter.adapters(game)
                mine = {n for n, v in vars(cls).items()
                        if not n.startswith('_')
                        and (inspect.isfunction(v)
                             or isinstance(v, property))}
                self.assertEqual(set(), mine - allowed)


class WhatTheProgramProposesIsMarked(unittest.TestCase):
    """`Z` proposes and you decide. The difference is written down.

    A description derived from command names on every run has four faults,
    and the guessing is not one of them:

        it runs every time        so the layout depends on the table
        it is in the path         `allocate` can see it
        it leaves no mark         a derived field reads like one you wrote
        it cannot be corrected    the table overwrites the file next run

    `core/guess.py` runs on one key, writes into `Need.guessed`, and skips
    a field that is NOT in there. A field's absence from that set means
    you decided it.
    """

    def toy(self, **said):
        """A need carrying what `said` says, and nothing marked."""
        need = corneeds.Need('Trim Hat', 'hat',
                             [[cactions.Bind('TRIM_UP')]])
        for field, value in said.items():
            setattr(need, field, value)
        return need

    def test_a_word_names_one_job_and_every_job_is_a_job(self):
        # The same clause `needs.check_rules` holds over the scoring
        # file. A job nothing knows is a proposal no overlay matches, and
        # a word in two jobs is a vote that depends on dict order.
        self.assertEqual([], cguess.check_table())

    def test_it_says_nothing_rather_than_guessing_wildly(self):
        # A quarter of a hand-written list reads as nothing here. Those
        # filed under a default are a judgement with no evidence. None is
        # the honest answer.
        self.assertIsNone(cguess.job_of('Zzz Qqq'))
        self.assertEqual('trim', cguess.job_of('Trim Hat - NOSE UP'))

    def test_a_name_nobody_put_spaces_in_still_reads(self):
        # Elite writes `RollAxisRaw` and X4 writes
        # `INPUT_RANGE_MAP_ZOOM_IN`. The name lowered before it is split
        # gives ONE token, and every word inside it is invisible: 17 of 50
        # silent names hold a word the table knows.
        self.assertEqual('flight', cguess.job_of('RollAxisRaw'))
        self.assertEqual('flight', cguess.job_of('KEY_BRAKES'))
        self.assertEqual('comms', cguess.job_of('Comms'))

    def test_what_it_fills_it_marks(self):
        maker = cguess.Guess(job_by_category={'Weapons': 'fire'},
                             device_by_category={'Stick': 'stick'})
        said = maker.about(cactions.Action('X', 'Master Arm',
                                           category='Stick'))
        self.assertEqual('stick', said.get('device'))

    def test_it_never_proposes_a_band(self):
        # No game's files record WHEN you reach for a thing, so a band
        # here invents the judgement the scorer leans on hardest.
        maker = cguess.Guess()
        for name in ('Master Arm', 'Gear', 'Trim Hat', 'Chaff'):
            said = maker.about(cactions.Action('X', name))
            with self.subTest(name=name):
                self.assertNotIn('urgency', said)

    def test_nothing_in_the_allocator_can_see_it(self):
        """The planner reads the needs FILE and never the classifier.

        Read over the source and not over the behaviour. A layout that
        happens to match proves nothing about what can be reached.
        """
        for name in ('needs', 'overlay', 'solvers'):
            path = os.path.join(REPO, 'core', f'{name}.py')
            with open(path, encoding='utf-8') as f:
                text = f.read()
            with self.subTest(module=name):
                # The import and the call, and not the word.
                # `core/needs.py` names `core/guess.py` in a comment,
                # which is how a reader finds out the mark exists.
                self.assertNotIn('import guess', text)
                self.assertNotIn('cguess.', text)
                self.assertNotIn('guess.Guess', text)


class NoGameCarriesAMechanism(unittest.TestCase):
    """The same work, written once.

    A table keyed by the map's HID axis names, and a body to look a slot
    up in it, is four copies across four games. One of the four disagreed
    with the review screen about which button a hat direction sat on,
    because the loop that found out was written four times.
    """

    def source(self, game):
        where = os.path.join(REPO, 'games', game, 'plan.py')
        with open(where, encoding='utf-8') as f:
            return f.read()

    def test_no_planner_keys_anything_on_a_map_axis_name(self):
        # The map's own words for an axis. A planner that names one as a
        # key holds its own copy of `HID_AXES`, and the position in
        # `AXES` is the whole mapping.
        for game in adapter.games():
            text = self.source(game)
            for hid in adapter.HID_AXES:
                with self.subTest(game=game, axis=hid):
                    self.assertNotIn(f"'{hid}':", text)
                    self.assertNotIn(f'"{hid}":', text)

    def test_no_planner_walks_the_placements(self):
        # `Adapter.rows` is that walk, once. Four writers otherwise hold
        # the same three nested loops down `placed`, `slots` and the
        # payload.
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertNotIn('layout.placed', self.source(game))


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
                # Empty is a state and not a fault. A needs file is
                # written by `J` on the review screen, so every game
                # starts with none and `undescribed_note` says so in
                # words. An assertion that the list is non-empty asserts
                # that the list ships with the planner.
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
    """A writer may not fetch a plan of its own.

    The review screen's whole job is to write some of a plan and not the
    rest. A writer that calls `build()` undoes the reviewer's decisions
    and says nothing: it writes everything, including what was cleared.

    No signature says that, and Python has no `private` to stop the call.
    So this reads the compiled function.
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

    A `.bak` beside the original is a file the game can find, and MSFS
    globs its own backups back in as profiles. `core.backup`'s docstring
    records four of the six carrying a scar from that.

    This is structural as far as it goes: a writer returns contents and
    has no file handle to leave anything with. What is left is a writer
    that delegates to a script of its own, which War Thunder and DCS both
    do, and this test holds that case.

    `lay_down` takes its reference point before the writer runs, so a file
    that appeared DURING the run is caught. Two directory listings
    compared afterwards hold the stray in the "before".
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

        # The whole of a game, as the interface leaves it: what it is
        # called, and how its own file is written. Everything else is
        # final on `Adapter`, and this fixture being six lines says so.
        class Toy(adapter.Planner):
            game = 'toy'
            title = 'Toy'

            def __init__(self):
                self.backup_dir = backups

            def write_layout(self, rows, layout):
                if stray:
                    with open(target + '.bak', 'w') as f:
                        f.write('oops')
                return {target: 'NEW\n'}

        return Toy()

    #: An empty plan. This is about laying a declared file down, so what
    #: the layout holds is beside the point. It has to BE a layout,
    #: because `rows()` walks it on the way to the writer.
    NOTHING = corneeds.Layout({}, [], [], [])

    def test_a_clean_write_lays_down_what_it_declared(self):
        said = self.writer().write_all(self.NOTHING)
        with open(self.target) as f:
            self.assertEqual('NEW\n', f.read())
        self.assertTrue(any('profile.cfg' in ln for ln in said))

    def test_the_copy_goes_through_core_backup(self):
        """The base calls `core.backup`, so no writer has to."""
        self.writer().write_all(self.NOTHING)
        kept = [f for _r, _d, fs in os.walk(os.path.join(self.tmp, 'backups'))
                for f in fs]
        self.assertIn('profile.cfg', kept)
        self.assertIn('MANIFEST', kept)

    def test_a_stray_in_the_game_directory_stops_the_write(self):
        with self.assertRaises(RuntimeError) as caught:
            self.writer(stray=True).write_all(self.NOTHING)
        self.assertIn('profile.cfg.bak', str(caught.exception))
        self.assertIn('core.backup', str(caught.exception))


class WhatYouClearedStaysCleared(unittest.TestCase):
    """The answers file is read once, and not on every replan.

    `build` runs again every time the screen replans: a key, an overlay,
    another aircraft. A game that reads its answers file there brings a
    row you cleared back carrying the `chose` you took off it. The `chose`
    pass puts it on the control, the mark goes green, and the next save
    writes the resurrected row. Clearing a hand-placed binding is then
    impossible.

    Measured on this desk: 32 of DCS's 32 rows and 32 of X4's 32 came
    back from one replan.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.file = os.path.join(self.tmp, 'toy-binds.json')
        with open(self.file, 'w') as f:
            json.dump({'binds': [{'what': 'Gear', 'role': 'stick',
                                  'control': 'a-button', 'how': 'chose'}]}, f)
        self.list = os.path.join(self.tmp, 'toy-needs.json')
        with open(self.list, 'w') as f:
            json.dump({'needs': [{'what': 'Gear', 'shape': 'button',
                                  'bindings': [[]]}]}, f)

    def toy(self, *rows):
        """A game whose two files are the temporary ones.

        `rows` replaces what the needs file holds, as the file holds it.
        The list is read from disk, so a fixture that handed over `Need`
        objects would test a path nothing uses.
        """
        if rows:
            with open(self.list, 'w') as f:
                json.dump({'needs': list(rows)}, f)
        binds, described = self.file, self.list

        class Toy(adapter.Planner):
            game = 'toy'
            title = 'Toy'
            # Absolute, so `here` joins to the temporary copy rather than
            # to the repository. `here` is this test file's directory.
            BINDS = binds
            NEEDS_FILE = described

            def write_layout(self, rows, layout): return {}

        return Toy()

    def test_the_first_build_reads_the_file(self):
        obj = self.toy()
        obj.build()
        self.assertEqual('chose', (obj.NEEDS[0].assignment or {}).get('how'))

    def test_a_replan_does_not_read_it_again(self):
        obj = self.toy()
        obj.build()
        obj.NEEDS[0].assignment = None
        obj.build()
        self.assertIsNone(obj.NEEDS[0].assignment)

    def test_another_adapter_reads_its_own(self):
        # Switching aircraft builds a second adapter, and that one has
        # decided nothing. The file is all it knows.
        was = self.toy()
        was.build()
        was.NEEDS[0].assignment = None
        now = self.toy()
        now.build()
        self.assertEqual('chose', (now.NEEDS[0].assignment or {}).get('how'))

    def test_an_axis_answer_comes_back_on_its_need(self):
        # An axis plan built fresh from the devices on every build has to
        # read its answers again every time, and that overwrites what the
        # session decided. An axis is a need: the same object all session,
        # answered once, and a replan cannot blank it.
        with open(self.file, 'w') as f:
            json.dump({'binds': [{'what': 'Pitch', 'role': 'stick',
                                  'control': 'main-stick', 'axis': 1,
                                  'invert': True, 'how': 'accepted'}]}, f)
        obj = self.toy({'what': 'Pitch', 'shape': 'stick', 'bindings': [[]],
                        'takes': corneeds.AXIS, 'device': 'stick',
                        'on': ['y']})
        obj.build()
        (need,) = obj.NEEDS
        self.assertEqual('accepted', (need.assignment or {}).get('how'))
        self.assertEqual(1, (need.assignment or {}).get('axis'))
        self.assertTrue(need.invert, 'which way round you left it')
        obj.build()
        self.assertTrue(need.invert)

    def test_no_game_reads_its_answers_twice(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                obj.build()
                for need in obj.NEEDS:
                    need.assignment = None
                obj.build()
                back = [n.what for n in obj.NEEDS if n.assignment]
                self.assertEqual([], back, 'came back from a replan')


class TheCacheBothSidesName(unittest.TestCase):
    """A harvest and a planner mean the same sections.

    They disagree in silence otherwise. The planner exits saying a file is
    missing while the file is there under another key, and the only way to
    find out is to run the game.
    """

    def test_every_key_a_planner_loads_is_one_the_harvest_writes(self):
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                where = os.path.join(REPO, 'games', game, 'harvest.py')
                if not os.path.exists(where):
                    # A game with no harvest file has no cache for a
                    # planner to disagree with.
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
                    # One file may hold several sections. Falcon BMS's
                    # does.
                    wanted = key if isinstance(key, tuple) else (key,)
                    for one in wanted:
                        if one is not None:
                            self.assertIn(one, written[filename])


class NoNameDecidesAnything(unittest.TestCase):
    """An action's NAME has no influence on the layout.

    This is the premise, held to. The algorithm transforms discrete
    measured values: the map says what a control IS, the harvest says
    which actions exist, the needs file hangs judgements on those
    identifiers, and the scorer lays one over the other.

    A string comparison anywhere in that path is a judgement smuggled in
    as a rule about spelling. Twelve of them lived across six games:
    `HINTS` over 852 DCS command names, `jobs.toml` phrases, `AXIS_ASK`,
    `MOVE_TO_DIR`, `STAGE_WORDS`, `context_of`, `'throttle' in name`,
    `_tail`, `safe$`.

    Measured by renaming. The same actions under different names land on
    the same controls. Nothing here reads a planner's source, so a regex
    moved somewhere this does not look does not satisfy it.
    """

    #: What a judgement is: which band, what shape, which device, which
    #: finger, whether you hold it, and what it is for. Everything a need
    #: carries that the catalogue cannot say.
    #: `urgency` is not here. The core gives one default to anything
    #: nobody has said anything about, and the test below holds it to
    #: that. An empty band is not a thing a need can have.
    JUDGEMENTS = (corneeds.WISHES + corneeds.TOLD
                  + ('suits', 'on', 'rests', 'invert'))

    def test_a_need_made_from_an_action_carries_no_judgement(self):
        """`add_need` is the only way an action becomes a need.

        So this is where a name could be read for a judgement, and where
        it must not be. The catalogue says the identifier, the name, and
        whether the action is an axis. That is the whole of what arrives.
        An axis asks for any lever and a button for any button, and `J` on
        the review screen is how one comes to say more.

        A planner that derives `device` or `suits` from how a command is
        spelled puts it on a need made here, and this fails.
        """
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                picked = [a for a in obj.catalogue()][:40]
                if not picked:
                    self.skipTest(f'{game} has no catalogue here')
                for action in picked:
                    need = obj.add_need(action)
                    self.assertEqual(action.name, need.what)
                    self.assertEqual(
                        'axis' if action.kind == 'axis' else 'button',
                        need.shape,
                        f'{action.id}: the shape came from somewhere else')
                    for field in self.JUDGEMENTS:
                        got = getattr(need, field, None)
                        if got in (None, False, 0, '', ()):
                            continue
                        # It may arrive judged. The game's own category
                        # says `Throttle Grip` is the throttle. It may not
                        # arrive judged in SILENCE: an unmarked judgement
                        # reads like one somebody wrote down, and
                        # `Need.guessed` is what marks it.
                        with self.subTest(field=field):
                            self.assertIn(
                                field, need.guessed,
                                f'{action.id} arrived judged and unmarked: '
                                f'{field} is {got!r}')

    def test_the_urgency_is_the_one_the_core_defines(self):
        # And not a band read off anything. No game's files record WHEN
        # you reach for a thing, so a proposal here invents the judgement
        # the scorer leans on hardest. `Guess.about` never returns
        # one.
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                picked = next(iter(obj.catalogue()), None)
                if picked is None:
                    self.skipTest(f'{game} has no catalogue here')
                self.assertEqual(corneeds.IN_THE_AIR,
                                 obj.add_need(picked).urgency)


class TheFrontDoorTellsTheTruth(unittest.TestCase):
    """What `./bind-wizard.py` prints, against what the games answer.

    `bind-wizard.py`'s own docstring states a clause ("Every planner owns
    --write") that nothing else checks against an adapter.

    A verb matrix in the table is seven columns per game, each cell a dot
    or a dash. Every cell comes from a key being in a dict that every game
    gets a copy of, so the grid reads `·` always. `GAPS` is the prose that
    explains a dash, and neither is here.
    """

    def setUp(self):
        self.bind = bind()

    def test_an_alias_names_a_game_that_is_there(self):
        """A name the table answers to and the filesystem does not is a
        name you type and nothing runs."""
        self.assertEqual([], sorted(set(self.bind.ALIASES)
                                    - set(self.bind.TITLES)))

    def test_the_table_lists_the_games_that_answer(self):
        """And not every directory under `games/`.

        `games/falconbms` and `games/warthunder` hold a needs list and a
        binds file with no planner beside them. A row for one is a word
        you type that reaches no script.
        """
        self.assertEqual(sorted(adapter.games()), sorted(self.bind.GAMES))
        for game in self.bind.GAMES:
            with self.subTest(game=game):
                self.assertTrue(os.path.isfile(
                    os.path.join(REPO, 'games', game, 'plan.py')))

    def test_every_game_is_titled_by_its_own_adapter(self):
        """And not by a file beside it.

        A title read out of `games/<game>/README.md` makes a Python file
        need a README to work, and it needs a test here to keep the
        heading in place.

        A README is documentation. The title is a fact the adapter states,
        and `discover()` reads it off the class without constructing
        one.
        """
        for game, title in self.bind.TITLES.items():
            with self.subTest(game=game):
                (cls,) = adapter.adapters(game)
                self.assertEqual(cls.title, title)

    def test_every_verb_is_a_flag_every_adapter_has(self):
        """One verb table for every game, so every game answers all of it.

        `VERB_FLAGS` turns a verb into a script and a flag. `plan` passes
        none and `harvest` runs the other script, so those two have nothing
        to find on a planner's parser.
        """
        flags_for = {'why': '--why', 'free': '--free', 'sheet': '--sheet',
                     'tui': '--tui', 'write': '--write'}
        self.assertEqual(sorted(set(self.bind.VERB_FLAGS)
                                - {'harvest', 'plan'}),
                         sorted(flags_for))
        for game in self.bind.GAMES:
            with self.subTest(game=game):
                obj = built(live(game))
                flags = {s for a in obj.parser()._actions
                         for s in a.option_strings}
                for verb, flag in flags_for.items():
                    self.assertIn(flag, flags, f'{game} {verb}')


class TheJudgementsHaveAHome(unittest.TestCase):
    """Where a game keeps what somebody decided, and how it gets back.

    A judgement is derived from nothing. Delete it and it is gone. So a
    screen that lets you make one has to be able to write it down.
    Unwritten, a promoted action lasts until you press `q`.
    """

    def planners(self):
        return [(g, live(g)) for g in adapter.games()]

    def test_a_game_with_a_hand_written_list_says_where_it_lives(self):
        for game, cls in self.planners():
            with self.subTest(game=game):
                # Named, and not present. `s` on the review screen writes
                # both files, so a game nobody has described has neither.
                # An assertion that they are on disk asserts that the
                # judgements ship with the code.
                self.assertTrue(cls.NEEDS_FILE,
                                f'{game} says nowhere to keep what a '
                                'function is')
                self.assertTrue(cls.BINDS,
                                f'{game} says nowhere to keep where things '
                                'sit')

    def test_every_axis_a_game_plans_is_a_need_like_any_other(self):
        # A tuple per game is `(ident, role, axis)` here and `(name,
        # role, index, inverse, props)` there, and four more shapes. Then
        # nothing draws them on a screen or holds them to a rule.
        for game, cls in self.planners():
            with self.subTest(game=game):
                try:
                    obj = cls()
                    # An axis need out of the game's OWN vocabulary, so
                    # this cannot pass over nothing. Read off whatever
                    # the planner ships, it is vacuous for a game with an
                    # empty needs file.
                    axis = next((a for a in obj.catalogue()
                                 if a.kind == corneeds.AXIS), None)
                    self.assertTrue(axis, f'{game} has no axis to bind')
                    obj.add_need(axis)
                    layout = obj.build()
                except SystemExit:
                    continue        # Nothing harvested on this
                                    # machine.
                # And it is a Placement on a Need, in the one list, with
                # an `OnAxis` slot that says which axis of the control it
                # took. There is no second kind of thing to check.
                self.assertTrue(layout.on_axes, f'{game} plans no axis')
                for p in layout.on_axes:
                    self.assertEqual(corneeds.AXIS, p.need.takes)
                    self.assertIsInstance(p, corneeds.Placement)
                    (slot,) = p.slots
                    self.assertIsInstance(slot[0], corneeds.OnAxis)
                    self.assertTrue(p.need.what)

    def test_a_kind_the_map_has_no_word_for_is_an_error(self):
        # The guard a rename needs. A kind per axis, as `stick-x`,
        # `stick-y` and `twist`, leaves three of the six games asking for
        # a word the map dropped. Each one gets an empty list and drops
        # the axis without a word: MSFS and War Thunder each planned a
        # layout with no aileron, elevator or rudder in it.
        import fake
        dev = fake.device('stick', [fake.button('B', 0)])
        self.assertEqual([], dev.axes(kind='dial'))   # A fair
                                                      # question.
        with self.assertRaises(ValueError) as caught:
            dev.axes(kind='stick-x')
        self.assertIn('stick-x', str(caught.exception))

    def test_every_game_lists_what_is_free_the_same_way(self):
        # One question and three layouts: the same four facts in a
        # different order with different brackets round them. An
        # overridable `free` is what lets two games override it, rather
        # than ask for the one thing the shared one lacks. That one thing
        # is their own numbering for a spare button, and `says_button` is
        # it.
        for game, cls in self.planners():
            with self.subTest(game=game):
                self.assertFalse('free' in vars(cls),
                                 f'{game} lists free controls its own way')

    def test_no_sidecar_keeps_a_screen_of_its_own(self):
        # A sidecar holds the game's own format and the things only that
        # game does, such as naming devices and picking a preset. Offered
        # no shared screen, a sidecar grows a binding table with the same
        # keys over the same three states.
        import glob
        for path in glob.glob(os.path.join(REPO, 'games', '*', '*.py')):
            if os.path.basename(path) in ('plan.py', 'harvest.py',
                                          'plan.py'):
                continue
            with self.subTest(file=os.path.basename(path)):
                with open(path, encoding='utf-8') as f:
                    body = f.read()
                self.assertNotIn('def run_table(', body,
                                 'a second binding screen')

    def test_every_game_opens_the_core_review(self):
        # `review` sits on `Adapter` and not on `Planner`, so every kind
        # of adapter is offered it. Offered none, a game grows a screen of
        # its own with the same keys over the same three states.
        for game, cls in self.planners():
            with self.subTest(game=game):
                self.assertFalse('review' in vars(cls),
                                 f'{game} opens a screen of its own again')

    def test_every_game_builds_the_core_sheet(self):
        # A game that writes its own sheet, with its own template,
        # drifts. The shared one learned to put axes inside their device,
        # to split the free controls by device, and to drop two
        # paragraphs of prose. None of that reaches the copy.
        for game, cls in self.planners():
            with self.subTest(game=game):
                self.assertTrue(hasattr(cls, 'sheet'))
                self.assertFalse('write_sheets' in vars(cls),
                                 f'{game} writes its own kneeboard again')
                # And a game with several sheets of its own says so with
                # a suffix, so both filenames keep the family's spelling.
                # Called on the class and not on an instance: DCS's reads
                # the module it was constructed for.
                self.assertTrue(callable(cls.sheet_suffix))

    def test_the_description_and_the_answer_are_different_files(self):
        # One file for both makes a row say what the function is AND
        # where the allocator put it, with nothing to say which half is
        # which.
        for game, cls in self.planners():
            with self.subTest(game=game):
                if not cls.NEEDS_FILE:
                    continue
                self.assertNotEqual(cls.NEEDS_FILE, cls.BINDS)
                for name in (cls.NEEDS_FILE, cls.BINDS):
                    self.assertNotIn(name, cls.CACHE,
                                     f'{game} lets the harvest write {name}')


class TheCatalogueSaysWhereItCameFrom(unittest.TestCase):
    """The vocabulary screen names the file it is reading.

    A count and nothing else leaves the one question a stale screen raises
    unanswered: which file is this, and is it the one I just
    re-harvested.
    """

    def test_every_game_names_it(self):
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertTrue(live(game).CATALOGUE,
                                f'{game} builds a catalogue from nowhere')

    def test_it_is_a_file_the_planner_actually_reads(self):
        # Against CACHE and not against the directory. A name nothing
        # loads puts a plausible, wrong file on the screen.
        for game in adapter.games():
            with self.subTest(game=game):
                cls = live(game)
                self.assertIn(cls.CATALOGUE, cls.CACHE)


class DroppingTheCache(unittest.TestCase):
    """The one destructive thing the screen does, held to what it may
    reach.

    A harvest runs again. Delete what it wrote and one command brings it
    back. A judgement does not: delete it and it is gone. The two sit in
    the same directory under alike names, and the key that removes the
    first must not reach the second.

    Care is not the mechanism. `CACHE` names what the harvest wrote, and
    `BINDS` is not in it, so the list this walks cannot hold the
    judgements however the walk is written.
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
    """A control's click is a button like the others, and it carries a
    slot like the others.

    A `push` field that each game fills its own way holds a list of Binds
    in one game, a bare Bind in another, and a bare callback string in a
    third. Every writer that walks `p.slots` then asks what it is
    holding: five `isinstance` branches across two games.

    Nothing is wrong with any of the three on its own. They cannot be
    written down together, and that is what a contract is for.
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


class AGameNobodyHasDescribed(unittest.TestCase):
    """A list with nothing on it says so, and says what to type.

    `0 controls proposed, 0 unplaced` reads as a desk with no room on it,
    and not as a game nobody has described. Every DCS module is in that
    state until somebody walks it, and so is a seventh game on the day
    its harvest lands.
    """

    def note(self, game):
        # `Any`. `_needs` is each game's own field, so nothing types
        # against the base class.
        on: typing.Any = built(live(game))
        on._needs = []
        return '\n'.join(on.undescribed_note())

    def test_it_says_nothing_describes_it_yet(self):
        for game in adapter.games():
            with self.subTest(game=game):
                said = self.note(game)
                self.assertIn('Nothing describes', said)
                self.assertIn('no functions to place', said)

    def test_and_names_the_command_that_describes_it(self):
        for game in adapter.games():
            with self.subTest(game=game):
                said = self.note(game)
                self.assertIn(f'./bind-wizard.py {game} tui', said)

    def test_a_game_with_variants_names_the_one_it_is_for(self):
        # DCS lays out one aircraft at a time, so `describe it` says
        # which. No other game has a variant, and for those the game's own
        # title is the thing being described.
        on: typing.Any = built(live('dcs'))
        on._needs = []
        said = '\n'.join(on.undescribed_note())
        self.assertIn(on.subtitle, said,
                      'the sentence does not name the module')
        self.assertIn(f'-a {on.aircraft}', said,
                      'the command to paste does not name the module')
        plain: typing.Any = built(live('x4'))
        plain._needs = []
        self.assertIn(plain.title, '\n'.join(plain.undescribed_note()))


class WhatTheScreenKeptIsWhatReachesTheGame(unittest.TestCase):
    """A writer takes the placements it is handed, and only those.

    The review screen's whole job is to write some of a plan and not the
    rest. A writer that calls `build()` for itself makes that screen
    impossible, and a writer that recomputes the plan from its own results
    file brings back anything you cleared.

    `write_layout` returns the file's whole TEXT, and that is what makes
    this checkable for every game at once. Narrow the layout, and the
    identifier of what was dropped is gone from what would be written.
    """

    def written(self, obj, layout):
        out = []
        for body in obj.write_layout(obj.rows(layout), layout).values():
            if body is adapter.MOVE:
                continue
            out.append(getattr(body, 'text', body))
        return '\n'.join(out)

    def test_a_binding_cleared_on_the_screen_does_not_reach_the_game(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                for action in [a for a in obj.catalogue()
                               if a.kind != corneeds.AXIS][:6]:
                    obj.add_need(action)
                full = obj.build()
                if not full.on_buttons:
                    self.skipTest(f'{game} placed no button here')
                try:
                    whole = self.written(obj, full)
                except SystemExit as e:
                    # The game is running, or its own file is not there.
                    # A fact about this machine, like `built`'s skips.
                    self.skipTest(f'{game}: {e}')
                dropped = full.on_buttons[0]
                # The game's own word for the control it sat on, which is
                # what a binding writes. Not the action id: a format whose
                # template lists every function, as Elite's base preset
                # does, carries the id whether anything is bound to it or
                # not. Counting ids proves nothing there.
                says = [obj.says_slot(dropped.role, slot,
                                      full.devices[dropped.role])
                        for slot, _p in dropped.slots]
                says = [one for one in says if one]
                if not says:
                    self.skipTest(f'{game} has no word for a button')
                before = sum(whole.count(one) for one in says)
                self.assertTrue(
                    before, f'{game} wrote none of {says} even when it was '
                            'placed, so clearing it proves nothing')
                kept = self.written(
                    obj, full.but([p for p in full.placed
                                   if p is not dropped]))
                self.assertLess(
                    sum(kept.count(one) for one in says), before,
                    f'{game} still writes {says} after the screen cleared '
                    'the binding on it')


class EveryGameHasACatalogue(unittest.TestCase):
    """The vocabulary, in one shape, from all six.

    This does NOT assert that a game has categories, modes or ranks. Four
    of the six have no categories and X4 counts nothing, and a test that
    demanded them pushes somebody into deriving one.
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
        # A blank row is unusable. The fallback to the id is why that
        # cannot happen, however thin a cache is.
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertTrue(all(a.name for a in self.catalogue(game)))

    def test_it_holds_what_the_hand_written_list_binds(self):
        # This is the point. The curated list is a slice of the
        # catalogue, and a miss means the translation dropped a section of
        # the cache.
        # From the filesystem, and not from a list written here. A game
        # that exists only in a table is a game the table can be wrong
        # about, so `adapter.games()` reads the directory.
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                # `unknown()` is that comparison, in the core, and
                # `main()` stops on it. A second copy here read a slot as
                # a string, and a slot holds `Bind`, so it compared the
                # empty set with the empty set and passed.
                self.assertEqual([], obj.unknown())


class TheDefaultVerb(unittest.TestCase):
    """`./bind-wizard.py x4` with no verb opens the screen.

    It printed the plan, which is the thing you read once to see whether
    the allocator got it right. The screen is the thing you come back to.
    """

    def setUp(self):
        self.bind = bind()

    def test_a_bare_game_opens_the_review(self):
        """`tui`, and nothing is asked to agree.

        A lookup in the game's own row, with a fallback to `plan`, has no
        row to disagree with it: every game answers the same interface,
        and no game is in the fallback's state. The verb is a constant in
        `main`, and this checks that a bare game reaches the screen.
        """
        for game in self.bind.GAMES:
            with self.subTest(game=game):
                ran = []
                with mock.patch.object(self.bind, 'which_desk',
                                       lambda rest: (None, None)), \
                     mock.patch.object(self.bind.subprocess, 'call',
                                       lambda cmd, cwd=None, env=None:
                                       ran.append(cmd) or 0), \
                     mock.patch.object(sys, 'argv',
                                       ['bind-wizard.py', game]):
                    self.bind.main()
                (cmd,) = ran
                self.assertIn('--tui', cmd)
                self.assertTrue(cmd[1].endswith(
                    os.path.join('games', game, 'plan.py')), cmd[1])


class RunDirectly(unittest.TestCase):
    """Every script with a `__main__`, run on its own.

    Nothing else here starts one as `__main__`. `adapter.load` imports the
    module and never reaches its `main()`, and the front door is checked
    as a verb table. So a script that calls something the core has moved
    is invisible to the whole suite.

    That has happened. `build()` moved from a function to a method, a
    sidecar went on calling `plan.build()`, and the script was dead on
    the first line that needed a plan. `--write` was fine, because it
    hands the writer a layout, and 168 tests stayed green. A type checker
    found it months later.

    `test_no_writer_reaches_build` is the opposite rule, and the two do
    not overlap. A WRITER may never fetch a plan of its own, because the
    review screen's whole job is to write some of one. A script started on
    its own has nobody to be handed a plan by, so it must.

    A game is two scripts, `harvest.py` and `plan.py`, and both answer on
    their own. This starts both.
    """

    def ran(self, game, script, *args):
        """The script, in its own interpreter, from its own directory.
        That is how `bind-wizard.py` runs it."""
        where = os.path.join(REPO, 'games', game)
        return subprocess.run([sys.executable, script, *args],
                              cwd=where, capture_output=True, text=True,
                              timeout=300)

    def test_a_planner_runs_as_its_own_script(self):
        for game in adapter.games():
            with self.subTest(game=game):
                # The same skip the rest of this file takes on a bare
                # clone. No harvest, or no device map, is a fact about
                # this machine and not about the code.
                built(live(game))
                done = self.ran(game, adapter.planner(game), '--why')
                self.assertEqual(0, done.returncode,
                                 done.stderr.strip()[-500:])

    @unittest.skipUnless('warthunder' in adapter.games(),
                         'war thunder is not in games/ yet')
    def test_the_sidecar_that_owns_a_format_runs_as_its_own_script(self):
        # War Thunder's, because it is the one that broke, and the one
        # game left with a sidecar. Every other game's format is read by
        # its `harvest.py` and written by its `plan.py`.
        built(live('warthunder'))
        done = self.ran('warthunder', 'write.py', '--dry-run')
        said = done.stderr.strip() + done.stdout.strip()
        if 'machine.blk' in said and 'no controls' in said:
            # The same kind of skip as `live`. What the game wrote in its
            # own configuration is a fact about this machine. The sidecar
            # reads that file to know which joystick slot is which, so
            # without it a dry run has nothing to be dry about.
            raise unittest.SkipTest('the installed machine.blk has no '
                                    'controls{} block')
        self.assertEqual(0, done.returncode, done.stderr.strip()[-500:])


if __name__ == '__main__':
    unittest.main()


class WhichDeskAPlannerIsFor(unittest.TestCase):
    """Every planner takes it, because every planner needs it. Which desk
    this is decides which device is the stick, and how far each control
    is."""

    def test_every_planner_takes_the_flag(self):
        for game in adapter.games():
            with self.subTest(game=game):
                obj = built(live(game))
                flags = {s for a in obj.parser()._actions
                         for s in a.option_strings}
                self.assertIn('--desk', flags)

    def test_it_says_the_same_thing_as_the_environment(self):
        was = os.environ.get('SIM_DEVICE_PROFILE')
        try:
            os.environ.pop('SIM_DEVICE_PROFILE', None)
            obj = built(live(adapter.games()[0]))
            args = obj.parser().parse_args(['--desk', 'Somewhere'])
            self.assertEqual('Somewhere', args.desk)
        finally:
            if was is not None:
                os.environ['SIM_DEVICE_PROFILE'] = was

    def test_saying_it_on_the_command_line_is_enough(self):
        # With nothing in the environment and more than one desk on file,
        # the flag is the only thing between a planner and the map's
        # refusal to guess.
        from core import devmap
        rigs = devmap.load().load_profiles()
        if len(rigs) < 2:
            raise unittest.SkipTest('one desk on file, so nothing to pick')
        game = adapter.games()[0]
        built(live(game))
        env = {k: v for k, v in os.environ.items()
               if k != 'SIM_DEVICE_PROFILE'}
        done = subprocess.run(
            [sys.executable, adapter.planner(game), '--desk', rigs[0].name],
            cwd=os.path.join(REPO, 'games', game), env=env,
            capture_output=True, text=True, timeout=300)
        self.assertEqual(0, done.returncode, done.stderr.strip()[-400:])

    def test_the_message_names_both_ways_of_saying_it(self):
        from core import devmap
        dm = devmap.load()

        def two(name=None):
            raise SystemExit('more than one profile')

        with mock.patch.object(dm, 'profile', two):
            with self.assertRaises(SystemExit) as caught:
                devmap.by_role()
        self.assertIn('--desk', str(caught.exception))


class TheLauncherAsking(unittest.TestCase):
    """`./bind-wizard.py` asks which desk, and only where somebody is
    there to answer."""

    def setUp(self):
        self.bind = adapter.from_file('bind_under_test',
                                      os.path.join(REPO, 'bind-wizard.py'),
                                      argv=['bind-wizard.py'])

    def rigs(self, *names):
        dm = __import__('core.devmap', fromlist=['devmap']).load()
        return [dm.Profile({'name': n, 'device': [
            {'slug': 'a-stick', 'role': 'stick'}]}, f'<{n}>') for n in names]

    def asked(self, rest=(), env=None, names=('Biurko', 'Fotel')):
        """(did it put a menu up, what it answered).

        With a terminal faked. Without one, every call here returns None
        for the same reason and the test says nothing.
        """
        dm = __import__('core.devmap', fromlist=['devmap']).load()
        put_up = []
        with mock.patch.object(sys.stdin, 'isatty', lambda: True), \
             mock.patch.object(sys.stderr, 'isatty', lambda: True), \
             mock.patch.object(dm, 'load_profiles',
                               lambda: self.rigs(*names)), \
             mock.patch.object(self.bind, 'pick_desk',
                               lambda rigs, where:
                               put_up.append(rigs) or ('Picked', where)), \
             mock.patch.dict(os.environ, env or {}, clear=True):
            got, _where = self.bind.which_desk(list(rest))
        return bool(put_up), got

    def test_with_two_desks_and_nothing_said_it_asks(self):
        self.assertEqual((True, 'Picked'), self.asked())

    def test_a_desk_said_on_the_command_line_is_not_asked_about(self):
        self.assertEqual((False, None), self.asked(['--desk', 'Biurko']))
        self.assertEqual((False, None), self.asked(['--desk=Biurko']))

    def test_nor_one_in_the_environment(self):
        self.assertEqual((False, None),
                         self.asked(env={'SIM_DEVICE_PROFILE': 'Biurko'}))

    def test_one_desk_is_not_a_question(self):
        self.assertEqual((False, None), self.asked(names=('Biurko',)))

    def test_and_nothing_is_asked_with_nobody_there(self):
        # A pipe, a script, or CI. The planner's own message names the
        # ways of saying it, and a prompt nobody can answer is a hang.
        dm = __import__('core.devmap', fromlist=['devmap']).load()
        put_up = []
        with mock.patch.object(sys.stdin, 'isatty', lambda: False), \
             mock.patch.object(dm, 'load_profiles',
                               lambda: self.rigs('Biurko', 'Fotel')), \
             mock.patch.object(self.bind, 'pick_desk',
                               lambda rigs, where: put_up.append(rigs)), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual((None, None), self.bind.which_desk([]))
        self.assertEqual([], put_up)


    def test_backing_out_picks_nothing(self):
        # ESC on that menu means "I did not say". It does not mean "the
        # first one". A menu that picks for you is how a layout comes out
        # for the wrong stick.
        dm = __import__('core.devmap', fromlist=['devmap']).load()
        with mock.patch.object(__import__('curses'), 'wrapper',
                               lambda run: (None, None)):
            self.assertEqual((None, None),
                             self.bind.pick_desk(self.rigs('Biurko', 'Fotel'),
                                                 '/somewhere'))

    def test_a_line_says_the_desk_and_what_is_on_it(self):
        one, two = self.rigs('Biurko', 'Fotel')
        two.devices = []
        said = self.bind.desk_items([one, two])
        self.assertIn('Biurko', said[0])
        self.assertIn('stick', said[0])
        self.assertIn('nothing on it', said[1])

    def test_the_names_line_up(self):
        said = self.bind.desk_items(self.rigs('A', 'A much longer name'))
        self.assertEqual(*[len(t) - len(t.lstrip()) for t in said])
        self.assertEqual(*[t.index('stick') for t in said])


class TheGameList(unittest.TestCase):
    """With no arguments the launcher ends in a game, or in nothing.

    A launcher that ends in the table and stops leaves you typing the
    game you have just read.
    """

    def setUp(self):
        self.bind = adapter.from_file('bind_under_test4',
                                      os.path.join(REPO, 'bind-wizard.py'),
                                      argv=['bind-wizard.py'])

    def test_a_line_says_the_word_you_type_and_what_it_is(self):
        said = self.bind.game_items()
        self.assertEqual(len(self.bind.GAMES), len(said))
        for line, game in zip(said, sorted(self.bind.GAMES)):
            with self.subTest(game=game):
                self.assertTrue(line.startswith(game))
                self.assertIn(self.bind.GAMES[game]['title'], line)

    def test_the_titles_line_up(self):
        said = self.bind.game_items()
        at = {line.index(self.bind.GAMES[game]['title'])
              for line, game in zip(said, sorted(self.bind.GAMES))}
        self.assertEqual(1, len(at))

    def test_nothing_is_drawn_with_nobody_there(self):
        # A pipe, a script, or CI. The table is the whole answer, and
        # this suite is one of the things that reads it.
        for stdin, stdout in ((False, True), (True, False)):
            with self.subTest(stdin=stdin, stdout=stdout):
                with mock.patch.object(sys.stdin, 'isatty',
                                       lambda: stdin), \
                     mock.patch.object(sys.stdout, 'isatty',
                                       lambda: stdout):
                    self.assertIsNone(self.bind.pick_game())

    def test_backing_out_picks_nothing(self):
        # ESC means "I did not say", as it does on the desk list.
        self.assertIsNone(self.chose(None))

    def test_what_it_picks_is_a_game_the_launcher_can_run(self):
        for i, game in enumerate(sorted(self.bind.GAMES)):
            with self.subTest(game=game):
                self.assertEqual(game, self.chose(i))

    def chose(self, row):
        """What `pick_game` answers when that row is the one picked."""
        with mock.patch.object(sys.stdin, 'isatty', lambda: True), \
             mock.patch.object(sys.stdout, 'isatty', lambda: True), \
             mock.patch.object(__import__('curses'), 'wrapper',
                               lambda run: row):
            return self.bind.pick_game()


class WhereTheDesksWereRead(unittest.TestCase):
    """Shown, and changeable. A desk is a fact about a room, and somebody
    who keeps these files somewhere synced says where they are."""

    def setUp(self):
        self.bind = adapter.from_file('bind_under_test2',
                                      os.path.join(REPO, 'bind-wizard.py'),
                                      argv=['bind-wizard.py'])

    def test_a_path_under_home_is_said_the_way_you_would_say_it(self):
        home = os.path.expanduser('~')
        self.assertEqual('~/desks',
                         self.bind.said_path(os.path.join(home, 'desks')))

    def test_and_one_outside_it_is_left_alone(self):
        self.assertEqual('/etc/desks', self.bind.said_path('/etc/desks'))

    def test_a_home_shaped_prefix_is_not_a_home(self):
        home = os.path.expanduser('~')
        self.assertEqual(home + 'x', self.bind.said_path(home + 'x'))

    def test_the_last_row_is_not_a_desk(self):
        dm = __import__('core.devmap', fromlist=['devmap']).load()
        rigs = [dm.Profile({'name': n, 'device': []}, f'<{n}>')
                for n in ('A', 'B')]
        self.assertEqual(2, len(self.bind.desk_items(rigs)))
        self.assertNotIn(self.bind.ELSEWHERE, self.bind.desk_items(rigs))


class PointingAtAnotherDirectory(unittest.TestCase):
    """The whole picker loop, driven against a screen that is not one."""

    def setUp(self):
        self.bind = adapter.from_file('bind_under_test3',
                                      os.path.join(REPO, 'bind-wizard.py'),
                                      argv=['bind-wizard.py'])
        self.dm = __import__('core.devmap', fromlist=['devmap']).load()

    def rigs(self, *names):
        return [self.dm.Profile({'name': n, 'device': []}, f'<{n}>')
                for n in names]

    def run_picker(self, keys, rigs, where='/somewhere'):
        # `setup` as well. It asks curses to hide the cursor and start
        # colour, and there is no terminal here to ask.
        import curses
        from core import tui as ctui
        from test_box import Keyed
        scr = Keyed(keys)
        with mock.patch.object(curses, 'wrapper', lambda run: run(scr)), \
             mock.patch.object(ctui, 'setup',
                               lambda s: ctui.Tui(s, ctui.Theme(False))):
            return self.bind.pick_desk(rigs, where), scr

    def test_the_blank_before_the_last_row_is_stepped_over(self):
        # It is not a desk, and not a place to read them from, so `↵
        # choose` on it means nothing.
        said = {}
        from core import tui as ctui
        import curses
        from test_box import Keyed
        with mock.patch.object(curses, 'wrapper', lambda run: run(Keyed([27]))), \
             mock.patch.object(ctui, 'setup',
                               lambda s: ctui.Tui(s, ctui.Theme(False))), \
             mock.patch.object(ctui.Tui, 'choose',
                               lambda self, title, lines, **kw:
                               said.update(kw, rows=lines) or None):
            self.bind.pick_desk(self.rigs('A', 'B'), '/somewhere')
        blank, = [n for n, (_tone, t) in enumerate(said['rows']) if not t]
        self.assertEqual([blank], list(said['skip']))
        self.assertEqual(self.bind.ELSEWHERE, said['rows'][-1][1])

    def test_picking_a_desk_hands_back_where_it_came_from(self):
        got, _scr = self.run_picker([10], self.rigs('A', 'B'))
        self.assertEqual(('A', '/somewhere'), got)

    def test_the_last_row_asks_for_a_directory(self):
        import curses
        here = os.path.dirname(os.path.abspath(__file__))
        typed = [curses.KEY_DOWN] * 2 + [10]        # down to `somewhere else`
        typed += [8] * 40 + [ord(c) for c in here] + [10, 27]
        got, _scr = self.run_picker(typed, self.rigs('A', 'B'))
        self.assertEqual((None, here), got)

    def test_return_on_the_path_you_came_in_with_changes_nothing(self):
        # It reads as backing out of the question. Taken as an answer, it
        # drops you into the planner with no desk chosen.
        #
        # Started from a directory that EXISTS, on purpose. From one that
        # does not, the `is it a directory` check catches it first and the
        # test passes whatever this does.
        import curses
        here = os.path.dirname(os.path.abspath(__file__))
        typed = [curses.KEY_DOWN] * 2 + [10]        # Down to `somewhere
                                                    # else`.
        typed += [10]                                # RETURN, nothing
                                                     # typed.
        typed += [curses.KEY_UP] * 2 + [10]          # Back up, pick the
                                                     # first.
        got, _scr = self.run_picker(typed, self.rigs('A', 'B'), where=here)
        self.assertEqual(('A', here), got)

    def test_a_directory_that_is_not_one_is_said_and_not_taken(self):
        import curses
        typed = [curses.KEY_DOWN] * 2 + [10]
        typed += [8] * 40 + [ord(c) for c in '/no/such/place'] + [10]
        typed += [27, 27]                    # Dismiss the notice, then
                                             # leave.
        got, scr = self.run_picker(typed, self.rigs('A', 'B'))
        self.assertEqual((None, None), got)
        self.assertIn('/no/such/place', '\n'.join(scr.frames))

    def test_no_desks_at_all_is_a_question(self):
        # One desk answers itself. None is not the same thing. The files
        # may be somewhere nothing has told this to look.
        dm = self.dm
        put_up = []
        with mock.patch.object(sys.stdin, 'isatty', lambda: True), \
             mock.patch.object(sys.stderr, 'isatty', lambda: True), \
             mock.patch.object(dm, 'load_profiles', lambda: []), \
             mock.patch.object(self.bind, 'pick_desk',
                               lambda rigs, where:
                               put_up.append(where) or (None, None)), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.bind.which_desk([])
        self.assertEqual([dm.PROFILES], put_up)

    def test_and_one_desk_answers_itself(self):
        dm = self.dm
        put_up = []
        with mock.patch.object(sys.stdin, 'isatty', lambda: True), \
             mock.patch.object(sys.stderr, 'isatty', lambda: True), \
             mock.patch.object(dm, 'load_profiles',
                               lambda: self.rigs('Only one')), \
             mock.patch.object(self.bind, 'pick_desk',
                               lambda rigs, where: put_up.append(where)), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual((None, None), self.bind.which_desk([]))
        self.assertEqual([], put_up)

    def test_a_directory_you_picked_reaches_the_planner(self):
        # Through the environment, because the planner is another process
        # and the map reads it there.
        said = {}
        with mock.patch.object(self.bind, 'which_desk',
                               lambda rest: ('Biurko', '/elsewhere')), \
             mock.patch.object(self.bind.subprocess, 'call',
                               lambda cmd, cwd=None, env=None:
                               said.update(env or {}) or 0), \
             mock.patch.object(sys, 'argv', ['bind-wizard.py', 'x4', 'why']):
            self.bind.main()
        self.assertEqual('Biurko', said.get('SIM_DEVICE_PROFILE'))
        self.assertEqual('/elsewhere', said.get('SIM_DEVICE_PROFILES'))

    def test_with_no_desks_at_all_it_still_offers_to_look_elsewhere(self):
        _got, scr = self.run_picker([27], [])
        self.assertIn(self.bind.ELSEWHERE, '\n'.join(scr.frames))


class WhichTemplateAGameIsLaidOutTo(unittest.TestCase):
    """Three places can say it, and they are read in one order.

        --overlay NAME   this run, whatever is on file. `none` too.
        the binds file   what `o` last kept, per game
        `OVERLAY`        the planner's own declaration

    The flag wins, so one run under another template costs nothing that
    is written down. The file beats the declaration, because which
    template you want is a judgement and the declaration is source.
    """

    def setUp(self):
        corneeds.OVERLAY = None

    def toy(self, declared):
        @typing.final
        class Toy(adapter.Planner):
            game = 'x4'                 # a game `overlays/` has rules for
            title = 'Toy'
            OVERLAY = declared
            BINDS = 'binds.json'
            NEEDS_FILE = 'needs.json'

            @typing.override
            def write_layout(self, rows, layout):
                return {}

        return Toy()

    def chosen(self, flag=None, declared='by-hand', filed=''):
        """Which template `overlay()` settles on, by its file's stem.

        `corneeds.filed_overlay` is patched rather than a file written,
        because `Adapter.filed_overlay` is final and the thing under test
        is the order the three sources are read in.
        """
        with mock.patch.object(adapter.corneeds, 'filed_overlay',
                               lambda d, f: filed), \
             mock.patch.object(sys, 'stderr', io.StringIO()):
            got = self.toy(declared).overlay(flag)
        return got.called if got is not None else ''

    def test_the_file_beats_the_declaration(self):
        self.assertEqual('f-18', self.chosen(filed='f-18'))

    def test_the_declaration_answers_where_the_file_says_nothing(self):
        self.assertEqual('by-hand', self.chosen())

    def test_the_flag_beats_the_file(self):
        # One run under another template, and nothing written down
        # changes. `o` on the screen is how a lasting change is made.
        self.assertEqual('by-hand', self.chosen('by-hand', filed='f-18'))

    def test_the_flag_can_ask_for_no_template_over_a_file(self):
        # `--overlay none` is an answer and not an absent one. Read as
        # "ask the file", it could not be given at all.
        self.assertEqual('', self.chosen('none', filed='f-18'))

    def test_a_game_with_no_binds_file_asks_nothing(self):
        @typing.final
        class NoFile(adapter.Planner):
            game = 'x4'
            title = 'No file'
            OVERLAY = 'by-hand'

            @typing.override
            def write_layout(self, rows, layout):
                return {}

        self.assertEqual('', NoFile().filed_overlay())

    def test_every_game_on_disk_reads_its_own(self):
        # '' for all four today, because none was saved with the field.
        # Neither that nor a missing file is a fault, and both mean "ask
        # the declaration".
        for game in adapter.games():
            with self.subTest(game=game):
                self.assertIsInstance(built(live(game)).filed_overlay(), str)

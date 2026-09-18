"""What a backup has to guarantee before it counts as one.

Every rule here exists because a writer in this repo got it wrong: copies that
landed in the folder the game reads, a run folder that ate the state it was
supposed to hold, a restore that only worked while the copy sat next to the
original.
"""

import os
import shutil
import tempfile
import time
import unittest

import fake                                                  # noqa: F401
from core import backup


class Temp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = os.path.join(self.tmp, 'store')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self, name, text, subdir=''):
        d = os.path.join(self.tmp, subdir) if subdir else self.tmp
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path

    def read(self, path):
        return open(path, encoding='utf-8').read()


class RoundTrip(Temp):
    def test_a_saved_file_comes_back_exactly(self):
        p = self.file('config.xml', 'original')
        backup.save('g', p, into=self.store)
        self.file('config.xml', 'rewritten')
        _dir, done = backup.restore('g', into=self.store)
        self.assertEqual([p], done)
        self.assertEqual('original', self.read(p))

    def test_nothing_is_left_beside_the_original(self):
        p = self.file('config.xml', 'original')
        backup.save('g', p, into=self.store)
        self.assertEqual(['config.xml'],
                         [f for f in os.listdir(self.tmp) if f != 'store'])

    def test_a_file_that_does_not_exist_yet_makes_no_run(self):
        # A writer creating a file for the first time has nothing to back up,
        # and an empty run folder would be a lie in `runs()`.
        where, saved = backup.save(
            'g', os.path.join(self.tmp, 'never'), into=self.store)
        self.assertIsNone(where)
        self.assertEqual([], saved)
        self.assertEqual([], backup.runs('g', into=self.store))

    def test_a_folder_without_a_manifest_is_not_one_of_ours(self):
        os.makedirs(os.path.join(self.store, 'g', '20260101-000000'))
        self.assertEqual([], backup.runs('g', into=self.store))


class Names(Temp):
    def test_two_files_of_the_same_name_are_told_apart(self):
        # War Thunder writes several machine.blk, one per account directory.
        a = self.file('machine.blk', 'A', subdir='last/production')
        b = self.file('machine.blk', 'B', subdir='12345/production')
        _dir, saved = backup.save('wt', a, b, into=self.store)
        self.assertEqual(2, len(set(n for n, _o in saved)))

    def test_and_each_goes_back_to_its_own_directory(self):
        a = self.file('machine.blk', 'A', subdir='last/production')
        b = self.file('machine.blk', 'B', subdir='12345/production')
        backup.save('wt', a, b, into=self.store)
        self.file('machine.blk', 'X', subdir='last/production')
        self.file('machine.blk', 'X', subdir='12345/production')
        backup.restore('wt', into=self.store)
        self.assertEqual('A', self.read(a))
        self.assertEqual('B', self.read(b))

    def test_a_name_only_grows_as_far_as_it_has_to(self):
        # Flattening the whole path would name every file after its absolute
        # location and make the folder unreadable.
        a = self.file('one.cfg', 'A')
        b = self.file('two.cfg', 'B')
        _dir, saved = backup.save('g', a, b, into=self.store)
        self.assertEqual({'one.cfg', 'two.cfg'}, {n for n, _o in saved})


class Runs(Temp):
    def test_one_stamp_groups_several_calls_into_one_run(self):
        # BMS writes two files under `./bind bms write`.
        a = self.file('a.cfg', 'A')
        b = self.file('b.cfg', 'B')
        when = backup.stamp()
        backup.save('g', a, into=self.store, when=when)
        backup.save('g', b, into=self.store, when=when)
        runs = backup.runs('g', into=self.store)
        self.assertEqual(1, len(runs))
        self.assertEqual(2, len(runs[0][2]))

    def test_a_run_holds_the_state_from_before_the_run(self):
        # DCS's --reseed rewrites one results file once per aircraft. Copying
        # it again on the second aircraft overwrote the only copy of the state
        # anybody wanted back.
        p = self.file('results.json', 'pristine')
        when = backup.stamp()
        backup.save('dcs', p, into=self.store, when=when)
        self.file('results.json', 'after the first aircraft')
        backup.save('dcs', p, into=self.store, when=when)
        _stamp, path, files = backup.runs('dcs', into=self.store)[0]
        self.assertEqual(1, len(files), 'the file is recorded once')
        self.assertEqual('pristine',
                         self.read(os.path.join(path, files[0][0])))

    def test_separate_runs_keep_separate_history(self):
        p = self.file('thing.cfg', 'v1')
        backup.save('g', p, into=self.store)
        self.file('thing.cfg', 'v2')
        time.sleep(1.1)                 # the stamp is second-resolution
        backup.save('g', p, into=self.store)
        runs = backup.runs('g', into=self.store)
        self.assertEqual(2, len(runs))
        self.assertEqual(['v1', 'v2'],
                         [self.read(os.path.join(d, f[0][0]))
                          for _s, d, f in runs])

    def test_restore_takes_the_newest_run_by_default(self):
        p = self.file('thing.cfg', 'v1')
        backup.save('g', p, into=self.store)
        self.file('thing.cfg', 'v2')
        time.sleep(1.1)
        backup.save('g', p, into=self.store)
        self.file('thing.cfg', 'v3')
        backup.restore('g', into=self.store)
        self.assertEqual('v2', self.read(p))

    def test_restore_takes_an_older_run_by_stamp_prefix(self):
        p = self.file('thing.cfg', 'v1')
        backup.save('g', p, into=self.store)
        first = backup.runs('g', into=self.store)[0][0]
        self.file('thing.cfg', 'v2')
        time.sleep(1.1)
        backup.save('g', p, into=self.store)
        backup.restore('g', first, into=self.store)
        self.assertEqual('v1', self.read(p))

    def test_restoring_nothing_is_an_error_and_not_a_silence(self):
        with self.assertRaises(SystemExit):
            backup.restore('g', into=self.store)


class Moving(Temp):
    def test_a_moved_file_leaves_the_game_folder(self):
        # BMS's axismapping.dat has to be GONE for the game to rebuild it.
        p = self.file('axismapping.dat', 'binary')
        _dir, saved = backup.save('bms', p, into=self.store, move=True)
        self.assertFalse(os.path.exists(p))
        self.assertEqual(1, len(saved))

    def test_a_move_onto_an_existing_copy_keeps_the_older_one(self):
        p = self.file('axismapping.dat', 'first')
        when = backup.stamp()
        backup.save('bms', p, into=self.store, move=True, when=when)
        self.file('axismapping.dat', 'second')
        where, saved = backup.save('bms', p, into=self.store, move=True,
                                   when=when)
        self.assertFalse(os.path.exists(p), 'it still had to leave')
        self.assertEqual('first',
                         self.read(os.path.join(where, 'axismapping.dat')))
        self.assertEqual('second',
                         self.read(os.path.join(where, saved[0][0])))


class Where(Temp):
    def test_the_argument_wins_over_the_environment(self):
        os.environ['SIM_BIND_BACKUPS'] = '/nowhere'
        try:
            self.assertEqual(self.store, backup.root(self.store))
        finally:
            del os.environ['SIM_BIND_BACKUPS']

    def test_the_environment_wins_over_the_repo(self):
        os.environ['SIM_BIND_BACKUPS'] = self.store
        try:
            self.assertEqual(self.store, backup.root())
        finally:
            del os.environ['SIM_BIND_BACKUPS']

    def test_the_default_is_inside_the_repo(self):
        self.assertEqual('backups', os.path.basename(backup.DEFAULT))
        self.assertTrue(os.path.isdir(os.path.dirname(backup.DEFAULT)))

    def test_a_tilde_is_expanded(self):
        self.assertTrue(backup.root('~/somewhere').startswith(
            os.path.expanduser('~')))

    def test_the_flag_lands_on_the_name_every_writer_reads(self):
        # Six writers pass `args.backup_dir` straight through. Renaming the
        # flag here breaks all of them at once, with an AttributeError a long
        # way from the cause.
        import argparse
        p = argparse.ArgumentParser()
        action = backup.add_argument(p, 'x4')
        self.assertEqual('backup_dir', action.dest)
        self.assertIsNone(action.default,
                          'a default here would shadow SIM_BIND_BACKUPS')
        self.assertIsNone(p.parse_args([]).backup_dir)
        self.assertEqual('/tmp/x',
                         p.parse_args(['--backup-dir', '/tmp/x']).backup_dir)


if __name__ == '__main__':
    unittest.main()

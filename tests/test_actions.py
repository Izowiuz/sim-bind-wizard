"""The one shape a game action takes.

`core/actions.py` is a record and two functions, so what is worth pinning is
the part that is a decision rather than a field: that nothing optional is
invented to fill a gap, and that the ordering a screen leans on still holds
for a game that counts nothing.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core.actions import (Action, Bind, PRESS, RELEASE,        # noqa: E402
                          by_id, dump, dump_binds, grouped, read,
                          read_binds)


class TheBind(unittest.TestCase):
    """What sits on one button, in a shape the core can read.

    A payload used to be whatever a game felt like -- a BMS callback, a
    War Thunder `(air, heli)` pair, an X4 `(kind, id)` per context -- and
    `core` carried it blindly, which is why every screen had to hand it
    back to the game to be turned into words. A `Bind` names an action the
    catalogue knows, so the core can answer for itself.
    """

    def test_it_is_a_press_unless_it_says_otherwise(self):
        # Five of the six games never say otherwise; BMS says it twice.
        self.assertEqual(PRESS, Bind('SimGear').edge)

    def test_release_is_the_other_half_of_one_binding(self):
        # `SimDeselectOverride` is not a second mode of the switch -- it is
        # what that switch does when you let go of it.
        b = Bind('SimDeselectOverride', edge=RELEASE)
        self.assertEqual(RELEASE, b.edge)
        self.assertNotEqual(Bind('SimDeselectOverride'), b)

    def test_two_binds_of_one_action_on_one_edge_are_the_same_bind(self):
        self.assertEqual(Bind('ID_GEAR'), Bind('ID_GEAR'))
        self.assertEqual(1, len({Bind('ID_GEAR'), Bind('ID_GEAR')}))

    def test_an_edge_nobody_recognises_is_refused(self):
        # A typo here would be written into a game's config and discovered
        # in the air, so it is refused where it is written instead.
        with self.assertRaises(ValueError):
            Bind('ID_GEAR', edge='hold')

    def test_it_resolves_against_a_catalogue(self):
        cat = by_id([Action('ID_GEAR', 'Toggle gear')])
        self.assertEqual('Toggle gear', Bind('ID_GEAR').named(cat))

    def test_an_action_the_catalogue_lost_still_answers(self):
        # A harvest after a game patch can drop an id somebody bound. The
        # row has to say something, and the id is better than a blank.
        self.assertEqual('ID_GONE', Bind('ID_GONE').named({}))


class TheRecord(unittest.TestCase):

    def test_a_name_falls_back_to_the_id(self):
        # X4 and Elite compute the name from the id, and War Thunder already
        # degrades to it on a thin cache, so this is the family's own habit.
        self.assertEqual('KEY_GEAR', Action('KEY_GEAR').name)

    def test_nothing_optional_is_invented(self):
        # Four of the six ship no categories and X4 counts nothing. A
        # derived stand-in would be read as a fact by the next person.
        a = Action('KEY_GEAR')
        self.assertIsNone(a.category)
        self.assertIsNone(a.mode)
        self.assertEqual(0, a.rank)

    def test_identity_is_the_id(self):
        # Two records for one id must not become two rows.
        self.assertEqual(Action('X', 'one'), Action('X', 'two'))
        self.assertEqual(1, len({Action('X', 'one'), Action('X', 'two')}))


class Grouping(unittest.TestCase):

    def test_no_categories_means_one_unnamed_group(self):
        got = grouped([Action('A'), Action('B')])
        self.assertEqual(1, len(got))
        self.assertIsNone(got[0][0])

    def test_the_unnamed_group_sorts_last(self):
        got = grouped([Action('A'), Action('B', category='Panel')])
        self.assertEqual(['Panel', None], [c for c, _a in got])

    def test_inside_a_group_the_most_bound_come_first(self):
        got = grouped([Action('rare', rank=1), Action('common', rank=90)])
        self.assertEqual(['common', 'rare'], [a.id for a in got[0][1]])

    def test_with_no_ranking_the_order_is_at_least_stable(self):
        # X4 counts nothing, so every rank is 0 and the id decides. A screen
        # whose rows move between runs is one you cannot learn.
        ids = ['INPUT_ACTION_B', 'INPUT_ACTION_A', 'INPUT_STATE_C']
        got = grouped([Action(i) for i in ids])
        self.assertEqual(sorted(ids), [a.id for a in got[0][1]])

    def test_by_id_keys_on_the_id(self):
        self.assertEqual({'A', 'B'}, set(by_id([Action('A'), Action('B')])))


class BindsOnDisk(unittest.TestCase):
    """A bind, written down and read back.

    What a need binds has lived in a Python literal since the first commit,
    so it has never had to survive a round trip. It does now: the judgements
    leave the source, and a bind that comes back subtly different is a
    binding the game will accept and nobody asked for.
    """

    def test_a_plain_press_writes_only_its_action(self):
        self.assertEqual([{'action': 'ID_GEAR'}], dump_binds([Bind('ID_GEAR')]))

    def test_the_other_half_of_a_binding_survives(self):
        # Two of the family's 63 BMS bindings are a press and a release of
        # one switch. A release that came back a press would fire on the
        # way down and never let go.
        (back,) = read_binds(dump_binds([Bind('SimDeselect', edge=RELEASE)]))
        self.assertEqual(RELEASE, back.edge)

    def test_the_file_a_binding_belongs_in_survives(self):
        # MSFS alone cannot read this off the id: which of its two
        # profiles a binding goes into was chosen by whoever wrote it.
        (back,) = read_binds(dump_binds([Bind('KEY_X', mode='heli')]))
        self.assertEqual('heli', back.mode)

    def test_a_slot_keeps_its_order(self):
        # A slot is a list and the order is which button it lands on.
        ids = ['C', 'A', 'B']
        got = read_binds(dump_binds([Bind(i) for i in ids]))
        self.assertEqual(ids, [b.action for b in got])


class OnDisk(unittest.TestCase):
    """The shape a harvest writes and a planner reads.

    The record already existed and already had six producers -- every
    `catalogue()` builds one. What it had no file, so the translating
    happened on the way OUT of the cache, once per game, in six places that
    could drift. Writing the record itself moves that to the way IN, where
    the game's own format is already being read anyway.

    Nothing optional is written. Four of the six ship no categories and X4
    counts nothing, so a file full of `"category": null` would be three
    thousand lines saying the same nothing -- and a reader that has to cope
    with a missing key anyway gains nothing from being told.
    """

    def test_a_bare_action_writes_only_what_it_has(self):
        self.assertEqual([{'id': 'KEY_GEAR', 'kind': 'button'}],
                         dump([Action('KEY_GEAR')]))

    def test_a_name_the_same_as_the_id_is_not_written_twice(self):
        # X4 and Elite compute the name from the id, so for them every
        # single row would otherwise carry it twice.
        self.assertNotIn('name', dump([Action('KEY_GEAR', 'KEY_GEAR')])[0])

    def test_everything_a_game_does_know_survives_the_trip(self):
        one = Action('SimGear', 'Landing gear', kind='button',
                     category='2.01 GEAR', mode='cockpit', rank=17)
        (back,) = read(dump([one]))
        for field in ('id', 'name', 'kind', 'category', 'mode', 'rank'):
            self.assertEqual(getattr(one, field), getattr(back, field))

    def test_a_row_from_an_older_harvest_still_reads(self):
        # The cache is regenerated, not migrated -- but a working copy that
        # predates a field should give a usable record rather than a
        # KeyError naming nothing.
        (back,) = read([{'id': 'KEY_GEAR'}])
        self.assertEqual('KEY_GEAR', back.id)
        self.assertEqual('button', back.kind)
        self.assertEqual(0, back.rank)

    def test_the_order_written_is_the_order_read(self):
        # A screen whose rows move between harvests is one you cannot learn.
        ids = ['C', 'A', 'B']
        self.assertEqual(ids, [a.id for a in read(dump(
            [Action(i) for i in ids]))])


if __name__ == '__main__':
    unittest.main()

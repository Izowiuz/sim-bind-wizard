"""What you want of a layout, as a file rather than as 86 hand-written fields.

A need says what a function IS: held down, used in a turn, found by feel. It
used to also say `stick`, and `stick` is not a property of firing a gun -- it
is a property of how somebody likes their desk. That opinion sat in 76
identical fields across five games, which is one opinion recorded 76 times and
so an opinion nobody could change.

The other half is what a per-need file could not say at all. Every control was
scored alone, so a modifier could land where your thumb already was and the
layer it shifts could land under that same thumb: each placement perfect, the
pair useless. `[[pair]]` is a claim about two controls, and `reachable
together` is `device-map-v2.md` §4 -- the first thing here that reads a spot's
hand and finger rather than only how far away it is.

What this file does NOT own, for the same reason `scoring.toml` does not, is
what a rule MEANS. The file names `reachable together`; `core/overlay.py`
writes it. A file that could define rules would need an expression language.
"""

import os
import tempfile
import unittest

import fake
from core import needs as corneeds
from core import overlay as coverlay
from core.actions import Bind
from core.needs import IN_A_TURN, Need, allocate


def written(body):
    """An overlay read off a file, because that is the only way in."""
    with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False,
                                     encoding='utf-8') as f:
        f.write(body)
        path = f.name
    try:
        return coverlay.read(path, game='x4')
    finally:
        os.unlink(path)


class WhatARuleAsksFor(unittest.TestCase):

    def needs(self):
        return [Need('Fire primary', 'trigger', [[Bind('FIRE')]],
                     suits='fire', urgency=IN_A_TURN),
                Need('Gear', 'button', [[Bind('GEAR')]], suits='state')]

    def test_it_sets_what_it_asks_for(self):
        got = self.needs()
        written('[[want]]\nsuits = "fire"\ndevice = "stick"\n').apply(got)
        self.assertEqual('stick', got[0].device)

    def test_it_leaves_alone_what_it_does_not_name(self):
        # The whole point of a rule over a family: it says nothing about
        # the rest, and the allocator judges those on reach and shape.
        got = self.needs()
        written('[[want]]\nsuits = "fire"\ndevice = "stick"\n').apply(got)
        self.assertIsNone(got[1].device)

    def test_every_condition_has_to_hold(self):
        # Not "any of them". A rule reads as one sentence, and `rare things
        # on the keyboard` means rare AND a thing, not either.
        got = self.needs()
        written('[[want]]\nsuits = "fire"\nurgency = 3\n'
                'device = "throttle"\n').apply(got)
        self.assertIsNone(got[0].device)

    def test_a_rule_with_no_conditions_reaches_everything(self):
        got = self.needs()
        written('[[want]]\ndevice = "throttle"\n').apply(got)
        self.assertEqual(['throttle', 'throttle'],
                         [n.device for n in got])

    def test_the_last_rule_wins(self):
        # So a file may say the broad wish first and the exception after
        # it, which is the order anybody would say them in.
        got = self.needs()
        written('[[want]]\ndevice = "throttle"\n\n'
                '[[want]]\nsuits = "fire"\ndevice = "stick"\n').apply(got)
        self.assertEqual(['stick', 'throttle'], [n.device for n in got])

    def test_it_can_ask_for_a_pin_a_layer_and_a_modifier(self):
        got = self.needs()
        written('[[want]]\nwhat = "Gear"\nprefer = "Keyboard B1 button"\n'
                'shift = true\nmodifier = true\n').apply(got)
        self.assertEqual('Keyboard B1 button', got[1].prefer)
        self.assertIs(True, getattr(got[1], 'shift'))
        self.assertIs(True, getattr(got[1], 'modifier'))

    def test_it_says_how_many_needs_it_touched(self):
        got = self.needs()
        rule = written('[[want]]\nsuits = "fire"\ndevice = "stick"\n')
        self.assertEqual(1, rule.apply(got))


class ARuleNamingOneFunctionIsNotGeneral(unittest.TestCase):
    """An overlay is shared; a rule naming `what` is about one game.

    MSFS and Falcon BMS both have a function called `Gear`, and BMS pins
    its own to a keyboard button. Without the scope MSFS's landing gear
    took that pin, which is not free there, and 27 bindings moved.
    """

    FILE = ('[[want]]\ngame = "falconbms"\nwhat = "Gear"\n'
            'prefer = "Keyboard B1 button"\n')

    def test_another_games_rule_does_not_reach_this_one(self):
        got = [Need('Gear', 'button', [[Bind('GEAR')]])]
        written(self.FILE).apply(got)          # read as x4
        self.assertIsNone(got[0].prefer)

    def test_its_own_games_rule_does(self):
        with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False,
                                         encoding='utf-8') as f:
            f.write(self.FILE)
            path = f.name
        try:
            got = [Need('Gear', 'button', [[Bind('GEAR')]])]
            coverlay.read(path, game='falconbms').apply(got)
        finally:
            os.unlink(path)
        self.assertEqual('Keyboard B1 button', got[0].prefer)

    def test_a_rule_naming_no_game_reaches_every_one(self):
        got = [Need('Gear', 'button', [[Bind('GEAR')]])]
        written('[[want]]\nwhat = "Gear"\ndevice = "stick"\n').apply(got)
        self.assertEqual('stick', got[0].device)


class AWordTheReaderDoesNotKnow(unittest.TestCase):
    """Is a mistake in the file, not something to skip.

    An overlay is the only place that says where you want things. A word
    quietly ignored lays the desk out as though you had asked for nothing,
    which looks exactly like the planner ignoring you.
    """

    def test_an_unknown_word_names_itself(self):
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[want]]\nurgnecy = 0\ndevice = "stick"\n')
        self.assertIn('urgnecy', str(caught.exception))

    def test_it_says_which_words_there_are(self):
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[want]]\nwobble = 1\ndevice = "stick"\n')
        self.assertIn('device', str(caught.exception))
        self.assertIn('suits', str(caught.exception))

    def test_a_want_that_asks_for_nothing_is_a_mistake(self):
        # All condition and no answer: it would read as a rule and do
        # nothing at all.
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[want]]\nsuits = "fire"\n')
        self.assertIn('asks for nothing', str(caught.exception))

    def test_a_rule_nobody_wrote_is_a_mistake(self):
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[pair]]\nrule = "holdable with the other"\n'
                    'one = { suits = "fire" }\nother = { suits = "lock" }\n')
        self.assertIn('reachable together', str(caught.exception))

    def test_a_pair_with_one_side_is_a_mistake(self):
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[pair]]\nrule = "reachable together"\n'
                    'one = { suits = "fire" }\n')
        self.assertIn('other', str(caught.exception))

    def test_a_pair_cannot_ask_for_anything(self):
        # Both sides are conditions. `device = "stick"` there would read
        # as "make it so", and a pair rule refuses rather than sets.
        with self.assertRaises(coverlay.Bad) as caught:
            written('[[pair]]\nrule = "reachable together"\n'
                    'one = { device = "stick" }\nother = { suits = "lock" }\n')
        self.assertIn('device', str(caught.exception))

    def test_an_overlay_nobody_wrote_lists_the_ones_there_are(self):
        with self.assertRaises(coverlay.Bad) as caught:
            coverlay.named('no-such-overlay')
        self.assertIn('by-hand', str(caught.exception))


class ReachableTogether(unittest.TestCase):
    """Two controls one hand can work without letting go of either.

    `device-map-v2.md` §4: different hands, or one position the hand takes
    from which both are reached by different fingers. Two things under one
    thumb are two things you do one after the other.
    """

    def rig(self, hand='right'):
        return fake.device('stick', [
            fake.button('Thumb A', 0, reach=fake.THUMB),
            fake.button('Thumb B', 1, reach=fake.THUMB),
            fake.button('Pinky', 2, reach=fake.PINKY),
            fake.button('Unmeasured', 3),
        ], hand=hand)

    def at(self, label, dev=None):
        return next(c for c in (dev or self.rig()).groups()
                    if c.label == label)

    def test_two_fingers_from_one_position_can(self):
        got = self.rig()
        self.assertTrue(coverlay.PAIRS['reachable together'](
            self.at('Thumb A', got), self.at('Pinky', got)))

    def test_one_finger_cannot(self):
        got = self.rig()
        self.assertFalse(coverlay.PAIRS['reachable together'](
            self.at('Thumb A', got), self.at('Thumb B', got)))

    def test_two_hands_always_can(self):
        one, other = self.rig('right'), self.rig('left')
        self.assertTrue(coverlay.PAIRS['reachable together'](
            self.at('Thumb A', one), self.at('Thumb A', other)))

    def test_a_control_nobody_has_reached_cannot(self):
        # It has no spots at all, so there is no position to compare and
        # no hand either. Saying yes here would be an answer invented out
        # of a desk nobody has walked.
        got = self.rig()
        self.assertFalse(coverlay.PAIRS['reachable together'](
            self.at('Thumb A', got), self.at('Unmeasured', got)))


class APairRuleReachesTheAllocator(unittest.TestCase):

    def rig(self):
        # All three one tier away from flying, so reach decides nothing and
        # the pair rule is the only thing that can separate them.
        return {'stick': fake.device('stick', [
            fake.button('Thumb A', 0, reach=fake.THUMB),
            fake.button('Thumb B', 1, reach=fake.THUMB),
            fake.button('Index', 2, reach=fake.INDEX),
        ], hand='right')}

    def needs(self):
        return [Need('Shift', 'button', [[Bind('SHIFT')]],
                     urgency=IN_A_TURN, suits='modifier'),
                Need('Shifted', 'button', [[Bind('OTHER')]],
                     urgency=IN_A_TURN, suits='layer')]

    def rule(self):
        return written('[[pair]]\nrule = "reachable together"\n'
                       'one = { suits = "modifier" }\n'
                       'other = { suits = "layer" }\n')

    def test_the_pair_does_not_land_on_one_finger(self):
        got = self.needs()
        placed, _unplaced, _free = allocate(got, self.rig(),
                                            overlay=self.rule())
        where = {p.need.what: p.ctrl.label for p in placed}
        self.assertEqual(2, len(where))
        self.assertIn('Index', where.values())
        self.assertNotEqual('thumb', 'index')

    def test_without_the_rule_it_does(self):
        # Which is the bug: two perfect placements and a useless pair.
        placed, _unplaced, _free = allocate(self.needs(), self.rig())
        self.assertEqual(['Thumb A', 'Thumb B'],
                         sorted(p.ctrl.label for p in placed))

    def test_a_rule_binds_every_pair_its_sides_match(self):
        got = self.needs() + [Need('Also shifted', 'button',
                                   [[Bind('THIRD')]], suits='layer')]
        pairs = self.rule().partners(got)
        self.assertEqual(2, len(pairs))

    def test_a_need_is_never_its_own_partner(self):
        got = [Need('Both', 'button', [[Bind('B')]], suits='modifier')]
        got[0].suits = 'modifier'
        rule = written('[[pair]]\nrule = "reachable together"\n'
                       'one = { suits = "modifier" }\n'
                       'other = { suits = "modifier" }\n')
        self.assertEqual([], rule.partners(got))


class TheOverlaysOnFile(unittest.TestCase):
    """The ones in `overlays/` have to load, or no planner starts."""

    def test_every_one_reads(self):
        self.assertTrue(coverlay.names())
        for name in coverlay.names():
            with self.subTest(overlay=name):
                self.assertIsNotNone(coverlay.named(name))

    def test_by_hand_carries_every_wish_the_needs_files_lost(self):
        # The transitional one: 86 wishes, and the proof that splitting
        # the files moved nothing is that it still asks for all of them.
        asked = 0
        for game in ('elite', 'falconbms', 'msfs', 'warthunder', 'x4'):
            got = coverlay.named('by-hand', game)
            asked += sum(1 for rule in got.wants
                         for key in coverlay.SETS if key in rule)
        self.assertEqual(86, asked)

    def test_a_needs_file_asks_for_nothing(self):
        # The split itself: a description says what the function is, and
        # every word about where it goes lives in an overlay.
        import glob
        import json
        for path in glob.glob('games/*/*-needs.json'):
            with self.subTest(file=path):
                with open(path, encoding='utf-8') as f:
                    rows = json.load(f)['needs']
                for row in rows:
                    for wish in corneeds.WISHES:
                        self.assertNotIn(wish, row, row['what'])


if __name__ == '__main__':
    unittest.main()

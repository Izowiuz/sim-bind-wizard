"""What you want of a layout, as a file rather than as 86 hand-written
fields.

A need says what a function IS: held down, used in a turn, found by feel.
It does not say `stick`. `stick` is not a property of firing a gun. It is
a property of how somebody likes their desk, and written per need it is
one opinion recorded 76 times, which is an opinion nobody can change.

The other half is what a per-need file cannot say at all. Every control
scored alone lets a modifier land where your thumb already is, and the
layer it shifts land under that same thumb: each placement perfect and the
pair useless. `[[pair]]` is a claim about two controls, and `reachable
together` reads a spot's hand and finger rather than how far away it is.

This file does NOT own what a rule MEANS, for the reason `scoring.toml`
does not. The file names `reachable together`, and `core/overlay.py`
writes it. A file that defined rules would need an expression language.
"""

import os
import re
import sys
import json
import tempfile
import typing
import unittest
from unittest import mock

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
                Need('Gear', 'button', [[Bind('GEAR')]], suits='systems')]

    def test_it_sets_what_it_asks_for(self):
        got = self.needs()
        written('[[want]]\nsuits = "fire"\ndevice = "stick"\n').apply(got)
        self.assertEqual('stick', got[0].device)

    def test_it_leaves_alone_what_it_does_not_name(self):
        # This is the point of a rule over a family. It says nothing
        # about the rest, and the allocator judges those on reach and
        # shape.
        got = self.needs()
        written('[[want]]\nsuits = "fire"\ndevice = "stick"\n').apply(got)
        self.assertIsNone(got[1].device)

    def test_every_condition_has_to_hold(self):
        # Not "any of them". A rule reads as one sentence, and `rare
        # things on the keyboard` means rare AND a thing.
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
        # So a file says the broad wish first and the exception after it.
        # That is the order anybody says them in.
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
    """An overlay is shared. A rule that names `what` is about one game.

    MSFS and Falcon BMS both hold a function called `Gear`, and Falcon BMS
    pins its own to a keyboard button. Without the scope, MSFS's landing
    gear takes that pin. The pin is not free there, and 27 bindings
    move.
    """

    FILE = ('[[want]]\ngame = "falconbms"\nwhat = "Gear"\n'
            'prefer = "Keyboard B1 button"\n')

    def test_another_games_rule_does_not_reach_this_one(self):
        got = [Need('Gear', 'button', [[Bind('GEAR')]])]
        written(self.FILE).apply(got)          # Read as x4.
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
    """A mistake in the file, and not something to skip.

    An overlay is the only place that says where you want things. A word
    ignored in silence lays the desk out as though you had asked for
    nothing, and that looks like the planner ignoring you.
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
        # All condition and no answer. Such a rule reads as a rule and
        # does nothing.
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
        # Both sides are conditions. `device = "stick"` there reads as
        # "make it so", and a pair rule refuses rather than sets.
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

    Two different hands, or one position the hand takes and reaches both
    from, with different fingers. Two things under one thumb are two
    things you do one after the other.
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
        # It has no spots, so there is no position to compare and no hand
        # either. Yes here is an answer invented out of a desk nobody has
        # walked.
        got = self.rig()
        self.assertFalse(coverlay.PAIRS['reachable together'](
            self.at('Thumb A', got), self.at('Unmeasured', got)))


class APairRuleReachesTheAllocator(unittest.TestCase):

    def rig(self):
        # All three are one tier away from flying, so reach decides
        # nothing and the pair rule is the only thing that separates
        # them.
        return {'stick': fake.device('stick', [
            fake.button('Thumb A', 0, reach=fake.THUMB),
            fake.button('Thumb B', 1, reach=fake.THUMB),
            fake.button('Index', 2, reach=fake.INDEX),
        ], hand='right')}

    def needs(self):
        return [Need('Shift', 'button', [[Bind('SHIFT')]],
                     urgency=IN_A_TURN, suits='systems'),
                Need('Shifted', 'button', [[Bind('OTHER')]],
                     urgency=IN_A_TURN, suits='fire')]

    def rule(self):
        return written('[[pair]]\nrule = "reachable together"\n'
                       'one = { suits = "systems" }\n'
                       'other = { suits = "fire" }\n')

    def test_the_pair_does_not_land_on_one_finger(self):
        got = self.needs()
        placed, _unplaced, _free = allocate(got, self.rig(),
                                            overlay=self.rule())
        where = {p.need.what: p.ctrl.label for p in placed}
        self.assertEqual(2, len(where))
        self.assertIn('Index', where.values())
        self.assertNotEqual('thumb', 'index')

    def test_without_the_rule_it_does(self):
        # That is the fault: two perfect placements and a useless pair.
        placed, _unplaced, _free = allocate(self.needs(), self.rig())
        self.assertEqual(['Thumb A', 'Thumb B'],
                         sorted(p.ctrl.label for p in placed))

    def test_a_rule_binds_every_pair_its_sides_match(self):
        got = self.needs() + [Need('Also shifted', 'button',
                                   [[Bind('THIRD')]], suits='fire')]
        pairs = self.rule().partners(got)
        self.assertEqual(2, len(pairs))

    def test_a_need_is_never_its_own_partner(self):
        got = [Need('Both', 'button', [[Bind('B')]], suits='systems')]
        rule = written('[[pair]]\nrule = "reachable together"\n'
                       'one = { suits = "systems" }\n'
                       'other = { suits = "systems" }\n')
        self.assertEqual([], rule.partners(got))


class APlaceOnTheHand(unittest.TestCase):
    """What makes an overlay a cockpit template and not a device
    preference.

    `prefer = "Top thumb hat"` is a label off one desk. The Hornet's
    castle switch, said as "the stick hand's thumb, without moving the
    hand", lands on whatever the desk in front of you has in that place.
    That is what lets one file lay out six games on anybody's hardware.
    """

    def rig(self):
        return {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Index', 1, reach=fake.INDEX),
            fake.button('Pinky', 2, reach=fake.PINKY),
            fake.button('Panel', 3, reach=fake.PANEL),
            fake.button('Unmeasured', 4),
        ], hand='right')}

    def at(self, label, devs):
        return next(c for c in devs['stick'].groups() if c.label == label)

    def need(self, **kw):
        got = Need('Guns', 'button', [[Bind('GUNS')]], suits='fire',
                   urgency=IN_A_TURN)
        for key, value in kw.items():
            setattr(got, key, value)
        return got

    def test_a_finger_is_a_wish_the_reader_takes(self):
        got = [self.need()]
        written('[[want]]\nsuits = "fire"\nfinger = "thumb"\n').apply(got)
        self.assertEqual('thumb', got[0].finger)

    def test_a_level_is_too(self):
        got = [self.need()]
        written('[[want]]\nsuits = "fire"\nlevel = "HOME"\n').apply(got)
        self.assertEqual('HOME', got[0].level)

    def test_a_word_the_map_does_not_say_is_a_mistake(self):
        # Against the MAP's own constants, and not against a list of
        # ours. These are constants in `devicemap.py`.
        for line, bad in (('finger = "thump"', 'thump'),
                          ('level = "home"', 'home'),
                          ('device = "yoke"', 'yoke')):
            with self.subTest(line=line):
                with self.assertRaises(coverlay.Bad) as caught:
                    written(f'[[want]]\nsuits = "fire"\n{line}\n')
                self.assertIn(bad, str(caught.exception))

    def test_a_control_in_the_right_place_counts_kept(self):
        devs = self.rig()
        self.assertEqual((1, 0), corneeds.place_wishes(
            self.at('Thumb', devs), self.need(finger='thumb')))

    def test_a_control_in_the_wrong_place_counts_broken(self):
        devs = self.rig()
        self.assertEqual((0, 1), corneeds.place_wishes(
            self.at('Index', devs), self.need(finger='thumb')))

    def test_both_words_count_separately(self):
        # A want that asks for a thumb at HOME makes two claims about
        # where a thing goes, and one of them answered is half an
        # answer.
        devs = self.rig()
        self.assertEqual((1, 1), corneeds.place_wishes(
            self.at('Pinky', devs), self.need(finger='pinky', level='HOME')))

    def test_a_control_nobody_has_measured_counts_neither(self):
        # Charged, it is charged for a desk nobody has walked, and not
        # for being in the wrong place.
        devs = self.rig()
        self.assertEqual((0, 0), corneeds.place_wishes(
            self.at('Unmeasured', devs), self.need(finger='thumb')))

    def test_a_need_with_no_wish_counts_neither(self):
        devs = self.rig()
        self.assertEqual((0, 0), corneeds.place_wishes(
            self.at('Thumb', devs), self.need()))

    def test_the_wish_moves_a_placement(self):
        devs = self.rig()
        rule = written('[[want]]\nsuits = "fire"\nfinger = "index"\n')
        got = [self.need()]
        placed, _un, _free = allocate(got, devs, overlay=rule)
        self.assertEqual('Index', placed[0].ctrl.label)

    def test_without_the_wish_it_goes_by_reach(self):
        # Reach rewards the least precious control that still does the
        # job, so the lone need takes the pinky and leaves the thumb for
        # whatever is still coming. The wish above overrules that, and
        # that is the whole of what a template does.
        placed, _un, _free = allocate([self.need()], self.rig())
        self.assertEqual('Pinky', placed[0].ctrl.label)

    def test_a_wish_is_a_lean_and_not_a_law(self):
        # +15 against a tier's worth of reach. A template that refused
        # everything it did not name places half an aircraft on a desk it
        # was not drawn for.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Far', 1, reach=fake.PANEL),
        ], hand='right')}
        rule = written('[[want]]\nsuits = "fire"\nfinger = "ring"\n')
        placed, unplaced, _free = allocate([self.need()], devs, overlay=rule)
        self.assertEqual([], unplaced, 'a lean refused the only homes there were')
        self.assertEqual(1, len(placed))


class HowMuchOfTheTemplateGotThrough(unittest.TestCase):
    """The count under a layout. Two overlays are compared on it.

    Without the count you read the whole layout with the file open beside
    it.
    """

    def rig(self):
        return {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Index', 1, reach=fake.INDEX),
        ], hand='right')}

    def needs(self):
        return [Need('Guns', 'button', [[Bind('GUNS')]], suits='fire',
                     urgency=IN_A_TURN),
                Need('Scan', 'button', [[Bind('SCAN')]], suits='sensor',
                     urgency=IN_A_TURN)]

    def layout(self, body):
        rule = written(body)
        got = self.needs()
        placed, unplaced, free = allocate(got, self.rig(), overlay=rule)
        return rule, corneeds.Layout(self.rig(), placed, unplaced, free)

    def test_it_counts_what_was_honoured(self):
        rule, layout = self.layout('[[want]]\nsuits = "fire"\n'
                                   'finger = "thumb"\n')
        kept, broken, lost = rule.kept(layout)
        self.assertEqual((1, 0), (kept, broken))
        self.assertEqual([], lost)

    def test_it_says_what_broke_and_what_it_got_instead(self):
        rule, layout = self.layout('[[want]]\nsuits = "fire"\n'
                                   'finger = "ring"\n')
        _kept, broken, lost = rule.kept(layout)
        self.assertEqual(1, broken)
        (what, word, want, instead), = lost
        self.assertEqual(('Guns', 'finger', 'ring', 'thumb'),
                         (what, word, want, instead))

    def test_an_overlay_asking_for_no_place_counts_nothing(self):
        # So `by-hand.toml` draws no line at all. It asks for devices,
        # and a device has its own terms.
        rule, layout = self.layout('[[want]]\nsuits = "fire"\n'
                                   'device = "stick"\n')
        self.assertEqual((0, 0, []), rule.kept(layout))


class LayingOneOnReplacesTheLast(unittest.TestCase):
    """An overlay replaces. It does not add.

    An `apply` that only writes leaves every need the second overlay says
    nothing about wearing the first file's finger, and `place_right` then
    counts a wish nobody asked for. `--overlay none` has the same hole.
    """

    def needs(self):
        return [Need('Guns', 'button', [[Bind('GUNS')]], suits='fire'),
                Need('Gear', 'button', [[Bind('GEAR')]], suits='systems')]

    def test_the_second_overlay_leaves_no_trace_of_the_first(self):
        got = self.needs()
        written('[[want]]\nsuits = "fire"\nfinger = "thumb"\n').apply(got)
        written('[[want]]\nsuits = "systems"\nfinger = "pinky"\n').apply(got)
        self.assertIsNone(got[0].finger, 'kept the first overlay\'s finger')
        self.assertEqual('pinky', got[1].finger)

    def test_forgetting_them_says_how_many_it_found(self):
        got = self.needs()
        written('[[want]]\nsuits = "fire"\nfinger = "thumb"\n'
                'device = "stick"\n').apply(got)
        self.assertEqual(2, corneeds.forget_wishes(got))
        self.assertEqual(0, corneeds.forget_wishes(got))

    def test_a_device_the_game_asked_for_stands(self):
        # The one wish that names a field the game names too, and the
        # game knows the thing. DCS reads the device off its own command
        # table, and that table is written from the aircraft.
        #
        # A template speaks one job at a time, and one word covers more
        # than you mean. `suits = "flight"` covers the flight axes AND
        # the speedbrake. Overwriting with it puts the Hornet's pitch on
        # the throttle, where no axis answers it, and moves five more
        # commands off the device the real jet keeps them on.
        (pitch,) = corneeds.read_needs([
            {'what': 'Pitch', 'shape': 'stick', 'takes': corneeds.AXIS,
             'device': 'stick', 'on': ['y'], 'bindings': [[]]}])
        written('[[want]]\nwhat = "Pitch"\ndevice = "throttle"\n').apply(
            [pitch])
        self.assertEqual('stick', pitch.device)

    def test_a_game_with_no_needs_file_keeps_its_ask_too(self):
        # DCS builds its needs from the module on every run, so no file
        # holds the ask. A field only a file fills is empty there, and
        # `forget_wishes` then wipes the Hornet's own device before any
        # scoring. That is the other half of pitch, roll and rudder going
        # to the throttle.
        pitch = Need('Pitch', 'stick', [[Bind('PITCH')]], suits='flight',
                     takes=corneeds.AXIS, device='stick')
        written('[[want]]\nsuits = "flight"\ndevice = "throttle"\n').apply(
            [pitch])
        self.assertEqual('stick', pitch.device, 'the ask survives the wish')
        corneeds.forget_wishes([pitch])
        self.assertEqual('stick', pitch.device, 'and the overlay coming off')

    def test_a_finger_the_game_asked_for_stands_too(self):
        # Said of every wish, and not of `device` alone. DCS's own table
        # knows which finger works a control on the real jet. A template
        # knows one word per job, and `suits = "fire"` is the trigger AND
        # the master mode buttons.
        fire = Need('Fire', 'trigger', [[Bind('GUNS')]], suits='fire',
                    device='stick', finger='index')
        written('[[want]]\nsuits = "fire"\nfinger = "thumb"\n'
                'level = "HOME"\n').apply([fire])
        self.assertEqual('index', fire.finger, 'the jet said index')
        self.assertEqual('HOME', fire.level,
                         'and the template still says the level')

    def test_a_device_it_said_nothing_about_is_a_wish_and_comes_off(self):
        # Where the game has no opinion, the template places it. Taking
        # the template off leaves the need asking for nothing. Otherwise a
        # save writes the wish as the game's own ask.
        (gear,) = corneeds.read_needs([
            {'what': 'Gear', 'shape': 'button', 'bindings': [[]]}])
        written('[[want]]\nwhat = "Gear"\ndevice = "throttle"\n').apply(
            [gear])
        self.assertEqual('throttle', gear.device, 'an overlay may ask')
        corneeds.forget_wishes([gear])
        self.assertIsNone(gear.device, 'and the wish comes off')
        self.assertIsNone(corneeds.dump_needs([gear])[0].get('device'),
                          'a save writes the ask, never the wish')

    def test_a_button_need_keeps_a_device_its_file_named_too(self):
        # One rule for either kind, and that is the point. A rule that
        # reads `takes` is two rules.
        (fire,) = corneeds.read_needs([
            {'what': 'Fire', 'shape': 'trigger', 'device': 'stick',
             'bindings': [[]]}])
        written('[[want]]\nwhat = "Fire"\ndevice = "throttle"\n').apply(
            [fire])
        corneeds.forget_wishes([fire])
        self.assertEqual('stick', fire.device)

    def test_forgetting_twice_finds_nothing_the_second_time(self):
        # A flag nobody set is False while the file says nothing, so a
        # counter that compares the two answers 4 where the answer is
        # 2.
        (fire,) = corneeds.read_needs([
            {'what': 'Fire', 'shape': 'trigger', 'device': 'stick',
             'bindings': [[]]}])
        written('[[want]]\nwhat = "Fire"\nfinger = "thumb"\n').apply([fire])
        self.assertEqual(1, corneeds.forget_wishes([fire]))
        self.assertEqual(0, corneeds.forget_wishes([fire]))

    def test_it_walks_the_wish_list_rather_than_one_of_its_own(self):
        # So a seventh wish is cleared by being in `WISHES`.
        got = self.needs()
        # Seen once first, which is what `apply` does before it wishes
        # anything. What a need wears the first time an overlay comes off
        # is the game's own ask, and these are set here by hand.
        corneeds.forget_wishes(got)
        for wish in corneeds.WISHES:
            setattr(got[0], wish, 'thumb' if wish == 'finger' else True)
        corneeds.forget_wishes(got)
        for wish in corneeds.WISHES:
            self.assertFalse(getattr(got[0], wish), wish)


class WhatTheDcsTableSays(unittest.TestCase):
    """The hint table is prose for a reader and nothing else.

    A table that carries the device, the band, the finger and the job
    builds a module's whole description by matching 80 patterns against
    852 command names, on every run.

    All of that is in `dcs-<module>-needs.json` now, per command, keyed by
    the command's own identifier. What is left here is what to tell
    somebody who has never flown the type.
    """

    def propose(self):
        import os
        from core import adapter
        return adapter.from_file(
            'dcs_propose_for_test',
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'games', 'dcs', 'plan.py'))

    def test_the_three_axes_the_aircraft_flies_on_find_a_home(self):
        # A table that asks the map for `stick-x`, `stick-y` and `twist`
        # asks for words the map does not use. A stick is one control with
        # three axes, so a kind per axis says the kind twice.
        #
        # `axes(kind=...)` filters on the CONTROL's kind, so all three ask
        # for a kind nothing has. Pitch, roll and rudder then come out as
        # `no axis on this hardware`, on a desk with a full stick on
        # it.
        m = self.propose()
        stick = fake.device('stick', axes=[
            {'index': 0, 'role': 'x'}, {'index': 1, 'role': 'y'},
            {'index': 2, 'role': 'z'}], controls=[
                fake.control('stick', 'Main stick', axes=[0, 1, 2])])
        for want, role in (('stick', 'x'), ('stick', 'y'), ('stick', 'z')):
            with self.subTest(axis=role):
                self.assertIsNotNone(stick.axis_of(want, role))
        # Which part of the stick pitch IS is in the module's needs file.
        # Read out of the command's own name instead, it is a guess. The
        # file says it, as every other game's file does.
        a = hornet()
        if a is None or not a.NEEDS:
            self.skipTest('nobody has described FA-18C here, so the file '
                          'has nothing to say about its axes yet')
        want = {'Pitch': 'y', 'Roll': 'x', 'Rudder': 'z'}
        found = 0
        for need in a.NEEDS:
            if need.what not in want:
                continue
            found += 1
            with self.subTest(name=need.what):
                self.assertEqual('stick', need.shape)
                self.assertEqual((want[need.what],), need.on)
                self.assertEqual('centred', need.rests,
                                 'it has to spring back or you cannot fly')
        self.assertTrue(found, 'the file names none of the three axes the '
                               'aircraft flies on')

class TheOverlaysOnFile(unittest.TestCase):
    """The ones in `overlays/` have to load, or no planner starts."""

    def test_each_one_remembers_its_own_filename(self):
        # What `--overlay` and the menu say, as against the display name
        # out of the file. `f-18.toml` calls itself `F/A-18C`. The menu
        # compares on this, so it does not read every overlay in the
        # directory to find out which one is on.
        got = coverlay.named('f-18')
        self.assertEqual('f-18', got.called)
        self.assertEqual('F/A-18C', got.name)

    def test_every_one_reads(self):
        self.assertTrue(coverlay.names())
        for name in coverlay.names():
            with self.subTest(overlay=name):
                self.assertIsNotNone(coverlay.named(name))

    def test_by_hand_carries_every_wish_the_needs_files_lost(self):
        # The transitional one. It holds 86 wishes, and it still asks for
        # all of them, which is the proof that splitting the files moved
        # nothing.
        asked = 0
        for game in ('elite', 'falconbms', 'msfs', 'warthunder', 'x4'):
            got = coverlay.named('by-hand', game)
            asked += sum(1 for rule in got.wants
                         for key in coverlay.SETS if key in rule)
        self.assertEqual(86, asked)

    #: What a needs file may say about where a function goes. A game that
    #: knows its own cockpit states a fact and not a preference: which
    #: device holds it, which of two levers, and which finger works it.
    #: DCS reads all three off the module's own command table, which is
    #: written from the aircraft.
    #:
    #: The rest of `WISHES` is a template's business. `level` is where the
    #: hand is. `shift` and `modifier` are claims about a layer. None of
    #: the three is a fact about a function.
    COCKPIT = ('device', 'prefer', 'finger')

    def test_a_needs_file_says_what_the_function_is(self):
        # The split. A description says what the function IS, and the
        # layer words live in an overlay.
        #
        # `device` is on both sides. `stick` is not a property of firing a
        # gun, which holds for a game whose file is somebody's desk
        # preference. It does not hold for the aircraft the Hornet's table
        # describes.
        import glob
        import json
        for path in glob.glob('games/*/*-needs.json'):
            with self.subTest(file=path):
                with open(path, encoding='utf-8') as f:
                    rows = json.load(f)['needs']
                for row in rows:
                    for wish in corneeds.WISHES:
                        if wish in self.COCKPIT:
                            continue
                        self.assertNotIn(wish, row, row['what'])

    def test_every_job_a_file_names_is_one_of_the_ten(self):
        # The word an overlay takes hold of. Sixty-five of the hundred
        # and forty-seven said nothing, so a template had nothing to match
        # for nearly half the list. The five hand-written files name one
        # on every row.
        #
        # A row can still be short of one, and seeing that is the point of
        # a file. DCS's three were seeded from a table of name patterns,
        # and seventeen functions across them matched no phrase: `Weapon
        # Fire`, `Cannon`, `Airbrake`, `Communication menu`.
        #
        # Under the patterns that hole is invisible, because no match and
        # no job are the same answer. A word nobody defines costs every
        # wish in the template, and it costs it in silence.
        import glob
        import json
        for path in glob.glob('games/*/*-needs.json'):
            with self.subTest(file=path):
                with open(path, encoding='utf-8') as f:
                    rows = json.load(f)['needs']
                for row in rows:
                    if row.get('suits') is None:
                        continue
                    self.assertIn(row['suits'], corneeds.JOBS, row['what'])


def hornet() -> typing.Any:
    """The Hornet's adapter, or None where DCS is not harvested here.

    `Any`, the way `tests/fake.py` and `test_listings` take a game. The
    adapter is loaded by path, so nothing here can be typed against it.
    """
    from core import adapter
    from core import vocab
    # `--aircraft` is this adapter's own argument, declared in its `SAYS`
    # and not on the base class, so the class comes through untyped.
    make: typing.Any = adapter.adapters('dcs')[0]
    try:
        return make(aircraft='FA-18C')
    except (FileNotFoundError, vocab.Missing, SystemExit):
        return None


@unittest.skipUnless(hornet(), 'dcs is not harvested here')
class TheHornetStaysInItsOwnCockpit(unittest.TestCase):
    """What a cockpit template is measured against: the real aircraft.

    Not the factory profiles. Those are Eagle Dynamics' bindings for
    particular HOTAS hardware, so a Warthog profile says `throttle`
    because a Warthog has buttons there, and not because the jet does.

    The aircraft itself is the `device` column of DCS's own table, written
    by hand from the cockpit, one row per concept.

    `--overlay f-18` moves the layout TOWARDS that. A template that
    overwrites the table moves it away: `suits = "flight"` is one word
    over the flight axes AND the speedbrake, so pitch, roll and rudder ask
    for a stick on the throttle, where no axis answers, and five more
    commands cross to the wrong hand.
    """

    @classmethod
    def setUpClass(cls):
        cls.a = hornet()
        if not cls.a.NEEDS:
            raise unittest.SkipTest(
                'nobody has described FA-18C here, so there is nothing to '
                'measure against the jet')
        cls.plain = cls.a.build()
        corneeds.OVERLAY = coverlay.named('f-18', 'dcs')
        corneeds.OVERLAY.apply(cls.a.NEEDS)
        cls.laid = cls.a.build()

    @classmethod
    def tearDownClass(cls):
        corneeds.OVERLAY = None
        corneeds.forget_wishes(cls.a.NEEDS)

    def jet(self, layout):
        """{function: (the device it asks for, the device it got)}.

        The yardstick is `device` on the need. "The real jet keeps this on
        the throttle" is a fact about the function, said once with `J`.
        `asked()` tells the game's own ask from an overlay's wish, which
        is the question here: the template is what is being measured.

        A pattern over a command's name is the one thing nothing here may
        decide from. A file of patterns is not a yardstick. It is the
        table again.
        """
        return {p.need.what: (corneeds.asked(p.need).get('device'), p.role)
                for p in layout.placed
                if corneeds.asked(p.need).get('device')}

    def elsewhere(self, layout):
        """The commands sitting on a device the jet does not use for them."""
        return sorted(cmd for cmd, (jet, got) in self.jet(layout).items()
                      if jet != got)

    def test_the_yardstick_is_not_empty(self):
        # Both answers below are about functions that NAME a device, so a
        # list where nobody has named one makes both vacuously true. The
        # column that carries this deleted, three tests go on passing
        # over nothing.
        self.assertTrue(self.jet(self.plain),
                        'no function in this module says which device the '
                        'real aircraft keeps it on, so there is nothing to '
                        'measure the template against')

    def test_the_template_moves_nothing_off_the_jets_own_device(self):
        self.assertEqual(self.elsewhere(self.plain),
                         self.elsewhere(self.laid))

    def test_and_the_template_costs_no_need_its_control(self):
        # Against the plain layout and not against zero. A function
        # nobody has described can go unplaced for its own reasons, and
        # `Communication menu` does. What the template may not do is take
        # a control away. It took three, and those three were pitch, roll
        # and rudder.
        self.assertLessEqual(len(self.laid.unplaced),
                             len(self.plain.unplaced),
                             [n.what for n in self.laid.unplaced])

    def test_it_holds_some_of_the_template_all_the_same(self):
        # Otherwise the answer above says only "the overlay does
        # nothing".
        kept, broken, _lost = corneeds.OVERLAY.kept(self.laid)
        self.assertGreater(kept, broken)


@unittest.skipUnless(hornet(), 'dcs is not harvested here')
class TheDescriptionIsReadRatherThanWorkedOut(unittest.TestCase):
    """DCS keeps `dcs-<module>-needs.json`, like the other five.

    A description worked out of the command NAMES on every run is 80
    patterns over 852 names, deciding which commands matter at all, what
    shape each one wants, which device holds it, and when you touch it.

    A pattern describes a module once. What a run reads is the file, and
    the fields in it are data like every other game's.
    """

    def test_the_list_is_the_file_and_the_file_names_the_module(self):
        # A table of 80 patterns over 852 command names IS the
        # description: it decides which commands matter, what shape each
        # one wants, which device holds it, and when you touch it. What a
        # run reads is the file, and `tests/test_contract.py` holds every
        # game to a layout that does not depend on an action's name.
        a: typing.Any = type(hornet())(aircraft='FA-18C')
        self.assertEqual('dcs-FA-18C-needs.json', a.NEEDS_FILE)
        self.assertEqual('dcs-FA-18C-binds.json', a.BINDS)
        self.assertEqual('dcs-FA-18C-actions.json', a.CATALOGUE)

    def test_and_the_hashes_come_off_the_bindings(self):
        """The command hashes are in `bindings` and nowhere else.

        A second copy of them on the need is empty for a need read out of
        the FILE, and eight places in the planner read that copy.

        There is no second copy to check against. The clause is that every
        hash a need carries is one the module has, and that is what the
        copy was for.
        """
        a = hornet()
        known = {x.id for x in a.catalogue()}
        self.assertTrue(a.NEEDS, 'nobody has described FA-18C here')
        for need in a.NEEDS:
            with self.subTest(need=need.what):
                said = [b.action for slot in need.bindings for b in slot]
                self.assertTrue(said, 'a need with no binding at all')
                for h in said:
                    self.assertIn(h, known)


if __name__ == '__main__':
    unittest.main()


class TheTemplateIsWrittenDown(unittest.TestCase):
    """`o` is a decision, so it reaches the file the rest of them do.

    Which template is on decides where every placement landed, so a file
    that holds the answer and not the template cannot be read back.

    Measured on the Hornet before this: `o f-18` took the list from 33
    accepted rows to 45, and the next open put it back to 33. Twelve of
    those rows sit somewhere else under `by-hand`, and `_came_by` is
    right to send them to `?`. The cause was that nothing wrote the
    template down.
    """

    def saved(self, overlay, needs=()):
        """What `filed_overlay` reads back out of a written file."""
        with tempfile.TemporaryDirectory() as d:
            corneeds.save_assignments(d, 'binds.json', list(needs), overlay)
            return corneeds.filed_overlay(d, 'binds.json')

    def test_a_name_comes_back(self):
        self.assertEqual('f-18', self.saved('f-18'))

    def test_no_template_comes_back_as_nothing(self):
        # "No template" is a decision. Absent, it reads as a game nobody
        # has laid out, and the declaration answers instead.
        self.assertEqual('', self.saved(None))
        self.assertEqual('', self.saved(''))

    def test_a_file_written_before_the_field_reads_as_nothing(self):
        # The four games on disk were saved without it. Neither is a
        # fault, and both mean "ask the declaration".
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'binds.json'), 'w',
                      encoding='utf-8') as f:
                f.write('{"binds": []}')
            self.assertEqual('', corneeds.filed_overlay(d, 'binds.json'))

    def test_a_game_nobody_has_saved_reads_as_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual('', corneeds.filed_overlay(d, 'binds.json'))

    def test_it_does_not_disturb_the_placements(self):
        # One more section in the same file, and not a second file.
        need = Need('Gear', 'button', [[Bind('GEAR')]])
        need.assignment = {'role': 'stick', 'control': 'thumb-a',
                           'how': corneeds.CHOSE}
        with tempfile.TemporaryDirectory() as d:
            corneeds.save_assignments(d, 'binds.json', [need], 'f-18')
            with open(os.path.join(d, 'binds.json'), encoding='utf-8') as f:
                got = json.load(f)
        self.assertEqual('f-18', got['overlay'])
        self.assertEqual(['Gear'], [r['what'] for r in got['binds']])

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
                Need('Gear', 'button', [[Bind('GEAR')]], suits='systems')]

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
        # Which is the bug: two perfect placements and a useless pair.
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
    """What makes an overlay a cockpit template, not a device preference.

    `prefer = "Top thumb hat"` is a label off one desk. The Hornet's castle
    switch said as "the stick hand's thumb, without moving the hand" lands
    on whatever the desk in front of you has in that place, which is what
    lets one file lay out six games on anybody's hardware.
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
        # Against the MAP's own constants, not a list of ours: these have
        # been in devicemap.py since before overlays existed.
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
        # A want asking for a thumb at HOME is two claims about where a
        # thing goes, and answering one of them is half an answer.
        devs = self.rig()
        self.assertEqual((1, 1), corneeds.place_wishes(
            self.at('Pinky', devs), self.need(finger='pinky', level='HOME')))

    def test_a_control_nobody_has_measured_counts_neither(self):
        # Charging it would be charging for a desk nobody has walked
        # rather than for being in the wrong place.
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
        # And reach rewards the LEAST precious control that still does the
        # job, so the lone need gets the pinky and leaves the thumb for
        # whatever might still be coming. The wish above is what overrules
        # that, which is the whole of what a template does.
        placed, _un, _free = allocate([self.need()], self.rig())
        self.assertEqual('Pinky', placed[0].ctrl.label)

    def test_a_wish_is_a_lean_and_not_a_law(self):
        # +15 against a tier's worth of reach: a template that refused
        # everything it did not name would place half an aircraft on a
        # desk that is not the one it was drawn for.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Far', 1, reach=fake.PANEL),
        ], hand='right')}
        rule = written('[[want]]\nsuits = "fire"\nfinger = "ring"\n')
        placed, unplaced, _free = allocate([self.need()], devs, overlay=rule)
        self.assertEqual([], unplaced, 'a lean refused the only homes there were')
        self.assertEqual(1, len(placed))


class HowMuchOfTheTemplateGotThrough(unittest.TestCase):
    """The count under a layout, which is what two overlays are compared on.

    Without it the only way to know whether an overlay did anything was to
    read the whole layout with the file open beside it.
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
        # Which is how the transitional `by-hand.toml` draws no line at
        # all: it asks for devices, and a device has its own terms.
        rule, layout = self.layout('[[want]]\nsuits = "fire"\n'
                                   'device = "stick"\n')
        self.assertEqual((0, 0, []), rule.kept(layout))


class LayingOneOnReplacesTheLast(unittest.TestCase):
    """An overlay is a replacement, not an addition.

    `apply` only ever wrote, and one overlay per process hid it: a second
    laid over the first left every need it says nothing about wearing the
    first file's finger, and `place_right` then counted a wish nobody had
    asked for. `--overlay none` had the same hole.
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

    def test_it_walks_the_wish_list_rather_than_one_of_its_own(self):
        # So a seventh wish is cleared by the fact of being in `WISHES`.
        got = self.needs()
        for wish in corneeds.WISHES:
            setattr(got[0], wish, 'thumb' if wish == 'finger' else True)
        corneeds.forget_wishes(got)
        for wish in corneeds.WISHES:
            self.assertFalse(getattr(got[0], wish), wish)


class DcsWorksOutItsOwnJobs(unittest.TestCase):
    """The one game with no needs file to write a job in.

    It derives its needs from the module's command vocabulary on every
    run, so there is nowhere to keep a judgement -- and until `jobs.toml`
    all 43 of the Hornet's controls had `suits = None`, so `f-18.toml`
    matched nothing in the one game where it is about the aircraft
    actually in the cockpit.

    Read off DCS's own names, which are the jet's: `Gun Trigger - SECOND
    DETENT`, `Sensor Control Switch`, `Throttle Designator Controller`.
    """

    def propose(self):
        import os
        from core import adapter
        return adapter.from_file(
            'dcs_propose_for_test',
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'games', 'dcs', 'propose.py'))

    def test_every_phrase_names_a_job_the_rules_define(self):
        m = self.propose()
        for phrase, job in m.jobs():
            with self.subTest(phrase=phrase):
                self.assertIn(job, corneeds.JOBS)

    def test_it_reads_the_jet_rather_than_guessing(self):
        m = self.propose()
        for name, want in (
                ('Gun Trigger - SECOND DETENT (Press to shoot)', 'fire'),
                ('Weapon Release Button', 'fire'),
                ('Sensor Control Switch', 'sensor'),
                ('Throttle Designator Controller - Depress', 'sensor'),
                ('Undesignate/Nose Wheel Steer Switch', 'lock'),
                ('Dispense Switch', 'defence'),
                ('Trimmer Switch', 'trim'),
                ('COMM Switch - MIDS A', 'comms'),
                ('Landing Gear Control Handle', 'systems'),
                ('Speed Brake Switch - EXTEND', 'flight'),
                ('Zoom View', 'view')):
            with self.subTest(name=name):
                self.assertEqual(want, m.job_of(name))

    def test_the_order_in_the_file_decides(self):
        # `fov select` has to be read before `select`, or the FLIR
        # field-of-view button becomes a weapon control.
        m = self.propose()
        self.assertEqual('sensor', m.job_of('RAID/FLIR FOV Select Button'))
        self.assertEqual('fire', m.job_of('Select'))
        # And `throttle designator` before `throttle`.
        self.assertEqual('sensor', m.job_of(
            'Throttle Designator Controller - Horizontal Axis'))
        self.assertEqual('flight', m.job_of('Throttle'))

    def test_the_three_axes_the_aircraft_flies_on_find_a_home(self):
        # `AXIS_FOR` asked the map for `stick-x`, `stick-y` and `twist`,
        # and the map stopped spelling it that way: a stick is one control
        # with three axes, so a kind per axis said the kind twice.
        # `axes(kind=...)` filters on the CONTROL's kind, so all three
        # asked for a kind nothing has. Pitch, roll and rudder came out as
        # `no axis on this hardware` on a desk with a full stick on it.
        m = self.propose()
        stick = fake.device('stick', axes=[
            {'index': 0, 'role': 'x'}, {'index': 1, 'role': 'y'},
            {'index': 2, 'role': 'z'}], controls=[
                fake.control('stick', 'Main stick', axes=[0, 1, 2])])
        for want, role in (('stick', 'x'), ('stick', 'y'), ('stick', 'z')):
            with self.subTest(axis=role):
                self.assertIsNotNone(stick.axis_of(want, role))
        for name in ('Pitch', 'Roll', 'Rudder'):
            with self.subTest(name=name):
                self.assertIn(m.AXIS_FOR[name][0], ('stick', 'lever'))
                self.assertIn(m.AXIS_FOR[name][1], ('x', 'y', 'z', ''))

    def test_a_name_nothing_matches_keeps_no_job(self):
        # Not a failure: a module nobody has been through lays out on
        # reach and shape, as it did before this file existed.
        self.assertIsNone(self.propose().job_of('Wobble Lever'))


class TheOverlaysOnFile(unittest.TestCase):
    """The ones in `overlays/` have to load, or no planner starts."""

    def test_each_one_remembers_its_own_filename(self):
        # What `--overlay` and the menu say, as against the display name
        # out of the file: `f-18.toml` calls itself `F/A-18C`. The menu
        # compares on this, so it does not have to read every overlay in
        # the directory to find out which one is on.
        got = coverlay.named('f-18')
        self.assertEqual('f-18', got.called)
        self.assertEqual('F/A-18C', got.name)

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

    def test_every_function_names_a_job_and_it_is_one_of_the_ten(self):
        # The word an overlay takes hold of. Sixty-five of the hundred and
        # forty-seven said nothing at all, so a template had nothing to
        # match for nearly half the list.
        import glob
        import json
        for path in glob.glob('games/*/*-needs.json'):
            with self.subTest(file=path):
                with open(path, encoding='utf-8') as f:
                    rows = json.load(f)['needs']
                for row in rows:
                    self.assertIn(row.get('suits'), corneeds.JOBS,
                                  row['what'])


if __name__ == '__main__':
    unittest.main()

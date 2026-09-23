"""What `allocate()` promises, held to it.

Nearly every rule in `core/needs.py` carries a comment saying what went wrong
before it existed -- the airbrake that left the thumb, the pinky shift that
lost its pin to the landing lights, the bomb release that landed on a latch.
Those comments are the specification, and each one is a test here: a rule with
a story attached is a rule somebody will be tempted to simplify away.

The hardware is synthetic (see fake.py) so a case can be exactly one thing.
Real captures are too rich to isolate a rule in -- and a test that needs the
author's own stick plugged in is not a test.
"""

import unittest
from unittest import mock

import fake
from core import devmap
from core import needs as corneeds
from core.actions import Bind
from core.needs import (Layout, Need, allocate, dump_needs, read_needs,
                        reach_tier, IN_A_TURN, ON_APPROACH, IN_THE_AIR,
                        ON_THE_RAMP)


def one(placed, what):
    """The placement for a need, by its name.

    Every caller has just asked the allocator to place that need and then
    reads `.ctrl` or `.slots` off the answer, so nothing here is the test
    failing rather than a case to handle -- and saying so once beats an
    Optional at ten call sites.
    """
    p = next((p for p in placed if p.need.what == what), None)
    assert p is not None, f'the allocator placed nothing for {what}'
    return p


class Reach(unittest.TestCase):
    """The floor and the ceiling: WHEN you touch a thing decides how good a
    home it deserves, in both directions."""

    def test_ramp_need_leaves_the_thumb_alone(self):
        # MIN_REACH[ON_THE_RAMP] is 2: without a floor, something you do once
        # with the canopy open takes a thumb position the moment one is free,
        # and the only defence left is hand-sorting the need list.
        #
        # The thumb button here is deliberately the one SCORING would pick
        # -- exact shape beats the panel dial's worse reach -- so the floor
        # is the only thing standing between a ramp switch and the best
        # position on the stick.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.control('dial', 'Panel dial', [1], reach=fake.PANEL),
        ])}
        need = Need('Canopy', 'button', ['CANOPY'], urgency=ON_THE_RAMP)
        placed, unplaced, _free = allocate([need], devs)
        self.assertEqual([], unplaced)
        self.assertEqual('Panel dial', placed[0].ctrl.label)

    def test_urgent_need_will_not_reach_past_the_ceiling(self):
        # MAX_REACH[IN_A_TURN] is 1. A panel control is tier 3.
        devs = {'stick': fake.device('stick', [
            fake.hat2('Panel rocker', 0, reach=fake.PANEL),
        ])}
        placed, unplaced, _free = allocate(
            [Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN)], devs)
        # ...but the relaxed pass lifts it, because a need wanting two buttons
        # has no borrow to fall back on.
        self.assertEqual([], unplaced)
        self.assertTrue(placed[0].need.relaxed)

    def test_ceiling_stays_up_for_a_need_that_could_borrow(self):
        # The lift is only for `wanted > 1`. A one-button need is meant to take
        # a borrowed thumb press over a whole control it must let go to reach,
        # and lifting the ceiling for it made it lose: War Thunder's radar ACM
        # and sight stabilisation left the thumb for the side dials.
        devs = {'stick': fake.device('stick', [
            fake.button('Panel button', 0, reach=fake.PANEL),
        ])}
        placed, unplaced, _free = allocate(
            [Need('Radar ACM', 'button', ['ACM'], urgency=IN_A_TURN)], devs)
        self.assertEqual([], placed)
        self.assertEqual(['Radar ACM'], [n.what for n in unplaced])

    def test_the_least_precious_control_that_fits_takes_the_need(self):
        # score is 100 + 12*tier, so a worse reach scores HIGHER: the good
        # positions stay free for whatever more urgent is still coming.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.button('Panel button', 1, reach=fake.PANEL),
        ])}
        placed, _un, free = allocate(
            [Need('Gear', 'button', ['GEAR'], urgency=IN_THE_AIR)], devs)
        self.assertEqual('Panel button', placed[0].ctrl.label)
        self.assertEqual(['Thumb button'], [c.label for _r, c in free])

    def test_an_unmeasured_reach_sits_below_every_measured_one(self):
        # Not middling: a control nobody has walked the fingers on is one
        # nothing is known about, and a number in the middle would be one
        # nothing could tell from a measurement.
        nobody = fake.device('stick', [fake.button('Nameless', 0)])
        self.assertIsNone(nobody.groups(bindable=True)[0].tier)
        got = reach_tier(nobody.groups(bindable=True)[0])
        furthest = reach_tier(fake.device('stick', [
            fake.button('Panel', 0, reach=fake.PANEL)])
            .groups(bindable=True)[0])
        self.assertGreater(got, furthest)


class Pins(unittest.TestCase):
    """`prefer` is a choice, and a choice has to outrank the ordering as well
    as the ranking or it is not one."""

    def test_a_pin_beats_the_ceiling(self):
        # The pin used to be a +500 bonus applied AFTER the ceiling, so a
        # pinned control the ceiling excluded scored None and the bonus never
        # ran: BMS's pinky shift silently moved to the thumb mini-stick.
        devs = {'stick': fake.device('stick', [
            fake.button('Pinky button', 0, reach=fake.PANEL),
            fake.button('Thumb button', 1, reach=fake.THUMB),
        ])}
        placed, unplaced, _free = allocate(
            [Need('Pinky shift', 'button', ['SHIFT'], urgency=IN_A_TURN,
                  prefer='Pinky button')], devs)
        self.assertEqual([], unplaced)
        self.assertEqual('Pinky button', placed[0].ctrl.label)

    def test_a_pin_is_placed_before_anything_more_urgent(self):
        # BMS's pinky shift lost its pin to the landing lights, because they
        # are touched on approach and it is not.
        # The pinned control is also the one the MORE urgent need would take
        # on score alone, which is the whole point: if urgency is consulted
        # first the pin loses its control and is quietly moved elsewhere.
        devs = {'stick': fake.device('stick', [
            fake.button('Pinky button', 0, reach=fake.PANEL),
            fake.button('Thumb button', 1, reach=fake.THUMB),
        ])}
        needs = [Need('Landing lights', 'button', ['LIGHTS'],
                      urgency=ON_APPROACH),
                 Need('Pinky shift', 'button', ['SHIFT'], urgency=IN_THE_AIR,
                      prefer='Pinky button')]
        placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual([], unplaced)
        self.assertEqual('Pinky button', one(placed, 'Pinky shift').ctrl.label)
        self.assertEqual('Thumb button',
                         one(placed, 'Landing lights').ctrl.label)

    def test_a_pin_cannot_put_four_directions_on_one_button(self):
        # Shape and capacity still have to fit.
        devs = {'stick': fake.device('stick', [
            fake.button('Only button', 0, reach=fake.THUMB),
        ])}
        placed, unplaced, _free = allocate(
            [Need('Trim', 'hat4', ['U', 'R', 'D', 'L'],
                  prefer='Only button')], devs)
        self.assertEqual([], placed)
        self.assertEqual(['Trim'], [n.what for n in unplaced])


class Slots(unittest.TestCase):
    """Which button a binding actually lands on."""

    def test_a_lone_binding_goes_on_the_click_not_the_first_direction(self):
        # On `buttons[0]` it reads as "push the hat left" when the obvious
        # gesture is to press the hat -- and it leaves the click idle.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
        ])}
        placed, _un, _free = allocate(
            [Need('Fire', 'hat4', ['FIRE'])], devs)
        self.assertEqual([(4, 'FIRE')], placed[0].slots)

    def test_on_matches_a_hat_that_names_its_directions_differently(self):
        # A speedbrake is fore/aft whatever hat it lands on; a hat captured as
        # up/down has to answer to forward/back.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB),
        ])}
        placed, _un, _free = allocate(
            [Need('Speedbrake', 'hat4', ['OPEN', 'CLOSE'],
                  on=('forward', 'back'))], devs)
        self.assertEqual([(0, 'OPEN'), (2, 'CLOSE')], placed[0].slots)

    def test_a_None_binding_leaves_that_direction_alone(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB),
        ])}
        placed, _un, _free = allocate(
            [Need('Trim', 'hat4', ['UP', None, 'DOWN', None])], devs)
        self.assertEqual([(0, 'UP'), (2, 'DOWN')], placed[0].slots)

    def test_push_is_appended_when_both_sides_have_one(self):
        devs = {'stick': fake.device('stick', [
            fake.hat2('Rocker', 0, reach=fake.THUMB, push=2),
        ])}
        placed, _un, _free = allocate(
            [Need('Flaps', 'hat2', ['UP', 'DOWN'], push='FLAPS_RESET')], devs)
        self.assertEqual([(0, 'UP'), (1, 'DOWN'), (2, 'FLAPS_RESET')],
                         placed[0].slots)


class NeedsOnDisk(unittest.TestCase):
    """The hand-written list, written down instead.

    147 needs across five games carry 373 judgements nothing derives --
    which band a thing is in, what shape it wants, which device it belongs
    on, what a human wrote about it. They have lived in a Python literal
    since the first commit, so nothing could change one without editing
    code, and nothing has ever had to survive a round trip.

    What is NOT here is the per-context split every game's constructor
    takes -- `air`/`heli`, `plane`/`glob`, `ship`/`map`/`foot`. Those zip
    into the slots and read back off the binds, so writing them too would
    be the same fact twice.
    """

    def back(self, need, also=()):
        (got,) = read_needs(dump_needs([need], also), also)
        return got

    def test_every_judgement_survives(self):
        one = Need('Airbrake', 'hat2', [[Bind('OUT')], [Bind('IN')]],
                   urgency=IN_A_TURN, suits='reflex', dev='throttle',
                   prefer='T1 rocker', on=('forward', 'back'), rank=17,
                   note='held, not tapped')
        got = self.back(one)
        for f in ('what', 'shape', 'urgency', 'suits', 'dev', 'prefer',
                  'on', 'rank', 'note'):
            self.assertEqual(getattr(one, f), getattr(got, f), f)

    def test_the_slots_come_back_in_the_order_they_went(self):
        # A slot's position is which button it lands on. Reordered, a trim
        # hat's directions land on different buttons and nothing raises.
        one = Need('Trim', 'hat4', [[Bind('U')], [Bind('R')],
                                    [Bind('D')], [Bind('L')]])
        self.assertEqual(
            [['U'], ['R'], ['D'], ['L']],
            [[b.action for b in slot] for slot in self.back(one).bindings])

    def test_a_slot_left_alone_stays_left_alone(self):
        # An empty slot means "this direction is not bound", which is not
        # the same as the slot not being there.
        one = Need('Half', 'hat2', [[Bind('UP')], []])
        self.assertEqual([1, 0], [len(s) for s in self.back(one).bindings])

    def test_a_click_survives(self):
        one = Need('Hat', 'hat4', [[Bind('U')]], push=[Bind('CLICK')])
        got = self.back(one)
        self.assertIsNotNone(got.push)

    def test_a_shape_written_as_a_choice_stays_a_choice(self):
        # `('button', 'hat2')` means "a button, or a rocker will do", and
        # JSON gives a list back -- `first_shape` must still be 'button'.
        one = Need('Gear', ('button', 'hat2'), [[Bind('G')]])
        got = self.back(one)
        self.assertEqual('button', got.first_shape)

    def test_a_field_only_one_game_has_is_named_not_bagged(self):
        # BMS alone marks a need as living on the shifted layer. A generic
        # `extra` bag would be the opaque payload this project spent its
        # time removing, so the game says which field it wants carried.
        class Shifted(Need):
            """What BMS's own subclass is, minus everything else."""
            shift = False

        one = Shifted('Pinky shift', 'button', [[Bind('SHIFT')]])
        one.shift = True
        back = read_needs(dump_needs([one], ('shift',)), ('shift',), Shifted)
        self.assertIs(True, back[0].shift)

    def test_a_need_the_allocator_has_touched_comes_back_untouched(self):
        # `relaxed` is set BY a run; it is not a judgement and writing it
        # down would make the next run start from the last one's outcome.
        one = Need('Gear', 'button', [[Bind('G')]])
        one.relaxed = True
        self.assertFalse(self.back(one).relaxed)


class Borrowing(unittest.TestCase):
    """The last pass: a one-button need takes a spare position on a control
    somebody else already owns."""

    def test_a_spare_click_is_lent_to_a_homeless_need(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
        ])}
        needs = [Need('Trim', 'hat4', ['U', 'R', 'D', 'L'],
                      urgency=IN_A_TURN),
                 Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)]
        placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual([], unplaced)
        self.assertEqual([(4, 'FIRE')], one(placed, 'Fire').slots)

    def test_nothing_is_borrowed_for_a_whole_control_need(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
        ])}
        needs = [Need('Trim', 'hat4', ['U', 'R', 'D', 'L']),
                 Need('Flaps', 'hat2', ['UP', 'DOWN'])]
        _placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual(['Flaps'], [n.what for n in unplaced])

    def test_a_latch_lends_its_click(self):
        # The click is a real button and is fair game.
        devs = {'stick': fake.device('stick', [
            fake.latch('Master arm', 0, reach=fake.THUMB, push=2),
        ])}
        needs = [Need('Master arm', 'latch', ['ARM', 'SAFE']),
                 Need('Bomb release', 'button', ['PICKLE'])]
        placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual([], unplaced)
        self.assertEqual([(2, 'PICKLE')], one(placed, 'Bomb release').slots)

    def test_a_latch_never_lends_a_position_even_with_one_going_spare(self):
        # A latch HOLDS whichever position it is in, so a press action
        # borrowed from one fires for as long as the lever sits there. Bomb
        # release landed on the master-arm latch exactly that way.
        #
        # Three positions, two of them bound, and the click taken by the
        # latch's own need: position 2 is genuinely free and must stay so.
        devs = {'stick': fake.device('stick', [
            fake.latch('Master arm', 0, positions=('off', 'on', 'aux'),
                       reach=fake.THUMB, push=3),
        ])}
        needs = [Need('Master arm', 'latch', ['ARM', 'SAFE'], push='TOGGLE'),
                 Need('Bomb release', 'button', ['PICKLE'])]
        placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual([(0, 'ARM'), (1, 'SAFE'), (3, 'TOGGLE')],
                         one(placed, 'Master arm').slots)
        self.assertEqual(['Bomb release'], [n.what for n in unplaced])

    def test_a_latch_with_no_click_lends_nothing_at_all(self):
        # Same spare position, no click to offer instead: the need stays
        # homeless rather than being handed a switch that holds itself down.
        devs = {'stick': fake.device('stick', [
            fake.latch('Master arm', 0, reach=fake.THUMB),
        ])}
        needs = [Need('Master arm', 'latch', ['ARM']),
                 Need('Bomb release', 'button', ['PICKLE'])]
        _placed, unplaced, _free = allocate(needs, devs)
        self.assertEqual(['Bomb release'], [n.what for n in unplaced])

    def test_a_borrowed_button_takes_its_control_out_of_free(self):
        # Free means every button of it is free, not merely that no need
        # chose the control.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
            fake.hat2('Spare rocker', 5, reach=fake.THUMB),
        ])}
        needs = [Need('Trim', 'hat4', ['U', 'R', 'D', 'L']),
                 Need('Fire', 'button', ['FIRE'])]
        placed, _un, free = allocate(needs, devs)
        borrowed = one(placed, 'Fire').ctrl.label
        self.assertNotIn(borrowed, [c.label for _r, c in free])


class Rejections(unittest.TestCase):
    """The reasons a control cannot play a part at all."""

    def test_a_game_may_veto_hardware_it_cannot_address(self):
        # BMS reads only a device's first 32 buttons.
        devs = {'stick': fake.device('stick', [
            fake.button('Low button', 0, reach=fake.PANEL),
            fake.button('High button', 40, reach=fake.PANEL),
        ])}
        needs = [Need('A', 'button', ['A']), Need('B', 'button', ['B'])]
        placed, unplaced, _free = allocate(
            needs, devs, usable=lambda role, c: max(c.bindable_buttons) < 32)
        self.assertEqual(['B'], [n.what for n in unplaced])
        self.assertEqual('Low button', placed[0].ctrl.label)

    def test_too_few_buttons_is_not_a_home(self):
        # A selector is an accepted stand-in for a hat4, so shape does not
        # reject this one -- only capacity does. Without that check the need
        # is placed and the fourth binding is silently dropped.
        devs = {'stick': fake.device('stick', [
            fake.selector('Three-way', 0, positions=3, reach=fake.PANEL),
        ])}
        _placed, unplaced, _free = allocate(
            [Need('Trim', 'hat4', ['U', 'R', 'D', 'L'])], devs)
        self.assertEqual(['Trim'], [n.what for n in unplaced])

    def test_a_substitute_shape_is_accepted_and_the_exact_one_preferred(self):
        # FITS['hat2'] allows a hat4 to stand in, but the real thing scores
        # +20 for being what was asked for.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.PANEL),
            fake.hat2('Panel rocker', 4, reach=fake.PANEL),
        ])}
        placed, _un, _free = allocate(
            [Need('Flaps', 'hat2', ['UP', 'DOWN'])], devs)
        self.assertEqual('Panel rocker', placed[0].ctrl.label)

    def test_an_unwired_control_is_never_offered(self):
        # The firmware reports it; nothing is physically behind it.
        devs = {'stick': fake.device('stick', [
            fake.control('unwired', 'Phantom', [0]),
            fake.button('Real button', 1, reach=fake.PANEL),
        ])}
        placed, _un, _free = allocate(
            [Need('Gear', 'button', ['GEAR'])], devs)
        self.assertEqual('Real button', placed[0].ctrl.label)


class LayoutShape(unittest.TestCase):
    """The one shape every adapter returns. Five of them used to disagree,
    which is why nothing generic could be written over the top."""

    def layout(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.button('Panel button', 1, reach=fake.PANEL),
            fake.hat4('Spare hat', 2, reach=fake.PANEL),
        ])}
        needs = [Need('Gear', 'button', ['GEAR'], urgency=ON_APPROACH),
                 Need('Canopy', 'button', ['CANOPY'], urgency=ON_THE_RAMP),
                 Need('Trim', 'hat8', ['A'] * 8)]
        return Layout(devs, *allocate(needs, devs), axes=[('pitch', 'stick')])

    def test_it_unpacks_in_the_canonical_order(self):
        devices, placed, unplaced, free, axes = self.layout()
        self.assertEqual(['stick'], list(devices))
        self.assertEqual(2, len(placed))
        self.assertEqual(['Trim'], [n.what for n in unplaced])
        self.assertEqual([('pitch', 'stick')], axes)
        self.assertTrue(all(len(f) == 2 for f in free))

    def test_but_swaps_the_placements_and_keeps_the_rest(self):
        # What a reviewer hands a writer: only the accepted bindings go in,
        # and nothing else about the plan changes.
        full = self.layout()
        one = [p for p in full.placed if p.need.what == 'Gear']
        cut = full.but(one)
        self.assertEqual(['Gear'], [p.need.what for p in cut.placed])
        self.assertEqual(full.devices, cut.devices)
        self.assertEqual(full.axes, cut.axes)
        self.assertEqual([n.what for n in full.unplaced],
                         [n.what for n in cut.unplaced])
        self.assertEqual(2, len(full.placed), 'the original is untouched')

    def test_by_device_groups_and_orders_by_urgency(self):
        rows = self.layout().by_device()
        self.assertEqual(['stick'], [role for role, _ps in rows])
        self.assertEqual(['Gear', 'Canopy'],
                         [p.need.what for p in rows[0][1]])

    def test_a_layout_says_what_it_holds(self):
        self.assertIn('2 placed', repr(self.layout()))


class Devices(unittest.TestCase):
    """Which hand a thing belongs in."""

    def test_a_need_pulls_towards_its_own_device(self):
        devs = fake.hotas(
            stick_controls=[fake.button('Stick button', 0, reach=fake.PANEL)],
            throttle_controls=[fake.button('Throttle button', 0,
                                           reach=fake.PANEL)])
        placed, _un, _free = allocate(
            [Need('Speedbrake', 'button', ['SB'], dev='throttle')], devs)
        self.assertEqual('throttle', placed[0].role)


if __name__ == '__main__':
    unittest.main()


class HowFarAControlIs(unittest.TestCase):
    """Measured on the map now, finger by finger, not matched out of prose.

    The old table read the map's own sentences for substrings -- 'thumb',
    'without releasing' -- so the tier a control got depended on the
    wording somebody typed while capturing it.
    """

    def ctrl(self, **kw):
        return fake.device('stick', [fake.button('One', 0, **kw)]) \
            .groups(bindable=True)[0]

    def test_a_measured_reach_is_the_number_the_map_gives(self):
        for reach, tier in ((fake.THUMB, 0), (fake.INDEX, 0),
                            (fake.PINKY, 1), (fake.MIDDLE, 1),
                            (fake.PANEL, 3)):
            with self.subTest(reach=reach):
                self.assertEqual(tier, reach_tier(self.ctrl(reach=reach)))

    def test_an_unmeasured_one_sorts_below_all_of_them(self):
        self.assertGreater(reach_tier(self.ctrl()),
                           reach_tier(self.ctrl(reach=fake.PANEL)))

    def test_it_says_how_it_is_reached_in_words(self):
        said = corneeds.reach_said(self.ctrl(reach=fake.PINKY))
        self.assertIn('pinky', said)
        self.assertIn(corneeds.REACH_MEANS[1], said)

    def test_and_says_nothing_when_nobody_measured(self):
        self.assertEqual('', corneeds.reach_said(self.ctrl()))

    def test_the_nearest_way_of_reaching_it_is_the_one_said(self):
        dev = fake.device('stick', [fake.button('One', 0, reach=fake.PANEL)])
        one = dev.groups(bindable=True)[0]
        one.access = [devmap.load().Spot(part='grip', level='OFF'),
                      devmap.load().Spot(part='grip', level='HOME',
                                         finger='thumb')]
        self.assertEqual(0, reach_tier(one))
        self.assertIn('thumb', corneeds.reach_said(one))


class WhatAnUnmeasuredControlIsAllowed(unittest.TestCase):
    """Placed, but last. Refusing it outright places nothing at all on a
    desk nobody has walked, which reads as a broken planner."""

    def test_it_can_still_take_the_most_urgent_need(self):
        devs = {'stick': fake.device('stick', [fake.button('One', 0)])}
        placed, unplaced, _f = allocate(
            [Need('Fire', 'button', ['F'], urgency=IN_A_TURN)], devs)
        self.assertEqual([], unplaced)
        self.assertEqual('One', placed[0].ctrl.label)

    def test_but_a_measured_one_out_of_the_band_is_still_refused(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Panel', 0, reach=fake.PANEL)])}
        _p, unplaced, _f = allocate(
            [Need('Fire', 'button', ['F'], urgency=IN_A_TURN)], devs)
        self.assertEqual(1, len(unplaced))

    def test_it_is_never_paid_for_being_far_away(self):
        # The reach term rewards the furthest control that still does the
        # job, because that leaves the near ones for something more
        # urgent. An unmeasured one is not known to be far, and paying it
        # anyway is how it beat a thumb button somebody had measured.
        need = Need('Fire', 'button', ['F'], urgency=IN_A_TURN)
        dev = fake.device('stick', [fake.button('Nobody', 0)])
        parts = []
        corneeds.score(dev.groups(bindable=True)[0], need, 'stick',
                       parts=parts)
        self.assertFalse([t for _d, t in parts if 'closer' in t], parts)

    def test_so_a_control_measured_further_off_beats_it(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Nobody measured this', 0),
            fake.button('Stretch', 1, reach=fake.PINKY)])}
        placed, _u, _f = allocate(
            [Need('Gear', 'button', ['GEAR'], urgency=ON_APPROACH)], devs)
        self.assertEqual('Stretch', placed[0].ctrl.label)


class SayingWhatWasNotMeasured(unittest.TestCase):
    """A layout on an unmeasured desk is real but not reach-aware."""

    def layout(self, *controls):
        devs = {'stick': fake.device('stick', list(controls))}
        return corneeds.Layout(devs, *allocate([], devs))

    def test_nothing_measured_says_so(self):
        got = self.layout(fake.button('One', 0), fake.button('Two', 1))
        self.assertEqual((2, 2), got.unmeasured())
        self.assertIn('no control', got.reach_note())

    def test_some_measured_counts_the_rest(self):
        got = self.layout(fake.button('One', 0, reach=fake.THUMB),
                          fake.button('Two', 1))
        self.assertEqual((1, 2), got.unmeasured())
        self.assertIn('1 of 2', got.reach_note())

    def test_all_measured_says_nothing(self):
        got = self.layout(fake.button('One', 0, reach=fake.THUMB))
        self.assertEqual((0, 1), got.unmeasured())
        self.assertEqual('', got.reach_note())


class WhichDeviceIsWhich(unittest.TestCase):
    """The desk says. It used to be guessed from what was plugged in."""

    def desk(self, *devices, name='a desk in a test'):
        dm = devmap.load()
        said = [{'slug': d.slug, 'role': d.kind, 'hand': 'left'}
                for d in devices]
        return dm.Profile({'name': name, 'device': said}, '<test-desk>')

    def test_it_keys_on_the_role_the_desk_gave_it(self):
        dm = devmap.load()
        have = dm.load_all(bare=True)
        rig = dm.Profile({'name': 'x', 'device': [
            {'slug': have[0].slug, 'role': 'collective'}]}, '<x>')
        with mock.patch.object(dm, 'profile', lambda name=None: rig):
            got = devmap.by_role('collective')
        self.assertEqual(['collective'], list(got))
        self.assertEqual(have[0].slug, got['collective'].slug)

    def test_a_device_the_desk_does_not_name_is_not_on_it(self):
        dm = devmap.load()
        have = dm.load_all(bare=True)
        self.assertGreater(len(have), 1, 'needs two captures to be a test')
        rig = dm.Profile({'name': 'x', 'device': [
            {'slug': have[0].slug, 'role': 'stick'}]}, '<x>')
        with mock.patch.object(dm, 'profile', lambda name=None: rig):
            got = devmap.by_role()
        self.assertEqual([have[0].slug], [d.slug for d in got.values()])

    def test_an_empty_desk_says_so_and_claims_nothing_else(self):
        # Never `you have no stick`: the hardware may be plugged in right
        # now, and this has no way of knowing. The desk is what is empty.
        dm = devmap.load()
        rig = dm.Profile({'name': 'Fotel', 'device': []}, '<x>')
        with mock.patch.object(dm, 'profile', lambda name=None: rig):
            with self.assertRaises(SystemExit) as caught:
                devmap.by_role('stick', 'throttle')
        said = str(caught.exception)
        self.assertIn('Fotel', said)
        self.assertIn('nothing on it', said)
        for word in ('stick', 'throttle'):
            with self.subTest(word=word):
                self.assertNotIn(word, said)

    def test_a_desk_that_names_devices_says_which_job_is_unfilled(self):
        dm = devmap.load()
        have = dm.load_all(bare=True)
        rig = dm.Profile({'name': 'Fotel', 'device': [
            {'slug': have[0].slug, 'role': 'collective'}]}, '<x>')
        with mock.patch.object(dm, 'profile', lambda name=None: rig):
            with self.assertRaises(SystemExit) as caught:
                devmap.by_role('stick')
        said = str(caught.exception)
        self.assertIn('stick', said)
        self.assertIn('collective', said)
        self.assertNotIn('nothing on it', said)

    def test_either_way_it_says_how_to_get_out_of_it(self):
        dm = devmap.load()
        for devices in ([], [{'slug': dm.load_all(bare=True)[0].slug,
                              'role': 'collective'}]):
            rig = dm.Profile({'name': 'Fotel', 'device': devices}, '<x>')
            with mock.patch.object(dm, 'profile', lambda name=None: rig):
                with self.assertRaises(SystemExit) as caught:
                    devmap.by_role('stick')
            with self.subTest(devices=len(devices)):
                self.assertIn('capture.py', str(caught.exception))
                self.assertIn('--desk', str(caught.exception))

    def test_no_desk_at_all_says_to_make_one(self):
        dm = devmap.load()
        with mock.patch.object(dm, 'profile', lambda name=None: None):
            with self.assertRaises(SystemExit) as caught:
                devmap.by_role()
        self.assertIn('capture.py', str(caught.exception))

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
from core import solve as csolve
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
            fake.unwired('Phantom', [0]),
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
        one.access = [devmap.load().Spot(role='grip', level='OFF'),
                      devmap.load().Spot(role='grip', level='HOME',
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


class EveryAxisAGamesNamesExists(unittest.TestCase):
    """A game names an axis by the control it is part of and which axis of
    it -- `('stick', 'x')`. It used to be one word, `stick-x`, which said
    the control's kind and the axis's part in it at once; when the map
    stopped spelling it that way the lookups silently found nothing, and
    x4 and Elite quietly lost their flight axes."""

    #: The tables, and where in a row the selector sits.
    TABLES = (('x4', 'AXIS_NEEDS', 2), ('elite', 'AXIS_NEEDS', 3),
              ('falconbms', 'AXIS_NEEDS', 2))

    def rows(self, game, table):
        mod = _plan_module(game)
        if mod is None:
            self.skipTest(f'{game} has no planner on this machine')
        return getattr(mod, table, None), mod

    def test_every_selector_names_a_kind_the_map_knows(self):
        import devicemap
        for game, table, at in self.TABLES:
            rows, _mod = self.rows(game, table)
            if rows is None:
                continue
            for row in rows:
                how = row[at]
                kind = (how[1] if how[0] == 'axis' else None) \
                    if isinstance(how, tuple) else None
                if kind is None and how == 'axis':
                    kind = row[at + 1][0]
                if kind is None:
                    continue
                with self.subTest(game=game, need=row[0]):
                    self.assertIn(kind, devicemap.KINDS)

    def test_no_selector_still_spells_it_as_one_word(self):
        for game, table, at in self.TABLES:
            rows, _mod = self.rows(game, table)
            if rows is None:
                continue
            for row in rows:
                said = repr(row)
                with self.subTest(game=game, need=row[0]):
                    for gone in ('stick-x', 'stick-y', 'mini-stick-x',
                                 'mini-stick-y'):
                        self.assertNotIn(gone, said)


def _plan_module(game):
    """A game's planner, imported the way `bind` imports it."""
    import importlib.util
    import os
    import sys
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games', game, 'plan.py')
    if not os.path.exists(path):
        return None
    here = os.path.dirname(path)
    sys.path.insert(0, here)
    try:
        spec = importlib.util.spec_from_file_location(f'{game}_plan', path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(here)


class TheAxisSelectorsPickTheRightAxis(unittest.TestCase):
    """Naming the kind alone finds the control's FIRST axis, so roll,
    pitch and yaw all landed on the same one. The role is what tells
    them apart, and a lookup that drops it is a lookup that silently
    binds three needs to one stick movement."""

    def rig(self):
        """A stick of three axes and a throttle of two, and nothing else."""
        stick = fake.device('stick', axes=[
            {'index': 0, 'role': 'x'}, {'index': 1, 'role': 'y'},
            {'index': 2, 'role': 'z'}, {'index': 3}], controls=[
            {'kind': 'stick', 'id': 'main', 'label': 'Main stick',
             'axes': [0, 1, 2]},
            {'kind': 'lever', 'id': 'brake', 'label': 'Brake', 'axes': [3]}])
        thr = fake.device('throttle', axes=[
            {'index': 0, 'role': 'x'}, {'index': 1, 'role': 'y'},
            {'index': 2}], controls=[
            {'kind': 'ministick', 'id': 'mini', 'label': 'Mini',
             'axes': [0, 1]},
            {'kind': 'dial', 'id': 'dial', 'label': 'Dial', 'axes': [2]}])
        return {'stick': stick, 'throttle': thr}

    def picked(self, mod, devs, role, row, at):
        """What one selector resolves to, through the GAME's own lookup.

        Not through `Device.axis_of`: the thing under test is the game
        asking, and a test that asks the map directly passes whatever
        the game does with the answer.
        """
        if hasattr(mod, 'axis_of'):
            got = mod.axis_of(devs, role, row[at])
        else:
            got = mod.find_axis(devs[role], row[at], row[at + 1])
        return None if got is None else got.index

    def each_game(self):
        for game, table, at in EveryAxisAGamesNamesExists.TABLES:
            mod = _plan_module(game)
            if mod is not None and hasattr(mod, table):
                yield game, mod, getattr(mod, table), at

    def test_each_axis_of_a_control_is_its_own(self):
        for game, mod, _rows, at in self.each_game():
            devs = self.rig()
            row = ['x', 'stick'] + [None] * 4
            seen = []
            for r in ('x', 'y', 'z'):
                row[at:at + 2] = (['axis', ('stick', r)] if at + 1 < len(row)
                                  and not hasattr(mod, 'axis_of')
                                  else [('axis', 'stick', r), None])
                seen.append(self.picked(mod, devs, 'stick', row, at))
            with self.subTest(game=game):
                self.assertEqual([0, 1, 2], seen)

    def test_a_control_with_one_axis_needs_no_role(self):
        for game, mod, _rows, at in self.each_game():
            devs = self.rig()
            row = ['x', 'stick'] + [None] * 4
            row[at:at + 2] = (['axis', ('lever', '')]
                              if not hasattr(mod, 'axis_of')
                              else [('axis', 'lever', ''), None])
            with self.subTest(game=game):
                self.assertEqual(3, self.picked(mod, devs, 'stick', row, at))

    def test_two_roles_of_one_control_never_land_on_one_axis(self):
        # The regression this guards: naming only the kind gave roll,
        # pitch and yaw the same axis. Not that two needs never share one
        # -- x4 binds the stick for flying and again for walking, which
        # is two contexts and one piece of plastic.
        for game, table, at in EveryAxisAGamesNamesExists.TABLES:
            mod = _plan_module(game)
            if mod is None or not hasattr(mod, table):
                continue
            devs, seen = self.rig(), {}
            for row in getattr(mod, table):
                how = row[at] if isinstance(row[at], tuple) else (
                    (row[at], *row[at + 1]) if row[at] == 'axis' else None)
                if how is None or how[0] != 'axis' or len(how) < 3:
                    continue
                if not how[2]:
                    continue        # one axis, so no role to collide
                if row[1] not in devs:
                    continue
                got = self.picked(mod, devs, row[1], row, at)
                if got is None:
                    continue
                key = (row[1], how[1], got)
                with self.subTest(game=game, need=row[0]):
                    self.assertIn(seen.get(key, how[2]), (how[2],),
                                  f'{how[1]} {seen.get(key)} and {how[2]}'
                                  ' are the same axis')
                seen[key] = how[2]


class TheRulesNameOnlyWordsTheMapProduces(unittest.TestCase):
    """Three tables in `scoring.toml` name shapes and directions, and
    nothing checked them. A shape nobody has -- a typo, or a kind the map
    has since renamed -- simply never matched, and the need asking for it
    went unplaced with no word about why."""

    def rules(self, **over):
        import copy
        got = copy.deepcopy(corneeds.RULES)
        got.update(over)
        return got

    def map_of(self):
        return devmap.load()

    def test_the_rules_on_file_agree_with_the_map(self):
        corneeds.check_rules(corneeds.RULES, self.map_of())

    def test_a_shape_the_map_has_no_word_for(self):
        with self.assertRaises(ValueError) as caught:
            corneeds.check_rules(
                self.rules(shapes={'hat4': ['hat4', 'wobbler']}),
                self.map_of())
        self.assertIn('wobbler', str(caught.exception))

    def test_a_need_shape_nothing_can_be(self):
        with self.assertRaises(ValueError):
            corneeds.check_rules(self.rules(shapes={'wobbler': ['hat4']}),
                                 self.map_of())

    def test_a_mechanism_that_is_not_a_kind(self):
        with self.assertRaises(ValueError):
            corneeds.check_rules(
                self.rules(mechanisms={'one': ['latch', 'wobbler']}),
                self.map_of())

    def test_a_direction_no_control_ever_says(self):
        # This is what it caught on the real file: `forward` and `back`
        # were listed as words a CONTROL might use, and the map has only
        # `fwd` and `aft`. Those entries could never match.
        with self.assertRaises(ValueError) as caught:
            corneeds.check_rules(
                self.rules(directions={'up': ['up', 'forward']}),
                self.map_of())
        self.assertIn('forward', str(caught.exception))

    def test_and_the_real_table_says_only_control_words(self):
        dm = self.map_of()
        ways = set(dm.DIRECTIONS) | {'push'}
        for want, names in corneeds.RULES['directions'].items():
            for one in names:
                with self.subTest(want=want, says=one):
                    self.assertIn(one, ways)

    def test_loading_the_map_is_what_runs_it(self):
        # Checked where both exist, not by whoever remembers to ask: a
        # shape the rules name and the map has never heard of matches
        # nothing, and the only sign is a need at the bottom of the
        # unplaced list.
        with mock.patch.object(corneeds, 'RULES',
                               self.rules(shapes={'wobbler': ['hat4']})):
            with self.assertRaises(ValueError) as caught:
                devmap.load()
        self.assertIn('wobbler', str(caught.exception))

    def test_the_need_side_still_says_what_a_person_would(self):
        # The left side is the word a need uses and is deliberately not
        # the map's: a game asks for `forward`, a hat reports `fwd`.
        self.assertIn('forward', corneeds.RULES['directions'])
        self.assertIn('back', corneeds.RULES['directions'])


class TheSolverIsNeverWorseThanWalkingTheList(unittest.TestCase):
    """Greedy takes the needs in urgency order and gives each the best
    control still free. It cannot undo a choice, so an early urgent need
    takes the one a later need needed more -- and the passes named
    `relaxed` and `borrowed` are what it does instead of backtracking.

    The model decides the whole assignment at once. The judgement is
    unchanged: `score()` still says how well a control plays a part, and
    its number is the objective. So a difference here is one greedy
    could not reach, not a difference of opinion.
    """

    def both(self, needs, devs):
        """(greedy, solver) -- (total points, placed, unplaced) for each."""
        if not csolve.have_it():
            self.skipTest('no ortools here; the solver half cannot run')
        out = []
        for on in (False, True):
            with mock.patch.object(csolve, 'have_it', lambda: on):
                placed, left, _free = allocate(needs, devs)
            out.append((sum(p.points or 0 for p in placed), len(placed),
                        len(left)))
        return out

    def tight(self):
        """Two needs and two controls, where taking the best first loses.

        The urgent need scores well on both; the other only on the one
        the urgent one would take. Walking the list places one of two.
        """
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.hat4('Hat', 1, reach=fake.THUMB)])}
        return [Need('Urgent', ('button', 'hat4'), [[Bind('A')]],
                     urgency=IN_A_TURN, dev='stick'),
                Need('Other', 'button', [[Bind('B')]],
                     urgency=ON_THE_RAMP, dev='stick')], devs

    def test_it_places_at_least_as_many(self):
        needs, devs = self.tight()
        greedy, solver = self.both(needs, devs)
        self.assertGreaterEqual(solver[1], greedy[1])

    def test_and_scores_at_least_as_well(self):
        needs, devs = self.tight()
        greedy, solver = self.both(needs, devs)
        self.assertGreaterEqual(solver[0], greedy[0])

    def test_without_the_solver_it_still_answers(self):
        # ortools is the one dependency outside the standard library in
        # this family. A clone without it gets the greedy layout, which
        # is worse than the best and much better than none.
        needs, devs = self.tight()
        with mock.patch.object(csolve, 'have_it', lambda: False):
            placed, _left, _free = allocate(needs, devs)
        self.assertTrue(placed)

    def test_a_pinned_need_still_gets_its_pin(self):
        # And the pin is the WORSE control, so the ranking would put it
        # elsewhere: a pin that only tips the scales is no use once
        # something outranks it. BMS's pinky shift lost the grip pinky
        # button to the landing lights exactly that way.
        if not csolve.have_it():
            self.skipTest('no ortools here; the solver half cannot run')
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Pinky', 1, reach=fake.PANEL)])}
        needs = [Need('Pinned', 'button', [[Bind('A')]], dev='stick',
                      prefer='Pinky', urgency=IN_A_TURN)]
        loose = Need('Pinned', 'button', [[Bind('A')]], dev='stick',
                     urgency=IN_A_TURN)
        with mock.patch.object(csolve, 'have_it', lambda: True):
            free, _l, _f = allocate([loose], devs)
        self.assertEqual(['Thumb'], [p.ctrl.label for p in free])
        for on in (False, True):
            with mock.patch.object(csolve, 'have_it', lambda on=on: on):
                placed, _left, _free = allocate(needs, devs)
            with self.subTest(solver=on):
                self.assertEqual(['Pinky'], [p.ctrl.label for p in placed])

    def test_no_control_takes_two_needs(self):
        if not csolve.have_it():
            self.skipTest('no ortools here; the solver half cannot run')
        needs, devs = self.tight()
        with mock.patch.object(csolve, 'have_it', lambda: True):
            placed, _left, _free = allocate(needs, devs)
        seen = [(p.role, p.ctrl.id) for p in placed]
        self.assertEqual(len(seen), len(set(seen)))


class WhatTheModelIsNotAllowedToDo(unittest.TestCase):
    """The constraints, each on its own. A dict of results hid two of
    them: a want that came back twice replaced itself, and a room taken
    twice looked like one placement."""

    def setUp(self):
        if not csolve.have_it():
            self.skipTest('no ortools here')

    def test_a_want_takes_one_room(self):
        got = csolve.best([('a', {1: 100, 2: 100})], [1, 2])
        self.assertEqual(1, len(got))

    def test_a_room_takes_one_want(self):
        got = csolve.best([('a', {1: 100}), ('b', {1: 100})], [1])
        self.assertEqual(1, len(got))

    def test_placing_beats_scoring(self):
        # Scores go negative -- a control on the wrong device with no
        # directions and buttons to spare -- and the only home for a
        # need can be one of those. Left unplaced it is a thing you
        # cannot do in the aircraft; placed badly it is a stretch.
        got = csolve.best([('a', {1: -200})], [1])
        self.assertEqual([('a', 1)], got)

    def test_and_it_still_prefers_the_better_room(self):
        got = csolve.best([('a', {1: 10, 2: 90})], [1, 2])
        self.assertEqual([('a', 2)], got)

    def test_it_gives_up_the_better_room_to_place_two(self):
        # The whole reason for the model: walking the list gives `a` the
        # 90 and leaves `b` nowhere.
        got = dict(csolve.best([('a', {1: 10, 2: 90}), ('b', {2: 90})],
                               [1, 2]))
        self.assertEqual({'a': 1, 'b': 2}, got)


class APinIsAConstraintAndNotABigNumber(unittest.TestCase):
    """It is worth +1000 as well, which outranks anything -- until the
    model can place one more need by moving it. Then a number loses and
    a constraint does not, and an explicit choice that the solver may
    trade away is not a choice."""

    def setUp(self):
        if not csolve.have_it():
            self.skipTest('no ortools here')

    def rig(self):
        """Two buttons. The pinned need fits either; the other fits only
        the pinned one, so placing both means breaking the pin."""
        devs = {'stick': fake.device('stick', [
            fake.button('Pin', 0, reach=fake.THUMB),
            fake.button('Spare', 1, reach=fake.THUMB)])}
        return [Need('Mine', 'button', [[Bind('A')]], dev='stick',
                     prefer='Pin', urgency=IN_A_TURN),
                Need('Other', 'button', [[Bind('B')]], dev='stick',
                     prefer='Pin', urgency=ON_THE_RAMP)], devs

    def test_the_pin_holds_even_where_breaking_it_places_more(self):
        needs, devs = self.rig()
        placed, left, _free = allocate(needs, devs)
        mine = next(p for p in placed if p.need.what == 'Mine')
        self.assertEqual('Pin', mine.ctrl.label)

    def test_and_the_other_is_told_rather_than_moved_quietly(self):
        needs, devs = self.rig()
        placed, _left, _free = allocate(needs, devs)
        other = next((p for p in placed if p.need.what == 'Other'), None)
        # Either left for the relaxed pass or put somewhere else -- but
        # never on the pin, which is somebody else's.
        if other is not None:
            self.assertNotEqual('Pin', other.ctrl.label)

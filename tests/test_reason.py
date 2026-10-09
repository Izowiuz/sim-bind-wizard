"""Why a binding is where it is, written down where the decision is made.

A score is a comparison. An explanation is not. A reader that wants the
second out of the first reverse-engineers it, and a reader that asks
`p.points == 200` holds a sentinel nobody dares change.

A `Reason` is written by the code that just decided, at the moment it
decided. Five things decide: a pin, the floored pass, the relaxed pass,
the share pass, and a hand on the review screen.

The arithmetic test keeps the others honest. `score()` is a sum of named
terms and a reason is the terms that fired, so the moment they stop adding
up to the score the explanation describes a run that did not happen.
"""

import unittest

import fake
from core import actions as cactions
from core.actions import Bind

from core import needs as corneeds
from core import review
from core.needs import (Layout, Need, allocate,
                        IN_A_TURN, IN_THE_AIR, ON_THE_RAMP)


def why(placed, what):
    """The reason for a need, by its name."""
    p = next((p for p in placed if p.need.what == what), None)
    assert p is not None, f'the allocator placed nothing for {what}'
    return p.why


def now(rv, need):
    """The reason on whatever this need is sitting on at the moment."""
    p = rv.at[need]
    assert p is not None, f'{need.what} is on nothing'
    assert p.why is not None, f'{need.what} is placed with no reason'
    return p.why


def said(reason):
    """Just the words, for a test that does not care about the numbers."""
    return ' · '.join(t for _d, t in reason.parts)


class TheArithmetic(unittest.TestCase):
    """The reason and the score are the same event described twice."""

    def test_the_parts_add_up_to_the_score(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
            fake.button('Panel button', 5, reach=fake.PANEL),
        ])}
        placed, _u, _f = allocate([
            Need('Trim', 'hat4', ['U', 'R', 'D', 'L'],
                 urgency=IN_A_TURN, device='stick'),
            Need('Canopy', 'button', ['CANOPY'], urgency=ON_THE_RAMP)], devs)
        for p in placed:
            self.assertEqual(p.points, sum(d for d, _t in p.why.parts),
                             f'{p.need.what}: {said(p.why)}')

    def test_a_shared_button_adds_up_too(self):
        # The share pass is scored by its own rows, and the polarity of
        # the reach term is flipped there. So it is a second sum to get
        # wrong.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4,
                      hold_ok=True, blind_distinct=0),
        ])}
        fire = Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)
        setattr(fire, 'held', True)
        setattr(fire, 'by_feel', True)
        placed, _u, _f = allocate([
            Need('Trim', 'hat4', ['U', 'R', 'D', 'L'], urgency=IN_A_TURN),
            fire], devs)
        p = next(p for p in placed if p.need.what == 'Fire')
        self.assertEqual('shared', p.why.how)
        self.assertEqual(p.points, sum(d for d, _t in p.why.parts))
        said = [t for _d, t in p.why.parts]
        self.assertIn('you can hold it', said)
        self.assertIn('you cannot find it by feel', said)

    def test_every_part_says_what_it_was_for(self):
        # A list of bare numbers is what this replaces.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB)])}
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        for delta, text in why(placed, 'Fire').parts:
            self.assertIsInstance(delta, int)
            self.assertTrue(text.strip(), 'a part with no words')


    def test_explaining_the_winner_does_not_change_it(self):
        # The reason comes from scoring the winning control a SECOND
        # time, with the terms collected, so the hot loop stays a
        # comparison between numbers.
        #
        # That is honest only while `score()` is pure. An impure one has
        # the explanation describe a different run from the decision, and
        # every other test here still passes.
        devs = fake.hotas(
            [fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
             fake.button('Pinky button', 5, reach=fake.PINKY)],
            [fake.button('Panel button', 0, reach=fake.PANEL)])
        need = Need('Trim', 'hat4', ['U', 'R', 'D', 'L'],
                    urgency=IN_A_TURN, device='stick')
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Thumb hat')
        quiet = corneeds.score(ctrl, need, 'stick')
        loud_parts = []
        loud = corneeds.score(ctrl, need, 'stick', parts=loud_parts)
        self.assertEqual(quiet, loud)
        self.assertEqual(quiet, sum(d for d, _t in loud_parts))


class ABindKnowsWhereItIs(unittest.TestCase):
    """The assignment, not the payload.

    A `Bind` that names an action and nothing else leaves where it ended
    up one level up, in the `Placement`, and every reader walks down to
    it. A bind carries its own role, its own button and its own account.
    """

    def placed(self, need=None, devs=None):
        devs = devs or {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4)])}
        need = need or Need('Trim', 'hat4', [[Bind(x)] for x in 'URDL'],
                            urgency=IN_A_TURN)
        placed, _u, _f = allocate([need], devs)
        return placed[0]

    def test_every_bind_says_which_device_and_which_button(self):
        p = self.placed()
        for button, slot in p.slots:
            for b in slot:
                self.assertEqual(p.role, b.role)
                self.assertEqual(button, b.button)

    def test_every_bind_carries_its_own_account(self):
        for _button, slot in self.placed().slots:
            for b in slot:
                self.assertIsNotNone(b.reason)

    def test_the_binds_of_one_hat_agree_about_the_control(self):
        # They share it, so they say the same thing about it.
        p = self.placed()
        said = {tuple(b.reason.parts)
                for _n, slot in p.slots for b in slot if b.reason}
        self.assertEqual(1, len(said))

    def test_where_it_landed_is_not_written_down_as_a_judgement(self):
        # `role`, `button` and `reason` are what a RUN worked out, like
        # `Need.relaxed`. A judgements file that remembered them starts
        # the next run from the last one's answer.
        p = self.placed()
        b = p.slots[0][1][0]
        self.assertEqual([{'action': b.action}], cactions.dump_binds([b]))


class WhichPass(unittest.TestCase):
    """Four ways in, and the screen does not guess which."""

    def test_a_pin_says_it_was_pinned(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.button('Pinky button', 1, reach=fake.PINKY),
        ])}
        placed, _u, _f = allocate(
            [Need('Shift', 'button', ['SHIFT'], urgency=IN_THE_AIR,
                  prefer='Pinky button')], devs)
        self.assertEqual('pinned', why(placed, 'Shift').how)

    def test_an_ordinary_placement_says_the_floor_held(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB)])}
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        self.assertEqual('floored', why(placed, 'Fire').how)

    def test_the_relaxed_pass_says_the_floor_came_off(self):
        # `MAX_REACH[IN_A_TURN]` is 1 and a panel control is tier 3, so
        # this lands once the ceiling is lifted.
        devs = {'stick': fake.device('stick', [
            fake.hat2('Panel rocker', 0, reach=fake.PANEL)])}
        placed, _u, _f = allocate(
            [Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN)],
            devs)
        self.assertEqual('relaxed', why(placed, 'Airbrake').how)

    def test_a_shared_button_says_it_was_shared(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4)])}
        placed, _u, _f = allocate([
            Need('Trim', 'hat4', ['U', 'R', 'D', 'L'], urgency=IN_A_TURN),
            Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        self.assertEqual('shared', why(placed, 'Fire').how)


class WhatItNames(unittest.TestCase):
    """The terms a person would ask about, in words rather than deltas."""

    def test_it_names_the_device_the_need_asked_for(self):
        devs = fake.hotas(
            [fake.button('Thumb button', 0, reach=fake.THUMB)],
            [fake.button('Throttle button', 0, reach=fake.THUMB)])
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN,
                  device='stick')], devs)
        self.assertIn('stick', said(why(placed, 'Fire')))

    def test_it_records_the_reach_it_took_and_the_one_allowed(self):
        # `in a turn` may reach to tier 1 with the floor on. Without both
        # numbers, "reached past the floor" is a claim with nothing behind
        # it.
        devs = {'stick': fake.device('stick', [
            fake.hat2('Panel rocker', 0, reach=fake.PANEL)])}
        placed, _u, _f = allocate(
            [Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN)],
            devs)
        r = why(placed, 'Airbrake')
        self.assertEqual(3, r.tier)
        self.assertGreater(r.tier, 1)


class ByHand(unittest.TestCase):
    """The fifth decider is a person. That is the one the screen says out
    loud."""

    def made(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.button('Panel button', 1, reach=fake.PANEL),
        ])}
        needs = [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)]
        lay = Layout(devs, *allocate(needs, devs))
        return review.Review(lay, 'Test'), needs[0], devs

    def test_the_planners_own_choice_is_not_yours(self):
        rv, need, _devs = self.made()
        self.assertNotEqual('yours', now(rv, need).how)

    def test_moving_it_by_hand_says_a_hand_did_it(self):
        rv, need, devs = self.made()
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(need, 'stick', ctrl)
        self.assertEqual('yours', now(rv, need).how)

    def test_moving_it_by_hand_keeps_what_the_planner_wanted(self):
        # The override mention on the detail panel is this field. `at`
        # compared against `plan` at drawing time gives the same answer
        # until something else moves a placement.
        rv, need, devs = self.made()
        was = rv.at[need]
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(need, 'stick', ctrl)
        self.assertIs(was, now(rv, need).instead)

    def test_a_hand_that_confirms_the_planner_has_nothing_to_undo(self):
        # Assigning what was already there is not an override. "Moved
        # from Thumb button" about a binding on the thumb button is the
        # screen arguing with the person reading it.
        rv, need, devs = self.made()
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Thumb button')
        rv.assign(need, 'stick', ctrl)
        self.assertIsNone(now(rv, need).instead)


class TheAccount(unittest.TestCase):
    """One description of a placement, for six games.

    One copy per game is about forty lines each, and every copy reads the
    same fields: the band, the floor, the pin, the note.

    What stays a game's own is what only it knows: Falcon BMS's DX number,
    X4's slot. The game appends those. It does not reassemble this.
    """

    def bits(self, need, devs=None):
        devs = devs or {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.hat2('Panel rocker', 1, reach=fake.PANEL)])}
        placed, _u, _f = allocate([need], devs)
        return corneeds.why_bits(placed[0])

    def test_it_names_the_band(self):
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN))
        self.assertIn('in a turn', got)

    def test_nobody_elses_profiles_are_in_the_account(self):
        # A line like "9 of 13 factory profiles bind it" gives every game
        # its own denominator: Elite 13 presets, Falcon BMS 22 vendor
        # profiles, War Thunder 29. Those profiles rank somebody else's
        # hardware, so neither the count nor the sentence is here.
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN))
        self.assertFalse(any('factory' in b or 'profile' in b for b in got),
                         got)

    def test_it_says_when_the_floor_came_off(self):
        got = self.bits(
            Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN),
            devs={'stick': fake.device('stick', [
                fake.hat2('Panel rocker', 0, reach=fake.PANEL)])})
        self.assertTrue(any('floor' in b for b in got), got)

    def test_it_carries_the_terms_the_score_was_made_of(self):
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN))
        self.assertTrue(any('exact shape' in b for b in got), got)

    def test_it_says_when_a_hand_chose_it(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB),
            fake.button('Panel button', 1, reach=fake.PANEL)])}
        needs = [Need('Fire', 'button', ['F'], urgency=IN_A_TURN)]
        rv = review.Review(Layout(devs, *allocate(needs, devs)), 'Test')
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(needs[0], 'stick', ctrl)
        p = rv.at[needs[0]]
        assert p is not None
        self.assertTrue(any('you' in b for b in corneeds.why_bits(p)))

    def test_a_placement_with_no_reason_still_says_the_band(self):
        # A planner may build one itself. A screen degrades rather than
        # fails, and the band is a fact about the need rather than about
        # the run.
        need = Need('Gun', 'button', ['F'], urgency=IN_A_TURN)
        ctrl = fake.device('stick', [
            fake.button('Trigger', 0)]).groups(bindable=True)[0]
        p = corneeds.Placement(need, 'stick', ctrl, [(0, ['F'])], 0)
        self.assertIn('in a turn', corneeds.why_bits(p))


if __name__ == '__main__':
    unittest.main()

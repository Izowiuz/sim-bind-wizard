"""Why a binding is where it is, written down where the decision is made.

`Placement.points` reached the Layout and two readers tried to get a reason
back out of it. BMS prints it. DCS asks `p.points == 200`, and its own
docstring owns up: "the claim marker `place()` sets, and it was the same
magic number before". A score is a comparison; an explanation is not, and
the moment somebody wants the second they start reverse-engineering the
first.

A `Reason` is written by the code that just decided, at the moment it
decided. Five things decide: a pin, the floored pass, the relaxed pass, the
borrow pass, and a hand on the review screen.

The arithmetic test is the one that keeps the others honest. `score()` is a
sum of named terms and a reason is the terms that fired, so the moment they
stop adding up to the score the explanation is describing a run that did
not happen.
"""

import os
import unittest

import fake
from core import adapter
from core import actions as cactions
from core.actions import Bind

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
                 urgency=IN_A_TURN, dev='stick'),
            Need('Canopy', 'button', ['CANOPY'], urgency=ON_THE_RAMP)], devs)
        for p in placed:
            self.assertEqual(p.points, sum(d for d, _t in p.why.parts),
                             f'{p.need.what}: {said(p.why)}')

    def test_a_borrowed_button_adds_up_too(self):
        # The borrow pass scores by its own formula -- the polarity of the
        # reach term is flipped -- so it is a second sum to get wrong.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
        ])}
        placed, _u, _f = allocate([
            Need('Trim', 'hat4', ['U', 'R', 'D', 'L'], urgency=IN_A_TURN),
            Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        p = next(p for p in placed if p.need.what == 'Fire')
        self.assertEqual(p.points, sum(d for d, _t in p.why.parts))

    def test_every_part_says_what_it_was_for(self):
        # A list of bare numbers is the thing being replaced.
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB)])}
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        for delta, text in why(placed, 'Fire').parts:
            self.assertIsInstance(delta, int)
            self.assertTrue(text.strip(), 'a part with no words')


    def test_explaining_the_winner_does_not_change_it(self):
        # The reason is got by scoring the winning control a SECOND time,
        # with the terms collected, so the hot loop can stay a comparison
        # between numbers. That is only honest while `score()` is pure: an
        # impure one would have the explanation describe a different run
        # from the decision, and every other test here would still pass.
        devs = fake.hotas(
            [fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
             fake.button('Pinky button', 5, reach=fake.PINKY)],
            [fake.button('Panel button', 0, reach=fake.PANEL)])
        need = Need('Trim', 'hat4', ['U', 'R', 'D', 'L'],
                    urgency=IN_A_TURN, dev='stick', suits='trim')
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Thumb hat')
        quiet = corneeds.score(ctrl, need, 'stick')
        loud_parts = []
        loud = corneeds.score(ctrl, need, 'stick', parts=loud_parts)
        self.assertEqual(quiet, loud)
        self.assertEqual(quiet, sum(d for d, _t in loud_parts))


class WhyThatButton(unittest.TestCase):
    """The second question, which nothing recorded.

    A hat gives four binds and they share a control, so they share every
    word of the account so far -- the band, the pass, the score. What
    differs between them is which BUTTON each landed on, and `slots_for`
    decides that by three rules and writes none of them down. Four
    identical explanations for four different bindings is worse than none:
    it looks like an answer.
    """

    def why_of(self, need, ctrl):
        said = []
        got = corneeds.slots_for(need, ctrl, why=said)
        self.assertEqual(len(got), len(said),
                         'one reason per button, or the pairing is a guess')
        return dict(zip(got, [t for _b, t in said]))

    def hat(self, push=None):
        return fake.device('stick', [
            fake.hat4('Thumb hat', 0, push=push)]).groups(bindable=True)[0]

    def test_a_lone_action_says_it_took_the_click(self):
        got = self.why_of(Need('Fire', 'hat4', [[Bind('F')]]),
                          self.hat(push=4))
        self.assertIn('click', got[4])

    def test_a_named_direction_says_which_one(self):
        need = Need('Speedbrake', 'hat4', [[Bind('OUT')], [Bind('IN')]],
                    on=('forward', 'back'))
        got = self.why_of(need, self.hat())
        self.assertIn('forward', got[0])
        self.assertIn('back', got[2])

    def test_press_order_says_it_is_press_order(self):
        need = Need('Trim', 'hat4', [[Bind(x)] for x in 'URDL'])
        got = self.why_of(need, self.hat())
        self.assertTrue(any('order' in t for t in got.values()), got)

    def test_directions_that_could_not_be_honoured_say_so(self):
        # `slots_for` falls back to press order in silence, so a four-way
        # need on a five-position selector landed on '1'..'4' while the
        # need still claimed it was bound fore and aft.
        sel = fake.device('stick', [
            fake.selector('Mode', 0, positions=5)]).groups(bindable=True)[0]
        need = Need('Speedbrake', 'selector',
                    [[Bind('OUT')], [Bind('IN')]], on=('forward', 'back'))
        got = self.why_of(need, sel)
        self.assertTrue(any('forward' in t and 'not' in t.lower()
                            for t in got.values()), got)


class ABindKnowsWhereItIs(unittest.TestCase):
    """The assignment, not the payload.

    A `Bind` named an action and nothing else, so where it ended up lived
    one level up in the `Placement` and every reader had to walk down to
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
        # They share it, so they had better say the same thing about it.
        p = self.placed()
        said = {tuple(b.reason.parts)
                for _n, slot in p.slots for b in slot if b.reason}
        self.assertEqual(1, len(said))

    def test_nothing_surprising_is_said_once_not_four_times(self):
        # Four binds that all arrived by press order arrived by press
        # order. Four spellings of that bury the one line that would say
        # otherwise.
        p = self.placed()
        spots = {b.reason.spot for _n, slot in p.slots for b in slot
                 if b.reason}
        # One distinct sentence, not its exact wording: this test is about
        # repetition, and pinning the prose made it break when the words
        # went man-terse and the rule had not moved.
        self.assertEqual(1, len(spots), spots)

    def test_a_direction_the_control_renames_says_so_per_button(self):
        # A speedbrake is fore/aft whatever hat it lands on. Landing
        # "forward" on a button the map calls "up" is the thing a reader
        # would otherwise have to work out from the hardware.
        need = Need('Speedbrake', 'hat4', [[Bind('OUT')], [Bind('IN')]],
                    on=('forward', 'back'), urgency=IN_A_TURN)
        p = self.placed(need=need)
        spots = {b.reason.spot for _n, slot in p.slots for b in slot
                 if b.reason}
        self.assertEqual(2, len(spots), spots)
        self.assertTrue(all('forward' in t or 'back' in t for t in spots),
                        spots)

    def test_where_it_landed_is_not_written_down_as_a_judgement(self):
        # `role`, `button` and `reason` are what a RUN worked out, like
        # `Need.relaxed`. A judgements file that remembered them would
        # have the next run start from the last one's answer.
        p = self.placed()
        b = p.slots[0][1][0]
        self.assertEqual([{'action': b.action}], cactions.dump_binds([b]))


class WhichPass(unittest.TestCase):
    """Four ways in, and the screen should not have to guess which."""

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
        # MAX_REACH[IN_A_TURN] is 1 and a panel control is tier 3, so this
        # only lands once the ceiling is lifted.
        devs = {'stick': fake.device('stick', [
            fake.hat2('Panel rocker', 0, reach=fake.PANEL)])}
        placed, _u, _f = allocate(
            [Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN)],
            devs)
        self.assertEqual('relaxed', why(placed, 'Airbrake').how)

    def test_a_borrowed_button_says_it_was_borrowed(self):
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4)])}
        placed, _u, _f = allocate([
            Need('Trim', 'hat4', ['U', 'R', 'D', 'L'], urgency=IN_A_TURN),
            Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN)], devs)
        self.assertEqual('borrowed', why(placed, 'Fire').how)


class WhatItNames(unittest.TestCase):
    """The terms a person would ask about, in words rather than deltas."""

    def test_it_names_the_device_the_need_asked_for(self):
        devs = fake.hotas(
            [fake.button('Thumb button', 0, reach=fake.THUMB)],
            [fake.button('Throttle button', 0, reach=fake.THUMB)])
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN,
                  dev='stick')], devs)
        self.assertIn('stick', said(why(placed, 'Fire')))

    def test_it_names_the_suits_tag_that_matched(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB,
                        suits=['gunnery'])])}
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['FIRE'], urgency=IN_A_TURN,
                  suits='gunnery')], devs)
        self.assertIn('gunnery', said(why(placed, 'Fire')))

    def test_it_records_the_reach_it_took_and_the_one_allowed(self):
        # `in a turn` may reach to tier 1 with the floor on. Without both
        # numbers "reached past the floor" is a claim with nothing behind it.
        devs = {'stick': fake.device('stick', [
            fake.hat2('Panel rocker', 0, reach=fake.PANEL)])}
        placed, _u, _f = allocate(
            [Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN)],
            devs)
        r = why(placed, 'Airbrake')
        self.assertEqual(3, r.tier)
        self.assertGreater(r.tier, 1)


class ByHand(unittest.TestCase):
    """The fifth decider is a person, and that is the one the screen has to
    say out loud."""

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
        # The override mention on the detail panel is this field. Comparing
        # `at` against `plan` at drawing time gets the same answer only
        # until something else moves a placement.
        rv, need, devs = self.made()
        was = rv.at[need]
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(need, 'stick', ctrl)
        self.assertIs(was, now(rv, need).instead)

    def test_a_hand_that_confirms_the_planner_has_nothing_to_undo(self):
        # Assigning what was already there is not an override, and saying
        # "moved from Thumb button" about a binding on the thumb button
        # would be the screen arguing with the person reading it.
        rv, need, devs = self.made()
        ctrl = next(c for c in devs['stick'].groups(bindable=True)
                    if c.label == 'Thumb button')
        rv.assign(need, 'stick', ctrl)
        self.assertIsNone(now(rv, need).instead)


class TheAccount(unittest.TestCase):
    """One description of a placement, for the six that had their own.

    `show(why=True)` is about 199 lines across the family -- roughly forty
    per game -- and every one of them reads the same fields: the band, the
    floor, the pin, the note. It is the same paragraph written six times,
    and the sixth copy is the one the rule forbids.

    What stays a game's own is what only it knows: War Thunder's factory
    count, BMS's DX number, X4's slot. Those are appended, not reassembled.
    """

    def bits(self, need, devs=None):
        devs = devs or {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB,
                        suits='gunnery'),
            fake.hat2('Panel rocker', 1, reach=fake.PANEL)])}
        placed, _u, _f = allocate([need], devs)
        return corneeds.why_bits(placed[0])

    def test_it_names_the_band(self):
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN))
        self.assertIn('in a turn', got)

    def test_the_denominator_is_the_games_to_give(self):
        # Elite counts out of 13 presets, BMS out of 22 vendor profiles,
        # War Thunder out of 29. The count is a shared field; what it is a
        # count OF is not, and six games saying it their own way was six
        # ways to say the same number.
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN,
                             rank=9))
        self.assertTrue(any('9 factory' in b for b in got), got)
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb button', 0, reach=fake.THUMB)])}
        placed, _u, _f = allocate(
            [Need('Fire', 'button', ['F'], urgency=IN_A_TURN, rank=9)], devs)
        self.assertTrue(any('9/13' in b
                            for b in corneeds.why_bits(placed[0], out_of=13)))

    def test_it_says_when_the_floor_came_off(self):
        got = self.bits(
            Need('Airbrake', 'hat2', ['OUT', 'IN'], urgency=IN_A_TURN),
            devs={'stick': fake.device('stick', [
                fake.hat2('Panel rocker', 0, reach=fake.PANEL)])})
        self.assertTrue(any('floor' in b for b in got), got)

    def test_it_carries_the_terms_the_score_was_made_of(self):
        got = self.bits(Need('Fire', 'button', ['F'], urgency=IN_A_TURN,
                             suits='gunnery'))
        self.assertTrue(any('suits gunnery' in b for b in got), got)

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
        # A planner may build one itself; a screen should degrade, not
        # crash, and the band is a fact about the need rather than the run.
        need = Need('Gun', 'button', ['F'], urgency=IN_A_TURN)
        ctrl = fake.device('stick', [
            fake.button('Trigger', 0)]).groups(bindable=True)[0]
        p = corneeds.Placement(need, 'stick', ctrl, [(0, ['F'])], 0)
        self.assertIn('in a turn', corneeds.why_bits(p))


class TheClaimMarker(unittest.TestCase):
    """The sentinel this record exists to retire.

    DCS builds some placements itself -- a trigger it claims outright,
    past the allocator -- and marked them by scoring them exactly 200 so it
    could find them again. `rows()` says so: "the claim marker `place()`
    sets, and it was the same magic number before". A number chosen to
    carry a meaning is a number nobody can change, and it is wrong the
    moment the allocator happens to score 200 honestly.
    """

    def rows_for(self, claimed_points):
        propose = adapter.from_file(
            'dcs_propose_under_test',
            os.path.join(REPO, 'games', 'dcs', 'propose.py'))
        devs = {'stick': fake.device('stick', [
            fake.trigger('Trigger', 0, reach=fake.INDEX),
            fake.button('Pinky button', 2, reach=fake.PINKY)])}
        ctrls = {c.label: c for c in devs['stick'].groups(bindable=True)}
        claim = corneeds.Placement(
            Need('Gun', 'trigger', ['FIRE']), 'stick', ctrls['Trigger'],
            [(0, ['FIRE'])], claimed_points,
            corneeds.Reason('claimed', points=claimed_points))
        ordinary = corneeds.Placement(
            Need('Gear', 'button', ['GEAR']), 'stick',
            ctrls['Pinky button'], [(2, ['GEAR'])], 137,
            corneeds.Reason('floored', points=137))
        layout = Layout(devs, [ordinary, claim], [], [])
        return [n.what for n, _spot, _s in propose.rows(layout)]

    def test_a_claim_is_found_by_what_it_says_not_by_its_score(self):
        # 201 rather than 200: the placement is the same claim, and a
        # listing that reorders because the number moved is reading the
        # wrong field.
        self.assertEqual(['Gun', 'Gear'], self.rows_for(201))

    def test_the_old_number_still_sorts_the_same_way(self):
        self.assertEqual(['Gun', 'Gear'], self.rows_for(200))


if __name__ == '__main__':
    unittest.main()

"""The review's bookkeeping, without a terminal.

`core/review.py` is two things bolted together: what the reviewer decided, and
how it is drawn. Only the first has anything to get wrong, and it is the half
that decides what ends up in the game's config -- so it is the half kept
outside the curses loop and tested here.

The rules under test are DCS's, because this table is its `run_table`
generalised: three states rather than two, proposing fills gaps and never
overwrites, choosing by hand needs no confirming, and `?` is a note to
yourself rather than a filter.
"""

import curses
import os
import re
import unittest

import fake
from core.actions import Action, Bind
from core import needs as corneeds
from core import review
from core import tui as ctui
from core.review import UNSET, PROPOSED, MINE, MARK
from core.needs import Layout, Need, allocate, IN_A_TURN, ON_THE_RAMP


def stick(*controls):
    return {'stick': fake.device('stick', list(controls))}


DEVS = lambda: stick(                                        # noqa: E731
    fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
    fake.button('Pinky button', 5, reach=fake.PINKY),
    fake.button('Panel button', 6, reach=fake.PANEL),
    fake.hat2('Panel rocker', 7, reach=fake.PANEL),
)

def plan():
    """Fresh needs every time, which is not fussiness.

    `allocate` writes `relaxed` onto a need and a reviewer writes
    `category`, so a module-level list is one set of objects shared by
    every test in the file -- and one test filing something under
    "Combat" put it there for all the others. It cost two failures in
    tests that were right.
    """
    return [Need('Trim', 'hat4',
                 [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]],
                 urgency=IN_A_TURN),
            Need('Gear', 'button', [[Bind('GEAR')]]),
            Need('Canopy', 'button', [[Bind('CANOPY')]],
                 urgency=ON_THE_RAMP)]


def made(needs=None, devs=None, **kw):
    devs = devs or DEVS()
    lay = Layout(devs, *allocate(list(needs or plan()), devs),
                 axes=[('pitch', 'stick')])
    return review.Review(lay, 'Test', 'fake hardware', **kw)


def map_text(rv):
    """The map screen as one string. It comes back as (tone, text) pairs,
    and most of these tests are asking about the text."""
    return '\n'.join(text for _tone, text in rv.map_lines())


def map_tone(rv, word):
    """The tone of the first map line mentioning `word`."""
    return next(tone for tone, text in rv.map_lines() if word in text)


def by(rv, what):
    return next(n for n in rv.needs if n.what == what)


def at(rv, need):
    """Where a need ended up.

    Every caller has just put it somewhere and then reads the control off
    the answer, so nothing is this test failing rather than a case to
    handle. Saying that once beats an Optional at two dozen call sites.
    """
    p = rv.at[need]
    assert p is not None, f'{need.what} is sitting on nothing'
    return p


def owns(rv, role, button):
    """The control owning a raw kernel button number.

    Every caller names a button the fake map has, so None is the test
    failing rather than an answer worth asserting on.
    """
    c = rv.control_at(role, button)
    assert c is not None, f'the map has no button {button} on the {role}'
    return c


def refused(rv, need, role, ctrl):
    """Why this need may not go on this control.

    `why_not` answers None for one that may, and every caller here is about
    a refusal -- so None is the test failing, not an answer to assert on.
    """
    no = rv.why_not(need, role, ctrl)
    assert no is not None, f'{need.what} was allowed onto it'
    return no


class Starting(unittest.TestCase):
    def test_a_plan_arrives_proposed_and_not_yours(self):
        # Nothing to confirm is nothing to review: the whole point of the
        # screen is that the planner's output has not been looked at yet.
        rv = made()
        self.assertEqual([PROPOSED] * 3, [rv.mark[n] for n in rv.needs])
        self.assertEqual((0, 3, 0), rv.counts())

    def test_a_need_it_could_not_place_starts_unset(self):
        rv = made([Need('Trim', 'hat8', [[Bind('A')]] * 8)])
        self.assertEqual(UNSET, rv.mark[by(rv, 'Trim')])
        self.assertEqual('(unset)', rv.where(by(rv, 'Trim')))
        self.assertEqual((0, 0, 1), rv.counts())

    def test_every_need_is_a_row_whether_it_has_a_control_or_not(self):
        rv = made(plan() + [Need('Trim8', 'hat8', [[Bind('A')]] * 8)])
        self.assertEqual(4, len([r for r in rv.rows() if r.kind == 'need']))


class Confirming(unittest.TestCase):
    def test_confirming_makes_it_yours(self):
        rv = made()
        rv.confirm(by(rv, 'Gear'))
        self.assertEqual(MINE, rv.mark[by(rv, 'Gear')])
        self.assertEqual((1, 2, 0), rv.counts())

    def test_confirming_twice_says_so_rather_than_pretending(self):
        rv = made()
        rv.confirm(by(rv, 'Gear'))
        self.assertIn('already yours', rv.confirm(by(rv, 'Gear')))

    def test_there_is_nothing_to_confirm_on_an_empty_row(self):
        rv = made([Need('Trim', 'hat8', [[Bind('A')]] * 8)])
        self.assertIn('nothing to confirm', rv.confirm(by(rv, 'Trim')))
        self.assertEqual(UNSET, rv.mark[by(rv, 'Trim')])

    def test_confirm_all_takes_the_proposals_and_leaves_the_gaps(self):
        rv = made(plan() + [Need('Trim8', 'hat8', [[Bind('A')]] * 8)])
        rv.confirm_all()
        self.assertEqual((3, 0, 1), rv.counts())


class Clearing(unittest.TestCase):
    def test_clearing_empties_the_row_but_keeps_it(self):
        rv = made()
        rv.clear(by(rv, 'Gear'))
        self.assertEqual(UNSET, rv.mark[by(rv, 'Gear')])
        self.assertIn('Gear', [r.text for r in rv.rows()
                               if r.kind == 'need'])

    def test_the_control_it_had_becomes_free_again(self):
        rv = made()
        had = at(rv, by(rv, 'Gear')).ctrl.label
        self.assertNotIn(had, [c.label for _r, c in rv.free()])
        rv.clear(by(rv, 'Gear'))
        self.assertIn(had, [c.label for _r, c in rv.free()])

    def test_a_cleared_need_is_not_written(self):
        rv = made()
        rv.clear(by(rv, 'Gear'))
        self.assertNotIn('Gear', [p.need.what for p in rv.result().placed])

    def test_clear_all_drops_the_proposals(self):
        rv = made()
        rv.clear_all()
        self.assertEqual((0, 0, 3), rv.counts())

    def test_clear_all_leaves_what_you_chose_alone(self):
        # The rule that makes X safe to press an hour in: it undoes the
        # planner, never you.
        rv = made()
        trim = by(rv, 'Trim')
        rv.confirm(trim)
        was = at(rv, trim).ctrl.label
        rv.clear_all()
        self.assertEqual(MINE, rv.mark[trim])
        self.assertEqual(was, at(rv, trim).ctrl.label)
        self.assertEqual((1, 0, 2), rv.counts())

    def test_the_controls_the_proposals_had_come_back_free(self):
        rv = made()
        had = at(rv, by(rv, 'Gear')).ctrl.label
        rv.clear_all()
        self.assertIn(had, [c.label for _r, c in rv.free()])

    def test_clear_all_says_when_there_is_nothing_to_drop(self):
        rv = made()
        rv.confirm_all()
        self.assertIn('no proposals left', rv.clear_all())

    def test_what_P_puts_in_X_takes_back_out(self):
        rv = made()
        rv.clear_all()
        rv.propose_all()
        rv.clear_all()
        self.assertEqual((0, 0, 3), rv.counts())


class Proposing(unittest.TestCase):
    def test_it_puts_the_planners_choice_back(self):
        rv = made()
        gear = by(rv, 'Gear')
        was = at(rv, gear).ctrl.label
        rv.clear(gear)
        rv.propose(gear)
        self.assertEqual(PROPOSED, rv.mark[gear])
        self.assertEqual(was, at(rv, gear).ctrl.label)

    def test_it_will_not_overwrite_something_you_chose(self):
        # The rule that makes "propose all" safe to press at any moment.
        rv = made()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        role, ctrl = rv.fits(gear)[-1]
        rv.assign(gear, role, ctrl)
        self.assertIn('yours already', rv.propose(gear))
        self.assertEqual(ctrl.label, at(rv, gear).ctrl.label)

    def test_it_says_so_when_the_planner_had_nothing(self):
        rv = made([Need('Trim', 'hat8', [[Bind('A')]] * 8)])
        self.assertIn('nowhere to put it', rv.propose(by(rv, 'Trim')))

    def test_it_refuses_a_control_someone_else_took_meanwhile(self):
        rv = made()
        gear, canopy = by(rv, 'Gear'), by(rv, 'Canopy')
        wanted = at(rv, gear).ctrl
        rv.clear(gear)
        rv.assign(canopy, 'stick', wanted)      # by hand, onto Gear's control
        self.assertIn('is taken now', rv.propose(gear))
        self.assertEqual(UNSET, rv.mark[gear])

    def test_propose_all_fills_only_the_gaps(self):
        rv = made()
        gear = by(rv, 'Gear')
        rv.confirm(by(rv, 'Trim'))              # yours
        rv.clear(gear)                          # a gap
        rv.propose_all()
        self.assertEqual(MINE, rv.mark[by(rv, 'Trim')], 'left alone')
        self.assertEqual(PROPOSED, rv.mark[gear], 'filled')

    def test_propose_all_says_when_there_is_nothing_to_do(self):
        self.assertIn('nothing left', made().propose_all())


class ByHand(unittest.TestCase):
    def test_choosing_it_yourself_needs_no_confirming(self):
        rv = made()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        rv.assign(gear, *rv.fits(gear)[0])
        self.assertEqual(MINE, rv.mark[gear])

    def test_it_lands_on_the_buttons_the_core_would_have_used(self):
        rv = made()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        role, ctrl = rv.fits(gear)[0]
        p = rv.assign(gear, role, ctrl)
        self.assertEqual(corneeds.slots_for(gear, ctrl)[:len(p.slots)],
                         [b for b, _v in p.slots])

    def test_reach_is_not_used_to_argue_with_the_reviewer(self):
        # The allocator refuses an `in a turn` need a control you must let go
        # of the grip to reach. Someone choosing by hand has decided otherwise.
        devs = stick(fake.button('Panel button', 0, reach=fake.PANEL))
        rv = made([Need('Radar', 'button', [[Bind('ACM')]], urgency=IN_A_TURN)],
                  devs=devs)
        radar = by(rv, 'Radar')
        self.assertEqual(UNSET, rv.mark[radar], 'the ceiling refused it')
        self.assertIn('Panel button', [c.label for _r, c in rv.fits(radar)])

    def test_a_control_of_the_wrong_shape_is_never_offered(self):
        rv = made()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        self.assertTrue(all(c.kind in gear.shapes
                            for _r, c in rv.fits(gear)))

    def test_a_control_with_too_few_buttons_is_never_offered(self):
        devs = stick(fake.selector('Three-way', 0, positions=3,
                                   reach=fake.PANEL))
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]])], devs=devs)
        self.assertEqual([], rv.fits(by(rv, 'Trim')))


class ByPress(unittest.TestCase):
    """Pressing a button can land anywhere, so unlike the list every refusal
    has to say what was wrong with it."""

    def setUp(self):
        self.rv = made()
        self.gear = by(self.rv, 'Gear')

    def ctrl(self, label):
        return next(c for c in self.rv.layout.devices['stick']
                    .groups(bindable=True) if c.label == label)

    def test_a_raw_button_number_becomes_the_control_that_owns_it(self):
        # A hat has four buttons and one identity: pressing any of them takes
        # the whole control, because a need wants a control.
        rv = self.rv
        self.assertEqual('Thumb hat', owns(rv, 'stick', 0).label)
        self.assertEqual('Thumb hat', owns(rv, 'stick', 3).label)
        self.assertEqual('Thumb hat', owns(rv, 'stick', 4).label,
                         'the click too')

    def test_a_button_in_no_control_resolves_to_nothing(self):
        self.assertIsNone(self.rv.control_at('stick', 99))
        self.assertIsNone(self.rv.control_at('nosuchrole', 0))

    def test_a_button_the_map_does_not_know_is_refused_by_name(self):
        self.assertIn('not in the device map',
                      refused(self.rv, self.gear, 'stick', None))

    def test_a_control_that_carries_nothing_is_refused(self):
        devs = stick(fake.control('unwired', 'Phantom', [0]),
                     fake.button('Panel button', 1, reach=fake.PANEL))
        rv = made([Need('Gear', 'button', [[Bind('GEAR')]])], devs=devs)
        phantom = next(c for c in rv.layout.devices['stick']._groups
                       if c.label == 'Phantom')
        self.assertIn('carries no binding',
                      refused(rv, by(rv, 'Gear'), 'stick', phantom))

    def test_the_wrong_shape_is_refused_and_both_shapes_are_named(self):
        trim = by(self.rv, 'Trim')                  # wants a hat4
        why = refused(self.rv, trim, 'stick', self.ctrl('Pinky button'))
        self.assertIn('button', why)
        self.assertIn('hat4', why)

    def test_too_few_buttons_is_refused_with_the_count(self):
        devs = stick(fake.selector('Three-way', 0, positions=3,
                                   reach=fake.PANEL))
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]])], devs=devs)
        three = rv.layout.devices['stick'].groups(bindable=True)[0]
        why = refused(rv, by(rv, 'Trim'), 'stick', three)
        self.assertIn('3', why)
        self.assertIn('4', why)

    def test_a_control_another_need_holds_is_refused_by_that_needs_name(self):
        # Canopy is a button need like Gear, so shape is not what refuses it
        # here -- it is genuinely occupied, and the message has to say by what.
        rv, gear = self.rv, self.gear
        canopy = by(rv, 'Canopy')
        why = refused(rv, gear, 'stick', at(rv, canopy).ctrl)
        self.assertIn('Canopy', why)
        self.assertIn('x clears it', why)

    def test_shape_is_reported_before_occupancy(self):
        # Pressing a hat while a button need is selected: that it is the wrong
        # shape matters more than who happens to be sitting on it, because it
        # would not work even if it were free.
        rv, gear = self.rv, self.gear
        why = refused(rv, gear, 'stick', at(rv, by(rv, 'Trim')).ctrl)
        self.assertIn('wants button', why)

    def test_moving_a_need_onto_the_control_it_already_has_is_fine(self):
        rv, gear = self.rv, self.gear
        self.assertIsNone(rv.why_not(gear, 'stick', at(rv, gear).ctrl))

    def test_a_control_that_fits_and_is_free_is_accepted(self):
        rv, gear = self.rv, self.gear
        rv.clear(gear)
        spare = next(c for _r, c in rv.fits(gear))
        self.assertIsNone(rv.why_not(gear, 'stick', spare))

    def test_who_has_names_the_holder_and_nothing_once_it_is_cleared(self):
        rv = self.rv
        trim = by(rv, 'Trim')
        held = at(rv, trim).ctrl
        self.assertIs(trim, rv.who_has('stick', held))
        rv.clear(trim)
        self.assertIsNone(rv.who_has('stick', held))


class Took(unittest.TestCase):
    """Everything that happens after the kernel says which button went down."""

    def setUp(self):
        self.rv = made()
        self.gear = by(self.rv, 'Gear')

    def test_pressing_a_free_control_assigns_it_and_it_is_yours(self):
        rv, gear = self.rv, self.gear
        rv.clear(gear)
        role, ctrl = rv.fits(gear)[0]           # whatever is actually spare
        said = rv.took(gear, role, ctrl.bindable_buttons[0])
        self.assertIn('(yours)', said)
        self.assertEqual(MINE, rv.mark[gear])
        self.assertEqual(ctrl.label, at(rv, gear).ctrl.label)

    def test_pressing_any_button_of_a_control_takes_the_whole_control(self):
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]])])
        trim = by(rv, 'Trim')
        rv.clear(trim)
        rv.took(trim, 'stick', 2)                   # the third of four
        self.assertEqual('Thumb hat', at(rv, trim).ctrl.label)
        self.assertEqual([0, 1, 2, 3], [b for b, _v in at(rv, trim).slots])

    def test_pressing_an_unmapped_button_changes_nothing(self):
        rv, gear = self.rv, self.gear
        was = rv.at[gear]
        self.assertIn('not in the device map', rv.took(gear, 'stick', 99))
        self.assertIs(was, rv.at[gear])

    def test_pressing_the_wrong_shape_changes_nothing(self):
        rv, gear = self.rv, self.gear
        rv.clear(gear)
        self.assertIn('wants button', rv.took(gear, 'stick', 0))
        self.assertEqual(UNSET, rv.mark[gear])

    def test_pressing_a_control_another_need_has_changes_nothing(self):
        rv, gear = self.rv, self.gear
        canopy = by(rv, 'Canopy')
        held = at(rv, canopy).ctrl.buttons[0]
        rv.clear(gear)
        self.assertIn('Canopy', rv.took(gear, 'stick', held))
        self.assertEqual(UNSET, rv.mark[gear])

    def test_pressing_the_control_it_already_has_is_harmless(self):
        rv, gear = self.rv, self.gear
        here = at(rv, gear).ctrl.buttons[0]
        self.assertIn('(yours)', rv.took(gear, 'stick', here))
        self.assertEqual(MINE, rv.mark[gear])


class WhereThePressLands(unittest.TestCase):
    """A press is a choice; `slots_for` is a guess. When they disagree about
    a single binding, the choice wins."""

    def trigger_plan(self):
        devs = stick(fake.trigger('Main trigger', 0,
                                  stages=('first', 'second', 'third'),
                                  reach=fake.INDEX))
        return made([Need('Fire', 'trigger', [[Bind('FIRE')]])], devs=devs)

    def test_a_lone_binding_lands_on_the_stage_you_pressed(self):
        # It used to land on the first stage whichever you pressed, because
        # slots_for picks for a need that has only one thing to place.
        for press in (0, 1, 2):
            rv = self.trigger_plan()
            fire = by(rv, 'Fire')
            rv.clear(fire)
            rv.took(fire, 'stick', press)
            self.assertEqual([press], [b for b, _v in at(rv, fire).slots],
                             f'pressing {press}')

    def test_and_the_status_names_the_position_it_went_to(self):
        rv = self.trigger_plan()
        fire = by(rv, 'Fire')
        rv.clear(fire)
        self.assertIn('second', rv.took(fire, 'stick', 1))

    def test_a_need_wanting_the_whole_control_still_gets_its_own_order(self):
        # Four directions are the control's business, not the corner you
        # happened to touch.
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]])])
        trim = by(rv, 'Trim')
        rv.clear(trim)
        rv.took(trim, 'stick', 2)
        self.assertEqual([0, 1, 2, 3], [b for b, _v in at(rv, trim).slots])

    def test_an_on_claim_beats_the_press(self):
        # `on` says a speedbrake is fore/aft whatever hat it lands on. Letting
        # a press overrule it is the lie `on` exists to stop.
        rv = made([Need('Speedbrake', 'hat4', [[Bind('OUT')]], on=('forward',))])
        sb = by(rv, 'Speedbrake')
        rv.clear(sb)
        rv.took(sb, 'stick', 3)                     # 'left'
        landed = at(rv, sb).slots[0][0]
        ctrl = at(rv, sb).ctrl
        self.assertEqual('up', ctrl.direction(landed))

    def test_a_contact_that_carries_no_binding_is_not_used(self):
        # A rest contact is closed whenever the control is untouched, so
        # anything on it runs all the time. Pressing one falls back and says
        # so rather than binding there.
        devs = stick(fake.control('hat2', 'Rocker', [0, 1], rest_contact=2,
                                  reach=fake.THUMB))
        rv = made([Need('Flaps', 'hat2', [[Bind('UP')]])], devs=devs)
        flaps = by(rv, 'Flaps')
        rv.clear(flaps)
        said = rv.took(flaps, 'stick', 2)
        self.assertNotIn(2, [b for b, _v in at(rv, flaps).slots])
        self.assertIn('carries no binding', said)

    def test_honours_press_says_why_in_each_case(self):
        rv = self.trigger_plan()
        fire = by(rv, 'Fire')
        ctrl = at(rv, fire).ctrl
        self.assertTrue(rv.honours_press(fire, ctrl, 1))
        many = Need('Trim', 'trigger', [[Bind('A')], [Bind('B')]])
        self.assertFalse(rv.honours_press(many, ctrl, 1), 'wants the control')
        aimed = Need('Brake', 'trigger', [[Bind('A')]], on=('first',))
        self.assertFalse(rv.honours_press(aimed, ctrl, 1), 'on wins')


class Writing(unittest.TestCase):
    def test_a_proposal_nobody_looked_at_is_still_written(self):
        # `?` says you did not check it, not that it is off -- the call DCS
        # makes too, whose generator has never filtered on the flag.
        rv = made()
        self.assertEqual((0, 3, 0), rv.counts())
        self.assertEqual(3, len(rv.result().placed))

    def test_only_needs_with_a_control_are_written(self):
        rv = made(plan() + [Need('Trim8', 'hat8', [[Bind('A')]] * 8)])
        self.assertEqual(3, len(rv.result().placed))

    def test_the_result_is_the_same_plan_narrowed(self):
        rv = made()
        rv.clear(by(rv, 'Gear'))
        out = rv.result()
        self.assertEqual(rv.layout.devices, out.devices)
        self.assertEqual([('pitch', 'stick')], out.axes)
        self.assertEqual(3, len(rv.layout.placed), 'the plan is not mutated')

    def test_a_hand_placed_need_reaches_the_writer(self):
        devs = stick(fake.button('Panel button', 0, reach=fake.PANEL))
        rv = made([Need('Radar', 'button', [[Bind('ACM')]], urgency=IN_A_TURN)],
                  devs=devs)
        radar = by(rv, 'Radar')
        rv.assign(radar, *rv.fits(radar)[0])
        self.assertEqual(['Radar'],
                         [p.need.what for p in rv.result().placed])


class Rows(unittest.TestCase):
    def test_rows_group_by_urgency_so_nothing_jumps_when_cleared(self):
        rv = made()
        before = [r.text for r in rv.rows()]
        rv.clear(by(rv, 'Gear'))
        self.assertEqual(before, [r.text for r in rv.rows()])

    def test_the_headings_are_the_urgency_names(self):
        heads = [r.text for r in made().rows() if r.kind == 'head']
        self.assertEqual(['IN A TURN', 'IN THE AIR', 'ON THE RAMP'], heads)

    def test_a_gap_cannot_be_selected(self):
        # A heading is a thing you act on -- `R` renames it -- so what is
        # left unselectable is what answers nothing.
        rows = made().rows()
        self.assertTrue(all(r.kind != 'gap' for r in rows if r.selectable))
        self.assertTrue(any(r.kind == 'gap' for r in rows))


class BindsUnderTheAction(unittest.TestCase):
    """What a need binds belongs under its row, not in the footer.

    The panel at the bottom showed `describe(p)` for whichever row the
    cursor was on, so you had to move onto a row to learn what it does and
    could never see two at once. X4 puts six lines there for one hat.
    """

    def rv(self, showing=True):
        """`h` off to start with, so a test about bind rows turns it on.

        That is the default the screen has: the list of what a game can do
        is what you come here to read, and the binds go under it on ask.
        """
        rv = made(describe=lambda p: [('up', 'Ship: one'),
                                      ('down', 'Ship: two')])
        rv.show_binds = showing
        return rv

    def test_they_are_hidden_to_start_with(self):
        rv = self.rv(showing=False)
        self.assertEqual([], [r for r in rv.rows() if r.kind == 'bind'])
        self.assertTrue([r for r in rv.rows() if r.kind == 'need'])

    def test_each_bind_is_a_row_under_its_need(self):
        rv = self.rv()
        rows = rv.rows()
        i = next(i for i, r in enumerate(rows)
                 if r.kind == 'need' and r.need.what == 'Gear')
        under = [r for r in rows[i + 1:i + 3]]
        self.assertTrue(all(r.kind == 'bind' for r in under))
        self.assertIn('Ship: one', under[0].text)
        self.assertIn('up', under[0].text)

    def test_a_bind_row_cannot_be_selected(self):
        # It is the answer to the row above, not a thing you put anywhere.
        rows = self.rv().rows()
        self.assertTrue(all(r.kind != 'bind'
                            for r in rows if r.selectable))
        self.assertTrue(any(r.kind == 'bind' for r in rows))

    def test_a_need_with_nothing_on_it_has_no_bind_rows(self):
        rv = self.rv()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        rows = rv.rows()
        i = next(i for i, r in enumerate(rows)
                 if r.kind == 'need' and r.need is gear)
        self.assertNotEqual('bind', rows[i + 1].kind)

    def test_an_unassigned_row_still_says_what_would_fit(self):
        # The footer these two used to check is gone -- what a row binds
        # has been on the tree since `h` arrived, and the function had no
        # caller left but them. The panel answers it now.
        rv = self.rv()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need is gear)
        said = '\n'.join(t for _tone, t in review._side(rv, row, 40))
        self.assertIn('fit', said)


class TheDetailPanel(unittest.TestCase):
    """What the right-hand panel says about the row you are on.

    It answers three questions and they are not the same question: what is
    this sitting on, what does it fire, and WHY is it there. The third had
    no answer at all -- the panel listed the control and its reach and
    stopped, so the one thing a reader actually argues with, the planner's
    choice, was the one thing it would not account for.

    `Reason` is that account, recorded where the decision was made. The
    panel is its first human reader.
    """

    def rv(self, **kw):
        return made(**kw)

    def side(self, rv, what, width=26):
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need.what == what)
        return review._side(rv, row, width)

    def text(self, rv, what, width=26):
        return '\n'.join(t for _tone, t in self.side(rv, what, width))

    def tone_of(self, rv, what, word, width=26):
        return next(tone for tone, t in self.side(rv, what, width)
                    if word in t)

    # ---- the why segment ----

    def test_it_says_which_band_the_need_is_in(self):
        self.assertIn('in a turn', self.text(self.rv(), 'Trim'))

    def test_it_gives_the_terms_the_score_was_made_of(self):
        # Not the total: 137 says nothing to a reader. The terms say what
        # the control was picked FOR, and each carries what it was worth.
        got = self.text(self.rv(), 'Trim')
        self.assertRegex(got, r'[+-]\d+ \S')

    def test_it_names_the_shape_the_control_matched(self):
        self.assertIn('hat4', self.text(self.rv(), 'Trim'))

    def test_a_placement_that_reached_past_the_floor_says_so(self):
        rv = made([Need('Airbrake', 'hat2', [[Bind('OUT')], [Bind('IN')]],
                        urgency=IN_A_TURN)],
                  devs=stick(fake.hat2('Panel rocker', 0,
                                       reach=fake.PANEL)))
        self.assertIn('floor', self.text(rv, 'Airbrake').lower())

    # ---- the override mention ----

    def test_it_says_whose_decision_this_was(self):
        # In the words the map's legend and `?` use, not its own: one
        # wording for one state, wherever it is named.
        self.assertIn(review.MARK_SAID[PROPOSED],
                      self.text(self.rv(), 'Trim'))

    def test_moving_it_by_hand_is_said_out_loud(self):
        rv = self.rv()
        gear = by(rv, 'Gear')
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(gear, 'stick', ctrl)
        self.assertIn('you', self.text(rv, 'Gear').lower())

    def test_it_says_where_the_planner_had_wanted_it(self):
        rv = self.rv()
        gear = by(rv, 'Gear')
        was = at(rv, gear).ctrl.label
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(gear, 'stick', ctrl)
        self.assertIn(was, self.text(rv, 'Gear'))

    def test_a_hand_that_agrees_with_the_planner_claims_no_move(self):
        # Putting it back where it already was is not an override, and
        # "moved from Thumb hat" about a binding on the thumb hat would be
        # the screen arguing with the person reading it.
        rv = self.rv()
        gear = by(rv, 'Gear')
        rv.assign(gear, 'stick', at(rv, gear).ctrl)
        self.assertNotIn('moved', self.text(rv, 'Gear').lower())

    # ---- which button of the control ----

    def test_a_control_with_several_binds_says_which_is_which(self):
        # Four binds on a hat share the control, so they share every word
        # of the account except this one. Without it the panel repeats one
        # sentence four times, which looks like an answer.
        got = self.text(self.rv(), 'Trim')
        self.assertIn('press order', got)

    def test_a_single_bind_is_not_told_which_of_one_button(self):
        # There is nothing to tell apart, and a heading over one obvious
        # line is a line you learn to skip.
        rv = self.rv()
        gear = by(rv, 'Gear')
        self.assertEqual(1, len(at(rv, gear).slots))
        self.assertNotIn('WHICH BUTTON', self.text(rv, 'Gear'))

    def test_a_hand_placed_bind_is_told_too(self):
        rv = self.rv()
        trim = by(rv, 'Trim')
        ctrl = at(rv, trim).ctrl
        rv.assign(trim, 'stick', ctrl)
        spots = [b.reason.spot for _n, slot in at(rv, trim).slots
                 for b in slot if b.reason]
        self.assertTrue(all(spots), spots)

    # ---- the colours ----

    def test_the_override_line_wears_the_same_tone_as_the_row(self):
        # `MINE` is a tone name as well as a state, deliberately, so the
        # table and the panel cannot disagree about what green means.
        rv = self.rv()
        gear = by(rv, 'Gear')
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(gear, 'stick', ctrl)
        self.assertEqual(MINE, self.tone_of(rv, 'Gear', 'you'))

    def test_the_sections_are_headings_not_plain_text(self):
        tones = {tone for tone, t in self.side(self.rv(), 'Trim')
                 if t.isupper() and t.strip()}
        self.assertEqual({'head'}, tones)

    # ---- the width ----

    def test_nothing_comes_back_wider_than_the_panel(self):
        # `_draw` wraps too, but without a hanging indent -- so a ledger
        # line it has to break lands flush left and stops reading as a
        # ledger. The panel wraps its own.
        for w in (18, 22, 26, 40):
            for _tone, t in self.side(self.rv(), 'Trim', w):
                self.assertLessEqual(len(t), w, repr(t))


class Categories(unittest.TestCase):
    """What the list groups by.

    It grouped by urgency band, which is the allocator's scale and not
    yours: four buckets, named for when you touch a thing, fixed in the
    source. A category is yours -- you name it, you put things in it, you
    move them between.

    They are two fields on purpose. "Combat" can hold something you reach
    for in a turn and something you set on the ramp, and the allocator
    still has to know which is which.
    """

    def groups(self, rv):
        return [r.text for r in rv.rows() if r.kind == 'head']

    def under(self, rv, group):
        out, seen = [], False
        for r in rv.rows():
            if r.kind == 'head':
                seen = r.text == group
            elif r.kind == 'need' and seen:
                out.append(r.text)
        return out

    def test_a_need_with_no_category_keeps_its_band(self):
        # Nothing has a category on the day this lands, so grouping by it
        # alone would empty every screen in the family.
        rv = made()
        self.assertIn('IN A TURN', self.groups(rv))
        self.assertIn('Trim', self.under(rv, 'IN A TURN'))

    def test_a_need_with_a_category_sits_under_it(self):
        rv = made()
        trim = by(rv, 'Trim')
        trim.category = 'Combat'
        self.assertIn('COMBAT', self.groups(rv))
        self.assertIn('Trim', self.under(rv, 'COMBAT'))
        self.assertNotIn('Trim', self.under(rv, 'IN A TURN'))

    def test_a_group_sorts_by_the_most_urgent_thing_in_it(self):
        # A category holding something you reach for in a turn belongs
        # above one whose most urgent member waits for the ramp -- the
        # same order the bands had, derived rather than declared.
        rv = made()
        by(rv, 'Canopy').category = 'Housekeeping'
        by(rv, 'Trim').category = 'Combat'
        got = self.groups(rv)
        self.assertLess(got.index('COMBAT'), got.index('HOUSEKEEPING'))

    def test_an_empty_category_is_not_a_heading(self):
        # `f` already skips a band it filtered empty; a category nobody
        # is in is a line you scroll past to reach the rows you asked for.
        rv = made()
        by(rv, 'Trim').category = 'Combat'
        rv.filter = 'gear'
        self.assertNotIn('COMBAT', self.groups(rv))


class Promoting(unittest.TestCase):
    """Taking something out of the vocabulary and putting it on the list.

    The screen showed 147 rows across five games while the games between
    them accept 5856 actions. The other 5709 were not hidden -- nothing
    ever knew about them, because the list was a hand-written literal and
    the vocabulary was only ever consulted to check spelling.
    """

    CAT = [Action('ID_GEAR', 'Landing gear'),
           Action('ID_FLARE', 'Countermeasures'),
           Action('ID_PITCH', 'Pitch', kind='axis')]

    def rv(self):
        return made(catalogue=self.CAT)

    def test_an_action_nobody_asked_for_is_not_on_the_list(self):
        rv = self.rv()
        self.assertNotIn('Landing gear', [n.what for n in rv.needs])

    def test_promoting_puts_it_under_the_category_you_named(self):
        rv = self.rv()
        rv.promote(self.CAT[0], 'Combat')
        need = next(n for n in rv.needs if n.what == 'Landing gear')
        self.assertEqual('Combat', need.category)
        self.assertIn('COMBAT', [r.text for r in rv.rows()
                                 if r.kind == 'head'])

    def test_what_it_binds_is_the_action_you_promoted(self):
        rv = self.rv()
        rv.promote(self.CAT[0], 'Combat')
        need = next(n for n in rv.needs if n.what == 'Landing gear')
        self.assertEqual([['ID_GEAR']],
                         [[b.action for b in slot] for slot in need.bindings])

    def test_it_arrives_carrying_nothing(self):
        # Promoting says "this matters", not "put it here". Where is the
        # next question and the screen already answers it.
        rv = self.rv()
        rv.promote(self.CAT[0], 'Combat')
        need = next(n for n in rv.needs if n.what == 'Landing gear')
        self.assertIsNone(rv.at[need])
        self.assertEqual(UNSET, rv.mark[need])

    def test_promoting_the_same_action_twice_is_once(self):
        rv = self.rv()
        rv.promote(self.CAT[0], 'Combat')
        rv.promote(self.CAT[0], 'Nav')
        self.assertEqual(1, sum(1 for n in rv.needs
                                if n.what == 'Landing gear'))

    def test_an_axis_says_it_cannot_go_that_way_yet(self):
        # Axes never went through the allocator in any game in the family,
        # so there is nothing for a promoted one to be placed on.
        rv = self.rv()
        said = rv.promote(self.CAT[2], 'Combat')
        self.assertIn('axis', said.lower())
        self.assertNotIn('Pitch', [n.what for n in rv.needs])

    def test_promoting_writes_it_down(self):
        # A judgement is derived from nothing. One that lasts until `q` is
        # a judgement you have to make again.
        kept = []
        rv = made(catalogue=self.CAT,
                  save=lambda needs: kept.append(list(needs)) or 'saved')
        rv.promote(self.CAT[0], 'Combat')
        self.assertTrue(kept, 'nothing was written')
        self.assertIn('Landing gear', [n.what for n in kept[-1]])

    def test_a_screen_with_nowhere_to_write_still_works(self):
        # DCS derives its needs, so there is no list to keep -- and a
        # screen that raised rather than said so would take the whole
        # review down over a thing it cannot help.
        rv = made(catalogue=self.CAT)
        said = rv.promote(self.CAT[0], 'Combat')
        self.assertIn('Landing gear', [n.what for n in rv.needs])
        self.assertTrue(said)

    def test_the_categories_in_use_can_be_offered(self):
        # So a menu can show what exists before asking for a new name.
        rv = self.rv()
        rv.promote(self.CAT[0], 'Combat')
        self.assertIn('Combat', rv.categories())
        self.assertIn('in a turn', rv.categories())


class Refiling(unittest.TestCase):
    """Moving something from one group to another.

    Promoting puts a thing on the list; this changes your mind about
    where it belongs. They are separate because the first reaches into
    the vocabulary and the second never leaves the list.
    """

    def test_it_moves_the_row(self):
        rv = made()
        trim = by(rv, 'Trim')
        rv.refile(trim, 'Combat')
        heads = [r.text for r in rv.rows() if r.kind == 'head']
        self.assertIn('COMBAT', heads)
        self.assertNotIn('IN A TURN', heads)

    def test_it_is_written_down(self):
        kept = []
        rv = made(save=lambda needs: kept.append(list(needs)) or 'ok')
        rv.refile(by(rv, 'Trim'), 'Combat')
        self.assertEqual(['Combat'], [n.category for n in kept[-1]
                                      if n.what == 'Trim'])

    def test_putting_it_back_in_its_band_forgets_the_category(self):
        # The band is the fallback, not a category -- filing something
        # under `in a turn` and having that written down as a name would
        # make the fallback a place you cannot leave.
        rv = made()
        trim = by(rv, 'Trim')
        rv.refile(trim, 'Combat')
        rv.refile(trim, 'in a turn')
        self.assertIsNone(trim.category)

    def test_it_does_not_touch_the_urgency(self):
        # Two fields on purpose: where you filed it and when you reach
        # for it are different questions, and the allocator reads one.
        rv = made()
        trim = by(rv, 'Trim')
        was = trim.urgency
        rv.refile(trim, 'Housekeeping')
        self.assertEqual(was, trim.urgency)


class SelectableHeadings(unittest.TestCase):
    """A category heading is a thing you can stand on.

    `R` renamed the group the cursor's row was IN, which meant renaming a
    category by standing on one of its members -- so the heading was the
    one thing on the screen you could read and not touch.

    Everything else stays guarded by `row.kind`. The handlers that need a
    `Need` keep asking for one and get None on a heading, which is the
    graceful half; the ones that act on a group have to branch on the kind
    themselves rather than lean on `need is not None`.
    """

    def rows(self, rv):
        return rv.rows()

    def test_a_heading_can_be_landed_on(self):
        rv = made()
        heads = [r for r in self.rows(rv) if r.kind == 'head']
        self.assertTrue(heads)
        self.assertTrue(all(r.selectable for r in heads))

    def test_a_gap_still_cannot(self):
        # It answers nothing and stopping on it is a keystroke for nothing.
        rv = made()
        gaps = [r for r in self.rows(rv) if r.kind == 'gap']
        self.assertTrue(gaps)
        self.assertFalse(any(r.selectable for r in gaps))

    def test_a_heading_carries_the_name_rename_needs(self):
        # `text` is upper-cased for the screen; `rename` needs what the
        # need actually holds, and 'IN A TURN' is not it.
        rv = made()
        head = next(r for r in self.rows(rv) if r.kind == 'head')
        self.assertEqual(head.text, head.group.upper())
        self.assertIn(head.group, rv.categories())

    def test_a_heading_has_no_need(self):
        # So every handler that wants one gets None and does nothing,
        # which is what keeps the rest of the loop untouched.
        rv = made()
        head = next(r for r in self.rows(rv) if r.kind == 'head')
        self.assertIsNone(head.need)


class ThePanelOnAHeading(unittest.TestCase):
    """Standing on a heading should say something.

    It said nothing: `_side` answered `[]` for anything that was not a
    need, so landing on a heading left an empty box beside it -- which
    reads as a hole rather than as a thing you are on.
    """

    def side(self, rv, name, width=28):
        row = next(r for r in rv.rows()
                   if r.kind == 'head' and r.group == name)
        return review._side(rv, row, width)

    def text(self, rv, name, width=28):
        return '\n'.join(t for _tone, t in self.side(rv, name, width))

    def test_it_names_the_group(self):
        self.assertIn('in a turn', self.text(made(), 'in a turn'))

    def test_it_counts_what_is_in_it(self):
        rv = made()
        rv.refile(by(rv, 'Gear'), 'Combat')
        rv.refile(by(rv, 'Canopy'), 'Combat')
        self.assertIn('2', self.text(rv, 'Combat'))

    def test_it_says_a_band_is_not_yours_to_rename(self):
        # Standing on one and pressing R is refused, and the panel should
        # say so before the keystroke rather than after it.
        self.assertIn('band', self.text(made(), 'in a turn').lower())

    def test_a_category_of_yours_says_nothing_of_the_kind(self):
        rv = made()
        rv.refile(by(rv, 'Gear'), 'Combat')
        self.assertNotIn('band', self.text(rv, 'Combat').lower())


class Renaming(unittest.TestCase):
    """Changing what a group is called, without emptying it first."""

    def test_everything_in_it_moves(self):
        rv = made()
        rv.refile(by(rv, 'Trim'), 'Combat')
        rv.refile(by(rv, 'Gear'), 'Combat')
        rv.rename('Combat', 'Fighting')
        self.assertEqual(['Fighting', 'Fighting'],
                         [n.category for n in rv.needs
                          if n.what in ('Trim', 'Gear')])

    def test_nothing_else_moves(self):
        rv = made()
        rv.refile(by(rv, 'Trim'), 'Combat')
        rv.rename('Combat', 'Fighting')
        self.assertIsNone(by(rv, 'Canopy').category)

    def test_renaming_a_band_is_refused(self):
        # A band is not a category, it is what a need falls back to. There
        # are four of them, they are the allocator's scale, and renaming
        # one here would say otherwise.
        rv = made()
        said = rv.rename('in a turn', 'Fighting')
        self.assertIn('band', said.lower())
        self.assertIsNone(by(rv, 'Trim').category)


class FilteringAndFolding(unittest.TestCase):
    """`f` narrows the action level, `h` hides what is under it."""

    def rv(self):
        rv = made(describe=lambda p: [('up', 'Ship: one'),
                                      ('down', 'Ship: two')])
        rv.show_binds = True
        return rv

    def names(self, rv):
        return [r.text for r in rv.rows() if r.kind == 'need']

    def test_the_filter_narrows_the_action_level(self):
        rv = self.rv()
        rv.filter = 'gear'
        self.assertEqual(['Gear'], self.names(rv))

    def test_it_does_not_care_about_case(self):
        rv = self.rv()
        rv.filter = 'GEAR'
        self.assertEqual(['Gear'], self.names(rv))

    def test_the_heading_stays(self):
        # Filtering is not flattening: a row still says which band it is in.
        rv = self.rv()
        rv.filter = 'gear'
        self.assertTrue([r for r in rv.rows() if r.kind == 'head'])

    def test_a_band_with_no_match_brings_no_heading(self):
        # The heading stays for what is there, not for what is not.
        rv = self.rv()
        rv.filter = 'gear'
        heads = [r.text for r in rv.rows() if r.kind == 'head']
        self.assertEqual(1, len(heads))

    def test_binds_follow_their_action_through_the_filter(self):
        rv = self.rv()
        rv.filter = 'gear'
        self.assertEqual(2, len([r for r in rv.rows()
                                 if r.kind == 'bind']))

    def test_an_empty_filter_shows_everything(self):
        rv = self.rv()
        rv.filter = 'gear'
        rv.filter = ''
        self.assertEqual(3, len(self.names(rv)))

    def test_folding_hides_the_binds_and_keeps_the_actions(self):
        rv = self.rv()
        rv.show_binds = False
        self.assertEqual([], [r for r in rv.rows() if r.kind == 'bind'])
        self.assertEqual(3, len(self.names(rv)))


class TheFilterSaysSoOnScreen(unittest.TestCase):
    """A narrowed list has to say it is narrowed.

    The status line said it once, on the keystroke, and then the next
    movement cleared it -- so a screen showing three of thirty-one rows
    looked exactly like a game with three needs.
    """

    def test_nothing_is_said_when_nothing_is_narrowed(self):
        self.assertEqual('', made().narrowed())

    def test_it_names_the_filter_and_counts_what_is_left(self):
        rv = made()
        rv.filter = 'gear'
        said = rv.narrowed()
        self.assertIn('gear', said)
        self.assertIn('1', said, 'one of the three matched')
        self.assertIn('3', said, 'out of three')

    def test_a_filter_that_matches_nothing_says_so_too(self):
        # The one case where the screen is empty, which is also the one
        # where "why is this empty" most needs answering.
        rv = made()
        rv.filter = 'no such thing'
        self.assertIn('no such thing', rv.narrowed())
        self.assertIn('0', rv.narrowed())


class TwoPanelsOrOne(unittest.TestCase):
    """Side by side where there is room, stacked where there is not.

    The detail panel used to be five lines at the bottom, and X4's `View`
    puts six under one hat -- so the one row that needed the space was the
    one that could not have it. A column has the height of the screen.
    """

    def test_a_wide_terminal_gets_two_panels(self):
        listed, detail = review._layout(100, 30)
        self.assertIsNotNone(detail)
        self.assertEqual(listed[1], 0, 'the list starts at the left edge')
        self.assertGreater(detail[1], listed[1] + 20)

    def test_they_do_not_overlap(self):
        listed, detail = review._layout(100, 30)
        self.assertLessEqual(listed[1] + listed[3], detail[1])

    def test_together_they_fill_the_width(self):
        for w in (90, 100, 120, 200):
            listed, detail = review._layout(w, 30)
            self.assertLessEqual(detail[1] + detail[3], w)
            self.assertGreaterEqual(detail[1] + detail[3], w - 1)

    def test_a_narrow_terminal_stacks_them(self):
        # 80 columns leaves the list about 50 wide, and
        # `throttle · Middle finger hat` does not fit in 50.
        listed, detail = review._layout(80, 30)
        self.assertEqual(listed[3], detail[3], 'both full width')
        self.assertGreater(detail[0], listed[0] + listed[2] - 1)

    def test_a_short_terminal_keeps_the_list_usable(self):
        # Stacked on a small screen, the detail must not eat the list.
        listed, detail = review._layout(80, 14)
        self.assertGreaterEqual(listed[2], 6)


class WhatItFound(unittest.TestCase):
    """The header line and the map screen: which device is which, and where
    the game was found."""

    def two_sticks(self):
        devs = {'stick': fake.device('stick', [
                    fake.button('Trigger', 0, reach=fake.INDEX)],
                    product='R-VPC Stick WarBRD-D'),
                'throttle': fake.device('throttle', [
                    fake.button('Pinky', 0, reach=fake.PANEL)],
                    product='L-VPC VMAX Prime Throttle')}
        lay = Layout(devs, *allocate([Need('Fire', 'button', [[Bind('F')]])], devs))
        return review.Review(lay, 'Test', paths=[('game', '/games/thing')])

    def test_the_header_names_the_device_behind_each_role(self):
        # A role is not a device: with two sticks in the map you choose one,
        # and a row reading "stick" no longer says which.
        line = self.two_sticks().device_line()
        self.assertIn('stick R-VPC Stick WarBRD-D', line)
        self.assertIn('throttle L-VPC VMAX Prime Throttle', line)

    def test_the_map_screen_says_where_the_game_was_found(self):
        lines = map_text(self.two_sticks())
        self.assertIn('WHERE', lines)
        self.assertIn('/games/thing', lines)

    def test_a_game_that_names_no_paths_gets_no_where_section(self):
        rv = made()
        self.assertNotIn('WHERE', map_text(rv))

    def test_the_map_screen_lists_every_control_with_what_is_on_it(self):
        rv = made()
        gear = by(rv, 'Gear')
        lines = map_text(rv)
        self.assertIn(at(rv, gear).ctrl.label, lines)
        self.assertIn('Gear', lines)
        self.assertIn('Thumb hat', lines, 'a control nobody took is listed')

    def test_it_marks_a_control_that_can_carry_nothing(self):
        devs = stick(fake.control('unwired', 'Phantom', [0]),
                     fake.button('Real', 1, reach=fake.PANEL))
        rv = made([Need('Gear', 'button', [[Bind('GEAR')]])], devs=devs)
        phantom = map_text(rv).splitlines()
        phantom = [ln for ln in phantom if 'Phantom' in ln][0]
        self.assertIn('carries nothing', phantom)
        self.assertEqual('meta', map_tone(rv, 'Phantom'),
                         'and it is drawn as dim as the ids above it')

    def test_it_shows_the_axes_of_a_control_that_has_no_buttons(self):
        devs = stick(fake.ministick('Mini-stick', 3, push=0,
                                    reach=fake.THUMB))
        rv = made([Need('Gear', 'button', [[Bind('GEAR')]])], devs=devs)
        line = [ln for ln in map_text(rv).splitlines()
                if 'Mini-stick' in ln][0]
        self.assertIn('ax3,4', line)
        self.assertIn('+0', line)

    def test_a_control_wears_the_state_of_the_need_sitting_on_it(self):
        # The point of the tones: the map and the table cannot disagree
        # about a binding, because they name its state with the same word.
        rv = made()
        gear = by(rv, 'Gear')
        label = at(rv, gear).ctrl.label
        self.assertEqual(PROPOSED, map_tone(rv, label))
        rv.confirm(gear)
        self.assertEqual(MINE, map_tone(rv, label))
        rv.clear(gear)
        self.assertEqual('plain', map_tone(rv, label),
                         'handed back, and back to an ordinary spare control')

    def test_a_section_heading_on_the_map_is_a_heading(self):
        rv = made()
        # The box's own title says "device map" now, so the first
        # heading inside it names what follows rather than repeating it.
        self.assertEqual('head', map_tone(rv, 'MARKS'))
        self.assertEqual('meta', map_tone(rv, 'buttons,'),
                         'ids and counts are true but never the answer')

    def test_the_map_is_three_levels_deep_and_looks_it(self):
        # WHERE / profile dir / the path itself are a section, the thing it
        # names and the detail under it -- and all three in one blue is a
        # listing you have to read from the top to know where you are.
        rv = self.two_sticks()
        self.assertEqual('head', map_tone(rv, 'WHERE'))
        self.assertEqual('subhead', map_tone(rv, 'game'))
        self.assertEqual('meta', map_tone(rv, '/games/thing'))
        self.assertEqual('subhead', map_tone(rv, 'WarBRD'),
                         'a device is named under DEVICE MAP, not beside it')

    def test_the_columns_are_named(self):
        # Five columns and nothing saying what they were: `2,3,4` in the
        # third one is a button list, and there was no way to know that
        # but to work it out from the numbers.
        head = [ln for ln in map_text(made()).splitlines()
                if 'KIND' in ln]
        self.assertTrue(head, 'no column header')
        for word in ('CONTROL', 'BUTTONS', 'REACH'):
            self.assertIn(word, head[0])

    def test_a_home_path_is_written_short(self):
        # A Proton prefix is 120 characters before it says anything, and
        # fourteen of them are this machine's home directory.
        rv = made(paths=[('game', os.path.expanduser('~/games/thing'))])
        self.assertIn('~/games/thing', map_text(rv))
        self.assertNotIn(os.path.expanduser('~/games'), map_text(rv))

    def test_the_map_comes_before_the_paths(self):
        # It is what the screen is for. The paths are reference, and nine
        # lines of them ahead of the thing you opened it to see is why it
        # read like a newspaper.
        lines = map_text(self.two_sticks())
        self.assertLess(lines.index('WarBRD'), lines.index('WHERE'))

    def test_every_control_carries_the_table_s_own_mark(self):
        # The colours went in before anything said what they meant, which
        # left some rows simply being a different colour. The mark says it.
        rv = made()
        gear = by(rv, 'Gear')
        label = at(rv, gear).ctrl.label
        self.assertIn(f'{MARK[PROPOSED]} button     {label}', map_text(rv))
        rv.confirm(gear)
        self.assertIn(f'{MARK[MINE]} button     {label}', map_text(rv))
        rv.clear(gear)
        self.assertIn(f'{MARK[UNSET]} button     {label}', map_text(rv))

    def test_the_map_says_what_its_colours_mean(self):
        # A legend drawn in the colours it explains: one line per tone,
        # because a line carries one.
        rv = made()
        # Against the constants, not their wording: the rule is one
        # line per state, drawn in that state's own tone, and pinning the
        # prose made this break when the words changed and the rule
        # had not.
        want = {t: f'{review.MARK[t]} {review.MARK_SAID[t]}'.strip()
                for t in (review.MINE, review.PROPOSED, review.UNSET)}
        legend = {tone: text for tone, text in rv.map_lines()
                  if text.strip() in want.values()}
        self.assertEqual(set(want), set(legend),
                         'each state, in its own tone')


class Theming(unittest.TestCase):
    """The palette is asked for by meaning, never by colour."""

    def test_every_tone_falls_back_to_a_plain_attribute(self):
        # No terminal here at all, which is the case `colour=False` covers:
        # nothing in Theme may touch curses until there is colour to set up.
        th = ctui.Theme()
        self.assertEqual(curses.A_BOLD, th.mine)
        self.assertEqual(curses.A_DIM, th.unset)
        self.assertEqual(curses.A_REVERSE, th.sel)
        self.assertEqual(0, th._pairs, 'no colour pair was allocated')

    def test_the_three_row_states_are_all_tones(self):
        # map_lines() hands the pager a name and _draw hands it a state;
        # both arrive at __getitem__, so the two vocabularies must match.
        th = ctui.Theme()
        for state in (UNSET, PROPOSED, MINE):
            self.assertEqual(getattr(th, state), th[state])
        for tone in ('head', 'meta', 'plain'):
            self.assertEqual(getattr(th, tone), th[tone])


class Folding(unittest.TestCase):
    """A Proton prefix is ninety characters before it says which game."""

    def test_a_short_path_is_left_alone(self):
        self.assertEqual(['/short/one'], review._fold('/short/one'))

    def test_a_long_one_breaks_at_directory_boundaries(self):
        p = '/home/someone/.local/share/Steam/steamapps/compatdata/429530/' \
            'pfx/drive_c/Falcon BMS 4.38/User/Config/BMS - VIRPIL.key'
        out = review._fold(p, width=60)
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(ln) <= 62 for ln in out), out)

    def test_it_stays_an_absolute_path(self):
        p = '/' + '/'.join(['directory'] * 12)
        self.assertTrue(review._fold(p, width=40)[0].startswith('/'))

    def test_nothing_is_lost(self):
        p = '/' + '/'.join(f'part{i}' for i in range(20))
        self.assertEqual(p, ''.join(review._fold(p, width=30)))


class Footer(unittest.TestCase):
    """Which keys exist, and where a reader is told.

    Two places now. The border carries the handful you reach for constantly
    and drops the rest when it runs out of room; `?` carries everything,
    which is where the capital forms live. So the border is allowed to be
    incomplete and `KEYS` is not.
    """

    WIDTH = 80

    #: `?` carries its own tones now, so these read the text half. The
    #: rules are about what the help SAYS, not how it is coloured.
    def said(self):
        return ' '.join(t for _tone, t in review.KEYS)

    def test_every_help_line_fits_a_standard_terminal(self):
        for _tone, line in review.KEYS:
            self.assertLessEqual(len(line), self.WIDTH - 1, line)

    def test_every_hint_in_the_border_is_also_in_the_help(self):
        # Otherwise the two drift and the short list becomes the only place
        # some key is named -- which is how `w write` went missing before.
        listed = self.said()
        for hint in review.HINTS:
            key = hint.split()[0]
            self.assertIn(key, listed, f'{hint!r} is nowhere in `?`')

    def test_moving_is_documented_at_all(self):
        # What it does, not how it is spelled: the last version of this
        # pinned 'g / G' and broke when the help went man-terse, which
        # told nobody anything about whether moving was documented.
        keys = self.said()
        for what in ('previous', 'next', 'first', 'last'):
            self.assertIn(what, keys)

    def test_every_branch_of_the_loop_is_reachable_from_the_footer(self):
        # Per branch, not per letter: `m` and `M` are one action under two
        # keys, while `c` and `C` are two actions. What has to be findable is
        # the action -- so each branch needs one of its keys spelled out.
        import inspect
        src = inspect.getsource(review._loop)
        listed = self.said()
        spelled = {'up': '↑', 'down': '↓', 'enter': '↵', 'esc': 'q',
                   ' ': 'SPACE'}
        branches = [frozenset(re.findall(r"'([^']+)'", m.group(1)))
                    for m in re.finditer(r"k (?:==|in) \(?([^:)]+)\)?:", src)]
        self.assertGreater(len(branches), 6, 'the parse found nothing')
        def spelled_out(token):
            # At a word boundary: a bare `in` check finds the `m` of
            # "confirm" and calls the map key documented.
            return re.search(rf'(^|[ ·/]){re.escape(token)}([ /]|$)', listed)

        for keys in branches:
            tokens = {spelled.get(k, k) for k in keys}
            self.assertTrue(any(spelled_out(t) for t in tokens),
                            f'{sorted(keys)} works, the footer never says so')


class Describing(unittest.TestCase):
    def test_a_game_that_supplies_nothing_still_works(self):
        rv = made()
        self.assertEqual([], rv.describe(rv.at[by(rv, 'Gear')]))

    def test_what_a_game_supplies_is_passed_straight_through(self):
        rv = made(describe=lambda p: [('push', p.need.what.upper())])
        self.assertEqual([('push', 'GEAR')],
                         rv.describe(rv.at[by(rv, 'Gear')]))


if __name__ == '__main__':
    unittest.main()

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

import unittest

import fake
from core import needs as corneeds
from core import review
from core.review import UNSET, PROPOSED, MINE
from core.needs import Layout, Need, allocate, IN_A_TURN, ON_THE_RAMP


def stick(*controls):
    return {'stick': fake.device('stick', list(controls))}


DEVS = lambda: stick(                                        # noqa: E731
    fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
    fake.button('Pinky button', 5, reach=fake.PINKY),
    fake.button('Panel button', 6, reach=fake.PANEL),
    fake.hat2('Panel rocker', 7, reach=fake.PANEL),
)

PLAN = [Need('Trim', 'hat4', ['U', 'R', 'D', 'L'], urgency=IN_A_TURN),
        Need('Gear', 'button', ['GEAR']),
        Need('Canopy', 'button', ['CANOPY'], urgency=ON_THE_RAMP)]


def made(needs=None, devs=None, **kw):
    devs = devs or DEVS()
    lay = Layout(devs, *allocate(list(needs or PLAN), devs),
                 axes=[('pitch', 'stick')])
    return review.Review(lay, 'Test', 'fake hardware', **kw)


def by(rv, what):
    return next(n for n in rv.needs if n.what == what)


class Starting(unittest.TestCase):
    def test_a_plan_arrives_proposed_and_not_yours(self):
        # Nothing to confirm is nothing to review: the whole point of the
        # screen is that the planner's output has not been looked at yet.
        rv = made()
        self.assertEqual([PROPOSED] * 3, [rv.mark[n] for n in rv.needs])
        self.assertEqual((0, 3, 0), rv.counts())

    def test_a_need_it_could_not_place_starts_unset(self):
        rv = made([Need('Trim', 'hat8', ['A'] * 8)])
        self.assertEqual(UNSET, rv.mark[by(rv, 'Trim')])
        self.assertEqual('(unset)', rv.where(by(rv, 'Trim')))
        self.assertEqual((0, 0, 1), rv.counts())

    def test_every_need_is_a_row_whether_it_has_a_control_or_not(self):
        rv = made(PLAN + [Need('Trim8', 'hat8', ['A'] * 8)])
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
        rv = made([Need('Trim', 'hat8', ['A'] * 8)])
        self.assertIn('nothing to confirm', rv.confirm(by(rv, 'Trim')))
        self.assertEqual(UNSET, rv.mark[by(rv, 'Trim')])

    def test_confirm_all_takes_the_proposals_and_leaves_the_gaps(self):
        rv = made(PLAN + [Need('Trim8', 'hat8', ['A'] * 8)])
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
        had = rv.at[by(rv, 'Gear')].ctrl.label
        self.assertNotIn(had, [c.label for _r, c in rv.free()])
        rv.clear(by(rv, 'Gear'))
        self.assertIn(had, [c.label for _r, c in rv.free()])

    def test_a_cleared_need_is_not_written(self):
        rv = made()
        rv.clear(by(rv, 'Gear'))
        self.assertNotIn('Gear', [p.need.what for p in rv.result().placed])


class Proposing(unittest.TestCase):
    def test_it_puts_the_planners_choice_back(self):
        rv = made()
        gear = by(rv, 'Gear')
        was = rv.at[gear].ctrl.label
        rv.clear(gear)
        rv.propose(gear)
        self.assertEqual(PROPOSED, rv.mark[gear])
        self.assertEqual(was, rv.at[gear].ctrl.label)

    def test_it_will_not_overwrite_something_you_chose(self):
        # The rule that makes "propose all" safe to press at any moment.
        rv = made()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        role, ctrl = rv.fits(gear)[-1]
        rv.assign(gear, role, ctrl)
        self.assertIn('yours already', rv.propose(gear))
        self.assertEqual(ctrl.label, rv.at[gear].ctrl.label)

    def test_it_says_so_when_the_planner_had_nothing(self):
        rv = made([Need('Trim', 'hat8', ['A'] * 8)])
        self.assertIn('nowhere to put it', rv.propose(by(rv, 'Trim')))

    def test_it_refuses_a_control_someone_else_took_meanwhile(self):
        rv = made()
        gear, canopy = by(rv, 'Gear'), by(rv, 'Canopy')
        wanted = rv.at[gear].ctrl
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
        rv = made([Need('Radar', 'button', ['ACM'], urgency=IN_A_TURN)],
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
        rv = made([Need('Trim', 'hat4', ['U', 'R', 'D', 'L'])], devs=devs)
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
        self.assertEqual('Thumb hat', rv.control_at('stick', 0).label)
        self.assertEqual('Thumb hat', rv.control_at('stick', 3).label)
        self.assertEqual('Thumb hat', rv.control_at('stick', 4).label,
                         'the click too')

    def test_a_button_in_no_control_resolves_to_nothing(self):
        self.assertIsNone(self.rv.control_at('stick', 99))
        self.assertIsNone(self.rv.control_at('nosuchrole', 0))

    def test_a_button_the_map_does_not_know_is_refused_by_name(self):
        self.assertIn('not in the device map',
                      self.rv.why_not(self.gear, 'stick', None))

    def test_a_control_that_carries_nothing_is_refused(self):
        devs = stick(fake.control('unwired', 'Phantom', [0]),
                     fake.button('Panel button', 1, reach=fake.PANEL))
        rv = made([Need('Gear', 'button', ['GEAR'])], devs=devs)
        phantom = next(c for c in rv.layout.devices['stick']._groups
                       if c.label == 'Phantom')
        self.assertIn('carries no binding',
                      rv.why_not(by(rv, 'Gear'), 'stick', phantom))

    def test_the_wrong_shape_is_refused_and_both_shapes_are_named(self):
        trim = by(self.rv, 'Trim')                  # wants a hat4
        why = self.rv.why_not(trim, 'stick', self.ctrl('Pinky button'))
        self.assertIn('button', why)
        self.assertIn('hat4', why)

    def test_too_few_buttons_is_refused_with_the_count(self):
        devs = stick(fake.selector('Three-way', 0, positions=3,
                                   reach=fake.PANEL))
        rv = made([Need('Trim', 'hat4', ['U', 'R', 'D', 'L'])], devs=devs)
        three = rv.layout.devices['stick'].groups(bindable=True)[0]
        why = rv.why_not(by(rv, 'Trim'), 'stick', three)
        self.assertIn('3', why)
        self.assertIn('4', why)

    def test_a_control_another_need_holds_is_refused_by_that_needs_name(self):
        # Canopy is a button need like Gear, so shape is not what refuses it
        # here -- it is genuinely occupied, and the message has to say by what.
        rv, gear = self.rv, self.gear
        canopy = by(rv, 'Canopy')
        why = rv.why_not(gear, 'stick', rv.at[canopy].ctrl)
        self.assertIn('Canopy', why)
        self.assertIn('x clears it', why)

    def test_shape_is_reported_before_occupancy(self):
        # Pressing a hat while a button need is selected: that it is the wrong
        # shape matters more than who happens to be sitting on it, because it
        # would not work even if it were free.
        rv, gear = self.rv, self.gear
        why = rv.why_not(gear, 'stick', rv.at[by(rv, 'Trim')].ctrl)
        self.assertIn('wants button', why)

    def test_moving_a_need_onto_the_control_it_already_has_is_fine(self):
        rv, gear = self.rv, self.gear
        self.assertIsNone(rv.why_not(gear, 'stick', rv.at[gear].ctrl))

    def test_a_control_that_fits_and_is_free_is_accepted(self):
        rv, gear = self.rv, self.gear
        rv.clear(gear)
        spare = next(c for _r, c in rv.fits(gear))
        self.assertIsNone(rv.why_not(gear, 'stick', spare))

    def test_who_has_names_the_holder_and_nothing_once_it_is_cleared(self):
        rv = self.rv
        trim = by(rv, 'Trim')
        held = rv.at[trim].ctrl
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
        self.assertEqual(ctrl.label, rv.at[gear].ctrl.label)

    def test_pressing_any_button_of_a_control_takes_the_whole_control(self):
        rv = made([Need('Trim', 'hat4', ['U', 'R', 'D', 'L'])])
        trim = by(rv, 'Trim')
        rv.clear(trim)
        rv.took(trim, 'stick', 2)                   # the third of four
        self.assertEqual('Thumb hat', rv.at[trim].ctrl.label)
        self.assertEqual([0, 1, 2, 3], [b for b, _v in rv.at[trim].slots])

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
        held = rv.at[canopy].ctrl.buttons[0]
        rv.clear(gear)
        self.assertIn('Canopy', rv.took(gear, 'stick', held))
        self.assertEqual(UNSET, rv.mark[gear])

    def test_pressing_the_control_it_already_has_is_harmless(self):
        rv, gear = self.rv, self.gear
        here = rv.at[gear].ctrl.buttons[0]
        self.assertIn('(yours)', rv.took(gear, 'stick', here))
        self.assertEqual(MINE, rv.mark[gear])


class WhereThePressLands(unittest.TestCase):
    """A press is a choice; `slots_for` is a guess. When they disagree about
    a single binding, the choice wins."""

    def trigger_plan(self):
        devs = stick(fake.trigger('Main trigger', 0,
                                  stages=('first', 'second', 'third'),
                                  reach=fake.INDEX))
        return made([Need('Fire', 'trigger', ['FIRE'])], devs=devs)

    def test_a_lone_binding_lands_on_the_stage_you_pressed(self):
        # It used to land on the first stage whichever you pressed, because
        # slots_for picks for a need that has only one thing to place.
        for press in (0, 1, 2):
            rv = self.trigger_plan()
            fire = by(rv, 'Fire')
            rv.clear(fire)
            rv.took(fire, 'stick', press)
            self.assertEqual([press], [b for b, _v in rv.at[fire].slots],
                             f'pressing {press}')

    def test_and_the_status_names_the_position_it_went_to(self):
        rv = self.trigger_plan()
        fire = by(rv, 'Fire')
        rv.clear(fire)
        self.assertIn('second', rv.took(fire, 'stick', 1))

    def test_a_need_wanting_the_whole_control_still_gets_its_own_order(self):
        # Four directions are the control's business, not the corner you
        # happened to touch.
        rv = made([Need('Trim', 'hat4', ['U', 'R', 'D', 'L'])])
        trim = by(rv, 'Trim')
        rv.clear(trim)
        rv.took(trim, 'stick', 2)
        self.assertEqual([0, 1, 2, 3], [b for b, _v in rv.at[trim].slots])

    def test_an_on_claim_beats_the_press(self):
        # `on` says a speedbrake is fore/aft whatever hat it lands on. Letting
        # a press overrule it is the lie `on` exists to stop.
        rv = made([Need('Speedbrake', 'hat4', ['OUT'], on=('forward',))])
        sb = by(rv, 'Speedbrake')
        rv.clear(sb)
        rv.took(sb, 'stick', 3)                     # 'left'
        landed = rv.at[sb].slots[0][0]
        ctrl = rv.at[sb].ctrl
        self.assertEqual('up', ctrl.direction(landed))

    def test_a_contact_that_carries_no_binding_is_not_used(self):
        # A rest contact is closed whenever the control is untouched, so
        # anything on it runs all the time. Pressing one falls back and says
        # so rather than binding there.
        devs = stick(fake.control('hat2', 'Rocker', [0, 1], rest_contact=2,
                                  reach=fake.THUMB))
        rv = made([Need('Flaps', 'hat2', ['UP'])], devs=devs)
        flaps = by(rv, 'Flaps')
        rv.clear(flaps)
        said = rv.took(flaps, 'stick', 2)
        self.assertNotIn(2, [b for b, _v in rv.at[flaps].slots])
        self.assertIn('carries no binding', said)

    def test_honours_press_says_why_in_each_case(self):
        rv = self.trigger_plan()
        fire = by(rv, 'Fire')
        ctrl = rv.at[fire].ctrl
        self.assertTrue(rv.honours_press(fire, ctrl, 1))
        many = Need('Trim', 'trigger', ['A', 'B'])
        self.assertFalse(rv.honours_press(many, ctrl, 1), 'wants the control')
        aimed = Need('Brake', 'trigger', ['A'], on=('first',))
        self.assertFalse(rv.honours_press(aimed, ctrl, 1), 'on wins')


class Writing(unittest.TestCase):
    def test_a_proposal_nobody_looked_at_is_still_written(self):
        # `?` says you did not check it, not that it is off -- the call DCS
        # makes too, whose generator has never filtered on the flag.
        rv = made()
        self.assertEqual((0, 3, 0), rv.counts())
        self.assertEqual(3, len(rv.result().placed))

    def test_only_needs_with_a_control_are_written(self):
        rv = made(PLAN + [Need('Trim8', 'hat8', ['A'] * 8)])
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
        rv = made([Need('Radar', 'button', ['ACM'], urgency=IN_A_TURN)],
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

    def test_only_needs_can_be_selected(self):
        rows = made().rows()
        self.assertTrue(all(r.kind == 'need' for r in rows if r.selectable))
        self.assertTrue(any(r.kind == 'head' for r in rows))


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

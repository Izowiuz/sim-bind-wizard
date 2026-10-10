"""The review's bookkeeping, without a terminal.

`core/review.py` holds two things: what the reviewer decided, and how it
is drawn. Only the first has anything to get wrong, and it decides what
ends up in the game's configuration. So it is kept outside the curses loop
and tested here.

The rules under test: three states rather than two, proposing fills gaps
and never overwrites, choosing by hand needs no confirming, and `?` is a
note to yourself rather than a filter.
"""

import curses
import inspect
import os
import re
import unittest
import unittest.mock

import fake
from core.actions import Action, Bind
from core import devmap
from core import needs as corneeds
from core import solvers as csolvers
from core import review
from core import tui as ctui
from core.review import UNSET, PROPOSED, MINE, MARK
from core.needs import Layout, Need, allocate, IN_A_TURN, ON_THE_RAMP
from test_box import Keyed


def stick(*controls):
    return {'stick': fake.device('stick', list(controls))}


DEVS = lambda: stick(                                        # noqa: E731
    fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
    fake.button('Pinky button', 5, reach=fake.PINKY),
    fake.button('Panel button', 6, reach=fake.PANEL),
    fake.hat2('Panel rocker', 7, reach=fake.PANEL),
)

def plan():
    """Fresh needs every time, and that is not fussiness.

    `allocate` writes `relaxed` onto a need, and a reviewer writes
    `category`. A module-level list is one set of objects shared by every
    test in the file, so one test filing something under "Combat" puts it
    there for all the others. That cost two failures in tests that were
    right.
    """
    return [Need('Trim', 'hat4',
                 [[Bind('U')], [Bind('R')], [Bind('D')], [Bind('L')]],
                 urgency=IN_A_TURN),
            Need('Gear', 'button', [[Bind('GEAR')]]),
            Need('Canopy', 'button', [[Bind('CANOPY')]],
                 urgency=ON_THE_RAMP)]


def made(needs=None, devs=None, **kw):
    devs = devs or DEVS()
    lay = Layout(devs, *allocate(list(needs or plan()), devs))
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

    `why_not` answers None for one that may, and every caller here is
    about a refusal. So None is the test failing, and not an answer to
    assert on.
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
        self.assertIn('is yours.', rv.confirm(by(rv, 'Gear')))

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

    def test_a_row_does_not_move_when_it_is_cleared(self):
        # The needs list runs every placement and then everything
        # unplaced. Rows in that order move: clearing a binding sends its
        # row to the bottom of its group on the next open, and a row you
        # are walking towards is not where you left it.
        rv = made()
        before = [r.text for r in rv.rows() if r.kind == 'need']
        for need in list(rv.needs):
            rv.clear(need)
        self.assertEqual(before,
                         [r.text for r in rv.rows() if r.kind == 'need'])

    def test_rows_are_in_name_order_inside_a_group(self):
        # The name is the one thing about a row that does not change when
        # you bind or clear it.
        rv = made()
        for _name, members in rv.groups():
            got = [n.what for n in members]
            self.assertEqual(sorted(got, key=str.lower), got)

    def test_clear_all_takes_yours_off_too(self):
        # It used to drop the proposals and nothing else, which left it
        # doing nothing at all on a screen you had just saved: everything
        # there is yours, so there was never a proposal to drop. `s` is
        # still what writes it, so the way back out is quitting.
        rv = made()
        trim = by(rv, 'Trim')
        rv.confirm(trim)
        rv.clear_all()
        self.assertEqual(UNSET, rv.mark[trim])
        self.assertIsNone(rv.at[trim])
        self.assertEqual((0, 0, 3), rv.counts())

    def test_the_controls_the_proposals_had_come_back_free(self):
        rv = made()
        had = at(rv, by(rv, 'Gear')).ctrl.label
        rv.clear_all()
        self.assertIn(had, [c.label for _r, c in rv.free()])

    def test_clear_all_says_when_there_is_nothing_bound(self):
        rv = made()
        rv.clear_all()
        self.assertIn('Nothing is bound.', rv.clear_all())

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
        self.assertIn('Press x to clear it first', rv.propose(gear))
        self.assertEqual(ctrl.label, at(rv, gear).ctrl.label)

    def test_it_says_so_when_the_planner_had_nothing(self):
        rv = made([Need('Trim', 'hat8', [[Bind('A')]] * 8)])
        self.assertIn('has no control for', rv.propose(by(rv, 'Trim')))

    def test_it_refuses_a_control_someone_else_took_meanwhile(self):
        rv = made()
        gear, canopy = by(rv, 'Gear'), by(rv, 'Canopy')
        wanted = at(rv, gear).ctrl
        rv.clear(gear)
        rv.assign(canopy, 'stick', wanted)      # by hand, onto Gear's control
        self.assertIn('is taken, so', rv.propose(gear))
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
        self.assertIn('does not have this button',
                      refused(self.rv, self.gear, 'stick', None))

    def test_a_control_that_carries_nothing_is_refused(self):
        devs = stick(fake.unwired('Phantom', [0]),
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
        # Canopy is a button need like Gear, so the shape is not what
        # refuses it here. The control is occupied, and the message says
        # by what.
        rv, gear = self.rv, self.gear
        canopy = by(rv, 'Canopy')
        why = refused(rv, gear, 'stick', at(rv, canopy).ctrl)
        self.assertIn('Canopy', why)
        self.assertIn('Press x to clear it', why)

    def test_shape_is_reported_before_occupancy(self):
        # Pressing a hat while a button need is selected: that it is the wrong
        # shape matters more than who happens to be sitting on it, because it
        # would not work even if it were free.
        rv, gear = self.rv, self.gear
        why = refused(rv, gear, 'stick', at(rv, by(rv, 'Trim')).ctrl)
        self.assertIn('This row needs a button', why)

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
        self.assertEqual([trim], rv.who_has('stick', held))
        rv.clear(trim)
        self.assertEqual([], rv.who_has('stick', held))

    def test_the_reach_column_is_a_number_and_a_finger(self):
        # It printed the words cut to ten, so a control nobody recorded a
        # finger for came out as `the hand o`. Asserted as the property,
        # not as the absence of one particular truncation: a column ten
        # wide can only hold a number, and a number needs the legend.
        import re
        lines = [t for _tone, t in self.rv.map_lines()]
        head = next(i for i, t in enumerate(lines) if 'REACH' in t
                    and 'CONTROL' in t)
        at = lines[head].index('REACH')
        rows = [t for t in lines[head + 1:] if t.startswith(('  +', '  ?',
                                                             '   '))]
        self.assertTrue(rows)
        for row in rows:
            cell = row[at:at + 10].strip()
            self.assertRegex(cell, r'^[0-9-]( \w+)?$', row)
        said = '\n'.join(lines)
        for n in corneeds.REACH_MEANS:
            if n != corneeds.UNMEASURED:
                self.assertIn(f'{n} {corneeds.REACH_MEANS[n]}', said)

    def test_who_has_names_every_need_on_one_control(self):
        # The share pass hands a leftover need one spare button of a
        # control something else took, so a hat holds four needs at once.
        # Thirteen controls across the five games do. The first one found
        # is the one the map names, as though the rest were nowhere.
        devs = {'stick': fake.device('stick', [
            fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4)])}
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')],
                                         [Bind('D')], [Bind('L')]]),
                   Need('Fire', 'button', [[Bind('FIRE')]])], devs=devs)
        ctrl = at(rv, by(rv, 'Trim')).ctrl
        self.assertEqual({'Trim', 'Fire'},
                         {n.what for n in rv.who_has('stick', ctrl)})
        said = '\n'.join(t for _tone, t in rv.map_lines())
        row = [ln for ln in said.splitlines() if 'Thumb hat' in ln][0]
        self.assertIn('Trim', row)
        self.assertIn('Fire', row)


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
        self.assertIn('does not have this button',
                      rv.took(gear, 'stick', 99))
        self.assertIs(was, rv.at[gear])

    def test_pressing_the_wrong_shape_changes_nothing(self):
        rv, gear = self.rv, self.gear
        rv.clear(gear)
        self.assertIn('This row needs a button',
                      rv.took(gear, 'stick', 0))
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
        self.assertTrue(corneeds.honours_press(fire, ctrl, 1))
        many = Need('Trim', 'trigger', [[Bind('A')], [Bind('B')]])
        self.assertFalse(corneeds.honours_press(many, ctrl, 1),
                         'wants the control')
        aimed = Need('Brake', 'trigger', [[Bind('A')]], on=('first',))
        self.assertFalse(corneeds.honours_press(aimed, ctrl, 1), 'on wins')


class Writing(unittest.TestCase):
    def test_a_proposal_nobody_looked_at_is_still_written(self):
        # `?` says you did not check it. It does not say the row is
        # off.
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
        self.assertEqual(2, len(out.placed))
        self.assertEqual(3, len(rv.layout.placed), 'the plan is not mutated')

    def test_axes_alone_are_something_to_write(self):
        # Clear every button and the layout still says which lever is
        # pitch, which is throttle, and which way round they run. That is
        # nine rows for the Hornet, and a check on BUTTONS alone refuses
        # to write any of it.
        from core import tui as ctui
        from test_box import Keyed
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.control('stick', 'Main stick', [], axes=[0])],
            [fake.axis(0, role='x')])}
        pitch = corneeds.Need('Pitch', 'stick', [[Bind('PITCH')]],
                              takes=corneeds.AXIS, device='stick')
        rv = made([pitch, Need('Boost', 'button', [[Bind('BOOST')]])],
                  devs=devs)
        for need in list(rv.needs):
            if need is not pitch:
                rv.clear(need)
        self.assertEqual([], rv.result().on_buttons)
        wrote = []
        tui = ctui.Tui(Keyed([10, 10, 27]), ctui.Theme(False))
        review._write(None, tui, rv, lambda kept: wrote.append(kept) or [])
        self.assertEqual(1, len(wrote), rv.status)
        self.assertEqual(['Pitch'],
                         [p.need.what for p in wrote[0].on_axes])

    def test_a_layout_with_neither_is_refused(self):
        from core import tui as ctui
        from test_box import Keyed
        rv = made()
        for need in list(rv.needs):
            rv.clear(need)
        tui = ctui.Tui(Keyed([10, 10, 27]), ctui.Theme(False))
        review._write(None, tui, rv, lambda kept: self.fail('wrote nothing'))
        self.assertIn('nothing to write', rv.status)

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
        # A heading is a thing you act on, because `R` renames it. What
        # is left unselectable is what answers nothing.
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
        # What a row binds is on the tree, under `h`. The panel answers
        # it. A footer for the same thing has no caller but a test.
        rv = self.rv()
        gear = by(rv, 'Gear')
        rv.clear(gear)
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need is gear)
        said = '\n'.join(t for _tone, t in review._side(rv, row, 40))
        self.assertIn('fit', said)

    def test_an_unassigned_row_costs_what_would_take_it(self):
        # It named the planner's choice and stopped. An empty row is
        # where "why there?" is still open, so it was the row that
        # answered least: nothing on screen to agree or disagree with.
        rv = self.rv()
        gear = by(rv, 'Gear')
        was = at(rv, gear).ctrl
        rv.clear(gear)
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need is gear)
        said = '\n'.join(t for _tone, t in review._side(rv, row, 60))
        self.assertIn('WHAT WOULD TAKE IT', said)
        self.assertIn('points', said)
        self.assertIn(f'WHAT MAKES {was.label.upper()} WORTH', said)


class TheDetailPanel(unittest.TestCase):
    """What the right-hand panel says about the row you are on.

    It answers three questions, and they are not the same question: what
    is this sitting on, what does it fire, and WHY is it there.

    A panel that lists the control and its reach and stops leaves the
    third unanswered. The planner's choice is the thing a reader argues
    with.

    `Reason` is the account of that choice, recorded where the decision
    was made. The panel is its first human reader.
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

    def test_it_says_what_else_was_in_the_running_and_who_has_it(self):
        # The panel drew the score: the band, the reach ceiling, and the
        # terms that summed to a total. That answers "how was this
        # scored", which for most bindings is not the reason. Over the
        # five games, 85 placements of 146 were ties and 24 more went
        # where they went because something better was taken; the score
        # breakdown was the true account of 16. So the panel names the
        # controls that beat it, and who is sitting on them.
        devs = stick(fake.button('Thumb', 0, reach=fake.THUMB),
                     fake.button('Pinky', 1, reach=fake.PINKY))
        rv = made([Need('First', 'button', [[Bind('A')]],
                        urgency=IN_A_TURN),
                   Need('Second', 'button', [[Bind('B')]],
                        urgency=IN_A_TURN)], devs=devs)
        got = self.text(rv, 'Second', width=44)
        self.assertIn('Thumb', got)
        self.assertIn('First', got, 'who is on the one that beat it')

    def test_every_token_of_wants_comes_from_the_needs_own_row(self):
        # Not derived and not prose: shape, device, band, and whichever
        # of the five flags somebody set, straight out of
        # `games/<g>/<g>-binds.json`. There is no sentence here to get
        # wrong.
        one = Need('Chaff', 'button', [[Bind('A')]], urgency=IN_A_TURN,
                   device='stick')
        setattr(one, 'by_feel', True)
        rv = made([one], devs=stick(fake.button('Thumb', 0,
                                                reach=fake.THUMB)))
        got = self.text(rv, 'Chaff', width=60)
        asked = got[got.index('WHAT IT ASKED FOR'):]
        asked = asked[:asked.index('WHICH CONTROL')]
        for token in ('button', 'stick', 'in a turn', 'found blind'):
            self.assertIn(token, asked)

    def test_a_flag_nobody_set_is_not_in_wants(self):
        rv = made([Need('Chaff', 'button', [[Bind('A')]])],
                  devs=stick(fake.button('Thumb', 0, reach=fake.THUMB)))
        got = self.text(rv, 'Chaff', 60)
        asked = got[got.index('WHAT IT ASKED FOR'):]
        asked = asked[:asked.index('WHICH CONTROL')]
        for phrase in ('held down', 'tapped', 'found blind'):
            self.assertNotIn(phrase, asked)

    def test_each_control_says_what_it_was_worth(self):
        # Every control is worth points to an action; the actions go in
        # order; each takes the free control worth most. The points are
        # the mechanism, so the points are a column.
        devs = stick(fake.button('Thumb', 0, reach=fake.THUMB),
                     fake.button('Pinky', 1, reach=fake.PINKY))
        rv = made([Need('A', 'button', [[Bind('A')]], urgency=IN_A_TURN),
                   Need('B', 'button', [[Bind('B')]], urgency=IN_A_TURN)],
                  devs=devs)
        got = self.text(rv, 'B', width=60)
        self.assertIn('points', got)
        for _s, role, ctrl in corneeds.ran_against(by(rv, 'B'),
                                                   rv.layout.devices):
            self.assertIn(ctrl.label, got)
            self.assertIn(str(_s), got)

    def test_the_winners_points_are_broken_down(self):
        # The last section: what the number was made of. The middle
        # section says which control, this one says how that control got
        # the number it did.
        devs = stick(fake.button('Thumb', 0, reach=fake.THUMB))
        rv = made([Need('A', 'button', [[Bind('A')]], urgency=IN_A_TURN)],
                  devs=devs)
        got = self.text(rv, 'A', width=60)
        self.assertIn('the shape and the count fit', got)
        self.assertRegex(got, r'\+\d+  \S')

    def test_a_control_carrying_several_needs_says_how_many(self):
        # The share pass hands a leftover need a spare button of a
        # control something else took, so several names belong on one
        # row. The first name and a count. The map screen has room for
        # all of them and this column has room for one.
        #
        # `Flaps` wants a hat2, and a hat4 stands in for one, so the
        # shared hat is a real candidate for it. A button need is never
        # ranked against a hat and sees nothing.
        devs = stick(fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4),
                     fake.hat2('Rocker', 5, reach=fake.PINKY))
        rv = made([Need('Trim', 'hat4', [[Bind(x)] for x in 'URDL']),
                   Need('Fire', 'button', [[Bind('F')]]),
                   Need('Flaps', 'hat2', [[Bind('U')], [Bind('D')]])],
                  devs=devs)
        hat = next(c for c in devs['stick'].groups()
                   if c.label == 'Thumb hat')
        self.assertGreater(len(rv.who_has('stick', hat)), 1,
                           'the rig must share the hat')
        self.assertRegex(self.text(rv, 'Flaps', width=60), r'Trim \+\d')

    def test_a_tie_shows_the_others_and_claims_nothing(self):
        # The commonest case by far. Equal rows side by side are the
        # answer; a line saying `nothing chose` repeats what they show.
        devs = stick(fake.button('One', 0, reach=fake.THUMB),
                     fake.button('Two', 1, reach=fake.THUMB))
        rv = made([Need('A', 'button', [[Bind('A')]]),
                   Need('B', 'button', [[Bind('B')]])], devs=devs)
        got = self.text(rv, 'B', width=60)
        self.assertIn('One', got)
        self.assertIn('Two', got)
        self.assertNotIn('freely', got)
        self.assertNotIn('nothing chose', got)

    def test_this_one_is_marked_and_says_nothing_else(self):
        # A mark at the start of the row does what `← this one` did.
        devs = stick(fake.button('Thumb', 0, reach=fake.THUMB))
        rv = made([Need('A', 'button', [[Bind('A')]])], devs=devs)
        got = self.text(rv, 'A', width=60)
        self.assertIn('\u25b6', got)
        self.assertNotIn('this one', got)

    def test_choosing_it_yourself_says_so_and_what_you_overrode(self):
        rv = self.rv()
        gear = by(rv, 'Gear')
        was = at(rv, gear).ctrl
        # Somewhere the planner did not pick, whichever solver ran: the
        # two of them disagree about most of a layout.
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c is not was and c.kind in gear.shapes)
        for holder in rv.who_has('stick', ctrl):
            rv.clear(holder)
        rv.assign(gear, 'stick', ctrl)
        got = self.text(rv, 'Gear', width=60)
        self.assertIn('by hand', got)
        self.assertIn(was.label, got, 'where the planner had wanted it')
        self.assertIn(f'The planner wants {was.label}.', got)

    def test_a_shared_button_says_which_pass_placed_it(self):
        # In `HOW IT WAS SET`, which is the section about how the row
        # came to be there, and in the words `CAME_BY` has for it.
        #
        # A sentence of its own under the candidate list, such as `This is
        # a spare button. Trim has the control.`, reads as a note about
        # the arrow above it, and nothing else on the panel says a share
        # happened.
        devs = stick(fake.hat4('Thumb hat', 0, reach=fake.THUMB, push=4))
        rv = made([Need('Trim', 'hat4', [[Bind(x)] for x in 'URDL']),
                   Need('Fire', 'button', [[Bind('F')]])], devs=devs)
        got = self.text(rv, 'Fire', width=60)
        self.assertIn('HOW IT WAS SET', got)
        self.assertIn('shares a control', got)
        head = got[got.index('HOW IT WAS SET'):]
        self.assertIn('shares', head[:head.index('WHICH CONTROL')])

    def test_the_only_control_that_fits_is_one_row_and_no_words(self):
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')],
                                         [Bind('D')], [Bind('L')]])],
                  devs=stick(fake.hat4('Only hat', 0, reach=fake.THUMB)))
        got = self.text(rv, 'Trim', width=60)
        tail = got[got.index('WHICH CONTROL GOT IT'):].splitlines()
        rows = [ln for ln in tail if '\u25b6' in ln]
        self.assertEqual(1, len(rows))
        self.assertIn('Only hat', rows[0])

    def test_it_names_the_shape_the_control_matched(self):
        self.assertIn('hat4', self.text(self.rv(), 'Trim'))

    def test_a_placement_that_reached_past_the_floor_says_so(self):
        rv = made([Need('Airbrake', 'hat2', [[Bind('OUT')], [Bind('IN')]],
                        urgency=IN_A_TURN)],
                  devs=stick(fake.hat2('Panel rocker', 0,
                                       reach=fake.PANEL)))
        self.assertIn('No closer control was free.',
                      self.text(rv, 'Airbrake', width=44))

    # ---- the override mention ----


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

    # ---- the decision, drawn ----

    def test_a_hand_placed_one_is_costed_like_any_other(self):
        # One line, the control's name, and a stop, on the argument that
        # you chose it and there is no argument to draw.
        #
        # What a control is worth to an action is a fact about the desk
        # and not about who typed it, and the number is the whole of what
        # there is to disagree with. Counted over the six games, that
        # panel refuses it on 45 rows of 174, and 31 of those are
        # DCS's.
        rv = self.rv()
        gear = by(rv, 'Gear')
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c.label == 'Panel button')
        rv.assign(gear, 'stick', ctrl)
        got = self.text(rv, 'Gear', width=60)
        self.assertIn('points', got)
        self.assertIn('WHAT MAKES PANEL BUTTON WORTH', got)

    # ---- which button of the control ----

    def test_which_button_is_not_a_section(self):
        # A phrase per binding, saying why that button, produces 223
        # phrases across the five games, and 221 of them say nothing
        # happened: `press order`, `as asked`, and `asked for back; this
        # control calls it aft` about two words for one direction.
        got = self.text(self.rv(), 'Trim', width=60)
        self.assertNotIn('WHICH BUTTON', got)
        for rule in ('press order', 'as asked'):
            self.assertNotIn(rule, got)
    def test_the_sections_are_headings_not_plain_text(self):
        tones = {tone for tone, t in self.side(self.rv(), 'Trim')
                 if t.isupper() and t.strip()}
        self.assertEqual({'head'}, tones)

    # ---- the width ----

    def test_nothing_comes_back_wider_than_the_panel(self):
        # `_draw` wraps without a hanging indent, so a ledger line it
        # breaks lands flush left and stops reading as a ledger. The
        # panel wraps its own lines.
        for w in (18, 22, 26, 40):
            for _tone, t in self.side(self.rv(), 'Trim', w):
                self.assertLessEqual(len(t), w, repr(t))


class HowItWasSet(unittest.TestCase):
    """The panel names which of the three ways a binding got there.

    Three can be true of a row and the file records which: the planner
    put it there and nobody has looked, the planner put it there and you
    said yes, you put it there by hand. The panel said one of them, as a
    phrase under the heading about which control beat which; the other
    two were only a row colour, and a colour is gone the moment you read
    the sheet instead of the screen.
    """

    def set(self, rv, what):
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need.what == what)
        said = '\n'.join(t for _tone, t in review._side(rv, row, 46))
        tail = said[said.index('HOW IT WAS SET'):]
        end = tail.find('WHICH CONTROL')
        return tail if end < 0 else tail[:end]

    def test_the_planner_put_it_there_and_you_have_not_looked(self):
        got = self.set(made(), 'Gear')
        self.assertIn('the planner', got)
        self.assertIn('nothing yet', got)

    def test_the_planner_put_it_there_and_you_said_yes(self):
        rv = made()
        rv.confirm(by(rv, 'Gear'))
        got = self.set(rv, 'Gear')
        self.assertIn('the planner', got)
        self.assertIn('yes, to this control', got)

    def test_you_said_yes_to_a_control_the_allocator_has_since_left(self):
        # The row is still yours in the file and the planner has moved
        # on: `yes, to this control` would be a lie about the control
        # under the cursor.
        rv = made()
        gear = by(rv, 'Gear')
        rv.confirm(gear)
        gear.assignment = dict(gear.assignment or {}, control='gone')
        self.assertIn('yes, to another control', self.set(rv, 'Gear'))

    def test_you_put_it_there_by_hand(self):
        rv = made()
        gear = by(rv, 'Gear')
        ctrl = next(c for c in rv.layout.devices['stick'].groups(bindable=True)
                    if c is not at(rv, gear).ctrl and c.kind in gear.shapes)
        for holder in rv.who_has('stick', ctrl):
            rv.clear(holder)
        rv.assign(gear, 'stick', ctrl)
        got = self.set(rv, 'Gear')
        self.assertIn('by hand', got)
        self.assertIn('yours', got)
        self.assertNotIn('set by  the planner', got)

    def test_it_is_not_under_the_heading_about_which_control_won(self):
        # Where it used to live. That heading answers "why this control
        # and not that one", and who typed it is not an answer to that.
        rv = made()
        rv.confirm(by(rv, 'Gear'))
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need.what == 'Gear')
        said = '\n'.join(t for _tone, t in review._side(rv, row, 46))
        self.assertLess(said.index('HOW IT WAS SET'),
                        said.index('WHICH CONTROL GOT IT'))
        self.assertNotIn('you said', said[said.index('WHICH CONTROL GOT IT'):])


class Categories(unittest.TestCase):
    """What the list groups by.

    The urgency band is the allocator's scale and not yours: four
    buckets, named for when you touch a thing, fixed in the source.

    A category is yours. You name it, you put things in it, and you move
    them between.

    They are two fields on purpose. "Combat" holds something you reach
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
        # A category that holds something you reach for in a turn belongs
        # above one whose most urgent member waits for the ramp. That is
        # the order the bands have, derived rather than declared.
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

    The screen shows 147 rows across five games, and those games accept
    5856 actions between them. The other 5709 are not hidden. Nothing
    knows about them, because the list is a hand-written literal and the
    vocabulary is consulted to check spelling.
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

    def test_an_axis_goes_on_the_list_like_anything_else(self):
        # It was refused, on the argument that an axis row needs a shape
        # and a rest and the vocabulary says neither. Axes go through
        # the allocator with every other need now, and `J` says both --
        # so the refusal was the last thing standing, and it stood in
        # the way of binding an axis by hand at all.
        rv = self.rv()
        said = rv.promote(self.CAT[2], 'Combat')
        self.assertIn('Pitch', [n.what for n in rv.needs])
        got = next(n for n in rv.needs if n.what == 'Pitch')
        self.assertEqual(corneeds.AXIS, got.takes)
        self.assertEqual('axis', got.shape, 'any lever will do')
        self.assertIn('on the list', said)

    def test_promoting_says_the_file_is_behind(self):
        # A judgement is derived from nothing, so it has to be keepable --
        # but not written on the keystroke: `s` writes, the way the
        # capture wizard does, and the screen says `unsaved` until it has.
        kept = []
        rv = made(catalogue=self.CAT,
                  save=lambda needs, axes=(): kept.append(list(needs)) or 'saved')
        rv.promote(self.CAT[0], 'Combat')
        self.assertEqual([], kept, 'wrote without being asked')
        self.assertTrue(rv.unsaved)
        rv.keep()
        self.assertIn('Landing gear', [n.what for n in kept[-1]])
        self.assertFalse(rv.unsaved)

    def test_a_screen_with_nowhere_to_write_still_works(self):
        # DCS derives its needs, so there is no list to keep. A screen
        # that raised over that takes the whole review down for a thing
        # it cannot help.
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

    def test_it_is_written_down_when_you_save(self):
        kept = []
        rv = made(save=lambda needs, axes=(): kept.append(list(needs)) or 'ok')
        rv.refile(by(rv, 'Trim'), 'Combat')
        self.assertTrue(rv.unsaved)
        rv.keep()
        self.assertEqual(['Combat'], [n.category for n in kept[-1]
                                      if n.what == 'Trim'])

    def test_putting_it_back_in_its_band_forgets_the_category(self):
        # The band is the fallback and not a category. Written down as a
        # name, it makes the fallback a place you cannot leave.
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
    """A category heading is a thing you stand on.

    `R` that renames the group the cursor's row is IN renames a category
    by standing on one of its members, and it leaves the heading the one
    thing on the screen you read and cannot touch.

    Everything else stays guarded by `row.kind`. A handler that needs a
    `Need` asks for one and gets None on a heading, which is the graceful
    half. A handler that acts on a group branches on the kind itself,
    rather than leaning on `need is not None`.
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
    """Standing on a heading says something.

    `_side` that answers `[]` for anything which is not a need leaves an
    empty box beside a heading, and that reads as a hole rather than as a
    thing you are on.
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


class BeforeWriting(unittest.TestCase):
    """What `w` says before it does it.

    The keystroke overwrites a game's configuration file. A warning that
    some bindings are still `?`, printed AFTER the file is written, is a
    warning about a decision already made.
    """

    def rv(self, **kw):
        return made(paths=[('writes', '/games/thing/inputmap_3.xml')], **kw)

    def text(self, rv, width=60):
        return '\n'.join(t for _tone, t in review._write_plan(rv, width))

    def test_it_names_the_file_it_will_write(self):
        self.assertIn('inputmap_3.xml', self.text(self.rv()))

    def test_it_says_how_much(self):
        rv = self.rv()
        n = len(rv.result().placed)
        self.assertIn(str(n), self.text(rv))

    def test_it_warns_that_unaccepted_ones_go_too(self):
        # Before, not after: `?` means you have not looked, and the file
        # is written with them in it either way.
        rv = self.rv()
        said = self.text(rv)
        self.assertIn(review.MARK_SAID[PROPOSED], said)

    def test_a_plan_you_have_been_through_says_nothing_of_the_kind(self):
        rv = self.rv()
        rv.confirm_all()
        self.assertNotIn(review.MARK_SAID[PROPOSED], self.text(rv))


class WhatYouDecidedOutLastsTheSession(unittest.TestCase):
    """What you decided outlasts the session.

    Marks and placements rebuilt from the planner on every open bring `C`
    over the whole list back purple and in the planner's order, and they
    move a binding you moved by hand back. Three things reach disk then:
    a category, a rename and an added entry. Nothing about where anything
    sits.

    Two strengths, because pressing RETURN and pressing `c` are not the
    same claim. `chose` takes the control before anything is scored.
    `accepted` changes no allocation: it records WHICH control you said
    yes to, so the row goes back to `?` the day the allocator moves it.
    """

    def rig(self, *labels):
        return {'stick': fake.device('stick', [
            fake.button(l, i, reach=fake.THUMB)
            for i, l in enumerate(labels)])}

    def setUp(self):
        self.saved = []
        self.devs = self.rig('Thumb A', 'Thumb B')
        self.needs = [Need('Boost', 'button', [[Bind('BOOST')]])]

    def open(self, devs=None):
        devs = devs or self.devs
        return made(self.needs, devs=devs,
                    save=lambda needs, axes=():
                    self.saved.append(needs),
                    # What the adapter hands the real screen. `p` on a
                    # row you cleared and saved lays the thing out again.
                    # The allocator was told to leave that row alone, so
                    # the last plan holds nothing for it.
                    rebuild=lambda: Layout(devs,
                                           *allocate(self.needs, devs)))

    def only(self, rv):
        return rv.needs[0]

    # ---- accepted: a note that survives, and knows when it is stale ----

    def test_accepting_survives_a_reopen(self):
        rv = self.open()
        rv.confirm_all()
        self.assertEqual(review.MINE, self.open().mark[self.only(rv)])

    def test_accepting_the_whole_list_is_one_write(self):
        rv = self.open()
        rv.confirm_all()
        self.assertEqual([], self.saved, 'wrote without being asked')
        rv.keep()
        self.assertEqual(1, len(self.saved), 'one write, not one per need')

    def test_accepting_does_not_freeze_the_allocator(self):
        # `c` over a full list is one keystroke. If it pinned every row
        # the allocator would never speak again, and the only way back
        # would be clearing forty-five rows by hand.
        rv = self.open()
        rv.confirm_all()
        need = self.only(rv)
        self.assertEqual(corneeds.ACCEPTED, need.assignment['how'])
        placed, _un, _free = allocate(self.needs, self.rig('Thumb B'))
        self.assertEqual('Thumb B', placed[0].ctrl.label)

    def test_a_row_the_allocator_moved_goes_back_to_asking(self):
        # The one moment the mark has something to tell you.
        rv = self.open()
        rv.confirm_all()
        moved = self.open(self.rig('Thumb B', 'Thumb C'))
        self.assertEqual(review.PROPOSED, moved.mark[self.only(moved)])

    # ---- chose: a fact, and nothing argues with it ----

    def test_choosing_by_hand_survives_a_reopen(self):
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        again = self.open()
        self.assertEqual(review.MINE, again.mark[self.only(again)])
        self.assertEqual('Thumb B', at(again, self.only(again)).ctrl.label)

    def test_choosing_by_hand_is_kept_when_you_save(self):
        # The test asserts the WRITE, because the objects live on in
        # memory either way and a reopen in one process proves nothing.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        self.assertEqual([], self.saved, 'wrote without being asked')
        self.assertTrue(rv.unsaved)
        rv.keep()
        self.assertEqual(1, len(self.saved))
        self.assertFalse(rv.unsaved)

    def test_what_you_chose_is_taken_before_anything_is_scored(self):
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        self.assertEqual(corneeds.CHOSE, self.only(rv).assignment['how'])
        # Something the allocator would rather have there cannot have it.
        rival = Need('Guns', 'button', [[Bind('GUNS')]],
                     urgency=corneeds.IN_A_TURN)
        placed, _un, _free = allocate(self.needs + [rival], self.devs)
        where = {p.need.what: p.ctrl.label for p in placed}
        self.assertEqual('Thumb B', where['Boost'])

    def test_a_control_you_chose_that_is_gone_leaves_the_row_empty(self):
        # Not moved, and not shared a button somewhere else either:
        # moving it is the one thing writing the choice down was for.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        placed, unplaced, _free = allocate(self.needs, self.rig('Thumb A'))
        self.assertEqual([], placed)
        self.assertEqual(['Boost'], [n.what for n in unplaced])

    def test_an_empty_row_says_which_kind_of_empty_it_is(self):
        # "The planner has no control for this row" and "the thing you
        # chose is gone" look identical on a row and want opposite things
        # from you.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        gone = self.open(self.rig('Thumb A'))
        need = self.only(gone)
        self.assertIsNone(gone.at[need])
        said = gone.unhonoured(need)
        self.assertIn('thumb-b', said)
        self.assertIn('does not have this control', said)
        # Joined with a space, not a newline: the panel wraps to its
        # width, so a sentence long enough to matter is split across two
        # of these pieces.
        panel = ' '.join(t for _tone, t in review._side(
            gone, review.Row('need', '', need=need), 60))
        self.assertIn('does not have this control', panel)

    def test_a_row_the_planner_simply_could_not_fill_says_no_such_thing(self):
        rv = made([Need('Trim', 'hat4', [[Bind('U')], [Bind('R')],
                                         [Bind('D')], [Bind('L')]])],
                  devs=self.rig('Only button'))
        need = rv.needs[0]
        self.assertIsNone(rv.at[need])
        self.assertEqual('', rv.unhonoured(need))

    def test_the_id_is_what_is_written_down_not_the_label(self):
        # A label is the thing the capture wizard lets you retype; the map
        # promises an id outlives that and renumbering the buttons.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        self.assertEqual(other.id, self.only(rv).assignment['control'])
        self.assertNotIn(other.label, self.only(rv).assignment.values())

    # ---- clearing ----

    def test_clearing_forgets_that_you_chose_it(self):
        # Otherwise `x` clears the screen and the next open puts it back
        # on the control you had just taken it off.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        rv.clear(self.only(rv))
        self.assertEqual(corneeds.CLEARED,
                         self.only(rv).assignment['how'])

    def test_a_row_you_cleared_opens_cleared(self):
        # The bug this file is the record of: the file held what sits
        # where and had no way to say "nothing, and I meant it", so `s`
        # answered that nothing had changed and the next open proposed
        # the row straight back.
        rv = self.open()
        rv.clear(self.only(rv))
        self.assertTrue(rv.unsaved)
        again = self.open()
        self.assertEqual(review.UNSET, again.mark[self.only(again)])
        self.assertIsNone(again.at[self.only(again)])

    def test_clearing_a_proposal_is_something_to_save(self):
        # It was not: `touched` ran only where you had chosen the control
        # by hand, so clearing what the planner proposed left the screen
        # saying `nothing has changed since the last save`.
        rv = self.open()
        self.assertEqual(review.PROPOSED, rv.mark[self.only(rv)])
        rv.clear(self.only(rv))
        self.assertTrue(rv.unsaved)

    def test_p_puts_back_a_row_you_cleared_and_saved(self):
        # Otherwise `x` on a saved row could only be undone by assigning
        # the thing by hand, and the key that says it restores a proposal
        # would answer that there is none to restore.
        rv = self.open()
        rv.clear(self.only(rv))
        again = self.open()
        again.propose(self.only(again))
        self.assertEqual(review.PROPOSED, again.mark[self.only(again)])
        self.assertIsNotNone(again.at[self.only(again)])

    def test_dropping_proposals_leaves_what_you_chose(self):
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        rv.clear_all()
        self.assertIsNotNone(self.only(rv).assignment)

    # ---- and it all round trips ----

    def test_it_survives_the_file(self):
        # Through the binds file, which is where it lives: the needs file
        # describes the function and says nothing about where it sits.
        rv = self.open()
        other = next(c for c in self.devs['stick'].groups()
                     if c.label == 'Thumb B')
        rv.assign(self.only(rv), 'stick', other)
        was = self.only(rv).assignment
        (back,) = corneeds.read_needs(corneeds.dump_needs(self.needs))
        self.assertIsNone(back.assignment)
        corneeds.read_assignments(corneeds.dump_assignments(self.needs),
                                  [back])
        self.assertEqual(was, back.assignment)

    def test_what_the_allocator_chose_comes_back_as_nothing(self):
        # It is written so a screen shows what moved since last time, and
        # read back as no claim at all. Otherwise every run starts from
        # wherever the last one stopped.
        rv = self.open()
        need = self.only(rv)
        need.assignment = {'role': 'stick', 'control': 'thumb-b',
                           'how': corneeds.SOLVED}
        (row,) = corneeds.dump_assignments([need])
        self.assertEqual(corneeds.SOLVED, row['how'])
        (back,) = corneeds.read_needs(corneeds.dump_needs([need]))
        corneeds.read_assignments([row], [back])
        self.assertIsNone(back.assignment)


class EveryKeyTheScreenNamesIsOneItAnswers(unittest.TestCase):
    """The help, the sill and the handler, held to each other.

    Three places name the keys, and somebody who renames one has to find
    all three. Without this test the only thing that catches a miss is
    pressing the key.

    A key named and not answered is worse than a missing line: you press
    it, nothing happens, and nothing says why. The one that loses work is
    `w` still reading "write" in the sill while the handler has stopped
    listening.
    """

    def named(self, rows):
        """The single letters a help table offers as keys."""
        out = set()
        for row in rows:
            text = row[1] if isinstance(row, tuple) else row
            if isinstance(row, tuple) and row[0] != 'plain':
                continue
            head = re.split(r'\s{3,}', text.strip(), maxsplit=1)[0]
            out |= {t for t in head.split() if len(t) == 1 and t.isalpha()}
        return out

    def answered(self):
        """The keys `_loop` compares against, read out of its source."""
        src = inspect.getsource(review._loop)
        return set(re.findall(r"k (?:==|in \()\s*'(\w)'", src)) | set(
            re.findall(r"'(\w)'[,)]", src))

    def test_every_key_the_help_names_is_answered(self):
        missing = self.named(review.KEYS) - self.answered()
        self.assertEqual(set(), missing, 'named in `?` and never answered')

    def test_every_key_the_sill_names_is_answered(self):
        missing = self.named(review.HINTS) - self.answered()
        self.assertEqual(set(), missing, 'shown in the sill and dead')

    def test_the_sill_and_the_help_agree(self):
        # The sill is a subset by design, because it holds what you reach
        # for constantly. A key in it the help has never heard of is one
        # a rename left behind.
        self.assertEqual(set(), self.named(review.HINTS)
                         - self.named(review.KEYS))

    def test_save_is_where_the_capture_wizard_puts_it(self):
        # The pair of tools is used in one sitting, and `s` SAVED in the
        # capture wizard from the first commit. Here it used to write the
        # game's own files, so one key meant two things across two tools
        # used in one evening.
        self.assertIn('s save', review.HINTS)
        self.assertIn('s', self.answered())

    def test_writing_the_game_has_its_own_key(self):
        self.assertIn('w write', review.HINTS)
        self.assertIn('w', self.answered())

    def test_no_key_is_answered_twice(self):
        # Answered is not the same as reachable. A `j` that is both a
        # step down the list AND the job menu answers at the step, which
        # comes first in the chain. The menu never opens, and `j job` in
        # the sill is a line about nothing. The two tests above pass
        # straight over that, because the key IS answered.
        #
        # Twice is allowed and used. `c` and `enter` mean one thing on an
        # axis row and another on a need, and each branch says which row
        # it wants. What kills a key is an earlier branch that asks for
        # nothing but the key. Nothing after that sees it.
        src = inspect.getsource(review._loop)
        branches = re.findall(r"^\s+(?:el)?if k (?:==|in) ([^:]+):", src,
                              re.M)
        alone, dead = set(), set()
        for cond in branches:
            test, _sep, rest = cond.partition(' and ')
            keys = {t.strip().strip("'") for t in test.strip('()').split(',')
                    if "'" in t}
            dead |= keys & alone
            if not rest:
                alone |= keys
        self.assertEqual(set(), dead, 'shadowed by an earlier branch')


class AGameMayPutAKeyOnTheScreen(unittest.TestCase):
    """For the one thing only that game does.

    DCS lays out one aircraft module at a time, because the Hornet's
    commands are not the Su-25T's. So changing which one means a
    different list, a different store and a different kneeboard. A menu
    of its own for that is half of why a game keeps a whole screen.
    """

    def rv(self, offers):
        return made([Need('Boost', 'button', [[Bind('BOOST')]])],
                    offers=offers)

    def test_the_word_goes_in_the_sill_beside_the_family_s(self):
        rv = self.rv([('t', 'type', lambda _rv, _tui: 'picked')])
        said = review.HINTS + tuple(f'{k} {w}' for k, w, _d in rv.offers)
        self.assertIn('t type', said)

    def test_a_key_the_screen_already_answers_to_is_refused(self):
        # Which of the two wins depends on the order of an elif chain,
        # and neither answer is a thing to find out at the keyboard.
        with self.assertRaises(ValueError) as caught:
            self.rv([('c', 'clash', lambda _rv, _tui: '')])
        self.assertIn('already', str(caught.exception))

    def test_a_game_that_offers_nothing_is_the_normal_case(self):
        self.assertEqual([], self.rv([]).offers)

    def driven(self, offers, keys):
        """`_loop` over a fake screen, and what it returned.

        `Sticks` opens no device until a capture asks it to, so a loop
        with no press in it costs nothing here.
        """
        rv = self.rv(offers)
        scr = Keyed(list(keys))
        # `setup` is the one part that wants a real terminal: it sets the
        # cursor and starts colour. A `Tui` over the fake screen is what
        # every other screen test uses.
        with unittest.mock.patch.object(
                review.ctui, 'setup',
                lambda s: ctui.Tui(s, ctui.Theme(False))):
            got = review._loop(scr, rv, None, review.Sticks(rv.layout))
        return got, scr.frames

    def test_a_word_it_answers_with_lands_in_the_status(self):
        got, _frames = self.driven(
            [('t', 'type', lambda _rv, _tui: 'picked the same one')],
            [ord('t'), ord('q')])
        self.assertIsNone(got)

    def test_an_adapter_it_answers_with_comes_back_out_of_the_loop(self):
        # This is DCS's `t`. The screen closes and `Adapter.review`
        # opens a new one on what comes back, because another aircraft is
        # another list, another store and another kneeboard. A loop that
        # swallowed this left the key doing nothing you could see.
        sentinel = object()
        got, _frames = self.driven(
            [('t', 'type', lambda _rv, _tui: sentinel)],
            [ord('t')])
        self.assertIs(sentinel, got)


class AnAxisIsARowLikeAnyOther(unittest.TestCase):
    """The axes, on the one list, answering the one set of keys.

    A second model of everything is their own object, their own resolver,
    their own section at the bottom of the list, their own panel, their
    own file section, and their own branch of `c`, `x`, `↵` and `i`. None
    of that is a decision. It is how they grow.

    The one thing that is different is that a lever is NAMED and not
    chosen, and that is one pass in the allocator.
    """

    def rv(self, **kw):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.control('stick', 'Main stick', [], axes=[0, 1])],
            [fake.axis(0, role='x'),
             fake.axis(1, hid='Y', role='y', moves_with=[0],
                       coupling='fixed')])}
        pitch = corneeds.Need('Pitch', 'stick', [[Bind('PITCH')]],
                              takes=corneeds.AXIS, device='stick',
                              on=('y',), urgency=IN_A_TURN)
        boost = Need('Boost', 'button', [[Bind('BOOST')]])
        return made([pitch, boost], devs=devs,
                    save=lambda needs: 'ok', **kw), pitch

    def row_of(self, rv, need):
        return next(r for r in rv.rows()
                    if r.kind == 'need' and r.need is need)

    def panel(self, rv, need, width=44):
        return '\n'.join(t for _tone, t in review._side(
            rv, self.row_of(rv, need), width))

    def test_it_is_in_the_list_with_everything_else(self):
        # Not in a section of its own at the bottom. It is filed by band
        # like every other row, and `f` filters it like every other row.
        rv, pitch = self.rv()
        rv.layout.axes = []
        self.assertNotIn('AXES', [r.text for r in rv.rows()])
        row = self.row_of(rv, pitch)
        self.assertEqual('Pitch', row.text)
        self.assertTrue(row.selectable)

    def test_it_wears_the_same_two_marks(self):
        rv, pitch = self.rv()
        self.assertEqual(PROPOSED, rv.mark[pitch])
        rv.confirm(pitch)
        self.assertEqual(MINE, rv.mark[pitch])

    def test_c_says_yes_to_it(self):
        rv, pitch = self.rv()
        self.assertIn('confirmed', rv.confirm(pitch))
        self.assertIn('is yours.', rv.confirm(pitch))

    def test_capital_c_takes_it_too(self):
        # `C` over the needs alone leaves the axes purple. That is what
        # "I saved it and it is still purple" was, and there is nothing
        # left for `C` to walk past.
        rv, pitch = self.rv()
        rv.confirm_all()
        self.assertEqual(MINE, rv.mark[pitch])
        self.assertEqual(0, rv.counts()[1])

    def test_x_clears_it_like_any_other_row(self):
        rv, pitch = self.rv()
        self.assertIn('is clear.', rv.clear(pitch))
        self.assertIsNone(rv.at[pitch])
        self.assertEqual(UNSET, rv.mark[pitch])
        self.assertIn('Pitch', rv.propose(pitch))

    def test_i_turns_it_round_and_says_so(self):
        rv, pitch = self.rv()
        self.assertIn('is inverted', rv.turn_round(pitch))
        self.assertTrue(pitch.invert)
        self.assertIn('is not inverted', rv.turn_round(pitch))
        self.assertFalse(pitch.invert)

    def test_i_on_a_button_row_says_it_is_not_an_axis(self):
        rv, _pitch = self.rv()
        self.assertIn('not an axis', rv.turn_round(by(rv, 'Boost')))

    def test_turning_it_round_makes_the_file_behind(self):
        rv, pitch = self.rv()
        rv.turn_round(pitch)
        self.assertTrue(rv.unsaved)

    def test_the_tally_counts_it(self):
        rv, _pitch = self.rv()
        mine, prop, _unset = rv.counts()
        self.assertEqual(2, mine + prop)

    def test_the_row_says_which_lever_not_which_control(self):
        # `stick · Main stick` was the whole answer for pitch, roll AND
        # rudder.
        rv, pitch = self.rv()
        self.assertIn('(y)', rv.where(pitch))
        rv.turn_round(pitch)
        self.assertIn('inverted', rv.where(pitch))

    def test_the_panel_has_the_sections_a_button_row_has(self):
        rv, pitch = self.rv()
        said = self.panel(rv, pitch)
        self.assertIn('WHERE', said)
        self.assertIn('WHAT IT ASKED FOR', said)
        self.assertIn('HOW IT WAS SET', said)
        self.assertIn('lever', said)

    def test_the_panel_draws_no_points_for_it(self):
        # Not because it is a lesser row: it was never compared with
        # anything, so a score would be the screen inventing a contest.
        rv, pitch = self.rv()
        said = self.panel(rv, pitch)
        self.assertNotIn('points', said)
        self.assertNotIn('WHICH CONTROL GOT IT', said)

    def test_the_panel_says_what_the_map_measured(self):
        rv, pitch = self.rv()
        said = self.panel(rv, pitch)
        self.assertNotIn('THE LEVER', said)
        if getattr(rv.lever(rv.at[pitch]), 'rest', ''):
            self.assertIn('HOW IT MOVES', said)

    def test_the_panel_lists_the_device_s_other_levers(self):
        rv, pitch = self.rv()
        dev = rv.layout.devices['stick']
        if len(list(dev.axes())) <= 1:
            self.skipTest('the fake stick has one axis')
        self.assertIn('EVERY LEVER', self.panel(rv, pitch))

    def test_a_replan_keeps_what_you_said_about_it(self):
        # It is the same object through a replan, the way every other
        # need is, so there is nothing to carry across by hand.
        rv, pitch = self.rv()
        rv.confirm(pitch)
        rv.turn_round(pitch)
        rv.relay(corneeds.Layout(rv.layout.devices,
                                 *allocate(list(rv.needs),
                                           rv.layout.devices)))
        self.assertEqual(MINE, rv.mark[pitch])
        self.assertTrue(pitch.invert)

    def test_an_axis_this_desk_cannot_answer_is_unplaced(self):
        devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB)])}
        nope = corneeds.Need('Pedals', 'pedal', [[Bind('P')]],
                             takes=corneeds.AXIS, device='stick')
        rv = made([nope], devs=devs)
        self.assertIsNone(rv.at[nope])
        self.assertIn('NOWHERE', '\n'.join(
            t for _tone, t in review._side(rv, self.row_of(rv, nope), 40)))

    def test_the_keys_are_the_ones_in_the_sill_and_the_help(self):
        self.assertIn('i invert', review.HINTS)
        self.assertIn('  i ', '\n'.join(t for _tone, t in review.KEYS))


class _Answers:
    """A `tui` that answers `choose` from a list, for the walks.

    The form and its sub-walks are `choose` boxes and nothing else, so a
    test drives them by saying which row each box comes back with.
    """

    def __init__(self, picks):
        self.picks = list(picks)
        self.asked = []

    def choose(self, title, lines, **kw):
        self.asked.append((title, [t for _tone, t in lines]))
        return self.picks.pop(0) if self.picks else None


class _Fake:
    """An axis object with just enough on it to be drawn."""
    index = 0
    label = 'Main stick'


class LayingItOutToAnOverlay(unittest.TestCase):
    """`o` puts a cockpit template on, takes it off, and plans again.

    A flag at startup and nothing else means trying a template means
    quitting, and the screen says nothing about whether one is on. Two
    things then look identical on a row: "the planner had no wishes" and
    "the planner ignored mine".
    """

    def setUp(self):
        self.devs = {'stick': fake.device('stick', [
            fake.button('Thumb', 0, reach=fake.THUMB),
            fake.button('Index', 1, reach=fake.INDEX),
        ], hand='right')}
        self.needs = [Need('Guns', 'button', [[Bind('GUNS')]], suits='fire',
                           urgency=corneeds.IN_A_TURN)]

    def rv(self, rebuild=True):
        def build():
            return corneeds.Layout(
                self.devs, *allocate(self.needs, self.devs))

        return made(self.needs, devs=self.devs, game='x4',
                    rebuild=build if rebuild else None)

    def tearDown(self):
        corneeds.OVERLAY = None
        corneeds.forget_wishes(self.needs)

    def test_it_says_there_is_none_rather_than_staying_quiet(self):
        self.assertIn('no overlay', review._tally(self.rv()))

    def test_laying_one_on_names_it_and_counts_what_got_through(self):
        rv = self.rv()
        said = rv.lay_over('f-18')
        self.assertIn('F/A-18C', said)
        self.assertIn('place wishes kept', said)
        self.assertIn('F/A-18C', review._tally(rv))

    def test_taking_it_off_plans_without_wishes(self):
        rv = self.rv()
        rv.lay_over('f-18')
        said = rv.lay_over(None)
        self.assertIn('The reach and the shape decide', said)
        self.assertIn('no overlay', review._tally(rv))
        self.assertIsNone(self.needs[0].finger, 'kept a wish nobody asked')

    def test_switching_is_the_same_as_starting_with_it(self):
        # The whole point of clearing the wishes first: f-18 after
        # spaceship has to count what f-18 alone counts.
        one, other = self.rv(), self.rv()
        alone = one.lay_over('f-18')
        other.lay_over('generic-hotas-spaceship')
        after = other.lay_over('f-18')
        self.assertEqual(alone, after)

    def test_what_you_decided_survives_the_relay(self):
        # The Need objects are the same objects, which is what makes this
        # safe to put on a keystroke.
        rv = self.rv()
        need = rv.needs[0]
        rv.assign(need, 'stick', self.at('Index'))
        rv.refile(need, 'Combat')
        rv.lay_over('f-18')
        self.assertEqual('Combat', need.category)
        self.assertEqual('fire', need.suits)
        self.assertEqual(corneeds.CHOSE, (need.assignment or {})['how'])
        self.assertEqual('Index', at(rv, need).ctrl.label)

    def test_a_game_that_cannot_lay_itself_out_again_says_so(self):
        said = self.rv(rebuild=False).lay_over('f-18')
        self.assertIn('cannot make a layout again', said)

    def test_an_overlay_nobody_wrote_says_which_there_are(self):
        said = self.rv().lay_over('no-such-thing')
        self.assertIn('by-hand', said)

    def test_the_map_screen_names_the_desk_and_the_overlay(self):
        rv = self.rv()
        rv.lay_over('f-18')
        got = '\n'.join(t for _tone, t in rv.map_lines())
        self.assertIn('LAID OUT FOR', got)
        self.assertIn('a desk in a test', got)
        self.assertIn('F/A-18C', got)
        self.assertIn('wishes kept', got)

    def test_the_key_is_in_the_sill_and_the_help(self):
        self.assertIn('o overlay', review.HINTS)
        self.assertIn('  o ', '\n'.join(t for _tone, t in review.KEYS))

    def at(self, label):
        return next(c for c in self.devs['stick'].groups()
                    if c.label == label)


class WhatAFunctionIsFor(unittest.TestCase):
    """The job is the one word an overlay takes hold of.

    As free text, invisible on screen, it is absent from 65 of the 147
    functions: a template has nothing to match for nearly half the list,
    and nothing says so.

    It is on the panel, and `J` sets it from the closed table. A function
    filed under the wrong job misses every wish in every template, and
    that looks like a template that did not apply.
    """

    def rv(self):
        return made([Need('Boost', 'button', [[Bind('BOOST')]],
                          suits='flight')],
                    save=lambda needs, axes=(): 'wrote 1')

    def side(self, rv):
        row = next(r for r in rv.rows() if r.kind == 'need')
        return '\n'.join(t for _tone, t in review._side(rv, row, 40))

    def test_the_panel_says_it(self):
        self.assertIn('job', self.side(self.rv()))
        self.assertIn('flight', self.side(self.rv()))

    def test_setting_it_changes_the_word(self):
        rv = self.rv()
        need = rv.needs[0]
        said = rv.refile_job(need, 'systems')
        self.assertEqual('systems', need.suits)
        self.assertIn('systems', said)

    def test_setting_it_makes_the_file_behind(self):
        rv = self.rv()
        rv.refile_job(rv.needs[0], 'systems')
        self.assertTrue(rv.unsaved)

    def test_a_word_outside_the_table_is_refused(self):
        rv = self.rv()
        need = rv.needs[0]
        said = rv.refile_job(need, 'reflex')
        self.assertEqual('flight', need.suits, 'took a word nobody wrote')
        self.assertIn('not a job', said)

    def test_the_key_is_in_the_sill_and_the_help(self):
        # `J`: `j` is a step down the list, and the step is first in the
        # chain, so the menu on `j` could not be opened at all.
        self.assertIn('J what it is', review.HINTS)
        self.assertIn('  J ', '\n'.join(t for _tone, t in review.KEYS))


class WhatAFunctionIs(unittest.TestCase):
    """The form behind `J`: everything the scorer reads about a function.

    One key per field runs out of keys. `J` asks the job and `i` turns an
    axis round, and nothing asks the band, the shape, the device or the
    hand. The game whose needs were worked out from its own command names
    then has no way to correct them.
    """

    def rv(self, need=None, catalogue=()):
        return made([need or Need('Boost', 'button', [[Bind('BOOST')]],
                                  suits='flight')],
                    catalogue=catalogue,
                    save=lambda needs, axes=(): 'wrote 1')

    def axis(self):
        return Need('Pitch', 'stick', [[Bind('PITCH')]], suits='flight',
                    takes=corneeds.AXIS, rests='centred', on=('y',))

    def test_every_field_it_offers_is_one_the_scorer_reads(self):
        # A row that sets something nothing scores is a question that
        # wastes your time and reads as if it mattered.
        need = self.axis()
        for field, label, kind, _when in review.DESCRIBED:
            with self.subTest(field=field):
                self.assertTrue(hasattr(need, field), field)
                self.assertTrue(label and kind)

    def test_every_word_it_offers_is_one_the_tables_define(self):
        # The point of the closed lists: a form cannot ask for a job, a
        # shape, a band, a device, a finger or a rest that nothing
        # scores, because it reads the same tables the scorer reads.
        dm = devmap.load()
        known = {
            'job': set(corneeds.JOBS),
            'band': set(range(len(corneeds.URGENCY_NAME))),
            'shape': set(corneeds.RULES['shapes']),
            'flag': {True, False},
            'device': set(dm.ROLES_ON_A_DESK),
            'finger': set(dm.FINGERS) - {dm.HAND},
            'rests': set(corneeds.RESTS),
        }
        need = self.axis()
        for _field, _label, kind, _when in review.DESCRIBED:
            if kind == 'on':
                # Its own list, and its own screen: the words a control
                # answers with, which is why `_ways` takes the control.
                got = set(review._ways(need, None))
                self.assertTrue(got <= {'x', 'y', 'z'}, got)
                continue
            with self.subTest(kind=kind):
                got = {v for v, _said in review._choices(need, kind)}
                self.assertTrue(got)
                self.assertTrue(got <= known[kind], got - known[kind])

    def test_an_axis_is_asked_what_it_rests_at_and_a_button_is_not(self):
        # `rests` is the one field that is about an axis and nothing
        # else, and a button asked where it rests is a question with no
        # answer.
        for need, want in ((self.axis(), True),
                           (Need('Gear', 'button', [[Bind('GEAR')]]), False)):
            with self.subTest(takes=need.takes):
                rows = [f for f, _l, _k, when in review.DESCRIBED
                        if when == 'always' or need.takes == corneeds.AXIS]
                self.assertEqual(want, 'rests' in rows)

    def test_saying_one_thing_marks_the_file_behind(self):
        rv = self.rv()
        need = rv.needs[0]
        rv.say(need, 'shape', 'hat2')
        self.assertEqual('hat2', need.shape)
        self.assertTrue(rv.unsaved)
        self.assertEqual('a shape changed', rv.since)

    def test_a_flag_takes_no_article(self):
        rv = self.rv()
        rv.say(rv.needs[0], 'held', True)
        self.assertIs(True, rv.needs[0].held)
        self.assertEqual('held changed', rv.since)

    def test_saying_what_it_already_says_changes_nothing(self):
        # Picking the value it is already on said `unsaved` for it, and
        # then the save box named a change nobody made.
        rv = self.rv()
        rv.say(rv.needs[0], 'shape', 'button')
        self.assertFalse(rv.unsaved)

    def test_the_job_goes_through_the_one_check_there_is(self):
        # `refile_job` holds the word list. Two ways in would be two
        # chances for a word nobody wrote.
        rv = self.rv()
        rv.say(rv.needs[0], 'suits', 'reflex')
        self.assertEqual('flight', rv.needs[0].suits)

    def test_which_way_a_family_points_is_asked_per_member(self):
        # `on` is three questions wearing one name. For a family it is
        # one answer per member, in the order the bindings are in,
        # because that order IS which button gets which.
        need = Need('Select', 'hat4',
                    [[Bind('AMRAAM')], [Bind('GUN')], [Bind('AIM9')],
                     [Bind('SPARROW')]], suits='fire',
                    on=('left', 'down', 'down', 'up'))
        rv = self.rv(need, catalogue=[
            Action('AMRAAM', 'Select AMRAAM'), Action('GUN', 'Select Gun'),
            Action('AIM9', 'Select Sidewinder'),
            Action('SPARROW', 'Select Sparrow')])
        ways = review._ways(need, None)
        tui = _Answers([2, ways.index('right')])
        said = review._pick_on(tui, rv, need)
        self.assertTrue(said)
        self.assertEqual(('left', 'down', 'right', 'up'), need.on)
        # Named out of the game's own vocabulary, not numbered: the four
        # rows of the first box are the four commands of the switch, and
        # `Select Sidewinder` is the one this test moved.
        first = tui.asked[0][1]
        self.assertTrue(any('Select Sidewinder' in t for t in first), first)
        self.assertFalse(any('AIM9' in t for t in first), first)

    def test_and_an_axis_is_asked_which_part_of_the_control_it_is(self):
        need = self.axis()
        rv = self.rv(need)
        said = review._pick_on(_Answers([0]), rv, need)
        self.assertTrue(said)
        self.assertEqual(('x',), need.on)

    def test_the_words_are_the_maps_own(self):
        # A hat takes the direction words `[directions]` accepts; an
        # axis takes which part of the control it is.
        hat = Need('Trim', 'hat4', [[Bind('U')], [Bind('D')]], suits='trim')
        self.assertTrue(set(review._ways(hat, None))
                        >= set(corneeds.RULES['directions']))
        self.assertEqual(('x', 'y', 'z'), review._ways(self.axis(), None))

    def test_a_lone_button_is_not_asked_which_way_it_points(self):
        # One press has no direction to choose, and a row offering one
        # is a question with no answer.
        lone = Need('Gear', 'button', [[Bind('GEAR')]])
        self.assertFalse(review._applies('moves', lone))
        for need in (self.axis(),
                     Need('Trim', 'hat2', [[Bind('U')], [Bind('D')]])):
            with self.subTest(what=need.what):
                self.assertTrue(review._applies('moves', need))

    def test_a_field_can_be_taken_back_to_nothing(self):
        # `device` and `finger` are the cockpit, and a module that does
        # not keep a thing under a finger has to be able to say so.
        rv = self.rv()
        rv.say(rv.needs[0], 'finger', 'thumb')
        rv.say(rv.needs[0], 'finger', None)
        self.assertIsNone(rv.needs[0].finger)


class SavingIsAKeystroke(unittest.TestCase):
    """Nothing reaches disk until `s`, the way the capture wizard works.

    A write on every decision is eight call sites and a whole-file
    rewrite each. The argument for it is that a save key you can forget
    is how an evening of choices comes back purple.

    The answer is that `s` means save in the other half of the pair, used
    in the same sitting, and one key meaning two things is worse than the
    keystroke it saves. So the frame says `unsaved`, and the save is
    offered on the way out.
    """

    def setUp(self):
        self.saved = []
        self.devs = {'stick': fake.device('stick', [
            fake.button('Thumb A', 0, reach=fake.THUMB),
            fake.button('Thumb B', 1, reach=fake.THUMB)])}
        self.needs = [Need('Boost', 'button', [[Bind('BOOST')]])]

    def rv(self, save=True):
        return made(self.needs, devs=self.devs,
                    save=((lambda needs, axes=(): self.saved.append(list(needs))
                           or 'wrote 1') if save else None))

    def test_a_fresh_screen_has_nothing_to_save(self):
        self.assertFalse(self.rv().unsaved)

    def test_a_decision_makes_it_unsaved(self):
        rv = self.rv()
        rv.confirm_all()
        self.assertTrue(rv.unsaved)

    def test_saving_clears_it_and_says_what_was_written(self):
        rv = self.rv()
        rv.confirm_all()
        said, still = rv.keep()
        self.assertEqual('wrote 1', said)
        self.assertFalse(still)
        self.assertFalse(rv.unsaved)

    def test_the_frame_says_unsaved_while_it_is(self):
        # On the tally, not in the status line: a status line says what
        # just happened and goes on the next keypress, and this is a state
        # of the file.
        rv = self.rv()
        rv.confirm_all()
        self.assertIn('unsaved', review._tally(rv))

    def test_the_frame_stops_saying_it(self):
        rv = self.rv()
        rv.confirm_all()
        rv.keep()
        self.assertNotIn('unsaved', review._tally(rv))

    def test_the_box_names_what_the_files_do_not_have(self):
        # The counts say how much is about to be written. Somebody who
        # sees this box on the way out after pressing `s` is asking what
        # changed since, and twelve keys can have changed it. One of those
        # keys is a button read off the stick while the box asking for it
        # was on screen.
        rv = self.rv()
        rv.confirm_all()
        said = '\n'.join(t for _tone, t in review._save_plan(rv, 44))
        self.assertIn('SINCE THE LAST SAVE', said)
        self.assertIn('confirmed in bulk', said)

    def test_a_fresh_screen_has_nothing_to_name(self):
        said = '\n'.join(t for _tone, t in review._save_plan(self.rv(), 44))
        self.assertNotIn('SINCE', said)

    def test_saving_forgets_it(self):
        rv = self.rv()
        rv.confirm_all()
        rv.keep()
        self.assertEqual('', rv.since)

    def test_every_key_that_marks_the_screen_says_which_it_was(self):
        # A phrase per call site, so the box can never come up with the
        # mark set and nothing to show for it.
        with open(review.__file__) as f:
            src = f.read()
        self.assertNotIn('self.touched()', src)

    def test_a_screen_with_nowhere_to_write_says_so_rather_than_raising(self):
        # DCS derives its needs. A screen that raised would take the whole
        # review down over a thing it cannot help.
        rv = self.rv(save=False)
        rv.confirm_all()
        said, still = rv.keep()
        self.assertIn('makes its own list', said)
        self.assertTrue(still)

    def test_a_save_that_fails_leaves_it_unsaved(self):
        # Otherwise the frame says the files have it and they do not.
        def refuse(_needs, _axes=()):
            raise OSError('read-only file system')

        rv = made(self.needs, devs=self.devs, save=refuse)
        rv.confirm_all()
        said, still = rv.keep()
        self.assertIn('read-only', said)
        self.assertTrue(still)
        self.assertTrue(rv.unsaved)


class TheRulesScreen(unittest.TestCase):
    """How a control is chosen, drawn from the tables that choose it.

    The point is not that it explains the allocator. A hand-written
    paragraph does that, until somebody changes a number.

    The point is that it cannot go stale. Every line it draws is read out
    of the table the allocator reads, so tuning a weight rewrites the
    screen.

    The pass order is NOT here. That is control flow, and deriving it
    needs a parser. It is one sentence, written out.
    """

    def said(self, rv=None):
        return '\n'.join(t for _tone, t in (rv or made()).rules_lines(60))

    def test_it_names_every_band(self):
        for band in corneeds.URGENCY_NAME:
            self.assertIn(band, self.said())

    def test_a_band_shows_the_reach_it_may_take(self):
        # The number, not a word for it: `in a turn` may reach to 1 and
        # everything else to 3, and that is the whole floor-and-ceiling
        # rule in one row.
        said = self.said()
        for band, limit in zip(corneeds.URGENCY_NAME,
                               corneeds.MAX_REACH.values()):
            # The table row, not any line that mentions the band: the
            # paragraph above the table names two of them.
            row = [ln for ln in said.splitlines()
                   if ln.strip().startswith(band)]
            self.assertTrue(row, band)
            self.assertIn(str(limit), row[0])

    def test_it_shows_what_each_thing_is_worth(self):
        # The weights were the one part of the scoring the screen could
        # not show, because they were literals inside `score()`.
        said = self.said()
        for term in corneeds.TERMS:
            self.assertIn(str(term['weight']), said, term['name'])

    def test_it_leaves_the_working_out_in_the_file(self):
        # Every `note` drawn here puts the reason a limit is what it is
        # on the screen beside the limit. Half a page of why a weight was
        # retuned, under some rows and not others, reads as noise that
        # turns up at random. Whoever is about to change a number is
        # looking at scoring.toml, and the notes are there.
        said = self.said()
        noted = [x for x in list(corneeds.RULES['band'])
                 + list(corneeds.TERMS) + list(corneeds.FACTS)
                 if 'note' in x]
        self.assertTrue(noted, 'nothing carries a note')
        for one in noted:
            self.assertNotIn(one['note'].split('.')[0][:40], said)

    def test_it_says_who_chooses_between_two_equal_answers(self):
        # Most of a layout is ties, and which answer you get out of them
        # is `--solver`: greedy and the model differ on 25 of X4's 32
        # bindings. A screen called "why a control is chosen" that never
        # mentions this is explaining half the decision.
        said = self.said()
        for name, what, _why in csolvers.choices():
            self.assertIn(name, said)
            # A prefix: the screen wraps, so a whole sentence is not in
            # it as one string.
            self.assertIn(what[:28], said)

    def test_it_names_every_step_of_which_binding_goes_first(self):
        # This was a paragraph, and a paragraph does not move when the
        # sort key does: it still said a pin went first long after what
        # you choose by hand started outranking one, and stopped at the
        # factory count after a step was added under it.
        said = self.said()
        for what, why in corneeds.ORDERED_BY:
            # The table holds a fragment and the screen starts a sentence
            # with it, so the capital is the screen's.
            self.assertIn(what[0].upper() + what[1:], said)
            # A prefix: the screen wraps at the width it is given.
            self.assertIn(why.split()[0] + ' ' + why.split()[1], said)

    def test_it_names_every_refusal(self):
        # These four were transcribed into the screen as literals, which
        # made this the one place that could disagree with the allocator.
        # It then did: a fifth refusal arrived and the screen kept saying
        # there were four.
        said = self.said()
        # The table holds a fragment and the screen makes it a sentence,
        # so the comparison is against the sentence the screen makes.
        for gate in corneeds.GATES:
            self.assertIn(review._sentence(gate['says']), said)
        for fact in corneeds.FACTS:
            if fact.get('refuses'):
                self.assertIn(review._sentence(fact['says']), said,
                              fact['reads'])
        # Asserting the four strings are present passes whether they were
        # read or typed, because typed they were copied correctly. So say
        # something else in the table and see whether the screen changes
        # its mind: transcribed, it cannot.
        mine = corneeds.merge_rules(corneeds.RULES, {})
        mine['gate'] = [dict(g, says='the dog ate it')
                        for g in mine['gate']]
        self.assertIn('The dog ate it.', self.said(made(rules=mine)))
        for gate in corneeds.GATES:
            self.assertNotIn(gate['says'], self.said(made(rules=mine)))

    def test_it_shows_what_the_desk_measured(self):
        # 205 answers you gave the capture wizard decide bindings, so the
        # screen that explains the decision names them. It names what
        # turns each one on as well: a fact the binding does not ask for
        # counts for nothing, and a screen that left that out would
        # describe a harsher allocator than the one that ran.
        said = self.said()
        for fact in corneeds.FACTS:
            self.assertIn(fact['asked'], said, fact['reads'])
            self.assertIn(fact.get('general', fact['says']), said)
            for key in ('yes', 'no', 'scale'):
                if key in fact:
                    self.assertIn(str(fact[key]), said, fact['reads'])

    def test_a_fact_added_to_the_file_appears_without_touching_this(self):
        # The same property the scoring has: a sixth question the capture
        # wizard starts asking is a block in a file. A screen somebody has
        # to remember to update is a screen that will be wrong.
        mine = corneeds.merge_rules(corneeds.RULES, {})
        mine['fact'] = list(mine['fact']) + [
            {'reads': 'cumulative', 'asked': 'staged', 'yes': 7, 'no': -3,
             'says': 'it stages', 'not': 'it does not stage'}]
        said = self.said(made(rules=mine))
        self.assertIn('staged', said)
        self.assertIn('it stages', said)

    def test_it_is_derived_and_not_transcribed(self):
        # The test that earns the screen. Move a limit and the screen
        # moves with it. A hand-written one does not. DCS needs this,
        # because it tightens a band: the core's numbers there explain
        # somebody else's allocator.
        mine = corneeds.merge_rules(
            corneeds.RULES, {'band': [{'name': 'in the air',
                                       'takes': [0, 1]}]})
        rv = made(rules=mine)
        row = [ln for ln in self.said(rv).splitlines()
               if 'in the air' in ln][0]
        self.assertIn('0 to 1', row)

    def test_it_lists_every_pass(self):
        # Derived from CAME_BY it showed three of four: that table holds
        # what is worth SAYING about a placement, so it leaves out the
        # ordinary pass and takes in two things that are not passes.
        said = self.said()
        for how, _what in corneeds.PASSES:
            self.assertIn(how, said)

    def test_it_lists_what_stands_in_for_what(self):
        for shape, subs in corneeds.FITS.items():
            row = [ln for ln in self.said().splitlines()
                   if ln.strip().startswith(shape + ' ')]
            self.assertTrue(row, shape)
            for sub in subs[1:]:
                self.assertIn(sub, row[0])

    def test_it_says_what_every_tier_means(self):
        # The number comes off the map, measured finger by finger. A
        # screen that showed it bare would be showing an index into a
        # table the reader has not got.
        said = self.said()
        for tier, means in corneeds.REACH_MEANS.items():
            with self.subTest(tier=tier):
                self.assertIn(means, said)
                self.assertIn(str(tier), said)


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
    """A narrowed list says it is narrowed.

    Said once on the keystroke, and cleared by the next movement, a
    screen showing three of thirty-one rows looks like a game with three
    needs.
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
    """Side by side where there is room, and stacked where there is not.

    A detail panel of five lines at the bottom cannot hold X4's `View`,
    which puts six bindings under one hat. The row that needs the space
    is the one that cannot have it. A column has the height of the
    screen.

    The right column is split again, in height: the detail is about the
    row the cursor is on and the free list is about the desk. Neither
    answers the other's question, so neither can be the other's tail.
    """

    def test_a_wide_terminal_gets_two_panels(self):
        listed, detail, _free = review._layout(100, 30)
        self.assertIsNotNone(detail)
        self.assertEqual(listed[1], 0, 'the list starts at the left edge')
        self.assertGreater(detail[1], listed[1] + 20)

    def test_they_do_not_overlap(self):
        listed, detail, _free = review._layout(100, 30)
        self.assertLessEqual(listed[1] + listed[3], detail[1])

    def test_together_they_fill_the_width(self):
        for w in (90, 100, 120, 200):
            listed, detail, _free = review._layout(w, 30)
            self.assertLessEqual(detail[1] + detail[3], w)
            self.assertGreaterEqual(detail[1] + detail[3], w - 1)

    def test_a_narrow_terminal_stacks_them(self):
        # 80 columns leaves the list about 50 wide, and
        # `throttle · Middle finger hat` does not fit in 50.
        listed, detail, _free = review._layout(80, 30)
        self.assertEqual(listed[3], detail[3], 'both full width')
        self.assertGreater(detail[0], listed[0] + listed[2] - 1)

    def test_a_short_terminal_keeps_the_list_usable(self):
        # Stacked on a small screen, the detail must not eat the list.
        listed, _detail, _free = review._layout(80, 14)
        self.assertGreaterEqual(listed[2], 6)

    # ---- the free panel under the detail ----

    def test_a_tall_column_gets_a_free_panel(self):
        _listed, detail, free = review._layout(100, 30)
        self.assertIsNotNone(free)
        assert free is not None
        self.assertEqual(detail[1], free[1], 'the same column')
        self.assertEqual(detail[3], free[3], 'the same width')

    def test_the_two_do_not_overlap(self):
        _listed, detail, free = review._layout(100, 30)
        assert free is not None
        self.assertEqual(detail[0] + detail[2], free[0])

    def test_together_they_fill_the_column(self):
        for h in (24, 30, 40, 60):
            with self.subTest(height=h):
                _listed, detail, free = review._layout(100, h)
                assert free is not None
                self.assertEqual(h, detail[2] + free[2])

    def test_a_short_column_drops_it(self):
        # The detail is unreadable below about ten rows, and the free
        # list is the half you can reach another way.
        _listed, detail, free = review._layout(100, 20)
        self.assertIsNone(free)
        self.assertEqual(20, detail[2], 'the detail takes the column')

    def test_a_stacked_screen_has_no_room_for_it(self):
        _listed, _detail, free = review._layout(80, 30)
        self.assertIsNone(free)

    def test_the_detail_keeps_the_larger_half(self):
        # It is about the row you are on, which is what the keys act on.
        _listed, detail, free = review._layout(100, 30)
        assert free is not None
        self.assertGreater(detail[2], free[2])


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
        devs = stick(fake.unwired('Phantom', [0]),
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
        # WHERE, the profile directory and the path itself are a section,
        # the thing it names, and the detail under it. All three in one
        # blue is a listing you read from the top to know where you
        # are.
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
        # Otherwise the two drift, and the short list becomes the only
        # place some key is named.
        #
        # A single character is matched as it is written: `c` and `C` are
        # two actions, so the case IS the key. A word is matched either
        # way, because there the case is spelling: the help names a key
        # like `SPACE` or `TAB` in capitals and the sill writes `tab
        # panel` beside `c accept`.
        listed = self.said()
        for hint in review.HINTS:
            key = hint.split()[0]
            said = listed if len(key) == 1 else listed.lower()
            want = key if len(key) == 1 else key.lower()
            self.assertIn(want, said, f'{hint!r} is nowhere in `?`')

    def test_moving_is_documented_at_all(self):
        # What it does, not how it is spelled: a version of this that
        # pinned 'g / G' broke when the help went man-terse, which told
        # nobody anything about whether moving was documented.
        #
        # `panels`, because the arrows move in whichever one TAB is on
        # and the help has to say that much. `first` and `last` are the
        # two ends, which is the other half of moving.
        keys = self.said().lower()
        for what in ('panels', 'scroll', 'first', 'last'):
            self.assertIn(what, keys)

    def test_every_branch_of_the_loop_is_reachable_from_the_footer(self):
        # Per branch, and not per letter. `m` and `M` are one action
        # under two keys, and `c` and `C` are two actions. The action is
        # what has to be findable, so each branch spells out one of its
        # keys.
        import inspect
        src = inspect.getsource(review._loop)
        listed = self.said()
        spelled = {'up': '↑', 'down': '↓', 'enter': '↵', 'esc': 'q',
                   ' ': 'SPACE', 'tab': 'TAB', 'shift-tab': 'Shift-TAB'}
        branches = [frozenset(re.findall(r"'([^']+)'", m.group(1)))
                    for m in re.finditer(r"k (?:==|in) \(?([^:)]+)\)?:", src)]
        self.assertGreater(len(branches), 6, 'the parse found nothing')
        def spelled_out(token):
            # At a word boundary: a bare `in` check finds the `m` of
            # "confirm" and calls the map key documented.
            return re.search(rf'(^|[ ·/]){re.escape(token)}([ /]|$)', listed)

        for keys in branches:
            if not keys:
                # A branch on no literal key at all: the game's own
                # offers, whose words go into the sill beside these at
                # draw time because only the adapter knows them.
                continue
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


class AFieldNobodyAnsweredSaysSo(unittest.TestCase):
    """`WHAT IT ASKED FOR` draws an empty field as `MISSING`.

    Four of its fields are ones the scorer reads and a row can be
    without. Left out of the panel, the row says nothing about them, and
    a reader cannot tell a field nobody answered from a field this panel
    does not show.

    Measured on X4's 45 rows: 32 carry no `device` and 27 no `on`. Those
    32 are placed on reach and shape alone, and nothing else on the
    screen says so.
    """

    def side(self, need):
        rv = made([need])
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need is need)
        return '\n'.join(t for _tone, t in review._side(rv, row, 46))

    def asked(self, need):
        """Just the `WHAT IT ASKED FOR` section."""
        said = self.side(need).split('WHAT IT ASKED FOR')[1]
        return said.split('\n\n')[0]

    def test_a_row_with_no_job_says_missing(self):
        said = self.asked(Need('Gear', 'button', [[Bind('GEAR')]]))
        self.assertIn('job', said)
        self.assertIn(review.MISSING, said)

    def test_a_row_with_no_device_says_missing(self):
        # 32 of X4's 45. A row with no device is scored on reach and
        # shape alone, which is a different layout from one that asked.
        said = self.asked(Need('Gear', 'button', [[Bind('GEAR')]],
                               suits='systems'))
        self.assertRegex(said, r'device\s+' + review.MISSING)

    def test_a_family_with_no_directions_says_missing(self):
        # A hat without `on` lands in press order, and not where the
        # switch moves.
        said = self.asked(Need('Trim', 'hat4', [[Bind('U')], [Bind('R')],
                                                [Bind('D')], [Bind('L')]],
                               suits='trim'))
        self.assertRegex(said, r'on\s+' + review.MISSING)

    def test_one_binding_is_not_asked_for_directions(self):
        # A lone press has no direction to choose, so there is nothing
        # missing from it.
        said = self.asked(Need('Gear', 'button', [[Bind('GEAR')]],
                               suits='systems'))
        self.assertNotRegex(said, r'\bon\s')

    def test_an_answered_field_says_the_answer(self):
        said = self.asked(Need('Gear', 'button', [[Bind('GEAR')]],
                               suits='systems', device='stick'))
        self.assertNotIn(review.MISSING, said)
        self.assertIn('systems', said)
        self.assertIn('stick', said)


class WhatHappensToTheRow(unittest.TestCase):
    """The last section of the panel: the state, and what moves it.

    Every other section answers a question about the past. This one
    answers the two a reader has next: where does this row stand, and
    what changes it.

    The four states differ in what moves them, which is why each one
    gets its own line.
    """

    def last(self, rv, what):
        """The `WHAT HAPPENS TO IT` section of one row's panel."""
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need.what == what)
        said = '\n'.join(t for _tone, t in review._side(rv, row, 60))
        self.assertIn('WHAT HAPPENS TO IT', said)
        return said.split('WHAT HAPPENS TO IT')[1]

    def test_a_proposal_says_the_next_plan_can_move_it(self):
        rv = made()
        said = self.last(rv, 'Gear')
        self.assertIn('The program put this here', said)
        self.assertIn('next plan', said)

    def test_your_own_choice_says_nothing_moves_it(self):
        rv = made()
        need = by(rv, 'Gear')
        rv.assign(need, 'stick', DEVS()['stick'].groups()[1])
        said = self.last(rv, 'Gear')
        self.assertIn('You put this here', said)
        self.assertIn('Nothing moves it', said)

    def test_a_proposal_you_accepted_says_what_can_move_it(self):
        # Two decisions wear the mark `+`, and they differ in exactly
        # what this section answers. `chose` takes the control before
        # anything is scored, so nothing moves it. `accepted` changes no
        # allocation: the row still competes, and a new desk or a new
        # list moves it and sends the mark back to `?`.
        #
        # One sentence for both says "nothing moves it" about a row a
        # replan can move, which is the opposite of true.
        rv = made()
        need = by(rv, 'Gear')
        rv.confirm(need)
        said = self.last(rv, 'Gear')
        self.assertIn('You accepted this control', said)
        self.assertNotIn('Nothing moves it', said)
        self.assertIn('move it back', said)
        # And it names the mark the row goes back to, so the sentence
        # points at a thing the legend explains.
        self.assertIn(MARK[PROPOSED], said)

    def test_the_two_strengths_do_not_read_the_same(self):
        chose, accepted = made(), made()
        chose.assign(by(chose, 'Gear'), 'stick',
                     DEVS()['stick'].groups()[1])
        accepted.confirm(by(accepted, 'Gear'))
        self.assertNotEqual(self.last(chose, 'Gear'),
                            self.last(accepted, 'Gear'))

    def test_a_row_you_emptied_says_no_pass_fills_it(self):
        # `x` writes `how: cleared`, and the allocator is told to leave
        # such a row alone. Said as "the program found no control", it
        # would be blaming the planner for your own decision.
        rv = made()
        rv.clear(by(rv, 'Gear'))
        said = self.last(rv, 'Gear')
        self.assertIn('You emptied this row', said)

    def test_a_row_with_nowhere_to_go_says_the_program_found_none(self):
        # An encoder, on a desk with no encoder on it. The shape gate
        # refuses every control, so this row is empty and nobody
        # emptied it.
        rv = made([Need('Range', 'encoder', [[Bind('UP')], [Bind('DN')]],
                        suits='sensor')])
        said = self.last(rv, 'Range')
        self.assertIn('found no control', said)

    def test_a_row_with_no_job_says_no_overlay_reaches_it(self):
        # The job is the one word an overlay matches on, so a row
        # without one is invisible to every template.
        rv = made([Need('Gear', 'button', [[Bind('GEAR')]])])
        self.assertIn('no job', self.last(rv, 'Gear'))

    def test_a_row_with_a_job_does_not_say_it(self):
        rv = made([Need('Gear', 'button', [[Bind('GEAR')]],
                        suits='systems')])
        self.assertNotIn('no job', self.last(rv, 'Gear'))

    def test_it_is_the_last_thing_on_the_panel(self):
        # The two questions a reader has next, so they are where the
        # reader stops.
        rv = made()
        row = next(r for r in rv.rows()
                   if r.kind == 'need' and r.need.what == 'Gear')
        said = [t for _tone, t in review._side(rv, row, 60) if t.strip()]
        head = next(i for i, t in enumerate(said)
                    if 'WHAT HAPPENS TO IT' in t)
        self.assertLessEqual(len(said) - head, 4)


class WhatTheProgramPlacedIsWrittenDown(unittest.TestCase):
    """The binds file answers what is on the desk, not what a hand
    touched.

    `dump_assignments` writes a row for every need that carries an
    assignment. A proposal carried none, so `X` then `P` then `s` wrote a
    file with no rows in it while the screen held 42 placed. That is the
    opposite of what that function's own first line promises.

    `SOLVED` is the word for a placement the program made.
    `read_assignments` drops such a row, so the next run scores from
    scratch, and the `yours` pass takes `CHOSE` alone. What the row buys
    is `stayed`, the term worth +20 that keeps a layout from reshuffling,
    and a screen that can say what moved.
    """

    def test_a_proposal_reaches_the_file(self):
        rv = made()
        rows = corneeds.dump_assignments(rv.needs)
        self.assertEqual(len(rv.placements()), len(rows))
        self.assertEqual({corneeds.SOLVED}, {r['how'] for r in rows})

    def test_it_names_the_control_it_sits_on(self):
        rv = made()
        # `at` for a row the planner placed, which `made()` guarantees.
        # None here is the fixture failing rather than a case to handle.
        at = rv.at[by(rv, 'Gear')]
        assert at is not None
        (row,) = [r for r in corneeds.dump_assignments(rv.needs)
                  if r['what'] == 'Gear']
        self.assertEqual(at.role, row['role'])
        self.assertEqual(at.ctrl.id, row['control'])

    def test_it_reads_back_as_no_claim(self):
        # Otherwise every run starts from wherever the last one stopped.
        rv = made()
        rows = corneeds.dump_assignments(rv.needs)
        fresh = corneeds.read_needs(corneeds.dump_needs(rv.needs))
        corneeds.read_assignments(rows, fresh)
        self.assertEqual([None] * len(fresh), [n.assignment for n in fresh])

    def test_a_decision_of_yours_is_not_overwritten(self):
        # `chose`, `accepted` and `cleared` are answers. This is a note
        # about a proposal, and a replan must not turn one into the other.
        rv = made()
        rv.assign(by(rv, 'Gear'), 'stick', DEVS()['stick'].groups()[1])
        rv.confirm(by(rv, 'Trim'))
        rv.clear(by(rv, 'Canopy'))
        was = {n.what: (n.assignment or {}).get('how') for n in rv.needs}
        rv.relay(Layout(DEVS(), *allocate(rv.needs, DEVS())))
        for what, how in was.items():
            with self.subTest(what=what):
                need = by(rv, what)
                self.assertEqual(how, (need.assignment or {}).get('how'))

    def test_a_cleared_row_writes_no_control(self):
        # `x` is the one decision of yours that names no control, so a
        # replan must not fill the gap it made with a `solver` row.
        rv = made()
        rv.clear(by(rv, 'Gear'))
        rv.relay(Layout(DEVS(), *allocate(rv.needs, DEVS())))
        said = by(rv, 'Gear').assignment or {}
        self.assertEqual(corneeds.CLEARED, said.get('how'))
        self.assertIsNone(said.get('control'))


class LayingItOutMarksTheScreen(unittest.TestCase):
    """`o` is a decision, so the frame says the files do not have it.

    Unmarked, the frame says nothing, `q` offers nothing, and the choice
    lasts until you quit. Measured on the Hornet: `o f-18` took the list
    from 33 accepted rows to 45, and the next open put it back to 33.
    """

    def rv(self):
        return made(rebuild=lambda: Layout(DEVS(),
                                           *allocate(plan(), DEVS())))

    def test_putting_one_on_says_unsaved(self):
        rv = self.rv()
        self.assertFalse(rv.unsaved)
        rv.lay_over('f-18')
        self.assertTrue(rv.unsaved)
        self.assertIn('f-18', rv.since)

    def test_taking_every_one_off_says_unsaved(self):
        # "No template" is a decision too, and the file holds it.
        rv = self.rv()
        rv.lay_over(None)
        self.assertTrue(rv.unsaved)
        self.assertIn('no template', rv.since)

    def test_a_name_nothing_answers_to_changes_nothing(self):
        rv = self.rv()
        said = rv.lay_over('no-such-overlay')
        self.assertIn('no-such-overlay', said)
        self.assertFalse(rv.unsaved)


class Stub:
    """One `js` node, with the events it is about to report.

    `core/capture.py`'s `Device` opens a file descriptor in its
    constructor, so a test cannot make one. This answers the two things
    `Sticks.touched` reads off it, and keeps `axis_vals` the way the real
    one does: updated as the batch is parsed, before the caller sees it.
    """

    def __init__(self, role, batches, rest=None):
        self.role = role
        self.batches = list(batches)
        self.axis_vals = dict(rest or {})

    def read_events(self):
        got = self.batches.pop(0) if self.batches else []
        for kind, number, value in got:
            if kind == 'axis':
                self.axis_vals[number] = value
        return got


class WhatIsUnderYourHand(unittest.TestCase):
    """`Sticks.touched`: which control was just pressed or moved.

    An axis is measured against where it was before a hand took hold,
    and not against the value it had one tick ago. A tick is 50 ms: a
    lever moved by hand travels a few hundred units in that time, and a
    threshold against the previous tick asks for a fifth of the range
    inside a twentieth of a second. Nothing a hand does clears that, so
    nothing moving ever showed.
    """

    def sticks(self, *devices):
        rv = made()
        s = review.Sticks(rv.layout)
        s.opened = True
        s.devices = list(devices)
        return s

    def test_a_press_is_reported(self):
        s = self.sticks(Stub('stick', [[('button', 7, 1)]]))
        self.assertEqual(('stick', 'button', 7), s.touched())

    def test_letting_go_is_not(self):
        # A release is not a thing you are showing the screen.
        s = self.sticks(Stub('stick', [[('button', 7, 0)]]))
        self.assertIsNone(s.touched())

    def test_a_quiet_tick_says_nothing(self):
        s = self.sticks(Stub('stick', [[]]))
        self.assertIsNone(s.touched())

    def test_a_lever_moved_by_hand_is_reported(self):
        # Four ticks of a few hundred units each, which is what a hand
        # does. Against the previous tick none of them clears the bar.
        dev = Stub('stick', [[('axis', 1, v)] for v in
                             (200, 900, 2000, 3600)], rest={1: 0})
        s = self.sticks(dev)
        said = [s.touched() for _ in range(4)]
        self.assertEqual([None, None, None, ('stick', 'axis', 1)], said)

    def test_jitter_at_rest_is_not_a_move(self):
        # A lever at rest wanders by a few hundred either way.
        dev = Stub('stick', [[('axis', 1, v)] for v in
                             (120, -90, 200, -150)], rest={1: 0})
        s = self.sticks(dev)
        self.assertEqual([None] * 4, [s.touched() for _ in range(4)])

    def test_a_lever_parked_at_one_end_is_not_a_move(self):
        # The driver reports where every axis is when the node opens. A
        # reader that took that for a movement would show a press
        # nobody made.
        dev = Stub('stick', [[('axis', 3, -32767)]], rest={3: -32767})
        self.assertIsNone(self.sticks(dev).touched())

    def test_it_keeps_reporting_while_the_lever_travels(self):
        dev = Stub('stick', [[('axis', 1, v)] for v in
                             (4000, 9000, 16000)], rest={1: 0})
        s = self.sticks(dev)
        self.assertEqual([('stick', 'axis', 1)] * 3,
                         [s.touched() for _ in range(3)])

    def test_a_lever_that_stopped_is_the_next_baseline(self):
        # Let go at 9000 and that is where it lives now, so the next
        # move is measured from there rather than from zero.
        dev = Stub('stick', [[('axis', 1, 9000)], [], [('axis', 1, 10000)]],
                   rest={1: 0})
        s = self.sticks(dev)
        self.assertEqual(('stick', 'axis', 1), s.touched())
        self.assertIsNone(s.touched())          # quiet, so it re-bases
        self.assertIsNone(s.touched())          # 1000 from 9000

    def test_the_newest_thing_in_a_batch_wins(self):
        # A caller that polls once a tick wants what is under the hand
        # now, not the oldest thing in the queue.
        s = self.sticks(Stub('stick', [[('button', 2, 1),
                                        ('button', 5, 1)]]))
        self.assertEqual(('stick', 'button', 5), s.touched())

    def test_two_devices_are_both_read(self):
        s = self.sticks(Stub('stick', [[]]),
                        Stub('throttle', [[('button', 9, 1)]]))
        self.assertEqual(('throttle', 'button', 9), s.touched())

    def test_nothing_plugged_in_answers_nothing(self):
        self.assertIsNone(self.sticks().touched())


class WhatTheCornerSays(unittest.TestCase):
    """`Review.pressed`: what was just touched, in words.

    A number is not an answer to "which one did I press": it is the same
    question again. This says which device, what the control is called,
    which part of it this is, and what is on it.
    """

    def said(self, rv, role, kind, index):
        return [t for _tone, t in rv.pressed(role, kind, index)]

    def test_a_button_names_its_control(self):
        rv = made()
        said = self.said(rv, 'stick', 'button', 5)
        self.assertIn('stick  js 5', said)
        self.assertIn('Pinky button', said)

    def test_a_hat_names_the_direction_too(self):
        # Four buttons wear one label, so the label alone does not say
        # which one is under your thumb.
        rv = made()
        said = self.said(rv, 'stick', 'button', 0)
        self.assertIn('Thumb hat', said)
        self.assertIn('up', said)

    def test_it_says_what_is_on_the_control(self):
        rv = made()
        need = by(rv, 'Gear')
        at = rv.at[need]
        assert at is not None
        said = self.said(rv, at.role, 'button', at.slots[0][0])
        self.assertIn('Gear', said)

    def test_a_spare_control_says_so(self):
        rv = made()
        rv.clear_all()
        said = self.said(rv, 'stick', 'button', 5)
        self.assertIn('Nothing is on it.', said)

    def test_a_number_the_map_does_not_name(self):
        # A button the firmware reports with nothing behind it. The map
        # is where that gets answered, and saying so beats a blank box.
        rv = made()
        said = self.said(rv, 'stick', 'button', 99)
        self.assertIn('The device map does not name it.', said)

    def test_a_device_the_layout_has_not_got(self):
        self.assertEqual([], made().pressed('pedals', 'button', 0))

    def test_several_needs_on_one_control_are_one_name_and_a_count(self):
        # The share pass hands a leftover need a spare button of a
        # control something else owns, so four names can belong on one
        # line. A list cut mid-word reads as a name nobody gave: X4's
        # main stick comes out as `INPUT_RANGE_STEERING_PRIMARY,
        # INPUT_RANG`.
        self.assertEqual('Gear +1', review._one_of(['Gear', 'Canopy']))
        self.assertEqual('Gear +2',
                         review._one_of(['Gear', 'Canopy', 'Trim']))

    def test_one_name_carries_no_count(self):
        self.assertEqual('Gear', review._one_of(['Gear']))
        self.assertEqual('', review._one_of([]))


class TabWalksThePanels(unittest.TestCase):
    """TAB chooses what the arrows move, and nothing else changes.

    Every other key goes on acting on the row under the cursor in the
    list, so `c` accepts that row whatever the arrows are pointed at.
    The cursor stays lit for the same reason.

    The free list is 20 controls on MSFS and the panel holds three. Read
    with no way to scroll, the rest is dropped in silence, which is the
    one thing a box may not do.
    """

    def driven(self, keys, h=40, w=120, needs=None):
        """`_loop` over a fake screen, and the state it left behind."""
        rv = made(needs, rebuild=lambda: Layout(DEVS(),
                                                *allocate(plan(), DEVS())))
        scr = Keyed(list(keys) + [ord('q')], h=h, w=w)
        seen = {}
        was = review._draw

        def watch(scr, rv, sel, state, theme, focus=review.LIST, **kw):
            seen.update(state)
            seen['sel'] = sel
            seen['focus'] = focus
            return was(scr, rv, sel, state, theme, focus, **kw)

        with unittest.mock.patch.object(
                review.ctui, 'setup',
                lambda s: ctui.Tui(s, ctui.Theme(False))), \
             unittest.mock.patch.object(review, '_draw', watch):
            review._loop(scr, rv, None, review.Sticks(rv.layout))
        return seen, scr.frames

    def test_the_list_has_it_to_start_with(self):
        seen, _frames = self.driven([])
        self.assertEqual(review.LIST, seen.get('focus', review.LIST))

    def test_tab_moves_it_on(self):
        seen, _frames = self.driven([9])
        self.assertEqual(review.DETAIL, seen['focus'])

    def test_it_comes_back_round(self):
        # Three panels on a wide screen, so three presses is where you
        # started.
        seen, _frames = self.driven([9, 9, 9])
        self.assertEqual(review.LIST, seen['focus'])

    def test_shift_tab_goes_back(self):
        import curses
        seen, _frames = self.driven([curses.KEY_BTAB])
        self.assertEqual(review.FREE, seen['focus'])

    def test_a_screen_with_no_free_panel_skips_it(self):
        # Stacked, so there is nowhere to put one. Two panels, and two
        # presses is where you started.
        seen, _frames = self.driven([9, 9], w=80)
        self.assertEqual(review.LIST, seen['focus'])

    # ---- what the arrows do ----

    def test_the_arrows_move_the_cursor_on_the_list(self):
        import curses
        seen, _frames = self.driven([curses.KEY_DOWN, curses.KEY_DOWN])
        self.assertGreater(seen['sel'], 0)
        self.assertEqual(0, seen.get(review.DETAIL, 0))

    def test_they_scroll_the_panel_they_are_pointed_at(self):
        import curses
        seen, _frames = self.driven([9, curses.KEY_DOWN, curses.KEY_DOWN])
        self.assertGreater(seen[review.DETAIL], 0)

    def test_the_cursor_does_not_move_while_they_scroll(self):
        # The keys act on the row under it, so it has to stay put.
        import curses
        a, _f = self.driven([])
        b, _f = self.driven([9, curses.KEY_DOWN, curses.KEY_DOWN])
        self.assertEqual(a['sel'], b['sel'])

    def test_a_key_that_is_not_an_arrow_acts_on_the_list(self):
        # `x` empties the row under the cursor, whatever TAB is on.
        #
        # Down first. The cursor opens on the first selectable row and
        # that is a heading, which carries no need, so `x` there has
        # nothing to empty. After TAB the arrows scroll a panel and
        # cannot reach a row at all.
        import curses
        rv = made(rebuild=lambda: Layout(DEVS(), *allocate(plan(), DEVS())))
        scr = Keyed([curses.KEY_DOWN, 9, ord('x'), ord('q')], h=40, w=120)
        with unittest.mock.patch.object(
                review.ctui, 'setup',
                lambda s: ctui.Tui(s, ctui.Theme(False))):
            review._loop(scr, rv, None, review.Sticks(rv.layout))
        self.assertEqual(1, sum(1 for n in rv.needs
                                if (n.assignment or {}).get('how')
                                == corneeds.CLEARED))

    def test_scrolling_up_from_the_top_stays_at_the_top(self):
        import curses
        seen, _frames = self.driven([9, curses.KEY_UP, curses.KEY_UP])
        self.assertEqual(0, seen[review.DETAIL])

    # ---- how the focus is drawn ----

    def test_the_focused_panel_is_heavy(self):
        _seen, frames = self.driven([])
        said = frames[-1]
        self.assertIn('┏', said, 'the list has the focus and is heavy')
        self.assertIn('╭', said, 'and the others are not')

    def test_only_one_panel_is_heavy(self):
        _seen, frames = self.driven([9])
        self.assertEqual(1, frames[-1].count('┏'))

    def test_the_focused_panel_says_the_arrows_scroll_it(self):
        _seen, frames = self.driven([9])
        self.assertIn(review.SCROLL, frames[-1])


class WhatTheVocabularyCallsTaken(unittest.TestCase):
    """Which actions the vocabulary screen marks as already on a row.

    That screen offers what is left. An action it calls free is one you
    can promote, and promoting a thing that has a row already makes two
    rows for one function.
    """

    def test_an_action_on_a_press_is_taken(self):
        # Measured on Elite: `UI_Select` sits on the press of a hat and
        # was the one action of 76 that a walk down `bindings` called
        # free.
        needs = plan() + [Need('Views', 'hat4',
                               [[Bind('U')], [Bind('R')],
                                [Bind('D')], [Bind('L')]],
                               push=[Bind('RESET')])]
        self.assertIn('RESET', review._on_a_row(needs))

    def test_every_action_a_slot_binds_is_taken(self):
        # One control, two game ids: Elite binds the ship's command and
        # the buggy's off one press. Both name the row that has them.
        needs = [Need('Map', 'button', [[Bind('MAP'), Bind('MAP_BUGGY')]])]
        self.assertEqual({'MAP': 'Map', 'MAP_BUGGY': 'Map'},
                         review._on_a_row(needs))

    def test_it_says_which_row_has_the_action(self):
        # Elite shows 49 rows and binds 76 actions. The other 27 are
        # inside rows, and this screen is the only one that holds them
        # all, so it is the one that has to say where each went.
        needs = plan() + [Need('Views', 'hat4',
                               [[Bind('U')], [Bind('R')],
                                [Bind('D')], [Bind('L')]],
                               push=[Bind('RESET')])]
        got = review._on_a_row(needs)
        self.assertEqual('Views', got['RESET'])
        self.assertEqual('Gear', got['GEAR'])
        # `Trim` binds `U` too, and it is first. Two rows on one action
        # is a thing to see, and the screen shows the one that has it.
        self.assertEqual('Trim', got['U'])

    def test_an_action_nobody_binds_is_not_taken(self):
        self.assertNotIn('RESET', review._on_a_row(plan()))


class TheHeaderKeepsTheTally(unittest.TestCase):
    """The counts, the overlay and `unsaved` sit beside the title.

    `lid` drops its right-hand line whole, and the list panel used to ask
    for the width its ROWS want. Measured before this was fixed: the rows
    wanted 68 columns on Elite and 66 on X4, the header wanted 70 and 82,
    and both games lost the line at EVERY terminal width. A wider
    terminal did not help, because the surplus goes to the detail panel.
    """

    def test_the_width_it_asks_for_is_the_width_lid_keeps_it_at(self):
        # The threshold lives beside `lid`, so the two cannot drift. This
        # reads it off `lid` itself rather than repeating the sum.
        for title, right in (
                ('DCS World · F/A-18C · VIRPIL', '+35 · ?12 · F/A-18C'),
                ('Elite Dangerous · VIRPIL · Izowiuz-PLAN',
                 '+49 · Generic spaceship'),
                ('X4 Foundations · VIRPIL · inputmap_3.xml',
                 '+38 · ?11 · 1 unassigned · By hand')):
            with self.subTest(title=title):
                want = ctui.lid_wants(title, right)
                self.assertIn(right, ctui.lid(want, title, right))
                self.assertNotIn(right, ctui.lid(want - 1, title, right))

    def test_a_long_subtitle_does_not_take_the_tally_off_the_screen(self):
        rv = made()
        rv.subtitle = 'VIRPIL · Izowiuz-PLAN · a very long file name.xml'
        scr = Keyed([ord('q')], h=40, w=160)
        with unittest.mock.patch.object(
                review.ctui, 'setup',
                lambda s: ctui.Tui(s, ctui.Theme(False))):
            review._loop(scr, rv, None, review.Sticks(rv.layout))
        self.assertIn(review._tally(rv), scr.frames[-1])


class TheVocabularyShowsTheRowYouAreOn(unittest.TestCase):
    """The cursor is on a row you can see.

    `page` is the body: every row between the lid and the sill. The draw
    took one fewer than that and the scroll clamped to `page`, so the
    cursor could sit on the row under the last one drawn. Moving down
    kept it there, and the highlighted action was then invisible for the
    whole way down a 440-row list.
    """

    def frame(self, h, downs):
        cat = [Action(f'ID_{i:03}', f'Action {i:03}') for i in range(60)]
        rv = made(catalogue=cat)
        scr = Keyed([ord('j')] * downs + [ord('q')], h=h, w=100)
        review._browse(scr, ctui.Tui(scr, ctui.Theme(False)), rv)
        return scr.frames[-1]

    def test_the_one_under_the_cursor_is_drawn(self):
        for h, downs in ((20, 25), (20, 40), (14, 30), (40, 50)):
            with self.subTest(h=h, downs=downs):
                self.assertIn(f'Action {downs:03}', self.frame(h, downs))

    def test_the_body_is_drawn_whole(self):
        # One row short left a blank line above the sill, which is the
        # room for one more action of 440.
        said = [line for line in self.frame(20, 0).split('\n')[1:-1]
                if 'Action' in line]
        self.assertEqual(20 - 2, len(said))


class TheVocabularySaysWhereAnActionWent(unittest.TestCase):
    """Which row has this action, beside the action.

    Elite shows 49 rows and binds 76 actions: a row carries a hat's four
    directions, its press, and the buggy's command beside the ship's.
    The list names the rows, `BINDS` opens one row at a time, and this
    screen is the only one that holds all 76.
    """

    CAT = [Action('ID_GEAR', 'Landing gear'),
           Action('ID_U', 'Trim up'),
           Action('ID_SPARE', 'Nothing has this')]

    def frame(self):
        needs = [Need('Gear', 'button', [[Bind('ID_GEAR')]]),
                 Need('Trim', 'hat4', [[Bind('ID_U')], [], [], []])]
        rv = made(needs, catalogue=self.CAT)
        scr = Keyed([ord('q')], h=20, w=110)
        review._browse(scr, ctui.Tui(scr, ctui.Theme(False)), rv)
        # Keyed by the id, which is the one word on the line that
        # cannot be the name of a row as well.
        return {a.id: line for line in scr.frames[-1].split('\n')
                for a in self.CAT if a.id in line}

    def test_the_row_that_has_it_is_on_the_line(self):
        got = self.frame()
        self.assertIn('Gear', got['ID_GEAR'])
        self.assertIn('Trim', got['ID_U'])

    def test_an_action_no_row_has_names_none(self):
        said = self.frame()['ID_SPARE']
        self.assertNotIn('Gear', said)
        self.assertNotIn('Trim', said)


class WhatYourHandIsOnLightsUp(unittest.TestCase):
    """A press names the control in the corner and marks its rows.

    The box answers "which control is this". The list answers "which
    function is on it". Reading a column of control names to find the
    row is the work a press is there to save.

    The cursor stays where it is. It is what `c`, `x` and `↵` act on,
    and a lever nudged by a sleeve would move it under them.
    """

    def touched(self, rv, what):
        """(role, kind, index) for the input a row sits on."""
        p = at(rv, by(rv, what))
        button = p.slots[0][0]
        return (p.role,
                'axis' if isinstance(button, corneeds.OnAxis) else 'button',
                button.index if isinstance(button, corneeds.OnAxis)
                else button)

    def test_the_row_on_the_input_comes_back(self):
        rv = made()
        need = by(rv, 'Gear')
        self.assertIn(need, rv.on_input(*self.touched(rv, 'Gear')))

    def test_a_role_no_device_answers_names_nothing(self):
        self.assertEqual([], made().on_input('pedals', 'button', 0))

    def test_an_input_the_map_does_not_name_names_nothing(self):
        self.assertEqual([], made().on_input('stick', 'button', 999))

    def test_every_row_it_marks_is_one_the_corner_names(self):
        # The box names what the CONTROL carries and the rows say what
        # the BUTTON does, so the marked rows are some of what the box
        # names and never a row it leaves out.
        rv = made()
        got = self.touched(rv, 'Gear')
        said = ' '.join(t for _tone, t in rv.pressed(*got))
        lit = rv.on_input(*got)
        self.assertTrue(lit)
        for need in lit:
            self.assertIn(need.what, said)

    def test_one_direction_of_a_shared_hat_marks_one_row(self):
        # Four of Elite's rows share the stick's top thumb hat. A hat
        # marked whole leaves the reader working out which of them the
        # thumb just did.
        rv = made()
        got = self.touched(rv, 'Trim')
        ctrl, _part = rv.touched_at(*got)
        self.assertLessEqual(len(rv.on_input(*got)),
                             len(rv.who_has(got[0], ctrl)))

    def test_the_mark_is_added_to_the_tone_the_row_already_has(self):
        rv = made()
        need = by(rv, 'Gear')
        scr = Keyed([], h=30, w=120)
        theme = ctui.Theme(False)
        seen = {}

        def catch(s, y, x, text, attr=curses.A_NORMAL):
            if 'Gear' in text:
                seen[len(seen)] = attr

        with unittest.mock.patch.object(review, '_put', catch):
            review._draw(scr, rv, 0, {'top': 0}, theme)
            review._draw(scr, rv, 0, {'top': 0}, theme, lit=frozenset([need]))
        dark, lit = seen[0], seen[1]
        self.assertNotEqual(dark, lit)
        self.assertEqual(dark | theme.touched, lit)

    def test_a_press_does_not_move_the_cursor(self):
        # The device map jumps the cursor to the pressed row. Here the
        # cursor is what `c`, `x` and `↵` act on, so a lever nudged by a
        # sleeve would move them off the row you are reading.
        rv = made()
        p = at(rv, by(rv, 'Canopy'))
        button = p.slots[0][0]
        kind = 'axis' if isinstance(button, corneeds.OnAxis) else 'button'
        index = button.index if kind == 'axis' else button
        scr = Keyed([ord('q')], h=30, w=120)
        sels, first, was = [], [True], review._draw

        def once():
            # One event, then quiet. A press that never stopped would
            # hold the corner box up for the whole run.
            if first[0]:
                first[0] = False
                return (p.role, kind, index)
            return None

        def watch(s, r, sel, state, theme, focus=review.LIST, **kw):
            sels.append(sel)
            return was(s, r, sel, state, theme, focus, **kw)

        sticks = review.Sticks(rv.layout)
        with unittest.mock.patch.object(
                review.ctui, 'setup',
                lambda s: ctui.Tui(s, ctui.Theme(False))), \
             unittest.mock.patch.object(review, '_draw', watch), \
             unittest.mock.patch.object(sticks, 'touched', once), \
             unittest.mock.patch.object(sticks, 'open', lambda: None):
            review._loop(scr, rv, None, sticks)
        self.assertTrue(sels)
        self.assertEqual(1, len(set(sels)))

"""The rules the allocator works from, as a file rather than as literals.

The weights are judgements. "+25 because it suits the job" against "+20
because it is exactly the shape asked for" is somebody's opinion about
which matters more, and this project moves judgements out of source --
the 382 in `games/*/‑binds.json` went first and these are the same kind.

What a file may NOT hold is what a condition MEANS. `device_matches` is a
predicate over a control and a need; the file names it, `core/needs.py`
writes it. A file that could define conditions would need an expression
language, and that is a worse thing to own than this one.

So the two halves have to be held to each other, which is what these do.
"""

import unittest

import fake
from core import devmap
from core import needs as corneeds


class TheDescriptor(unittest.TestCase):

    def test_every_condition_named_has_one_written(self):
        # A typo in the file would otherwise be a term that silently never
        # fires -- a weight nobody applies, and a screen that says it does.
        for term in corneeds.TERMS:
            self.assertIn(term['when'], corneeds.WHEN, term['says'])
        for gate in corneeds.GATES:
            self.assertIn(gate['when'], corneeds.REFUSE, gate['says'])

    def test_every_condition_written_is_one_the_file_names(self):
        # The other way: a predicate nothing references is a rule that was
        # removed from the file and left behind in the code.
        named = {t['when'] for t in corneeds.TERMS}
        self.assertEqual(set(corneeds.WHEN), named)
        self.assertEqual(set(corneeds.REFUSE),
                         {g['when'] for g in corneeds.GATES})

    def test_every_term_is_named_once(self):
        # The handle an override uses. Three terms are conditioned on
        # `always`, so the condition cannot be it.
        names = [t['name'] for t in corneeds.TERMS]
        self.assertEqual(len(names), len(set(names)), names)

    def test_a_term_with_holes_in_its_words_has_a_general_form(self):
        # `says` is filled from the run. The screen that explains the
        # rules has no run, and `pinned to {label}` on it is a hole.
        for term in corneeds.TERMS:
            if '{' in term['says']:
                self.assertIn('general', term, term['name'])
                self.assertNotIn('{', term['general'], term['name'])

    def test_every_multiplier_named_has_one_written(self):
        for term in corneeds.TERMS:
            if 'per' in term:
                self.assertIn(term['per'], corneeds.PER, term['says'])

    def test_a_term_that_stops_is_worth_more_than_the_rest_together(self):
        # A pin outranks the reach tables, not just the ranking, so it has
        # to beat any sum the ordinary terms can reach.
        stops = [t for t in corneeds.TERMS if t.get('stops')]
        self.assertTrue(stops)
        rest = sum(abs(t['weight']) for t in corneeds.TERMS
                   if not t.get('stops'))
        self.assertGreater(stops[0]['weight'], rest)

    def test_the_tables_the_allocator_uses_come_from_the_file(self):
        # Not transcribed beside it: one definition, or they drift.
        self.assertEqual(len(corneeds.RULES['band']),
                         len(corneeds.URGENCY_NAME))
        self.assertEqual(len(corneeds.RULES['shapes']), len(corneeds.FITS))
        self.assertEqual(corneeds.RULES['reach']['unmeasured'],
                         corneeds.UNMEASURED)

    def test_a_band_may_not_reach_closer_than_it_may_reach(self):
        # `takes` is [closest, furthest]; the other way round would make a
        # band that can take nothing, and nothing would say why.
        for n, band in enumerate(corneeds.RULES['band']):
            low, high = band['takes']
            self.assertLessEqual(low, high, band['name'])
            self.assertEqual(low, corneeds.MIN_REACH[n])
            self.assertEqual(high, corneeds.MAX_REACH[n])

    def test_every_shape_stands_in_for_itself_first(self):
        # The first entry scores the exact-shape bonus, so a list whose
        # head is something else hands the bonus to a substitute.
        for shape, subs in corneeds.FITS.items():
            self.assertEqual(shape, subs[0])


class TheFactTable(unittest.TestCase):
    """The five ergonomic answers the map collects, and what they cost.

    Unlike a term, a fact names no predicate: `reads` names a field on the
    control and the row's shape does the rest. So the lock here is not
    "every name has a definition" -- it is `check_rules`, which fails the
    whole map load on a `reads` the map does not measure, and these, which
    hold the three shapes to what they promise.
    """

    def ctrl(self, **facts):
        dev = fake.device('stick', [fake.button('B', 0, reach=fake.THUMB,
                                                **facts)])
        return list(dev.groups())[0]

    def need(self, urgency=corneeds.IN_A_TURN, **flags):
        one = corneeds.Need('X', 'button', [['A']], urgency=urgency)
        for flag, value in flags.items():
            setattr(one, flag, value)
        return one

    def points(self, ctrl, need):
        # Asserted rather than returned raw: a gate answers None and
        # every caller here is doing arithmetic. `refused` is the one
        # that wants the other answer.
        got = corneeds.score(ctrl, need, 'stick')
        assert got is not None
        return got

    def refused(self, ctrl, need):
        return corneeds.score(ctrl, need, 'stick') is None

    def words(self, ctrl, need):
        parts = []
        corneeds.score(ctrl, need, 'stick', parts=parts)
        return [text for delta, text in parts if delta]

    # ---- the three shapes ----

    def test_a_bool_fact_pays_both_ways(self):
        yes = self.points(self.ctrl(hold_ok=True), self.need(held=True))
        no = self.points(self.ctrl(hold_ok=False), self.need(held=True))
        plain = self.points(self.ctrl(), self.need())
        self.assertGreater(yes, plain)
        self.assertLess(no, plain)
        self.assertIn('you can hold it', self.words(self.ctrl(hold_ok=True),
                                                    self.need(held=True)))

    def test_a_scale_fact_pays_per_step(self):
        # Generic over the table: both the shapes in it are here, one
        # charging the answer and one charging the shortfall from it.
        for fact in corneeds.FACTS:
            if 'scale' not in fact:
                continue
            asked = self.need(**{fact['asked']: True})
            got = [self.points(self.ctrl(**{fact['reads']: n}), asked)
                   for n in (0, 1, 2)]
            self.assertEqual(got[1] - got[0], got[2] - got[1], fact['reads'])
            self.assertNotEqual(got[0], got[2], fact['reads'])

    def test_a_scale_fact_worth_nothing_says_nothing(self):
        # `0  hard to find by feel` on a screen reads as a fact about the
        # control, and it is the absence of one.
        self.assertNotIn('hard to find by feel',
                         self.words(self.ctrl(blind_distinct=2),
                                    self.need(by_feel=True)))

    def test_a_scale_fact_has_words_for_more_than_one(self):
        self.assertIn('you cannot find it by feel',
                      self.words(self.ctrl(blind_distinct=0),
                                 self.need(by_feel=True)))

    def test_a_shortfall_is_charged_from_the_best_answer_down(self):
        # The other way round -- paying for the answer -- paid nearly
        # every control on this desk the same and decided nothing.
        best = self.points(self.ctrl(blind_distinct=2),
                           self.need(by_feel=True))
        self.assertEqual(self.points(self.ctrl(), self.need()), best)
        self.assertLess(self.points(self.ctrl(blind_distinct=1),
                                    self.need(by_feel=True)), best)

    def test_a_refusing_fact_refuses(self):
        self.assertTrue(self.refused(self.ctrl(modifier_ok=False),
                                     self.need(modifier=True)))

    # ---- the two rules that hold for every row, present and future ----

    def test_a_fact_nobody_answered_counts_for_nothing(self):
        # None is an unwalked desk, not a middling answer. Generic over
        # the table, so a sixth fact is covered the day it is written.
        plain = self.points(self.ctrl(), self.need())
        for fact in corneeds.FACTS:
            self.assertEqual(
                plain, self.points(self.ctrl(),
                                   self.need(**{fact['asked']: True})),
                fact['reads'])

    def test_a_fact_the_need_does_not_ask_for_counts_for_nothing(self):
        # The thing that keeps a term from being weather: it moves the
        # handful of needs somebody judged, and nothing else.
        plain = self.points(self.ctrl(), self.need())
        for fact in corneeds.FACTS:
            for answer in (True, False):
                self.assertEqual(
                    plain, self.points(self.ctrl(**{fact['reads']: answer}),
                                       self.need()),
                    f'{fact["reads"]} = {answer}')

    def test_a_refusing_fact_refuses_only_on_a_measured_no(self):
        # A gate that refused out of ignorance would leave BMS's shift
        # nowhere at all on a map nobody has answered yet.
        for fact in corneeds.FACTS:
            if not fact.get('refuses'):
                continue
            asked = self.need(**{fact['asked']: True})
            self.assertFalse(self.refused(self.ctrl(), asked),
                             fact['reads'])
            self.assertFalse(
                self.refused(self.ctrl(**{fact['reads']: True}), asked))
            self.assertTrue(
                self.refused(self.ctrl(**{fact['reads']: False}), asked))

    # ---- the property the whole table exists for ----

    def test_a_new_fact_costs_no_python(self):
        # This is the point of the table rather than five more lambdas in
        # WHEN, so it is the one thing that has to be tested directly: a
        # block in the file, and the flag, the predicate and the words all
        # appear. Nothing below imports or patches any code.
        rules = corneeds.merge_rules(corneeds.RULES, {})
        rules['fact'] = list(rules['fact']) + [
            {'reads': 'cumulative', 'asked': 'staged', 'yes': 7, 'no': -3,
             'says': 'it stages', 'not': 'it does not stage'}]
        one = corneeds.Need('X', 'button', [['A']])
        setattr(one, 'staged', True)
        staged = self.ctrl()
        staged.cumulative = True
        parts = []
        got = corneeds.score(staged, one, 'stick', parts=parts, rules=rules)
        self.assertEqual(7, dict((t, d) for d, t in parts)['it stages'])
        plain = corneeds.score(staged, one, 'stick', rules=rules)
        self.assertEqual(got, plain)

    # ---- what check_rules will not let into the file ----

    def bad(self, row):
        rules = corneeds.merge_rules(corneeds.RULES, {})
        rules['fact'] = [row]
        with self.assertRaises(ValueError) as caught:
            corneeds.check_rules(rules, devmap.load())
        return str(caught.exception)

    def test_a_fact_the_map_does_not_measure_is_refused(self):
        self.assertIn('hold_okk', self.bad(
            {'reads': 'hold_okk', 'asked': 'held', 'yes': 1, 'no': -1}))

    def test_a_fact_nothing_turns_on_is_refused(self):
        self.assertIn('asked', self.bad(
            {'reads': 'hold_ok', 'yes': 1, 'no': -1}))

    def test_a_shortfall_with_nothing_to_charge_is_refused(self):
        self.assertIn('no `scale`', self.bad(
            {'reads': 'blind_distinct', 'asked': 'by_feel', 'below': 2,
             'yes': 1, 'no': -1}))

    def test_a_fact_weighs_exactly_one_way(self):
        self.assertIn('at once', self.bad(
            {'reads': 'hold_ok', 'asked': 'held', 'yes': 1, 'no': -1,
             'scale': 2}))
        self.assertIn('weighs nothing', self.bad(
            {'reads': 'hold_ok', 'asked': 'held'}))

    def test_a_bool_fact_needs_a_weight_for_both_answers(self):
        self.assertIn('both', self.bad(
            {'reads': 'hold_ok', 'asked': 'held', 'yes': 1}))


class AGameOverTheTop(unittest.TestCase):
    """A game's own rules, merged over the core's.

    Two games already needed this and got it as a function argument: DCS
    replaces the band limits, BMS vetoes controls the game cannot address.
    The first is data and belongs in a file; the second stays a hook,
    because only the game knows which of its buttons it can reach.
    """

    def merged(self, extra):
        return corneeds.merge_rules(corneeds.RULES, extra)

    def test_a_band_is_replaced_by_name_not_by_position(self):
        # By position, inserting a band in the core file would silently
        # repoint every override in the family at the wrong one.
        got = self.merged({'band': [{'name': 'in the air', 'takes': [0, 1]}]})
        by_name = {b['name']: b['takes'] for b in got['band']}
        self.assertEqual([0, 1], by_name['in the air'])
        self.assertEqual([0, 1], by_name['in a turn'], 'the rest stand')

    def test_a_band_the_core_does_not_have_is_refused(self):
        # A typo would otherwise add a fifth band nothing places into.
        with self.assertRaises(ValueError):
            self.merged({'band': [{'name': 'mid-burn', 'takes': [0, 1]}]})

    def test_a_weight_can_be_retuned(self):
        got = self.merged({'term': [{'name': 'click', 'weight': 99}]})
        weights = {t['name']: t['weight'] for t in got['term']}
        self.assertEqual(99, weights['click'])
        self.assertEqual(100, weights['fits'], 'the rest stand')
        self.assertEqual({t['name']: t['says'] for t in
                          corneeds.RULES['term']}['click'],
                         {t['name']: t['says'] for t in got['term']}['click'],
                         'what it says is kept when only the weight moves')

    def test_a_condition_the_core_does_not_define_is_refused(self):
        with self.assertRaises(ValueError):
            self.merged({'term': [{'name': 'vibes', 'weight': 1}]})

    def test_the_core_is_not_changed_by_merging_over_it(self):
        was = corneeds.RULES['band'][2]['takes']
        self.merged({'band': [{'name': 'in the air', 'takes': [0, 1]}]})
        self.assertEqual(was, corneeds.RULES['band'][2]['takes'])


if __name__ == '__main__':
    unittest.main()

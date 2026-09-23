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

import fake                                                  # noqa: F401
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

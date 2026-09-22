"""The frame a panel is drawn in, as strings.

btop puts its chrome in the border -- the title, the counts and the key
names all live in the box edge rather than in rows of their own -- and that
is the whole reason to have a frame at all: three lines of key names at the
bottom of a 24-row terminal is an eighth of the screen spent on something
you read once.

The two builders here are pure, which is the point. The last two attempts
at chrome drew one thing over another and every test passed, because they
all asked what the text said rather than what reached the screen. A string
cannot paint over itself.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core.tui import lid, sill                                 # noqa: E402


class TheLid(unittest.TestCase):
    """The top edge: what this panel is, and what it is showing."""

    def test_it_is_exactly_as_wide_as_asked(self):
        for w in (20, 40, 79, 100):
            self.assertEqual(w, len(lid(w, 'actions', 'find · 3 of 32')))

    def test_it_carries_the_title(self):
        self.assertIn('actions', lid(40, 'actions'))

    def test_the_right_hand_note_sits_at_the_right(self):
        got = lid(40, 'a', 'note')
        self.assertGreater(got.index('note'), got.index('a'))
        self.assertTrue(got.endswith('note ╮'))

    def test_a_note_too_wide_to_fit_is_dropped_not_wrapped(self):
        # Better a plain edge than a border that has eaten the title.
        got = lid(20, 'actions', 'a very long note indeed')
        self.assertIn('actions', got)
        self.assertEqual(20, len(got))

    def test_a_title_too_wide_to_fit_is_cut(self):
        got = lid(16, 'an extremely long panel name')
        self.assertEqual(16, len(got))
        self.assertTrue(got.startswith('╭'))
        self.assertTrue(got.endswith('╮'))

    def test_a_box_too_narrow_for_anything_is_still_a_box(self):
        self.assertEqual('╭╮', lid(2, 'actions'))
        self.assertEqual('', lid(0, 'actions'))


class TheSill(unittest.TestCase):
    """The bottom edge: which keys do what, and where you are."""

    def test_it_is_exactly_as_wide_as_asked(self):
        for w in (20, 40, 79, 100):
            self.assertEqual(w, len(sill(w, ('↑↓ move', '↵ press'), '1/32')))

    def test_every_key_that_fits_is_shown(self):
        got = sill(60, ('↑↓ move', '↵ press', 'q quit'), '')
        for k in ('↑↓ move', '↵ press', 'q quit'):
            self.assertIn(k, got)

    def test_keys_that_do_not_fit_are_dropped_from_the_end(self):
        # Losing the last hint beats losing the frame. Moving is listed
        # first everywhere for this reason: it is what survives.
        got = sill(24, ('↑↓ move', '↵ press', 'q quit'), '')
        self.assertIn('↑↓ move', got)
        self.assertNotIn('q quit', got)
        self.assertEqual(24, len(got))

    def test_the_tail_sits_at_the_right(self):
        got = sill(50, ('↑↓ move',), '12/32')
        self.assertTrue(got.endswith('12/32 ╯'))

    def test_the_tail_wins_over_a_key(self):
        # Where you are is the thing that changes; a key name is not.
        got = sill(26, ('↑↓ move', '↵ press'), '12/32')
        self.assertIn('12/32', got)
        self.assertEqual(26, len(got))


if __name__ == '__main__':
    unittest.main()

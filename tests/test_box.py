"""The frame a panel is drawn in, as strings.

The chrome lives in the border. The title, the counts and the key names
all sit in the box edge rather than in rows of their own, and that is the
reason to have a frame: three lines of key names at the bottom of a
24-row terminal spends an eighth of the screen on something you read
once. btop does it this way.

The two builders here are pure, and that is the point. Chrome drawn in
pieces paints one thing over another, and a test that asks what the text
said does not catch it. A string cannot paint over itself.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from core.tui import (CHOOSE_KEYS, box_for, lid, overflows,     # noqa: E402
                      rows_in, sill)


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
        # A plain edge beats a border that has eaten the title.
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
        # first everywhere for that reason. It is what survives.
        got = sill(24, ('↑↓ move', '↵ press', 'q quit'), '')
        self.assertIn('↑↓ move', got)
        self.assertNotIn('q quit', got)
        self.assertEqual(24, len(got))

    def test_the_tail_sits_at_the_right(self):
        got = sill(50, ('↑↓ move',), '12/32')
        self.assertTrue(got.endswith('12/32 ╯'))

    def test_the_tail_wins_over_a_key(self):
        # Where you are is the thing that changes. A key name is not.
        got = sill(26, ('↑↓ move', '↵ press'), '12/32')
        self.assertIn('12/32', got)
        self.assertEqual(26, len(got))


class HowBigAPopup(unittest.TestCase):
    """A box sized to what it holds, and honest where it cannot hold it.

    A box that renders `lines[:bh - 2]` and stops ends the help list on a
    24-row terminal, with nothing to say it has. The keys that fall off
    are the ones furthest down, and that is where the less-used ones live.
    Somebody looking for help is looking there.
    """

    def test_a_short_list_gets_a_box_its_own_size(self):
        _y, _x, bh, _bw = box_for(['one', 'two'], 24, 80, 'keys')
        self.assertEqual(2, rows_in(bh))

    def test_a_box_keeps_a_blank_row_above_its_sill(self):
        # Text that runs into the bottom edge reads as text cut off
        # there.
        _y, _x, bh, _bw = box_for(['one', 'two'], 24, 80, 'keys')
        self.assertEqual(rows_in(bh) + 2 + 1, bh)

    def test_a_long_list_stops_at_the_screen(self):
        _y, _x, bh, _bw = box_for([f'line {i}' for i in range(90)],
                                  24, 80, 'keys')
        self.assertLessEqual(bh, 24)

    def test_the_box_is_never_wider_than_the_screen(self):
        _y, _x, _bh, bw = box_for(['x' * 200], 24, 80, 'keys')
        self.assertLessEqual(bw, 80)

    def test_a_full_box_is_the_whole_screen(self):
        # The vocabulary screen and the device map are lists you work in.
        # They are not notices you read. Centred and sized to content,
        # they sit in a hole, and every row they could have shown is one
        # they did not.
        self.assertEqual((0, 0, 24, 80),
                         box_for(['one'], 24, 80, 'map', full=True))

    def test_it_says_when_more_is_coming_than_fits(self):
        self.assertTrue(overflows([f'line {i}' for i in range(90)], 24, 80,
                                  'keys'))
        self.assertFalse(overflows(['one', 'two'], 24, 80, 'keys'))



class ABoxLeavesRoomForItsOwnKeys(unittest.TestCase):
    """Room for the keys.

    `sill` drops the keys that do not fit. A short list under a short
    title makes a box too narrow to say `↵ choose`, and that is the way
    out of the box.
    """

    def test_the_keys_widen_a_narrow_box(self):
        body = ['a', 'b']
        bare = box_for(body, 24, 80, 'Pick')[3]
        with_keys = box_for(body, 24, 80, 'Pick', keys=CHOOSE_KEYS)[3]
        self.assertGreater(with_keys, bare)

    def test_and_all_of_them_reach_the_sill(self):
        # With the tail, because `sill` keeps that before any key. A box
        # sized for the keys alone still drops the last one.
        _y, _x, _h, bw = box_for(['a'], 24, 80, 'Pick', keys=CHOOSE_KEYS,
                                 tail='1 of 2')
        said = sill(bw, CHOOSE_KEYS, '1 of 2')
        for key in CHOOSE_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, said)
        self.assertIn('1 of 2', said)

    def test_the_tail_widens_it_too(self):
        keys = CHOOSE_KEYS
        self.assertGreater(
            box_for(['a'], 24, 80, 'Pick', keys=keys, tail='20 of 35')[3],
            box_for(['a'], 24, 80, 'Pick', keys=keys)[3])

    def test_a_box_wide_enough_already_is_not_widened(self):
        body = ['x' * 60]
        self.assertEqual(box_for(body, 24, 80, 'Pick')[3],
                         box_for(body, 24, 80, 'Pick', keys=CHOOSE_KEYS)[3])

    def test_no_keys_asks_for_no_room(self):
        body = ['a', 'b']
        self.assertEqual(box_for(body, 24, 80, 'Pick')[3],
                         box_for(body, 24, 80, 'Pick', keys=())[3])

    def test_it_never_outgrows_the_screen(self):
        wide = tuple(f'{"k" * 20} {n}' for n in range(6))
        self.assertLessEqual(box_for(['a'], 24, 40, 'Pick', keys=wide)[3], 38)


class TheCounterDoesNotResizeTheBox(unittest.TestCase):
    """The width holds as the cursor moves.

    `1 of 12` is narrower than `12 of 12`, and a box that sizes itself to
    whichever one is showing changes width as you scroll.
    """

    def widths(self, count):
        wide = len(str(count))
        return {box_for(['a'] * count, 40, 80, 'Pick', keys=CHOOSE_KEYS,
                        tail=f'{n:>{wide}} of {count}')[3]
                for n in range(1, count + 1)}

    def test_every_row_gives_the_same_width(self):
        self.assertEqual(1, len(self.widths(12)))

    def test_and_at_three_digits_too(self):
        self.assertEqual(1, len(self.widths(120)))


class Keyed:
    """A screen that records every frame and answers with these keys."""

    def __init__(self, keys, h=24, w=80):
        self.h, self.w, self.keys = h, w, list(keys)
        self.frames, self.drawn = [], []
        self.erase()

    def getmaxyx(self):
        return self.h, self.w

    def erase(self):
        self.rows = [[' '] * self.w for _ in range(self.h)]

    def refresh(self):
        self.frames.append('\n'.join(''.join(r) for r in self.rows))

    def getch(self):
        return self.keys.pop(0) if self.keys else 27

    def addstr(self, y, x, text, attr=0):
        self.drawn.append((y, x, text, attr))
        for i, ch in enumerate(text):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.rows[y][x + i] = ch

    def lit(self, attr):
        """What was drawn with this attribute, newest frame first."""
        return [t for _y, _x, t, a in self.drawn if a == attr]


class ThePickerAsItIsDriven(unittest.TestCase):
    """The width the cursor actually sees, frame by frame."""

    def lids(self, count=12):
        import curses
        from core import tui as ctui
        scr = Keyed([curses.KEY_DOWN] * (count - 1) + [27])
        ctui.Tui(scr, ctui.Theme(False)).choose(
            'Pick', [('plain', f'row {n}') for n in range(count)])
        out = []
        for frame in scr.frames:
            top = next(ln for ln in frame.splitlines() if ctui.TL in ln)
            out.append(len(top.strip()))
        return out

    def test_it_does_not_change_width_as_the_cursor_moves(self):
        # `1 of 12` is narrower than `12 of 12`, and a box that sizes
        # itself to whichever one is showing twitches as you scroll.
        said = self.lids()
        self.assertGreater(len(said), 1, 'nothing was drawn')
        self.assertEqual(1, len(set(said)), said)

    def test_and_says_every_key_on_every_frame(self):
        from core import tui as ctui
        scr = Keyed([ctui.curses.KEY_DOWN, 27])
        ctui.Tui(scr, ctui.Theme(False)).choose(
            'Pick', [('plain', f'row {n}') for n in range(12)])
        for n, frame in enumerate(scr.frames):
            for key in ctui.CHOOSE_KEYS:
                with self.subTest(frame=n, key=key):
                    self.assertIn(key, frame)


class RowsThatAreNotPartOfTheList(unittest.TestCase):
    """`head` says where a list came from, above the list and inside the
    box.

    The sill's note pushes the keys off, and the way out of a box is not
    the thing to trade away.
    """

    def driven(self, head, keys=()):
        import curses
        from core import tui as ctui
        scr = Keyed(list(keys) + [27])
        got = ctui.Tui(scr, ctui.Theme(False)).choose(
            'Pick', [('plain', f'row {n}') for n in range(3)], head=head)
        return got, scr.frames

    def test_the_head_is_on_the_screen(self):
        _got, frames = self.driven([('meta', 'read from /somewhere')])
        self.assertIn('read from /somewhere', frames[0])

    def test_the_cursor_starts_on_the_list_and_not_on_the_head(self):
        # The returned index says nothing about which row is lit, and a
        # lit head reads as a heading you can choose.
        import curses
        from core import tui as ctui
        scr = Keyed([27])
        theme = ctui.Theme(False)
        ctui.Tui(scr, theme).choose(
            'Pick', [('plain', f'row {n}') for n in range(3)],
            head=[('meta', 'read from /somewhere')])
        self.assertEqual(['row 0'], [t.strip() for t in scr.lit(theme.sel)])

    def test_the_cursor_cannot_leave_the_list(self):
        import curses
        got, _frames = self.driven([('meta', 'x'), ('plain', '')],
                                   [curses.KEY_DOWN] * 6 + [10])
        self.assertEqual(2, got)

    def test_and_what_it_returns_indexes_the_list(self):
        import curses
        got, _frames = self.driven([('meta', 'x'), ('plain', '')],
                                   [curses.KEY_DOWN, curses.KEY_DOWN, 10])
        self.assertEqual(2, got)

    def test_the_keys_still_fit(self):
        from core import tui as ctui
        _got, frames = self.driven([('meta', 'read from /somewhere')])
        for key in ctui.CHOOSE_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, frames[0])

    def test_the_count_is_of_the_list_and_not_of_the_rows(self):
        _got, frames = self.driven([('meta', 'x'), ('plain', '')])
        self.assertIn('1 of 3', frames[0])
if __name__ == '__main__':
    unittest.main()


class WhatTheFrameLooksLike(unittest.TestCase):
    """Every row of it, on a grid.

    A string cannot paint over itself, so a test over the text does not
    catch chrome drawn in pieces.
    """

    def drawn(self, body, title='Pick', keys=CHOOSE_KEYS, tail='1 of 2'):
        from core import tui as ctui
        scr = Keyed([27], h=14, w=60)
        ctui.Tui(scr, ctui.Theme(False)).box(
            title, [('plain', t) for t in body], keys, tail)
        return [''.join(r) for r in scr.rows]

    def box_rows(self, body, **kw):
        from core import tui as ctui
        return [r for r in self.drawn(body, **kw)
                if ctui.V in r or ctui.TL in r or ctui.BL in r]

    def test_every_row_of_the_frame_is_the_same_width(self):
        got = [r.strip() for r in self.box_rows(['one', 'two'])]
        self.assertEqual(1, len(set(len(r) for r in got)), got)

    def test_the_blank_row_has_sides_like_every_other(self):
        from core import tui as ctui
        got = [r.strip() for r in self.box_rows(['one', 'two'])]
        blank = got[-2]
        self.assertTrue(blank.startswith(ctui.V), blank)
        self.assertTrue(blank.endswith(ctui.V), blank)
        self.assertEqual('', blank.strip(ctui.V).strip())

    def test_a_line_is_not_flush_against_the_sides(self):
        from core import tui as ctui
        got = [r.strip() for r in self.box_rows(['one'])]
        text = got[1]
        self.assertTrue(text.startswith(ctui.V + ' ' * ctui.GAP), repr(text))
        self.assertTrue(text.endswith(' ' * ctui.GAP + ctui.V), repr(text))

    def test_a_line_that_fits_the_screen_is_not_cut(self):
        # The box is sized to what it holds, so what it holds has to
        # survive. A gap counted on one side and not allowed for on the
        # other takes its room out of the text.
        # No keys and no tail, so the text alone decides the width. The
        # keys are wide enough to hide a mistake here.
        said = 'a line of some length'
        got = [r.strip() for r in self.box_rows([said], keys=(), tail='')]
        self.assertIn(said, got[1])

    def test_a_line_too_long_stops_inside_the_frame(self):
        from core import tui as ctui
        got = [r.strip() for r in self.box_rows(['x' * 200])]
        for row in got:
            with self.subTest(row=row):
                self.assertEqual(len(got[0]), len(row))
        self.assertTrue(got[1].endswith(' ' * ctui.GAP + ctui.V),
                        repr(got[1]))


class RowsTheCursorStepsOver(unittest.TestCase):
    """A blank row holding two kinds of thing apart.

    Landing on it is landing on nothing, and `↵ choose` there means
    nothing.
    """

    def driven(self, keys, skip=(1,), count=4):
        from core import tui as ctui
        scr = Keyed(list(keys) + [27], h=16, w=60)
        theme = ctui.Theme(False)
        lines = [('plain', '') if n in skip else ('plain', f'row {n}')
                 for n in range(count)]
        got = ctui.Tui(scr, theme).choose('Pick', lines, skip=skip)
        return got, scr, theme

    def test_going_down_lands_past_the_blank(self):
        import curses
        got, _scr, _t = self.driven([curses.KEY_DOWN, 10])
        self.assertEqual(2, got)

    def test_and_coming_back_up_does_too(self):
        import curses
        got, _scr, _t = self.driven([curses.KEY_DOWN] * 2
                                    + [curses.KEY_UP] * 2 + [10])
        self.assertEqual(0, got)

    def test_the_blank_is_never_the_one_lit(self):
        import curses
        _got, scr, theme = self.driven([curses.KEY_DOWN] * 4)
        for said in scr.lit(theme.sel):
            with self.subTest(said=said):
                self.assertTrue(said.strip())

    def test_the_last_row_is_reachable(self):
        got, _scr, _t = self.driven([ord('G'), 10])
        self.assertEqual(3, got)

    def test_the_count_leaves_the_blank_out(self):
        _got, scr, _t = self.driven([])
        self.assertIn('1 of 3', scr.frames[0])

    def test_a_list_that_is_all_blanks_answers_nothing(self):
        got, _scr, _t = self.driven([10], skip=(0, 1, 2, 3))
        self.assertIsNone(got)


class TheCornerBox(unittest.TestCase):
    """A small box in the bottom right, over whatever is already there.

    It answers a question about what is behind it, so it is drawn after
    that screen and not instead of it. The device map draws the same box
    for the same question.
    """

    def drawn(self, lines, h=24, w=80, title='pressed'):
        import curses
        from core import tui as ctui
        scr = Keyed([], h=h, w=w)
        tui = ctui.Tui(scr, ctui.Theme(False))
        for row in range(h):                    # a list behind it
            tui._put(row, 0, 'x' * (w - 1))
        tui.corner(title, lines)
        scr.refresh()
        return scr.frames[-1].split('\n')

    def test_nothing_at_all_draws_nothing(self):
        # The box is there while there is something to say and gone the
        # rest of the time. That is what tells a reader it is about the
        # moment.
        rows = self.drawn([])
        self.assertEqual({'x'}, set(''.join(rows).replace(' ', '')))

    def test_it_sits_in_the_bottom_right(self):
        rows = self.drawn([('plain', 'js 23')])
        lit = [n for n, r in enumerate(rows) if '╭' in r or '╰' in r]
        self.assertTrue(lit, rows)
        # The last row of the screen is left to the sill behind it.
        self.assertLess(max(lit), len(rows) - 1)
        self.assertGreater(rows[max(lit)].index('╰'), len(rows[0]) // 2)

    def test_the_title_is_in_the_edge(self):
        rows = self.drawn([('plain', 'js 23')], title='pressed')
        self.assertIn('pressed', '\n'.join(rows))

    def test_what_it_says_is_on_the_screen(self):
        rows = self.drawn([('plain', 'throttle  js 23'),
                           ('meta', 'Middle finger hat  up')])
        said = '\n'.join(rows)
        self.assertIn('throttle  js 23', said)
        self.assertIn('Middle finger hat  up', said)

    def test_it_leaves_a_blank_column_down_its_left(self):
        # The list behind runs up to the frame and is cut mid-word. The
        # box's body row, not its sill: a sill is corners and a rule.
        rows = self.drawn([('plain', 'js 23')])
        body = next(r for r in rows if '│' in r)
        self.assertEqual(' ', body[body.index('│') - 1])

    def test_it_does_not_hide_the_list_above_it(self):
        rows = self.drawn([('plain', 'js 23')])
        self.assertEqual('x' * 79, rows[0].rstrip())

    def test_more_than_fits_is_cut_rather_than_grown(self):
        rows = self.drawn([('plain', f'line {n}') for n in range(40)])
        self.assertEqual(24, len(rows))

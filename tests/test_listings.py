"""What a game says back about a layout, and what it writes from one.

Four places where a game disagrees with the layout it was handed. They sit
together because they are one fault in four coats: a listing or a writer
that works off something OTHER than what it was given. That is a field
that no longer exists, a list rebuilt instead of read, an order derived
instead of taken, or a whole argument ignored.

Each one is dormant today for its own reason: nothing goes unplaced,
nobody runs `free` twice, nobody notices a button moved. Every one of
those reasons stops holding the moment the need list comes from a game's
whole vocabulary rather than from a hand-written list of thirty.
"""

import json
import os
import sys
import typing
import unittest

import fake
from core import adapter
from core import needs as corneeds
from core import vocab

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def game(name) -> typing.Any:
    """An adapter instance, or None if this clone has no harvest for it."""
    try:
        return adapter.adapters(name)[0]()
    except (FileNotFoundError, vocab.Missing, SystemExit):
        return None


#: `Any`, for the reason `game()` returns one. The adapter is loaded by
#: path, so nothing here can be typed against it. The conditional
#: otherwise narrows to None for a game that is not in `games/` yet.
WT: typing.Any = (game('warthunder')
                  if 'warthunder' in adapter.games() else None)


@unittest.skipUnless(WT, 'war thunder is not harvested here')
class WarThunderUnmet(unittest.TestCase):
    """The branch that runs where something finds no control.

    It has never run. War Thunder places all 28 of its needs, so `unmet`
    is empty every time, and the two faults below sit in that line. A need
    list that grows from 28 to 654 reaches them.
    """

    def listing(self, need):
        layout = corneeds.Layout({}, [], [need], [])
        return '\n'.join(WT.show(layout))

    def test_a_need_that_found_nothing_can_be_listed_at_all(self):
        # `n.reflex` is not a field of `Need`, and this line reads it.
        got = self.listing(WT.NEEDS[0])
        self.assertIn(WT.NEEDS[0].what, got)

    def test_the_shape_is_named_not_spelled_out(self):
        # `'/'.join(n.shape)` on the string 'button' gives 'b/u/t/t/o/n'.
        # Every other listing guards this with an `isinstance`. This line
        # does not, and 27 of War Thunder's 28 needs carry a string.
        need = next(n for n in WT.NEEDS if isinstance(n.shape, str))
        got = self.listing(need)
        self.assertIn(f'wanted {need.shape}', got)
        self.assertNotIn('/'.join(need.shape), got)


#: From the filesystem, and not from a list written here. A game that
#: exists only in a table is a game the table can be wrong about.
GAMES = {name: game(name) for name in adapter.games()}


class WhatIsFree(unittest.TestCase):
    """`free` is offered to you as somewhere to put a thing.

    So the one thing it may never hold is a control that already carries a
    binding. The main trigger offered to a cold-start switch is the
    listing arguing with the layout it came from.
    """

    def test_no_game_offers_a_control_it_has_already_used(self):
        tried = 0
        for name, g in GAMES.items():
            if g is None:
                continue
            tried += 1
            layout = g.build()
            busy = {(p.role, p.ctrl.label) for p in layout.placed}
            offered = {(role, c.label) for role, c in layout.free}
            self.assertEqual(
                set(), busy & offered,
                f'{name} offers {len(busy & offered)} control(s) that are '
                f'already carrying something: '
                + ', '.join(f'{r}/{lbl}' for r, lbl in sorted(busy & offered)))
        self.assertGreater(tried, 0, 'no game is harvested here')


if __name__ == '__main__':
    unittest.main()

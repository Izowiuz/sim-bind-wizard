"""What a game says back about a layout, and what it writes from one.

Four places where a game disagrees with the layout it was handed. They are
gathered here because they are one fault wearing four coats: a listing or a
writer that works off something OTHER than what it was given -- a field that
no longer exists, a list rebuilt instead of read, an order derived instead of
taken, a whole argument ignored.

Each is dormant today for its own reason -- nothing goes unplaced, nobody
runs `free` twice, nobody notices a button moved. Every one of those reasons
stops holding the moment the need list comes from a game's whole vocabulary
instead of a hand-written list of thirty.
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


WT = game('warthunder')


@unittest.skipUnless(WT, 'war thunder is not harvested here')
class WarThunderUnmet(unittest.TestCase):
    """The branch that runs when something finds no control.

    It has never run. War Thunder places all 28 of its needs, so `unmet` is
    empty every time, and the two faults below have sat in that line since
    it was written. Growing the need list from 28 to 654 is exactly what
    reaches them.
    """

    def listing(self, need):
        layout = corneeds.Layout({}, [], [need], [], [])
        return '\n'.join(WT.show(layout))

    def test_a_need_that_found_nothing_can_be_listed_at_all(self):
        # `n.reflex` was taken off `Need` -- "reflex is gone", says the
        # docstring in this same file -- and this line still reads it.
        got = self.listing(WT.NEEDS[0])
        self.assertIn(WT.NEEDS[0].what, got)

    def test_the_shape_is_named_not_spelled_out(self):
        # `'/'.join(n.shape)` on the string 'button' gives 'b/u/t/t/o/n'.
        # Every other listing in the family guards this with an isinstance;
        # this one line does not, and 27 of War Thunder's 28 needs carry a
        # string.
        need = next(n for n in WT.NEEDS if isinstance(n.shape, str))
        got = self.listing(need)
        self.assertIn(f'wanted {need.shape}', got)
        self.assertNotIn('/'.join(need.shape), got)


GAMES = {name: game(name) for name in
         ('x4', 'elite', 'warthunder', 'falconbms', 'msfs', 'dcs')}


class WhatIsFree(unittest.TestCase):
    """`free` is offered to you as somewhere to put a thing.

    So the one thing it may never contain is a control that already
    carries a binding -- offering the main trigger to a cold-start switch
    is the listing arguing with the layout it came from.
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


DCS = GAMES['dcs']


@unittest.skipUnless(DCS, 'dcs is not harvested here')
class DcsSeed(unittest.TestCase):
    """What the review narrowed has to reach the file.

    Five games hand `write_layout` the layout the reviewer accepted, and
    `Layout.but()` exists for exactly that. DCS takes the same argument and
    recomputes the whole plan from scratch instead, so anything cleared on
    the review screen comes back.
    """

    def recs(self, layout):
        written = DCS.seed(layout)
        (text,) = written.values()
        return json.loads(text)['aircraft'][DCS.aircraft]

    def test_clearing_every_binding_leaves_only_the_axes(self):
        # The starkest form: accept nothing at all. Axes never went through
        # the allocator, so they stay -- but not one button should.
        full = DCS.build()
        self.assertTrue(full.placed, 'nothing was placed to clear')
        got = self.recs(full.but([]))
        self.assertEqual({'axis'}, {r['type'] for r in got.values()} or
                         {'axis'})

    def test_one_binding_cleared_stays_cleared(self):
        full = DCS.build()
        dropped = next(p for p in full.placed
                       if p.why is None or p.why.how != 'claimed')
        kept = full.but([p for p in full.placed if p is not dropped])
        got = self.recs(kept)
        for h in dropped.need.members:
            self.assertNotIn(h, got,
                             f'{dropped.need.what!r} was cleared and came '
                             f'back anyway')


if __name__ == '__main__':
    unittest.main()

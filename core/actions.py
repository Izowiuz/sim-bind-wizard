"""One shape for a game action, whatever the game calls it.

Six harvests write six shapes and only the envelope is shared: X4 keeps
`{kind: [id]}`, Elite a list plus a separate `{fn: {votes, where}}`, BMS a
full record per callback, MSFS `{action: [contexts]}`, War Thunder
`{ID: [en, pl]}`, DCS a tree per aircraft. Nothing outside a game's own
`plan.py` can read any of them, which is why every screen in the family is
fed by a hand-written list instead of by the vocabulary.

This is the shape they translate into. It carries what all six between them
already know and nothing they would have to invent:

    id        the game's own identifier      INPUT_STATE_FP_USE
    name      human-readable                 "Use (on foot)"
    kind      'button' | 'axis'
    category  the game's own grouping        optional
    mode      which context it answers in    optional
    rank      how many factory profiles bind it, 0 where nobody counts

`category`, `mode` and `rank` are optional on purpose. Four of the six ship
no categories and X4 counts nothing, so a reader has to cope with their
absence anyway -- and deriving one to fill the gap puts a guess where the
next reader will find a fact.

The translating stays in each game's `catalogue()`, because how a cache is
laid out is a fact about that game. `core` owns the shape, the game owns the
reading, and when a harvest writes this shape directly its `catalogue()`
becomes a loop with nothing above it changing.
"""


#: When a bind fires. `RELEASE` exists because one BMS switch needs telling
#: what to do when you let go -- `SimSelectMRMOverride` on the way down and
#: `SimDeselectOverride` on the way up -- and that is one binding with two
#: halves rather than two modes of the same button. Two of the family's 63
#: BMS bindings use it and nothing else ever has.
PRESS, RELEASE = 'press', 'release'

EDGES = (PRESS, RELEASE)


class Bind:
    """One action on one button, and when it fires.

    This is what `Need.bindings` holds, and the reason it is a record and
    not a bare id. A payload used to be whatever a game felt like -- a BMS
    callback, a War Thunder `(air, heli)` pair, an X4 `(kind, id)` per
    context -- so the core carried it blindly and had to hand it back to
    the game to turn into words. A `Bind` names an action the catalogue
    knows, so the core answers for itself.

    What used to travel as a per-context tuple is simply several binds on
    one button now. Where the context is a property of the action the id
    says so and `Action.mode` carries it; where it is a property of the
    BINDING -- MSFS choosing which of its two files this goes into -- it
    rides here instead.
    """

    __slots__ = ('action', 'edge', 'mode')

    def __init__(self, action, edge=PRESS, mode=None):
        if edge not in EDGES:
            # Refused here rather than discovered in the air: a typo would
            # otherwise be written into a game's config unremarked.
            raise ValueError(f'{edge!r} is not one of {EDGES}')
        #: the id of an `Action`, not the Action itself -- a layout outlives
        #: the catalogue it was planned against, and a harvest after a game
        #: patch may no longer have the record.
        self.action = action
        self.edge = edge
        #: which of the game's buckets this binding goes to, when the
        #: action itself cannot say. Four of the six read the context off
        #: the id -- War Thunder's `_HELICOPTER`, X4's `MAP_`/`FP_`,
        #: Elite's `Buggy` -- so they leave it None and `Action.mode`
        #: carries it. MSFS cannot: its aeroplane/helicopter/global split
        #: is which FILE a binding is written into, chosen by whoever
        #: wrote it, and no rule over the name will find it.
        self.mode = mode

    def named(self, catalogue):
        """What to call this on a screen. `catalogue` is `by_id`'s dict.

        Falls back to the id, because an id somebody bound and a harvest
        later lost still has to draw a row.
        """
        a = catalogue.get(self.action)
        return a.name if a is not None else self.action

    def __repr__(self):
        return (f'<Bind {self.action}>' if self.edge == PRESS
                else f'<Bind {self.action} on {self.edge}>')

    def __eq__(self, other):
        return (isinstance(other, Bind) and self.action == other.action
                and self.edge == other.edge and self.mode == other.mode)

    def __hash__(self):
        return hash((self.action, self.edge, self.mode))


class Action:
    """One thing a game can be told to do."""

    __slots__ = ('id', 'name', 'kind', 'category', 'mode', 'rank')

    def __init__(self, id, name=None, kind='button',
                 category=None, mode=None, rank=0):
        self.id = id
        #: falls back to the id, which is what X4 and Elite compute anyway
        #: and what War Thunder already degrades to on a thin cache.
        self.name = name or id
        self.kind = kind
        self.category = category
        self.mode = mode
        self.rank = rank

    def __repr__(self):
        return f'<Action {self.id} {self.kind}>'

    def __eq__(self, other):
        return isinstance(other, Action) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


def grouped(actions):
    """[(category, [Action])] -- a catalogue in the order a screen wants it.

    Sorted by category with the unnamed one last, and by rank inside each,
    so the most-bound come first where a game counts and the order is at
    least stable where it does not. A game with no categories yields one
    unnamed group, which a screen draws without a heading rather than
    inventing one.
    """
    groups = {}
    for a in actions:
        groups.setdefault(a.category, []).append(a)
    return [(c, sorted(groups[c], key=lambda a: (-a.rank, a.id)))
            for c in sorted(groups, key=lambda c: (c is None, c or ''))]


def by_id(actions):
    return {a.id: a for a in actions}

"""One shape for a game action, whatever the game calls it.

Six harvests write six shapes. X4 keeps `{kind: [id]}`, Elite a list of
functions, Falcon BMS a full record per callback, MSFS `{action:
[contexts]}`, War Thunder `{ID: [en, pl]}`, DCS a tree per aircraft. Only
the envelope is shared.

This is the shape they translate into. It carries what all six already
know. It carries nothing they would have to invent.

    id        the game's own identifier      INPUT_STATE_FP_USE
    name      human-readable                 "Use (on foot)"
    kind      'button' | 'axis'
    category  the game's own grouping        optional
    mode      which context it answers in    optional

`category` and `mode` are optional on purpose. Four of the six ship no
categories, so a reader copes with an absent one anyway. A derived one
puts a guess where the next reader finds a fact.

Each game's `catalogue()` does the translating, because how a cache is
laid out is a fact about that game. The core owns the shape. The game owns
the reading. A harvest that writes this shape directly leaves its
`catalogue()` a loop.
"""


#: When a bind fires. `RELEASE` exists for one Falcon BMS switch:
#: `SimSelectMRMOverride` fires on the way down and `SimDeselectOverride`
#: on the way up. That is one binding with two halves, not two modes of
#: one button. Two of the 63 BMS bindings use it.
PRESS, RELEASE = 'press', 'release'

EDGES = (PRESS, RELEASE)


class Bind:
    """One action on one button, and when it fires.

    This is what `Need.bindings` holds. It is a record rather than a bare
    id so that the core can answer for itself: a `Bind` names an action
    the catalogue knows, and the core turns it into words without asking
    the game.

    A context that is a property of the ACTION rides on `Action.mode`,
    because the id says it. A context that is a property of the BINDING
    rides here. MSFS chooses which of its two files a binding goes into,
    and that is the second case.
    """

    __slots__ = ('action', 'edge', 'mode', 'role', 'button', 'reason')

    def __init__(self, action, edge=PRESS, mode=None):
        if edge not in EDGES:
            # Refused here. A typo otherwise reaches a game's
            # configuration file and nothing remarks on it.
            raise ValueError(f'{edge!r} is not an edge. These are: '
                             + ', '.join(EDGES) + '.')
        #: the id of an `Action`, not the Action. A layout outlives the
        #: catalogue it was planned against, and a harvest taken after a
        #: game patch can lack the record.
        self.action = action
        self.edge = edge
        #: which of the game's buckets this binding goes to, where the
        #: action cannot say. Four of the six read the context off the id:
        #: War Thunder's `_HELICOPTER`, X4's `MAP_` and `FP_`, Elite's
        #: `Buggy`. Those leave this None and `Action.mode` carries it.
        #: MSFS cannot. Its aeroplane, helicopter and global split is
        #: which FILE a binding is written into, and whoever wrote the
        #: binding chose that. No rule over the name will find it.
        self.mode = mode
        #: Where a run put it, and its account of why. Empty until a run
        #: does. A run WORKS these out, so `dump_binds` leaves them out
        #: and the next run starts from the judgements.
        self.role = None
        self.button = None
        self.reason = None

    def placed_on(self, role, button, reason=None):
        """Say where this bind ended up. Returns it, to build in place."""
        self.role, self.button, self.reason = role, button, reason
        return self

    def named(self, catalogue):
        """What to call this on a screen. `catalogue` is `by_id`'s dict.

        It falls back to the id. An id somebody bound and a later harvest
        lost still has to draw a row.
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

    __slots__ = ('id', 'name', 'kind', 'category', 'mode')

    def __init__(self, id, name=None, kind='button',
                 category=None, mode=None):
        self.id = id
        #: It falls back to the id. X4 and Elite compute the name anyway,
        #: and War Thunder degrades to the id on a thin cache.
        self.name = name or id
        self.kind = kind
        self.category = category
        self.mode = mode

    def __repr__(self):
        return f'<Action {self.id} {self.kind}>'

    def __eq__(self, other):
        return isinstance(other, Action) and self.id == other.id

    def __hash__(self):
        return hash(self.id)


def dump_binds(binds):
    """[Bind] -> [dict]. A press with nothing else to say is one key.

    `edge` and `mode` are left out at their defaults. Five of the six
    games never set either, and `{"action": "ID_GEAR"}` is a slot somebody
    can read.
    """
    out = []
    for b in binds:
        row = {'action': b.action}
        if b.edge != PRESS:
            row['edge'] = b.edge
        if b.mode is not None:
            row['mode'] = b.mode
        out.append(row)
    return out


def read_binds(rows):
    """[dict] -> [Bind], in the order written. The order is which button."""
    return [Bind(r['action'], r.get('edge', PRESS), r.get('mode'))
            for r in rows]


def dump(actions):
    """[Action] -> [dict], the rows a harvest writes down.

    The record is written on the way IN, where the game's own format is
    being read anyway. Six `catalogue()` methods translate into this
    record, so translating on the way OUT of the cache means six places
    free to drift.

    Only what the game said. A field at its default is left out: MSFS
    ships 3111 actions and four of the six games have no categories, so
    writing them is thousands of lines carrying the word `null`. A reader
    copes with an absent key anyway.

    `kind` is the exception and is always written. `button` and `axis` are
    a real fork. They decide which half of a game's configuration a
    binding goes into.
    """
    out = []
    for a in actions:
        row = {'id': a.id, 'kind': a.kind}
        if a.name != a.id:
            row['name'] = a.name
        if a.category is not None:
            row['category'] = a.category
        if a.mode is not None:
            row['mode'] = a.mode
        out.append(row)
    return out


def read(rows):
    """[dict] -> [Action], in the order they were written.

    Every field but the id has a default. A working copy whose cache
    predates a field therefore gives a usable record, not a `KeyError`
    that names nothing. The cache is regenerated rather than migrated,
    because it is derived from the installed game. The run that finds a
    stale one still has to be able to say so.
    """
    return [Action(r['id'], r.get('name'), r.get('kind', 'button'),
                   r.get('category'), r.get('mode'))
            for r in rows]


def grouped(actions):
    """[(category, [Action])] -- a catalogue in the order a screen wants.

    Sorted by category, with the unnamed category last, and by id inside
    each category. A game with no categories gives one unnamed group. A
    screen draws that group without a heading.
    """
    groups = {}
    for a in actions:
        groups.setdefault(a.category, []).append(a)
    return [(c, sorted(groups[c], key=lambda a: a.id))
            for c in sorted(groups, key=lambda c: (c is None, c or ''))]


def by_id(actions):
    return {a.id: a for a in actions}

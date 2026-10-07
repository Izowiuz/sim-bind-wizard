"""One way of laying a game out, written down instead of repeated per action.

A need says what a function IS and how you use it: held, rapid, found by feel,
in which band. It says nothing about where you want it, and it should not --
`stick` is not a property of firing a gun, it is a property of how you like
your desk. That belonged in 76 identical hand-written fields, and an opinion
written 76 times is an opinion you cannot change.

An overlay says it once:

    [[want]]
    suits  = "fire"
    device = "stick"

Every key that is not something an overlay may SET is a condition on the need,
and all of them must hold. So the rule above is read "for every need whose
family is `fire`, ask for the stick", and a rule naming `what` applies to one
need by name -- which is what `overlays/by-hand.toml` is, today's wishes
carried over unchanged so that nothing is lost on the way to rules.

The other half is the one thing a per-need file could not say at all:

    [[pair]]
    rule  = "reachable together"
    one   = { modifier = true }
    other = { shift = true }

Two needs, and a claim about the controls they land on rather than about
either one of them. Until this existed every control was scored alone, so a
modifier could land where your thumb already was and the layer it shifted
could land under the same thumb -- each placement perfect, the pair useless.

The rule vocabulary is closed and checked when the file loads, the way the
device map checks its own words: a rule nobody implements is a mistake in the
file, and a reader that skipped it would lay the desk out as though you had
asked for nothing.
"""

import os
import tomllib

from core import needs as corneeds


HERE = os.path.dirname(os.path.abspath(__file__))

#: Where overlays live: beside `core`, not inside it. They are yours, like the
#: desks in the device map's `profiles/` -- a desk says what your hardware is,
#: an overlay says what you like doing with it.
WHERE = os.path.join(os.path.dirname(HERE), 'overlays')

#: What a `[[want]]` may set on a need. Everything else in the table is a
#: condition, which is why this list exists rather than a `when`/`then` split:
#: a rule reads as one sentence, and the only thing you have to know to read
#: it is which half of the words are the answer.
SETS = corneeds.WISHES

#: Which of them name a word the device map owns, and which constant says
#: what that word may be. Checked when the file loads, so `finger = "thump"`
#: is an error rather than a wish that silently never matches anything.
#: Nothing is invented here: the map has held these since long before an
#: overlay existed, and a desk's capture already answers in them.
FROM_THE_MAP = {'device': 'ROLES_ON_A_DESK', 'finger': 'FINGERS',
                'level': 'LEVELS'}

#: What a `[[want]]` may ask ABOUT a need -- its description, and nothing
#: derived from a run. `bindings`, `push` and `on` are left out on purpose:
#: they are lists, and a condition on a list is the expression language this
#: format refuses. `modifier` is left out for a sharper reason: it is a wish,
#: and a word that both asked and answered would make `modifier = true` a
#: rule that only fires on needs that already said so.
ASKS = ('what', 'shape', 'urgency', 'suits', 'category') + corneeds.TOLD

#: The one condition that is not about a need: which game the rule is for.
#: An overlay is general, and a rule naming `what` is not -- two games can
#: both have a function called `Gear` and want different things of it, and
#: MSFS's landing gear took Falcon's pin to a keyboard button exactly that
#: way. Checked when the file loads rather than per need: the planner knows
#: which game it is, so what reaches the allocator is already this game's.
SCOPE = 'game'


class Bad(SystemExit):
    """The file says something the reader does not know.

    Always a fault in the file. An overlay is the only place that says where
    you want things, so a word quietly skipped lays the desk out as though you
    had not asked -- which looks exactly like the planner ignoring you.
    """


def _reachable_together(one, other):
    """Can a hand work both of these without letting go of either?

    Different hands, always. Otherwise there has to be one position the hand
    takes from which both are reached, and by DIFFERENT fingers -- two things
    under one thumb are two things you do one after the other.

    `part` and not `level`, and the map says why: EXTENDED is not a posture of
    its own, so a thumb at HOME and a pinky reaching are the same hand in the
    same place doing two things. Comparing the raw level called that pair
    incompatible, which is the one case the rule exists for.

    This is `device-map-v2.md` §4, and it is the first thing in this tool that
    reads a spot's `hand`, `finger` and `part` rather than only how far away
    it is.
    """
    for a in one.access:
        for b in other.access:
            if a.hand and b.hand and a.hand != b.hand:
                return True
            if (a.part == b.part and a.finger and b.finger
                    and a.finger != b.finger):
                return True
    return False


#: The claims an overlay may make about two controls at once.
PAIRS = {'reachable together': _reachable_together}


def _matches(need, rule):
    """Does this need answer every condition the rule names?"""
    return all(getattr(need, key, None) == want
               for key, want in rule.items() if key in ASKS)


class Overlay:
    """A name, and what it asks for."""

    def __init__(self, name, says, wants=(), pairs=(), called=''):
        self.name = name
        #: The file's own stem, which is what `--overlay` and the menu
        #: say. Kept because `name` is the display name out of the file
        #: and the two differ -- `f-18.toml` calls itself `F/A-18C`. The
        #: menu used to re-read every overlay to work this out, so one
        #: unreadable file in the directory took the review down on a
        #: keypress.
        self.called = called
        self.says = says
        self.wants = list(wants)
        self.pairs = list(pairs)

    def apply(self, needs):
        """Set what the rules ask for. Returns how many needs were touched.

        Every wish is taken off first, so laying this overlay on is
        REPLACING whatever was on before rather than adding to it. One
        overlay per process hid the difference; a menu that switches
        between them does not.

        Later rules win, so a file may state the broad wish first and the
        exception after it, which is the order you would say them in.
        """
        corneeds.forget_wishes(needs)
        touched = set()
        for n, need in enumerate(needs):
            for rule in self.wants:
                if not _matches(need, rule):
                    continue
                for key in SETS:
                    if key in rule:
                        setattr(need, key, rule[key])
                        touched.add(n)
        return len(touched)

    def partners(self, needs):
        """[(need, need, rule name)] -- every pair the file's rules bind.

        Both halves of a `[[pair]]` are conditions over needs, so one rule
        can bind several pairs: a modifier and each of the four needs living
        on its layer.
        """
        out = []
        for rule in self.pairs:
            left = [x for x in needs if _matches(x, rule['one'])]
            right = [x for x in needs if _matches(x, rule['other'])]
            for a in left:
                for b in right:
                    if a is not b:
                        out.append((a, b, rule['rule']))
        return out

    def kept(self, layout):
        """(kept, broken, [what broke]) -- how much of this got honoured.

        The answer to "is this overlay doing anything". A template is a
        lean rather than a law, so some of it loses to reach and to what
        is already taken -- and without a count the only way to know how
        much was to read the whole layout and remember the file.

        Counted per WORD, not per need: a want asking for a thumb at HOME
        is two claims about where a thing goes, and honouring one of them
        is half an answer rather than a whole one.
        """
        kept, broken, lost = 0, 0, []
        for placed in layout.placed:
            need = placed.need
            for word in corneeds.PLACED_BY:
                want = getattr(need, word, None)
                if not want:
                    continue
                got = corneeds.PLACE[word](placed.ctrl)
                if not got:
                    continue
                if got == want:
                    kept += 1
                else:
                    broken += 1
                    lost.append((need.what, word, want, got))
        return kept, broken, lost

    def bound(self, needs):
        """`partners`, with each rule as the test itself.

        What the allocator wants: it asks the question per candidate
        control, in the hot loop, and handing it the callable means
        nothing down there has to keep the overlay around to look a name
        up in.
        """
        self.apply(needs)
        return [(a, b, PAIRS[rule]) for a, b, rule in self.partners(needs)]

    def __repr__(self):
        return (f'<Overlay {self.name!r} {len(self.wants)} wants '
                f'{len(self.pairs)} pairs>')


def _mine(rows, game):
    """The rows that are for this game: the unscoped ones, and its own."""
    return [r for r in rows if SCOPE not in r or r[SCOPE] == game]


def _in_the_map(rule, where):
    """Every map word this rule uses, against the map's own list.

    Not at import, and not a list of our own: `core.devmap` finds the map,
    and the words have been constants in it since before there were
    overlays. A desk's capture already answers in them, so an overlay that
    agrees with the map needs nothing added to either.
    """
    from core import devmap
    devicemap = devmap.load()
    for word, says in FROM_THE_MAP.items():
        want = rule.get(word)
        known = getattr(devicemap, says)
        if want is not None and want not in known:
            # The map spells "the whole hand" as the empty string, and an
            # empty wish here means no wish at all -- so that one is not
            # askable, and listing it as `''` would read as a typo.
            said = ', '.join(repr(k) for k in known if k)
            raise Bad(f'{where}: {word} = {want!r} is not one the map says. '
                      f'There are: {said}')


def read(path, game=None):
    """An overlay off disk, or `Bad` saying which line to fix.

    `game` drops every rule written for a different one, so the overlay
    handed to a planner asks only for things that game has.
    """
    with open(path, 'rb') as f:
        got = tomllib.load(f)
    name = got.get('name') or os.path.splitext(os.path.basename(path))[0]
    wants = _mine(got.get('want', []), game)
    for rule in wants:
        unknown = sorted(set(rule) - set(SETS) - set(ASKS) - {SCOPE})
        if unknown:
            raise Bad(f'{os.path.basename(path)}: a want names '
                      f'{", ".join(unknown)}, which is neither something to '
                      f'ask for ({", ".join(SETS)}) nor something to ask '
                      f'about ({", ".join(ASKS)})')
        if not any(key in rule for key in SETS):
            raise Bad(f'{os.path.basename(path)}: a want asks for nothing -- '
                      f'it names only {", ".join(sorted(rule))}')
        _in_the_map(rule, os.path.basename(path))
    pairs = _mine(got.get('pair', []), game)
    for rule in pairs:
        if rule.get('rule') not in PAIRS:
            raise Bad(f'{os.path.basename(path)}: no rule called '
                      f'{rule.get("rule")!r}. There are: '
                      f'{", ".join(sorted(PAIRS))}')
        for half in ('one', 'other'):
            if not rule.get(half):
                raise Bad(f'{os.path.basename(path)}: the '
                          f'{rule["rule"]!r} rule has no {half!r} side')
            unknown = sorted(set(rule[half]) - set(ASKS))
            if unknown:
                raise Bad(f'{os.path.basename(path)}: the {half} side of '
                          f'{rule["rule"]!r} names {", ".join(unknown)}, '
                          f'which is not something to ask about')
    return Overlay(name, got.get('says', ''), wants, pairs,
                   called=os.path.splitext(os.path.basename(path))[0])


def named(name, game=None):
    """The overlay called `name`, from `overlays/`, scoped to one game."""
    path = os.path.join(WHERE, f'{name}.toml')
    if not os.path.exists(path):
        there = ', '.join(names()) or 'none'
        raise Bad(f'no overlay called {name!r}. There are: {there}')
    return read(path, game)


def names():
    """What is in `overlays/`, for a message or a menu."""
    if not os.path.isdir(WHERE):
        return []
    return sorted(f[:-5] for f in os.listdir(WHERE) if f.endswith('.toml'))

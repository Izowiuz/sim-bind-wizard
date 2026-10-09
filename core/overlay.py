"""One way of laying a game out, written once instead of once per action.

A need says what a function IS and how you use it: held, rapid, found by
feel, in which band. It says nothing about where you want it. `stick` is
not a property of firing a gun. It is a property of how you like your desk.

An overlay says it once:

    [[want]]
    suits  = "fire"
    device = "stick"

A key an overlay may SET is an answer. Every other key is a condition on
the need, and all the conditions have to hold. So read the rule above as
"for every need whose family is `fire`, ask for the stick". A rule that
names `what` applies to one need by name, and `overlays/by-hand.toml` is
a file of those.

The other half is the thing a per-need file cannot say at all:

    [[pair]]
    rule  = "reachable together"
    one   = { modifier = true }
    other = { shift = true }

That is two needs, and a claim about the controls they land on rather than
about either need. Without it every control is scored alone: a modifier
lands where your thumb already is, and the layer it shifts lands under the
same thumb. Each placement is perfect and the pair is useless.

The rule vocabulary is closed and it is checked when the file loads. The
device map checks its own words the same way. A rule nothing implements is
a mistake in the file, and a reader that skipped it would lay the desk out
as though you had asked for nothing.
"""

import os
import tomllib

from core import needs as corneeds


HERE = os.path.dirname(os.path.abspath(__file__))

#: Where overlays live: beside `core`, not inside it. They are yours, like
#: the desks in the device map's `profiles/`. A desk says what your hardware
#: is. An overlay says what you like doing with it.
WHERE = os.path.join(os.path.dirname(HERE), 'overlays')

#: What a `[[want]]` may set on a need. Every other key in the table is a
#: condition. This list exists in place of a `when` and `then` split, so a
#: rule reads as one sentence. To read it you need to know which of its
#: words are the answer.
SETS = corneeds.WISHES

#: Which of them name a word the device map owns, and which constant holds
#: the words it may be. Checked when the file loads, so `finger = "thump"`
#: is an error. Unchecked it is a wish that matches nothing and says
#: nothing. Nothing is invented here: the map holds these words and a
#: desk's capture answers in them.
FROM_THE_MAP = {'device': 'ROLES_ON_A_DESK', 'finger': 'FINGERS',
                'level': 'LEVELS'}

#: What a `[[want]]` may ask ABOUT a need. That is the need's description
#: and nothing a run derived.
#:
#: `bindings`, `push` and `on` are left out on purpose. They are lists, and
#: a condition on a list is the expression language this format refuses.
#:
#: `modifier` is left out for another reason. It is a wish. A word that
#: both asks and answers makes `modifier = true` a rule that fires only on
#: the needs that already say so.
ASKS = ('what', 'shape', 'urgency', 'suits', 'category') + corneeds.TOLD

#: The one condition that is not about a need: which game the rule is for.
#: An overlay is general. A rule that names `what` is not. Two games can
#: both have a function called `Gear` and want different things of it, and
#: MSFS's landing gear took Falcon BMS's pin to a keyboard button that way.
#:
#: Checked when the file loads, not per need. The planner knows which game
#: it is, so what reaches the allocator is already this game's.
SCOPE = 'game'


class Bad(SystemExit):
    """The file says something the reader does not know.

    This is always a fault in the file. An overlay is the only place that
    says where you want things. A word skipped in silence lays the desk out
    as though you had not asked, and that looks like the planner ignoring
    you.
    """


def _reachable_together(one, other):
    """Can a hand work both of these without letting go of either?

    Two different hands always can. Otherwise the hand needs one position
    it reaches both from, and it has to reach them with DIFFERENT fingers.
    Two things under one thumb are two things you do one after the other.

    This compares `part` and not `level`. EXTENDED is not a posture of its
    own, so a thumb at HOME and a pinky reaching are one hand in one place
    doing two things. The raw level calls that pair incompatible, and that
    pair is the case the rule exists for.

    This reads a spot's `hand`, `finger` and `part` rather than how far away
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
        #: The file's own stem. That is what `--overlay` and the menu
        #: say. `name` is the display name out of the file, and the two
        #: differ: `f-18.toml` calls itself `F/A-18C`. Both are kept here,
        #: so the menu does not re-read every overlay to work one out.
        self.called = called
        self.says = says
        self.wants = list(wants)
        self.pairs = list(pairs)

    def apply(self, needs):
        """Set what the rules ask for. Returns how many needs it touched.

        Every wish comes off first. Laying an overlay on REPLACES what was
        on before. It does not add to it.

        Later rules win, so a file may state the broad wish first and the
        exception after it. That is the order you say them in.

        What the GAME asked for stands. A wish and an ask are the same
        field, such as `device` or `finger`, and the game knows the thing.
        DCS reads both off its own command table, and that table is
        written from the aircraft: `Pitch` is the stick because the
        Hornet's pitch is the stick, and the sensor switch is under the
        thumb because the grip has it there.

        A template speaks one JOB at a time, and one word covers more than
        you mean. `suits = "flight"` covers the flight axes AND the
        speedbrake. Overwriting with it put the Hornet's pitch, roll and
        rudder on the throttle, where no axis answers them, and it moved
        five more commands to the wrong hand.

        So the template is a lean. It places what the game said nothing
        about, and it leans on the rest at +15 against `device_right`'s
        +40. This holds for every wish, not for `device` alone.
        """
        corneeds.forget_wishes(needs)
        touched = set()
        for n, need in enumerate(needs):
            for rule in self.wants:
                if not _matches(need, rule):
                    continue
                for key in SETS:
                    if key not in rule or (need.ask or {}).get(key):
                        continue
                    setattr(need, key, rule[key])
                    touched.add(n)
        return len(touched)

    def partners(self, needs):
        """[(need, need, rule name)] -- every pair the file's rules bind.

        Both halves of a `[[pair]]` are conditions over needs, so one rule
        binds several pairs: a modifier, and each of the four needs that
        live on its layer.
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
        """(kept, broken, [what broke]) -- how much of this got through.

        This answers "is the overlay doing anything". A template is a lean
        and not a law, so some of it loses to reach and to what is already
        taken. Without a count you read the whole layout and remember the
        file.

        Counted per WORD, not per need. A want that asks for a thumb at
        HOME makes two claims about where a thing goes, and one of them
        honoured is half an answer.
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

        The allocator asks the question once per candidate control, inside
        the hot loop. It gets the callable, so nothing down there keeps the
        overlay around to look a name up in.
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

    Not at import, and not against a list of our own. `core.devmap` finds
    the map, and the words are constants in it. A desk's capture answers in
    those words, so an overlay that agrees with the map needs nothing added
    to either side.
    """
    from core import devmap
    devicemap = devmap.load()
    for word, says in FROM_THE_MAP.items():
        want = rule.get(word)
        known = getattr(devicemap, says)
        if want is not None and want not in known:
            # The map spells "the whole hand" as the empty string. An
            # empty wish here means no wish at all, so that word is not
            # askable. Listing it as `''` reads as a typo.
            said = ', '.join(repr(k) for k in known if k)
            raise Bad(f'{where}: {word} = {want!r} is not a word the map '
                      f'says. It says these: {said}.')


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
                      f'{", ".join(unknown)}. That is not something to ask '
                      f'for ({", ".join(SETS)}). It is not something to '
                      f'ask about either ({", ".join(ASKS)}).')
        if not any(key in rule for key in SETS):
            raise Bad(f'{os.path.basename(path)}: a want asks for '
                      f'nothing. It names only '
                      f'{", ".join(sorted(rule))}.')
        _in_the_map(rule, os.path.basename(path))
    pairs = _mine(got.get('pair', []), game)
    for rule in pairs:
        if rule.get('rule') not in PAIRS:
            raise Bad(f'{os.path.basename(path)}: no rule is called '
                      f'{rule.get("rule")!r}. These are: '
                      f'{", ".join(sorted(PAIRS))}.')
        for half in ('one', 'other'):
            if not rule.get(half):
                raise Bad(f'{os.path.basename(path)}: the '
                          f'{rule["rule"]!r} rule has no {half!r} side.')
            unknown = sorted(set(rule[half]) - set(ASKS))
            if unknown:
                raise Bad(f'{os.path.basename(path)}: the {half} side of '
                          f'{rule["rule"]!r} names {", ".join(unknown)}. '
                          'That is not something to ask about.')
    return Overlay(name, got.get('says', ''), wants, pairs,
                   called=os.path.splitext(os.path.basename(path))[0])


def named(name, game=None):
    """The overlay called `name`, from `overlays/`, scoped to one game."""
    path = os.path.join(WHERE, f'{name}.toml')
    if not os.path.exists(path):
        there = ', '.join(names()) or 'none'
        raise Bad(f'No overlay is called {name!r}. These are: {there}.')
    return read(path, game)


def names():
    """What is in `overlays/`, for a message or a menu."""
    if not os.path.isdir(WHERE):
        return []
    return sorted(f[:-5] for f in os.listdir(WHERE) if f.endswith('.toml'))

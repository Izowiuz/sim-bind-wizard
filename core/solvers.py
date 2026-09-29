"""Which need takes which control, once the scoring has said what each is worth.

`allocate` does the hard part: what a control is worth to a need, which
passes run, what a gate refuses outright, what you chose by hand. By the
time a solver is asked, the question is already arithmetic -- here are the
things to place, here is what each may take and what each would be worth,
choose. That is a small enough job to have more than one answer for, and
the answers differ in exactly one way: whether a choice can be undone.

They were not selectable, and that is the bug this is the fix for. The
model was used when `ortools` imported and the list-walk when it did not,
silently, with nothing said either way -- so `./bind x4 sheet` under a
python with ortools and the same command under one without produced two
different kneeboards for the same desk, 77 lines apart, and neither
mentioned the other existed.

A solver is a class so that adding one is adding a file's worth of code
and a line in `SOLVERS`, rather than another branch in `allocate`. The
next one is already described in `device-map-v2.md`: the Hungarian
algorithm, as a fast first answer to hand the model as a hint.
"""

import sys


class Solver:
    """Given what each need may take, choose who gets what.

    `wants` is [(want, {room: points})]: for each thing to place, where it
    may go and what each would be worth. `room` is everything that can
    take one, and each takes at most one.

    `best` returns [(want, room)] -- pairs rather than a mapping, so a
    want that came back twice is visible. As a dict it was not: the second
    quietly replaced the first, and the constraint saying a want takes one
    room could be removed without anything looking different.

    None means this solver could not answer, and the caller falls back.
    """

    #: What `--solver` calls it.
    name = ''
    #: One line, for `--help` and for the screen that explains the run.
    said = ''

    @classmethod
    def why_not(cls) -> str:
        """'' when this can run here, else the reason in one line."""
        return ''

    def best(self, wants, room):
        raise NotImplementedError


class Greedy(Solver):
    """The list in order, each taking the best still free.

    Cannot undo a choice, which is the whole of the difference: an early
    urgent need takes a control a later one needed more, and the passes
    named `relaxed` and `borrowed` are what this does instead of
    backtracking. Always available, needs nothing, and a layout found by
    walking the list is worse than the best one and much better than none.
    """

    name = 'greedy'
    said = 'walk the list, each taking the best still free'

    def best(self, wants, room):
        out, used = [], set()
        for want, may in wants:
            free = {j: s for j, s in may.items() if j not in used}
            if not free:
                continue
            # `-j` says the tie-break out loud. `max` keeps the first of
            # equals, which is the first the dict was BUILT in -- true to
            # the pool order only because the one caller happens to build
            # it that way. A rule that holds by coincidence is one the
            # other solver cannot be held to, and both of them now break
            # a tie towards the earlier control.
            j = max(free, key=lambda j: (free[j], -j))
            used.add(j)
            out.append((want, j))
        return out


class CpSat(Solver):
    """The whole assignment as one model, solved together.

    The judgement is unchanged -- `score()` still says how well a control
    plays a part, and its number is the objective coefficient -- and only
    the search changes. So a difference in the output is a difference
    `Greedy` could not reach, not a difference of opinion.
    """

    name = 'cp-sat'
    said = 'the whole assignment as one model (needs ortools)'

    #: Placing a need at all beats improving one already placed. A need
    #: left unplaced is a thing you cannot do in the aircraft; a need on a
    #: slightly worse control is a stretch. The gap has to be wider than
    #: any score.
    PLACED = 10_000

    def __init__(self, seconds=10):
        self.seconds = seconds

    @classmethod
    def why_not(cls):
        try:
            from ortools.sat.python import cp_model      # noqa: F401
        except ImportError:
            return 'ortools is not installed for this python'
        return ''

    def best(self, wants, room):
        """Points are integers because the solver wants them so; `score()`
        is already whole numbers, and rounding one that was not would
        change the ranking rather than the arithmetic."""
        from ortools.sat.python import cp_model
        room = list(room)
        model = cp_model.CpModel()
        pick = {}
        for n, (_want, may) in enumerate(wants):
            for where in may:
                pick[n, where] = model.new_bool_var(f'{n}@{where}')
        for n, (_want, may) in enumerate(wants):
            if may:
                model.add_at_most_one(pick[n, w] for w in may)
        for where in room:
            mine = [pick[n, where] for n, (_w, may) in enumerate(wants)
                    if where in may]
            if mine:
                model.add_at_most_one(mine)
        # Scaled, so that the same sum can carry a tie-break underneath
        # it. Without one the model has no preference between equally
        # good answers -- and most of a layout is equally good answers,
        # because a dozen thumb buttons are worth exactly the same to a
        # binding asking for a button. So every change re-rolled every
        # tie: moving ONE binding by hand moved 21 of X4's 32, and the
        # twenty were not consequences, they were noise.
        #
        # `- where` under the scale breaks a tie towards the earlier
        # control in the pool, which is what walking the list does
        # already: `max` over a dict built in pool order keeps the first.
        # So the two solvers now agree about ties and disagree only where
        # the model can actually do better.
        #
        # `big` is wider than every index in the model added together, so
        # the tie-break can never reach into a real difference of one
        # point.
        big = len(pick) * max(room, default=0) + 1
        model.maximize(sum(((self.PLACED + points) * big - where)
                           * pick[n, where]
                           for n, (_want, may) in enumerate(wants)
                           for where, points in may.items()))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.seconds
        # One worker, and a fixed seed. Eight workers race, and whichever
        # reaches an optimum first is the one answered with -- so the SAME
        # needs on the SAME desk came back differently run to run. Not by a
        # better layout: the ties. Most of a layout is ties, because a dozen
        # thumb buttons are worth exactly the same to a need that asks for a
        # button, and the solver has no reason to prefer one. Three of the six
        # games rebound 51 lines between two runs that differed in nothing.
        #
        # That is the muscle memory this tool exists to keep, and it also
        # makes every before-and-after comparison worthless -- a change cannot
        # be told from the weather. These models are tens of needs against
        # tens of controls and solve in milliseconds, so the parallel search
        # was buying nothing: timed over the three largest games, one worker
        # and eight are the same 0.3s, which is the interpreter starting.
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = 0
        got = solver.solve(model)
        if got not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        if got != cp_model.OPTIMAL:
            print('!! the solver ran out of time and answered with the best'
                  ' it had; the layout is good rather than best',
                  file=sys.stderr)
        return [(want, where)
                for n, (want, may) in enumerate(wants)
                for where in may if solver.value(pick[n, where])]


#: Every solver there is, best first. `best()` walks this, so the order is
#: which one a run gets when nobody named one.
SOLVERS = (CpSat, Greedy)

#: The one every desk can run, whatever is installed. Never `why_not`.
FALLBACK = Greedy


def named(name):
    """The class `--solver NAME` means.

    Raises rather than answering None. Its one caller has already had the
    name checked by argparse against `choices()`, so None there is not a
    state to handle -- and a signature that admits it makes every caller
    write a branch for something that cannot happen.
    """
    for one in SOLVERS:
        if one.name == name:
            return one
    raise ValueError(f'no solver called {name!r}; there is '
                     + ', '.join(one.name for one in SOLVERS))


def best():
    """The best solver this python can actually run.

    Greedy is last in `SOLVERS` and needs nothing, so this always answers.
    """
    for one in SOLVERS:
        if not one.why_not():
            return one()
    return FALLBACK()


def choices():
    """[(name, said, why_not)] for `--help` and for the screen."""
    return [(one.name, one.said, one.why_not()) for one in SOLVERS]

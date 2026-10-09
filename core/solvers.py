"""Which need takes which control, once the scoring says what each is worth.

`allocate` does the judgement. It says what a control is worth to a need,
which passes run, what a gate refuses, and what you chose by hand. By the
time a solver is asked, the question is arithmetic: here are the things to
place, here is what each may take and what each is worth, choose.

The solvers differ in one way. One can undo a choice. The other cannot.

`--solver` names one, and every run prints the name it used. Without that
flag the program takes the first solver that runs here.

A solver is a class, so another one is a file's worth of code and a line in
`SOLVERS`. It is not another branch in `allocate`.
"""

import sys


class Solver:
    """Given what each need may take, choose who gets what.

    `wants` is [(want, {room: points})]. For each thing to place it gives
    where that thing may go and what each place is worth. `room` is
    everything that can take one. Each room takes one thing at most.

    `best` returns [(want, room)]. Pairs, not a mapping: a want that comes
    back twice is visible in a list. In a dict the second one replaces the
    first, and the constraint that a want takes one room can then be
    removed with nothing looking different.

    None means this solver could not answer. The caller then falls back.
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
    """The list in order, each need taking the best control still free.

    This cannot undo a choice. That is the whole difference: an early
    urgent need takes a control a later need wanted more. The `relaxed`
    and `shared` passes are what this does in place of backtracking.

    It needs nothing and it always runs. A layout found by walking the
    list is worse than the best layout and much better than none.
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
            # equals, which is the first key the dict was built with. That
            # follows the pool order only because the one caller builds it
            # that way. Both solvers break a tie towards the earlier
            # control, and this is where one of them says so.
            j = max(free, key=lambda j: (free[j], -j))
            used.add(j)
            out.append((want, j))
        return out


class CpSat(Solver):
    """The whole assignment as one model, solved together.

    The judgement is the same one. `score()` says how well a control plays
    a part, and its number is the objective coefficient. Only the search
    changes. A difference in the output is therefore a difference `Greedy`
    cannot reach, not a difference of opinion.
    """

    name = 'cp-sat'
    said = 'the whole assignment as one model (needs ortools)'

    #: Placing a need beats improving a need already placed. An unplaced
    #: need is a thing you cannot do in the aircraft. A need on a slightly
    #: worse control is a stretch. So the gap is wider than any score.
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
        """The solver takes integers. `score()` returns whole numbers, so
        nothing is rounded here. Rounding a fraction would change the
        ranking rather than the arithmetic."""
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
        # The sum is scaled, so that it carries a tie-break underneath
        # it. Without a tie-break the model has no preference between two
        # equally good answers. Most of a layout is equally good answers,
        # because a dozen thumb buttons are worth the same to a need that
        # asks for a button. Every change then re-rolls every tie:
        # moving ONE binding by hand moved 21 of X4's 32 bindings, and
        # the twenty were noise.
        #
        # `- where` breaks a tie towards the earlier control in the pool.
        # That is what walking the list does already, because `max` over a
        # dict built in pool order keeps the first key. The two solvers
        # agree about ties and differ only where the model does better.
        #
        # `big` is wider than every index in the model added together, so
        # the tie-break cannot reach into a real difference of one point.
        big = len(pick) * max(room, default=0) + 1
        model.maximize(sum(((self.PLACED + points) * big - where)
                           * pick[n, where]
                           for n, (_want, may) in enumerate(wants)
                           for where, points in may.items()))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.seconds
        # One worker and a fixed seed. Eight workers race each other, and
        # the one that reaches an optimum first is the one answered with.
        # The SAME needs on the SAME desk then come back differently from
        # run to run. The difference is the ties, not a better layout.
        # Measured: three of the six games rebound 51 lines between two
        # runs that differed in nothing.
        #
        # Those lines are the muscle memory this program exists to keep.
        # They also make a before-and-after comparison worthless, because
        # a change cannot be told from the weather.
        #
        # The parallel search buys nothing here. These models are tens of
        # needs against tens of controls and solve in milliseconds. Timed
        # over the three largest games, one worker and eight workers both
        # take 0.3s, which is the interpreter starting.
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = 0
        got = solver.solve(model)
        if got not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        if got != cp_model.OPTIMAL:
            print('!! the solver ran out of time. It answered with the '
                  'best layout it had. That layout is good, not best.',
                  file=sys.stderr)
        return [(want, where)
                for n, (want, may) in enumerate(wants)
                for where in may if solver.value(pick[n, where])]


#: Every solver there is, best first. `best()` walks this list, so the
#: order decides which solver a run gets when nobody names one.
SOLVERS = (CpSat, Greedy)

#: The solver every desk can run, whatever is installed. It never answers
#: `why_not`.
FALLBACK = Greedy


def named(name):
    """The class `--solver NAME` means.

    This raises. It does not answer None. Argparse has already checked the
    name against `choices()`, so None is not a state the caller can reach.
    A signature that admits None makes every caller write a branch for it.
    """
    for one in SOLVERS:
        if one.name == name:
            return one
    raise ValueError(f'No solver is called {name!r}. These are: '
                     + ', '.join(one.name for one in SOLVERS) + '.')


def best():
    """The best solver this python can run.

    `Greedy` is last in `SOLVERS` and needs nothing, so this answers.
    """
    for one in SOLVERS:
        if not one.why_not():
            return one()
    return FALLBACK()


def choices():
    """[(name, said, why_not)] for `--help` and for the screen."""
    return [(one.name, one.said, one.why_not()) for one in SOLVERS]

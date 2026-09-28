"""Which control takes which need, decided all at once.

`allocate` walks the needs in urgency order and gives each the best control
still free. That cannot undo a choice: an early urgent need takes a control
a later one needed more, and the passes named `relaxed` and `borrowed` are
what greedy does instead of backtracking.

Here the whole assignment is one model. The judgement is unchanged --
`score()` still says how well a control plays a part, and its number is the
objective coefficient -- and only the search changes. So a difference in the
output is a difference greedy could not reach, not a difference of opinion.

Optional. `ortools` is the one dependency outside the standard library in
this family, and a clone without it falls back to the greedy allocator
rather than failing: a layout found by walking the list is worse than the
best one and much better than none.
"""

import sys

#: Placing a need at all beats improving one already placed. A need left
#: unplaced is a thing you cannot do in the aircraft; a need on a slightly
#: worse control is a stretch. The gap has to be wider than any score.
PLACED = 10_000


def have_it():
    """Whether the solver is installed."""
    try:
        from ortools.sat.python import cp_model      # noqa: F401
    except ImportError:
        return False
    return True


def best(wants, room, seconds=10):
    """[(want, room)] -- the assignment worth most, or None if unsolved.

    Pairs rather than a mapping, so a want that came back twice is
    visible. As a dict it was not: the second one quietly replaced the
    first, and the constraint saying a want takes one room could be
    removed without anything looking different.

    `wants` is [(want, {room: points})]: for each thing to place, what it
    may go on and what each is worth. `room` is everything that can take
    one, and each takes at most one.

    Points are integers because the solver wants them so; `score()` is
    already whole numbers, and rounding one that was not would change the
    ranking rather than the arithmetic.
    """
    from ortools.sat.python import cp_model
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
    model.maximize(sum((PLACED + points) * pick[n, where]
                       for n, (_want, may) in enumerate(wants)
                       for where, points in may.items()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_workers = 8
    got = solver.solve(model)
    if got not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    if got != cp_model.OPTIMAL:
        print('!! the solver ran out of time and answered with the best it'
              ' had; the layout is good rather than best', file=sys.stderr)
    return [(want, where)
            for n, (want, may) in enumerate(wants)
            for where in may if solver.value(pick[n, where])]

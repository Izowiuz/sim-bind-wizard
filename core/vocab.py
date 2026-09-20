"""Load what a harvest produced, without the planner caring whether it is
cached on disk or reparsed on the spot.

Three adapters had a near-identical `_built()` that opened a JSON file and
exited if it was missing. X4 has no such file at all, because reparsing four
46 KB XML files costs nothing where War Thunder has to unpack zstd archives and
BMS a 100 KB key file plus twenty-two vendor profiles. Both are right; the
difference should not reach `plan.py`.

    ACTIONS = vocab.load(HERE, 'wt-actions.json', key='actions')
    ACTIONS = vocab.load(HERE, None, build=harvest.vocabulary)

The output of a harvest is derived from the installed game, not source, so it
belongs in `.gitignore`.
"""

import json
import os


class Missing(SystemExit):
    """There is no cache, and no `build` to make one on the spot.

    A fact about this machine -- nobody has run the harvest here -- and not
    about the code. The distinction is the whole reason this is a class:
    `tests/test_contract.py` skips on this and fails on `Stale`, where before
    both arrived as the same bare `SystemExit` and a contract violation was
    indistinguishable from a clone nobody had harvested on.

    It subclasses `SystemExit` so that every `except SystemExit` already
    written against this module keeps working, and so an uncaught one still
    prints its message and exits 1 exactly as `sys.exit` did.
    """


class Stale(SystemExit):
    """A cache is there, and it is not the shape the planner asked for.

    Always a fault: either someone's working copy predates a change to the
    harvest, or a harvest and a planner disagree about what they call a
    section. Both are worth stopping for, which is why this is not `Missing`.

    It used to surface as a bare `KeyError` from the subscript below, which
    named the key and nothing else -- not the file, not the game, and not what
    to do about it.
    """


def _game(directory):
    """Which game a cache belongs to, for the message.

    The directory is always `games/<game>/`, and `<game>` is the word `bind`
    dispatches on, so the reader gets a command they can paste rather than a
    path they have to translate.
    """
    return os.path.basename(os.path.normpath(directory)) or '<game>'


def load(directory, filename, key=None, build=None):
    """A harvest's output: from the cache if there is one, else rebuilt.

    `build` is a zero-argument callable that reads the game directly. Give it
    for a game cheap enough to reparse; leave it out and a missing cache is an
    error telling you to run the harvest.
    """
    game = _game(directory)
    path = os.path.join(directory, filename) if filename else None
    if path and os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            # A harvest interrupted part-way leaves a truncated file behind,
            # and the next run reads it rather than the game.
            raise Stale(f'{filename} will not parse: {e}\n'
                        f'Run ./bind {game} harvest') from e
        if key is None:
            return data
        if not isinstance(data, dict) or key not in data:
            # Named, not listed: a cache with no envelope has its whole
            # vocabulary at the top level, and printing three thousand keys
            # buries the one sentence that says what to do.
            if not isinstance(data, dict):
                held = f'a {type(data).__name__}'
            elif len(data) > 6:
                held = (', '.join(sorted(data)[:6])
                        + f', and {len(data) - 6} more')
            else:
                held = ', '.join(sorted(data))
            raise Stale(f'{filename} has no "{key}" section -- it holds '
                        f'{held}.\nThe cache and the planner disagree about '
                        f'its shape.\nRun ./bind {game} harvest')
        return data[key]
    if build is not None:
        # `key` is applied only if the built data happens to carry it: a cache
        # wraps its sections in an envelope and a live `build()` return does
        # not, so the same call has to yield the same shape either way.
        data = build()
        return data[key] if key and isinstance(data, dict) and key in data \
            else data
    raise Missing(f'{filename} is missing -- it is built from the installed '
                  f'game, not kept in the repo.\nRun ./bind {game} harvest')


def save(directory, filename, **sections):
    """Write a harvest's output, and say what went where.

    Every harvest printed its own variation of this line; one wording means a
    reader who has seen one has seen them all.
    """
    path = os.path.join(directory, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sections, f, ensure_ascii=False, indent=0)
    sizes = ', '.join(f'{len(v)} {k}' for k, v in sections.items()
                      if hasattr(v, '__len__'))
    print(f'wrote {filename}: {sizes}')
    return path

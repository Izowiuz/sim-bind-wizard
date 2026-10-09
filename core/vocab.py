"""Load what a harvest produced.

A planner does not care whether the vocabulary sits in a cache on disk or
is reparsed on the spot. Each game is right about its own cost. Reparsing
X4's four 46 KB XML files costs nothing. War Thunder has to unpack zstd
archives and Falcon BMS a 100 KB key file, so those cache.

    ACTIONS = vocab.load(HERE, 'warthunder-actions.json', key='actions')
    ACTIONS = vocab.load(HERE, None, build=harvest.vocabulary)

A harvest's output is derived from the installed game. It is not source,
so it belongs in `.gitignore`.
"""

import json
import os


class Missing(SystemExit):
    """There is no cache, and no `build` to make one on the spot.

    This is a fact about the machine: nobody has run the harvest here. It
    is not a fault in the code. `tests/test_contract.py` skips on this and
    fails on `Stale`, so the two need separate classes.

    It subclasses `SystemExit`, so every `except SystemExit` written
    against this module keeps working. An uncaught one prints its message
    and exits 1.
    """


class Stale(SystemExit):
    """A cache is there, and its shape is not the one the planner asked for.

    This is always a fault. Either a working copy predates a change to the
    harvest, or a harvest and a planner disagree about what they call a
    section. Both are worth a stop, so this is not `Missing`.

    The message names the file, the game and the fix. A bare `KeyError`
    from the subscript below names the key only.
    """


def _game(directory):
    """Which game a cache belongs to, for the message.

    The directory is always `games/<game>/`. `<game>` is the word
    `bind-wizard.py` dispatches on, so the reader gets a command to paste
    rather than a path to translate.
    """
    return os.path.basename(os.path.normpath(directory)) or '<game>'


def load(directory, filename, key=None, build=None):
    """A harvest's output, from the cache or rebuilt.

    `build` is a callable that takes no argument and reads the game
    directly. Give it for a game cheap enough to reparse. Leave it out and
    a missing cache is an error that tells you to run the harvest.
    """
    game = _game(directory)
    path = os.path.join(directory, filename) if filename else None
    if path and os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            # A harvest stopped part way leaves a truncated file behind.
            # The next run reads that file instead of the game.
            raise Stale(f'{filename} does not parse: {e}\n'
                        f'Run ./bind-wizard.py {game} harvest.') from e
        if key is None:
            return data
        if not isinstance(data, dict) or key not in data:
            # Name what the file holds. Do not list it. A cache with no
            # envelope holds its whole vocabulary at the top level, and
            # three thousand keys bury the sentence that says what to do.
            if not isinstance(data, dict):
                held = f'a {type(data).__name__}'
            elif len(data) > 6:
                held = (', '.join(sorted(data)[:6])
                        + f', and {len(data) - 6} more')
            else:
                held = ', '.join(sorted(data))
            raise Stale(f'{filename} has no "{key}" section. It holds '
                        f'{held}.\nThe cache and the planner do not agree '
                        f'about its shape.\nRun ./bind-wizard.py {game} '
                        'harvest.')
        return data[key]
    if build is not None:
        # Apply `key` only where the built data carries it. A cache wraps
        # its sections in an envelope. A live `build()` return does not.
        # The same call has to give the same shape either way.
        data = build()
        return data[key] if key and isinstance(data, dict) and key in data \
            else data
    raise Missing(f'{filename} is missing. It is built from the installed '
                  'game. The repo does not keep it.\n'
                  f'Run ./bind-wizard.py {game} harvest.')


def _written(value, depth, inline):
    """`value` as JSON text, one thing per line down to `inline` deep.

    The depth is said rather than left to `json.dump`. `indent=0` writes
    every bracket on a line of its own, so one need with a five-way hat
    takes thirty-five lines, and thirty of those are punctuation around
    five identifiers. `indent=None` puts a 2500-row cache on one line.

    A row of a cache is one line, so `inline=1`. A need is a line per
    judgement with its identifiers and directions on that line, so
    `inline=2`. You read and edit the judgements. You skip the
    identifiers.
    """
    if depth > inline or not isinstance(value, (dict, list)) or not value:
        return json.dumps(value, ensure_ascii=False)
    lead, inner = '  ' * depth, '  ' * (depth + 1)
    if isinstance(value, dict):
        body = ',\n'.join(
            f'{inner}{json.dumps(k, ensure_ascii=False)}: '
            + _written(v, depth + 1, inline)
            for k, v in value.items())
        return '{\n' + body + f'\n{lead}}}'
    body = ',\n'.join(inner + _written(v, depth + 1, inline)
                       for v in value)
    return '[\n' + body + f'\n{lead}]'


def save(directory, filename, inline=1, **sections):
    """Write a harvest's output. Returns (path, what went where).

    The second half is returned, not printed. A print here reaches every
    caller, and one caller is the review screen, where stdout is the
    inside of the curses window being drawn. The line then lands mid
    status, glued to whatever is already there:

        10 assigned by youwrote x4-binds.json: 32 needs

    The caller with a terminal prints it.
    """
    path = os.path.join(directory, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_written(sections, 0, inline) + '\n')
    sizes = ', '.join(f'{len(v)} {k}' for k, v in sections.items()
                      if hasattr(v, '__len__'))
    return path, f'wrote {filename}: {sizes}'

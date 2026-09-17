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
import sys


def load(directory, filename, key=None, build=None):
    """A harvest's output: from the cache if there is one, else rebuilt.

    `build` is a zero-argument callable that reads the game directly. Give it
    for a game cheap enough to reparse; leave it out and a missing cache is an
    error telling you to run the harvest.
    """
    path = os.path.join(directory, filename) if filename else None
    if path and os.path.exists(path):
        data = json.load(open(path, encoding='utf-8'))
        return data[key] if key else data
    if build is not None:
        data = build()
        return data[key] if key and isinstance(data, dict) and key in data \
            else data
    sys.exit(f'{filename} is missing -- it is built from the installed game, '
             'not kept in the repo.\nRun ./harvest.py --json')


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

"""Keep a copy of every game file before a writer touches it, in one place.

Copies go into this repository, one folder per run. Nothing is left behind
in the game's own directories.

    backups/<game>/<stamp>/MANIFEST         stored name -> where it came from
    backups/<game>/<stamp>/<file>...

A backup that lives in the directory the game reads is a file the game can
find. MSFS finds its profiles by globbing `inputprofile_*`, and a sibling
copy matched that glob. A second run then bound into its own backup and
backed that file up again. The `.bak.X.bak.Y` files are the proof, and
`find_profiles` still carries the filter that works around them.

`backups/` is in `.gitignore`. Point it somewhere else, such as a cloud
folder or an external disk, with `--backup-dir` or `SIM_BIND_BACKUPS`.
Every writer takes the flag, because this module defines it.

The MANIFEST is what makes a restore generic. It names where each file
came from, so any run of any game can go back where it came from.

Nothing here prunes. A backup you deleted to save 40 KB is not a backup.
"""

import datetime
import os
import shutil
import sys

#: The repository root. `backups/` sits beside `core/` and `games/`.
#: SIM_BIND_BACKUPS overrides it, for copies on another disk.
DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backups')

MANIFEST = 'MANIFEST'


def stamp():
    """`20260918-213012`, the format every writer uses."""
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def root(into=None):
    """Where backups go: the argument, then the environment, then the repo."""
    return os.path.expanduser(into or os.environ.get('SIM_BIND_BACKUPS')
                              or DEFAULT)


def dir_for(game, into=None):
    """This game's folder. It is created when something is saved into it."""
    return os.path.join(root(into), game)


def add_argument(parser, game):
    """The `--backup-dir` flag, worded once.

    Games differ in what they write and when they write it. They do not
    differ in what the flag means. A reader who has seen one writer's
    `--help` has seen them all.
    """
    return parser.add_argument(
        '--backup-dir', metavar='DIR', default=None,
        help='Where to copy the files this replaces, before it replaces '
             f'them. The default is '
             f'{os.path.join("<repo>", "backups", game)}. SIM_BIND_BACKUPS '
             'moves it.')


def _unique(paths):
    """Stored names for these sources, disambiguated where they collide.

    War Thunder writes several files all called `machine.blk`, one per
    account directory. A flattened full path names every file after its
    absolute location and makes the folder unreadable. So a name grows a
    parent directory only when it has to, and it keeps growing until it is
    unique.
    """
    names = {}
    for p in paths:
        parts = os.path.abspath(p).split(os.sep)
        names[p] = parts[-1:]
    while True:
        seen = {}
        for p, parts in names.items():
            seen.setdefault(os.sep.join(parts), []).append(p)
        clash = [ps for ps in seen.values() if len(ps) > 1]
        if not clash:
            break
        grew = False
        for ps in clash:
            for p in ps:
                full = os.path.abspath(p).split(os.sep)
                if len(names[p]) < len(full):
                    names[p] = full[-(len(names[p]) + 1):]
                    grew = True
        if not grew:                    # two identical paths. Nothing to do.
            break
    return {p: '_'.join(n) for p, n in names.items()}


def save(game, *paths, into=None, move=False, when=None):
    """Copy these files into a run folder, or move them.

    Returns `(directory, [(stored name, original path)])`. A path that
    does not exist is skipped, because a writer creating a file for the
    first time has nothing to back up. No folder is made where that leaves
    nothing.

    Pass the same `when` to group several calls into one run. A file
    already stored under that stamp is then left as it is. A run folder
    holds what things looked like BEFORE the run: DCS's `--reseed`
    rewrites one results file once per aircraft, and a second copy
    overwrites the only copy of the state anybody wants back.

    `move=True` is for a file the writer needs gone rather than replaced.
    Falcon BMS's `axismapping.dat` has to be out of the way before the
    game rebuilds it from the defaults.
    """
    live = [p for p in paths if os.path.exists(p)]
    if not live:
        return None, []

    dest = os.path.join(dir_for(game, into), when or stamp())
    os.makedirs(dest, exist_ok=True)
    names = _unique(live)
    saved = []
    for path in live:
        name = names[path]
        target = os.path.join(dest, name)
        if os.path.exists(target):
            if not move:
                continue                # an earlier call in this run kept it
            # The file still has to leave. The copy already there is the
            # older one, so this one goes beside it.
            n = 1
            while os.path.exists(f'{target}.{n}'):
                n += 1
            name, target = f'{name}.{n}', f'{target}.{n}'
        (shutil.move if move else shutil.copy2)(path, target)
        saved.append((name, os.path.abspath(path)))

    if not saved:
        return dest, []
    with open(os.path.join(dest, MANIFEST), 'a', encoding='utf-8') as f:
        for name, path in saved:
            f.write(f'{name}\t{path}\n')
    return dest, saved


def runs(game, into=None):
    """`[(stamp, directory, [(stored name, original path)])]`, oldest first.

    A folder without a MANIFEST is not one of ours. It is left out rather
    than guessed at, because a restore needs to know where a file goes.
    """
    base = dir_for(game, into)
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name)
        manifest = os.path.join(path, MANIFEST)
        if not os.path.isfile(manifest):
            continue
        files = []
        for line in open(manifest, encoding='utf-8'):
            stored, _, original = line.rstrip('\n').partition('\t')
            if original:
                files.append((stored, original))
        out.append((name, path, files))
    return out


def restore(game, which=None, into=None):
    """Put a run's files back where they came from. Returns what it wrote.

    `which` is a stamp or a prefix of one. The newest run is the default,
    because the thing you want undone is nearly always the thing you just
    did.
    """
    have = runs(game, into)
    if not have:
        sys.exit(f'There are no backups for {game} under '
                 f'{dir_for(game, into)}.')
    if which:
        have = [r for r in have if r[0].startswith(which)]
        if not have:
            sys.exit(f'{game} has no backup that matches {which!r}.')
    _when, path, files = have[-1]

    done = []
    for stored, original in files:
        src = os.path.join(path, stored)
        if not os.path.exists(src):
            print(f'  The backup does not have {stored}.',
                  file=sys.stderr)
            continue
        os.makedirs(os.path.dirname(original), exist_ok=True)
        shutil.copy2(src, original)
        done.append(original)
    return path, done

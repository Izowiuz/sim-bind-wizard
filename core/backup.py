"""Keep a copy of every game file before a writer touches it, in one place.

Six writers had six answers. X4 and MSFS copied into
`~/OneDrive/backups/save-backup/<GAME>/<stamp>/` -- one person's cloud folder,
hard-coded as the default -- *and* left a `.bak.<stamp>` beside the original.
Falcon BMS, War Thunder and DCS only left the sibling. Elite wrote its preset
over whatever was there with no copy at all.

The sibling copies are the part that actually went wrong. MSFS finds its
profiles by globbing `inputprofile_*`, which matched the backups too, so a
second run bound into its own backup and backed THAT up again; the
`.bak.X.bak.Y` files were the proof, and `find_profiles` still carries the
regex that works around it. A backup that lives in the directory the game
reads is a file the game can find.

So: copies go into the repo by default, one folder per run, and nothing is
left behind in the game's own directories.

    backups/<game>/<stamp>/MANIFEST         stored name -> where it came from
    backups/<game>/<stamp>/<file>...

`backups/` is gitignored. Point it somewhere else -- a cloud folder, an
external disk -- with `--backup-dir` or `SIM_BIND_BACKUPS`, which every writer
takes because the flag is defined here.

The MANIFEST is what makes a restore generic. War Thunder's `--restore` used
to sort sibling filenames and copy the last one back, which only worked
because the copy sat next to the original; with a manifest any run of any game
can be put back where it came from.

Nothing here prunes. A backup you deleted to save 40 KB is not a backup.
"""

import datetime
import os
import shutil
import sys

#: The repo root: `backups/` sits beside `core/` and `games/`. Override with
#: SIM_BIND_BACKUPS, for someone who wants them on a different disk entirely.
DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backups')

MANIFEST = 'MANIFEST'


def stamp():
    """`20260918-213012` -- the same format every writer already used."""
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def root(into=None):
    """Where backups go: the argument, then the environment, then the repo."""
    return os.path.expanduser(into or os.environ.get('SIM_BIND_BACKUPS')
                              or DEFAULT)


def dir_for(game, into=None):
    """This game's folder. Not created until something is saved into it."""
    return os.path.join(root(into), game)


def add_argument(parser, game):
    """The `--backup-dir` flag, worded once.

    Games differ in what they write and when, but not in what the flag means,
    and a reader who has seen one writer's `--help` has seen them all.
    """
    return parser.add_argument(
        '--backup-dir', metavar='DIR', default=None,
        help='where to copy the files this replaces, before replacing them '
             f'(default {os.path.join("<repo>", "backups", game)}; '
             'SIM_BIND_BACKUPS moves it)')


def _unique(paths):
    """Stored names for these sources, disambiguated only where they collide.

    War Thunder writes several files all called `machine.blk`, one per account
    directory. Flattening the full path would name every file after its
    absolute location and make the folder unreadable, so a name only grows a
    parent directory when it has to -- and keeps growing until it is unique.
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
        if not grew:                    # two identical paths; nothing to do
            break
    return {p: '_'.join(n) for p, n in names.items()}


def save(game, *paths, into=None, move=False, when=None):
    """Copy (or move) these files into a run folder.

    Returns `(directory, [(stored name, original path)])`. A path that does not
    exist is skipped -- a writer creating a file for the first time has nothing
    to back up -- and if that leaves nothing at all, no folder is made.

    Pass the same `when` to group several calls into one run. A file already
    stored under that stamp is then left as it is, because a run folder holds
    what things looked like BEFORE the run: DCS's `--reseed` rewrites one
    results file once per aircraft, and copying it again on the second
    aircraft overwrote the only copy of the state anybody wanted back.

    `move=True` is for a file the writer needs *gone* rather than replaced:
    BMS's `axismapping.dat` has to be out of the way for the game to rebuild it
    from the defaults, and renaming it in place left the game's config folder
    full of `.dat.<stamp>.bak`.
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
            # It still has to leave, and the copy already there is the older
            # and therefore better one, so this goes beside it.
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

    A folder without a MANIFEST is not one of ours and is left out rather than
    guessed at -- the point of a restore is knowing where a file goes.
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
    """Put a run's files back where they came from. Returns what was written.

    `which` is a stamp, or a prefix of one; the newest run is the default,
    because the thing you want undone is nearly always the thing you just did.
    """
    have = runs(game, into)
    if not have:
        sys.exit(f'no backups for {game} under {dir_for(game, into)}')
    if which:
        have = [r for r in have if r[0].startswith(which)]
        if not have:
            sys.exit(f'{game} has no backup matching {which!r}')
    _when, path, files = have[-1]

    done = []
    for stored, original in files:
        src = os.path.join(path, stored)
        if not os.path.exists(src):
            print(f'  missing from the backup: {stored}', file=sys.stderr)
            continue
        os.makedirs(os.path.dirname(original), exist_ok=True)
        shutil.copy2(src, original)
        done.append(original)
    return path, done

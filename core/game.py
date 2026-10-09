"""Find where a game is installed and where it keeps its settings.

Where a game is, is per-game knowledge. The four installs differ: DCS sits
in a second Steam library, War Thunder is a native Linux build with no
prefix, MSFS keeps its profiles in Steam Cloud, and Falcon BMS installs
inside Falcon 4.0's Proton prefix rather than as a Steam app of its own.

What they share is the three lookups each one needs on the way: which
Steam libraries exist, what is in them, and where an appid's prefix is.
"""

import os
import re
import subprocess

STEAM = os.path.expanduser('~/.local/share/Steam')


def libraries():
    """Every Steam library on this machine, the main one first.

    This reads `libraryfolders.vdf`. A machine can hold more than one
    library, and DCS is on a second disk here.
    """
    out = [STEAM]
    vdf = os.path.join(STEAM, 'steamapps', 'libraryfolders.vdf')
    try:
        txt = open(vdf, encoding='utf-8', errors='replace').read()
    except OSError:
        return out
    for path in re.findall(r'"path"\s+"([^"]+)"', txt):
        if path not in out:
            out.append(path)
    return out


def install_dir(*names):
    """A game's install directory, by its folder name under `common/`.

    Give several names for a game that was renamed between versions. The
    first name that exists wins.
    """
    for lib in libraries():
        for name in names:
            path = os.path.join(lib, 'steamapps', 'common', name)
            if os.path.isdir(path):
                return path
    return None


def prefix(appid):
    """A game's Proton prefix, or None for a native build.

    `compatdata` sits next to the library the game is installed in, so
    this searches every library.
    """
    for lib in libraries():
        path = os.path.join(lib, 'steamapps', 'compatdata', str(appid), 'pfx')
        if os.path.isdir(path):
            return path
    return None


def in_prefix(appid, *parts):
    """A path inside a prefix's C: drive, or None.

    Most of what a wizard wants sits under the Windows user's Documents.
    That is `drive_c/users/steamuser`.
    """
    pfx = prefix(appid)
    if pfx is None:
        return None
    path = os.path.join(pfx, 'drive_c', *parts)
    return path if os.path.exists(path) else None


def _ourselves():
    """Our own pid and every ancestor of it.

    `running()` matches a pattern against whole command lines. Linux
    truncates a process name at 15 characters and `EliteDangerous64.exe`
    is twenty characters long, so a name match is not enough. A command
    line that mentions the game includes our own: `./bind-wizard.py x4
    write` carries `x4`, and a shell running `pgrep -f X4` carries `X4`.

    Measured: `game.running('X4', 'X4.exe')` answered True with no game
    installed and nothing playing, because the calling shell had `X4` in
    its own arguments. Every writer refuses on that answer, so the refusal
    was unconditional for any caller whose command line named the game.
    """
    seen, pid = set(), os.getpid()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            with open(f'/proc/{pid}/stat', encoding='utf-8') as f:
                # The name sits in brackets and can itself contain spaces.
                # Count the fields after it from the last ')'.
                rest = f.read().rpartition(')')[2].split()
            pid = int(rest[1])
        except (OSError, IndexError, ValueError):
            break
    return seen


def running(*patterns):
    """True while the game is up.

    Every writer here refuses to touch a configuration file while the game
    runs. Most of these sims rewrite that file when they exit, and the
    rewrite undoes the work. War Thunder rewrites it. Falcon BMS rewrites
    it. DCS does not, and the rule still holds for it.
    """
    mine = _ourselves()
    for pattern in patterns:
        try:
            got = subprocess.run(['pgrep', '-f', pattern],
                                 capture_output=True, text=True)
        except FileNotFoundError:
            return False
        for line in got.stdout.split():
            try:
                if int(line) not in mine:
                    return True
            except ValueError:
                continue
    return False

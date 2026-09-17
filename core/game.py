"""Find where a game is installed and where it keeps its settings.

Each of the four wizards worked this out for itself, and each got a slightly
different answer: DCS lives in a second Steam library, War Thunder is a native
Linux build with no prefix at all, MSFS keeps its profiles in Steam Cloud,
and Falcon BMS is installed *inside* Falcon 4.0's Proton prefix rather than
being a Steam app of its own.

So the shared part is not "where is the game" -- that is per-game knowledge --
but the three lookups every one of them needed on the way there: which Steam
libraries exist, what is in them, and where a given appid's prefix is.
"""

import glob
import os
import re
import subprocess

STEAM = os.path.expanduser('~/.local/share/Steam')


def libraries():
    """Every Steam library on this machine, main one first.

    Reading `libraryfolders.vdf` rather than assuming one library is not
    fussiness: DCS is on a second disk here, and the head-tracking bridge
    broke for a week because a tool assumed otherwise.
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
    """The install directory of a game, by its folder name under common/.

    Several names may be given for a game that has been renamed between
    versions; the first that exists wins.
    """
    for lib in libraries():
        for name in names:
            path = os.path.join(lib, 'steamapps', 'common', name)
            if os.path.isdir(path):
                return path
    return None


def prefix(appid):
    """A game's Proton prefix, or None for a native build.

    Note `compatdata` lives next to the library the game is installed in, so
    this searches all of them.
    """
    for lib in libraries():
        path = os.path.join(lib, 'steamapps', 'compatdata', str(appid), 'pfx')
        if os.path.isdir(path):
            return path
    return None


def in_prefix(appid, *parts):
    """A path inside a prefix's C: drive, or None.

    Most of what a wizard wants is under the Windows user's Documents, which
    is where `drive_c/users/steamuser` lands.
    """
    pfx = prefix(appid)
    if pfx is None:
        return None
    path = os.path.join(pfx, 'drive_c', *parts)
    return path if os.path.exists(path) else None


def userdata():
    """Steam's per-account userdata directories, which is where Cloud saves
    land -- MSFS keeps its input profiles there rather than in the prefix."""
    return sorted(glob.glob(os.path.join(STEAM, 'userdata', '*')))


def running(*patterns):
    """True while the game is up.

    Every writer in this family refuses to touch a config while the game is
    running, because most of these sims rewrite it on exit and would silently
    undo the work. War Thunder does; Falcon BMS does; DCS does not, but the
    rule is cheaper to keep than to remember exceptions for.
    """
    for pattern in patterns:
        try:
            if subprocess.run(['pgrep', '-f', pattern],
                              capture_output=True, text=True).stdout.strip():
                return True
        except FileNotFoundError:
            return False
    return False

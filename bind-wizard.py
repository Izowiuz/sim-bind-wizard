#!/usr/bin/env python3
"""bind-wizard.py - run one game's binding tools

SYNOPSIS
    ./bind-wizard.py
    ./bind-wizard.py GAME [VERB] [ARG...]

DESCRIPTION
    With no arguments, list the games. Then pick one from the list.
    VERB defaults to `tui`. Anything after it goes to the script.

    With more than one desk in the device map and none named, this
    asks which. Say it outright with `--desk NAME` or
    SIM_DEVICE_PROFILE.

    `--overlay NAME` picks a template from `overlays/`. A template says
    which place on the hand each family of functions belongs in, and
    which control carries the shift. `--overlay f-18` lays X4 out like
    a Hornet. The layout says how much of the template got through.
    `--overlay none` asks for nothing.

VERBS
    harvest   read the game's files, write the vocabulary cache
    plan      what it would bind, and where
    why       the same, plus the evidence for each control
    free      controls left unbound
    sheet     write KNEEBOARD.md and kneeboard.html
    tui       review the layout, save what you keep
    write     the whole layout, into the game

GAMES
    dcs  elite  msfs  x4

EXAMPLES
    ./bind-wizard.py x4 why --desk IzoDesk
    ./bind-wizard.py x4 sheet
    ./bind-wizard.py dcs plan -a su-25T

NOTES
    Every game answers all seven verbs.
    Close the game before you write.
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

#: verb -> (script, fixed arguments).
#:
#: One table for every game. Every game answers the same interface, so the
#: seven verbs mean the same seven things everywhere.
#:
#: The flags are written out here. Asking an adapter for them means
#: constructing one, and a constructor reads the cache and the device map.
#: `./bind-wizard.py` with no arguments stays instant on a clone that has
#: harvested nothing.
#:
#: `tests/test_contract.py` checks every row against the adapter's own
#: parser.
VERB_FLAGS = {
    'harvest': ('harvest.py', ('--json',)),
    'plan':    ('plan.py', ()),
    'why':     ('plan.py', ('--why',)),
    'free':    ('plan.py', ('--free',)),
    'sheet':   ('plan.py', ('--sheet', '--html')),
    'tui':     ('plan.py', ('--tui',)),
    'write':   ('plan.py', ('--write',)),
}

#: game -> the other names it answers to. This is per game: `ed` is what
#: Elite is called out loud, and nothing derives that from the folder name.
#:
#: A game in this table has a folder. An alias for a folder nobody has
#: written is a name the table answers to and the filesystem does not.
ALIASES = {}


def discover():
    """{game: title} -- every game under games/, titled by its adapter.

    The title is the `title` declaration, read off the CLASS. Importing a
    planner defines classes and reads nothing, so this costs one import. It
    touches no cache and no device map.

    `adapter.games()` decides what a game is. It answers an adapter, not a
    directory: `games/falconbms` and `games/warthunder` hold a needs list
    and a binds file with no planner beside them. A name here is a name you
    can type.
    """
    root = os.path.join(HERE, 'games')
    out = {}
    if not os.path.isdir(root):
        # A state, not a fault. The core is the thing that works, so a
        # checkout with no game in it lists nothing and starts.
        return out
    sys.path.insert(0, HERE)
    from core import adapter                                # noqa: E402
    for name in adapter.games():
        title = name
        try:
            found = adapter.adapters(name)
            if found:
                title = found[0].title
        except (OSError, SystemExit, ImportError, AttributeError):
            # A planner that will not import on this machine keeps its row,
            # under the word you type for it. The row is how you find out
            # the game is there.
            pass
        out[name] = title
    return out


TITLES = discover()
GAMES = {g: {'alias': ALIASES.get(g, ()), 'title': t}
         for g, t in TITLES.items()}


def resolve(name):
    """A game folder from a name or an alias."""
    if name in GAMES:
        return name
    for game, spec in GAMES.items():
        if name in spec.get('alias', ()):
            return game
    return None


def table():
    """The games, one per line, and the aliases under them."""
    for line in game_items():
        print(line)
    aliases = [(a, g) for g, s in sorted(GAMES.items())
               for a in s.get('alias', ())]
    if aliases:
        print('aliases: ' + ', '.join(f'{a} = {g}' for a, g in aliases))


def which_desk(rest):
    """(desk, where its file was read from), either of which may be None.

    Four conditions have to hold before this asks. The map cannot settle
    it alone. The command line does not say. The environment does not say.
    Somebody is at a terminal to answer. Otherwise this keeps quiet, and
    the planner's own message names the ways of saying it.

    One desk on file is no question. None at all is one: the files may sit
    somewhere this does not look yet.
    """
    if any(a == '--desk' or a.startswith('--desk=') for a in rest):
        return None, None
    if os.environ.get('SIM_DEVICE_PROFILE'):
        return None, None
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return None, None
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        dm = __import__('core.devmap', fromlist=['devmap']).load()
    except SystemExit:
        return None, None               # the planner says this better
    where = dm.PROFILES
    while True:
        rigs = [r for r in dm.load_profiles()]
        if len(rigs) == 1 and where == dm.PROFILES:
            return None, None
        desk, said = pick_desk(rigs, where)
        if desk is not None or said is None or said == where:
            return desk, said
        where = said
        dm.PROFILES = said


#: The last row of the desk list. It is not a desk. It is a place to look
#: for them.
ELSEWHERE = 'read desks from somewhere else…'


def said_path(where):
    """A directory as somebody says it, not as the OS spells it."""
    home = os.path.expanduser('~')
    return ('~' + where[len(home):]) if where.startswith(home + os.sep) \
        else where


def desk_items(rigs):
    """One line per desk: its name and what is on it.

    The names are yours, so a list of names alone does not say which room
    you are in. The devices say it. `nothing on it` is a desk you made and
    have not filled.
    """
    wide = max((len(r.name) for r in rigs), default=0)
    return [f'{r.name:<{wide}}   '
            + (', '.join(d.get('role') or d['slug'] for d in r.devices)
               or 'nothing on it')
            for r in rigs]


def pick_desk(rigs, where):
    """Put the desks on the screen the rest of this repository uses.

    Returns `(name, directory)`. The name is the desk to work at. The
    directory is where the desks were read from. Either may be None.

    The directory is shown and it is changeable. A desk is a fact about a
    room, so somebody with two rooms, or with these files kept somewhere
    synced, says where they are without an edit here.
    """
    import curses
    from core import tui as ctui

    def run(scr):
        tui = ctui.setup(scr)
        while True:
            rows = [('plain', t) for t in desk_items(rigs)]
            # A blank line between the desks and the row that is not one.
            # The cursor steps over the blank. `↵ choose` on a blank row
            # means nothing.
            rows += [('plain', ''), ('meta', ELSEWHERE)]
            got = tui.choose('Which desk is this for?', rows,
                             head=[('meta', f'read from {said_path(where)}'),
                                   ('plain', '')],
                             skip=[len(rigs)])
            if got is None:
                return None, None
            if got != len(rows) - 1:
                # A desk, by its index. The blank line is not a desk
                # either, so this tests the index rather than testing for
                # the last row.
                return rigs[got].name, where
            said = tui.ask('Read desks from',
                           ['A directory of .toml desks.'], value=where)
            # RETURN on the path you came in with chooses nothing. It backs
            # out of the question.
            if not said or said == where:
                continue
            if not os.path.isdir(said):
                tui.popup('Nothing there',
                          [('plain', f'{said} is not a directory.')])
                continue
            return None, said

    try:
        return curses.wrapper(run)
    except curses.error:
        # A terminal that cannot draw this. The planner's own message
        # covers it. The catch is narrow on purpose: a blanket catch here
        # swallows a mistake inside `run` and reports it as "no terminal".
        return None, None
    return rigs[got].name if got is not None else None


def game_items():
    """One line per game: the word you type and what it is.

    The word comes first. It is the half you reuse, because every other
    command in this family starts with it.
    """
    wide = max([0] + [len(g) for g in GAMES])
    return [f'{game:<{wide}}   {GAMES[game]["title"]}'
            for game in sorted(GAMES)]


def pick_game():
    """Which game to work on, or None when nobody picked one.

    The screen the desk list uses, asked the same way. The two questions
    come one after the other: which game, then which desk it is for.

    Only at a terminal. Piped, the table is the whole answer. The contract
    suite reads that table, and a screen has nothing to draw on there.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import curses
    from core import tui as ctui

    games = sorted(GAMES)

    def run(scr):
        tui = ctui.setup(scr)
        return tui.choose('Which game?',
                          [('plain', t) for t in game_items()])

    try:
        got = curses.wrapper(run)
    except curses.error:
        # The same narrow catch as `pick_desk`. This is a terminal that
        # cannot draw the screen, not a fault inside `run`.
        return None
    return games[got] if got is not None else None


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        if args:
            print(__doc__)
            return 0
        table()
        picked = pick_game()
        if picked is None:
            return 0
        # On into the dispatch below, as though you had typed it. The verb,
        # the desk and the subprocess are one path.
        args = [picked]

    game = resolve(args[0])
    if game is None:
        print(f'no game called {args[0]!r}. '
              'Try ./bind-wizard.py with no arguments.', file=sys.stderr)
        return 2

    # `tui` with no verb. The screen is the thing you come back to. `plan`
    # is the thing you read once, to see whether the allocator got it
    # right. Every game has a screen, so there is nothing to look up.
    verb = (args[1] if len(args) > 1 and not args[1].startswith('-')
            else 'tui')
    rest = args[2:] if len(args) > 1 and not args[1].startswith('-') \
        else args[1:]

    if verb not in VERB_FLAGS:
        print(f'there is no verb called {verb!r}. '
              'Try ./bind-wizard.py with no arguments.', file=sys.stderr)
        return 2

    # From the one table. Every game answers the same seven verbs, so no
    # game has a row of its own to disagree with it.
    script, fixed = VERB_FLAGS[verb]
    path = os.path.join(HERE, 'games', game, script)
    if not os.path.exists(path):
        print(f'{path} is missing', file=sys.stderr)
        return 2

    desk, where = which_desk(rest)
    env = dict(os.environ)
    if desk:
        env['SIM_DEVICE_PROFILE'] = desk
    if where:
        env['SIM_DEVICE_PROFILES'] = where
    env = env if (desk or where) else None

    cmd = [sys.executable, path, *fixed, *rest]
    print(f'--> games/{game}/{script} '
          + ' '.join([*fixed, *rest]), file=sys.stderr)
    return subprocess.call(cmd, cwd=os.path.join(HERE, 'games', game),
                           env=env)


if __name__ == '__main__':
    sys.exit(main())

"""What the core may assume about a game's adapter, as classes rather than
as a paragraph.

`core.needs.Layout` records what happens when a shape lives in the contract
as prose only: `build()` was in it from the start, its shape was not, and five
adapters drifted into five orders of the same five values. The cure was a
shape in the core. The same thing had happened one layer out -- six writers
reached six signatures, and one of them took `placed=None` and called
`build()` for itself, which is the clause the contract had been asking for
since it was written. This is the same cure, applied to the rest of it.

Three moments do the enforcing, and they are deliberately not one:

    class definition   __init_subclass__ rejects an override that cannot be
                       called the way the base promised, an override of a
                       @final method, and an @override that overrides nothing
    instantiation      abc refuses a subclass with an abstract member left
                       unimplemented, naming every one of them
    pyright            return types, parameter types, and an @override whose
                       name no base defines

Only the third can be absent from a clone, which is why the first covers
arity on its own rather than leaving it to the checker.

What none of them reach: a writer calling `self.build()` behind the interface.
Python has no `private`, so that clause is a test over the compiled function
(`tests/test_contract.py`) rather than a guarantee. The same goes for the
sidecar seam -- a script loaded by path is `Any` to pyright, so nothing is
checked across it.

Why classes at all, when the adapters were modules: a module cannot be
parameterised and an instance can. DCS derives its needs from the aircraft it
was asked about, so `NEEDS` as a module constant could never mean both the
Hornet's and the Su-25T's. Every other adapter was paying a smaller version of
the same price -- threading `--profile`, `--preset` or `--game-dir` down call
chains, and in one case laundering a flag through `os.environ` -- because
there was nowhere to put per-run configuration. `__init__` is that place.
"""

import abc
import argparse
import importlib.machinery
import importlib.util
import inspect
import os
import sys
import time
import typing

from core import actions as cactions
from core import backup
from core import needs as corneeds
from core import sheet as csheet
from core import review as creview
from core import vocab


# ------------------------------------------------------- the override guard

def _func(member):
    """The function inside whatever decorator wraps it, or None.

    A plain class attribute returns None on purpose: `NEEDS = [...]` is how
    five of the six games satisfy an abstract property, and an arity check has
    nothing to say about a list.
    """
    if isinstance(member, (classmethod, staticmethod)):
        return member.__func__
    if isinstance(member, property):
        return member.fget
    return member if inspect.isfunction(member) else None


def _calls(sig):
    """Every way a caller may legally invoke something with this signature.

    Values are all None: this is about arity and keyword names, never about
    types. Types are pyright's half and it is better at them.
    """
    pos = [p for p in sig.parameters.values()
           if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    kw = {p.name: None for p in sig.parameters.values()
          if p.kind is p.KEYWORD_ONLY and p.default is p.empty}
    least = sum(1 for p in pos if p.default is p.empty)
    for n in range(least, len(pos) + 1):
        yield [None] * n, dict(kw)


def _accepts(fn, base):
    """Can `fn` be called every way `base` declares it may be?

    Compatibility, not equality. An override may rename a parameter and may
    add one that has a default, and both are legal -- insisting on an
    identical signature would reject working code and teach people to switch
    the guard off. What it may not do is need an argument the base never
    promised, or refuse one the base did.

    `*args, **kwargs` passes. Nothing can be told from it, and guessing in
    either direction would be worse than admitting that.
    """
    try:
        fsig, bsig = inspect.signature(fn), inspect.signature(base)
    except (TypeError, ValueError):
        return True
    for args, kw in _calls(bsig):
        try:
            fsig.bind(*args, **kw)
        except TypeError:
            return False
    return True


def _inherited(cls, name):
    """What `name` meant before this class redefined it."""
    for parent in cls.__mro__[1:]:
        if name in vars(parent):
            return vars(parent)[name]
    return None


def _guard(cls):
    """Reject a bad override where a compiler would: at definition.

    `abc` checks that a name exists and never that it can be called, so
    `describe(self)` where the base said `describe(self, placement)` gets all
    the way to the call before anything notices -- and in the review screen
    that call is inside a curses loop.
    """
    for name, member in vars(cls).items():
        if name.startswith('__') and name.endswith('__'):
            continue
        fn, base = _func(member), _inherited(cls, name)
        if base is None:
            if fn is not None and getattr(fn, '__override__', False):
                raise TypeError(
                    f'{cls.__name__}.{name} is marked @override but no base '
                    'class defines it -- a typo here is silent otherwise')
            continue
        if getattr(_func(base) or base, '__final__', False):
            raise TypeError(f'{cls.__name__}.{name} overrides a final member')
        basefn = _func(base)
        if fn is not None and basefn is not None and not _accepts(fn, basefn):
            raise TypeError(
                f'{cls.__name__}.{name}{inspect.signature(fn)} cannot be '
                f'called the way {name}{inspect.signature(basefn)} promised')


# --------------------------------------------------------- what a writer says

def from_file(name, path, argv=None):
    """A module read from a file, under `name`, registered in `sys.modules`.

    Six places had these five lines and only three had the guard.
    `spec_from_file_location` answers None for a path Python will not treat
    as a module, and a spec with no loader for one it can see but cannot
    run; without the guard a missing or unreadable file came back as an
    AttributeError on None rather than a sentence naming the file.

    A file with no `.py` has to be handed its loader, which is the only way
    `bind` can be imported at all.

    `argv` swaps `sys.argv` around the execution and swallows the SystemExit
    that a script with its own argument parsing raises on the way past. That
    is what importing a sibling *script* rather than a module costs, and only
    the ones that own a format pay it.
    """
    loader = None
    if not path.endswith('.py'):
        loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_file_location(name, path, loader=loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'{path} cannot be loaded as a module')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    was = sys.argv
    if argv is not None:
        sys.argv = argv
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        if argv is None:
            raise
    finally:
        sys.argv = was
    return mod


class Text:
    """A file's whole new contents, and the encoding to lay it down in.

    The line endings are never translated -- what the writer computed goes out
    verbatim. BMS's key files are latin-1 with CRLF, and writing them with the
    platform default rewrites every line, which makes the backup useless for
    seeing what actually changed.
    """

    def __init__(self, text, encoding='utf-8'):
        self.text = text
        self.encoding = encoding

    def __len__(self):
        return len(self.text)

    def __repr__(self):
        return f'<Text {len(self.text)} chars, {self.encoding}>'


#: What a writer returns: {path: Text or str, or None to move the file aside}.
#: `None` is for a file the game must find *gone* rather than replaced --
#: BMS's `axismapping.dat`, which the game rebuilds from the defaults only if
#: it is missing.
MOVE = None


# ----------------------------------------------------------------- harvest

class Harvest(abc.ABC):
    """in: the game's files.  out: vocabulary and ranking JSON.

    `--json` exists because this created it, and the cache goes through
    `core.vocab.save` because this calls it. Three harvests used to write
    unconditionally with their own `json.dump`, one of them without an
    `encoding`, and two more disagreed about whether `--vocab --json` writes
    anything. None of that is reachable from here.
    """

    #: The game, as `bind` dispatches on it and as the directory is named.
    game: str

    #: filename -> the section names `core.vocab.save` will write under.
    #: Declared rather than passed, so `Adapter.CACHE` can be checked against
    #: it: a harvest and a planner disagreeing about a section name is a fault
    #: that otherwise waits until someone runs the game.
    files: dict

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        _guard(cls)

    @property
    def here(self):
        """The directory this harvest and its cache live in."""
        mod = sys.modules.get(type(self).__module__)
        path = getattr(mod, '__file__', None)
        if not path:
            raise RuntimeError(
                f'{type(self).__name__} is not in sys.modules, so it cannot '
                'find its own directory')
        return os.path.dirname(os.path.abspath(path))

    @abc.abstractmethod
    def read(self, args) -> dict:
        """{filename: {section: data}} -- everything the cache will hold."""

    @abc.abstractmethod
    def summary(self, data) -> list[str]:
        """The lines a bare run prints."""

    def arguments(self, parser) -> None:
        """This harvest's own flags. `--game-dir` belongs here."""

    @typing.final
    def parser(self):
        p = argparse.ArgumentParser(
            description=sys.modules[type(self).__module__].__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument('--json', action='store_true',
                       help='write the cache')
        self.arguments(p)
        return p

    @typing.final
    def main(self, argv=None) -> int:
        """Read, then print, then -- if asked -- write. In that order.

        The order is the point. Elite returned from `--vocab` before `--json`
        was consulted and X4 did not, so the same two flags meant opposite
        things in two adapters.
        """
        args = self.parser().parse_args(argv)
        data = self.read(args)
        for line in self.summary(data):
            print(line)
        if args.json:
            for filename, sections in data.items():
                vocab.save(self.here, filename, **sections)
        return 0


# ----------------------------------------------------------------- adapter

class Adapter(abc.ABC):
    """One game's planner: what the core may assume about it."""

    game: str
    title: str
    subtitle = ''

    #: Where copies of replaced files go. Set in `__init__` from the flag, so
    #: a writer never has to be handed it as an argument.
    backup_dir = None

    #: filename -> the section key `core.vocab.load` should take: None for
    #: a cache with no envelope, or a tuple where one file holds several and
    #: `cache()` is told which.
    CACHE: dict = {}

    #: constructor parameter -> extra flag spellings, for a game whose own
    #: word for something predates the common one.
    ALIASES: dict = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        _guard(cls)

    # ---- what the game knows ------------------------------------------

    @property
    @abc.abstractmethod
    def NEEDS(self) -> list:
        """[Need] -- what a pilot must be able to do, in this game's words.

        Five games satisfy this with a plain class attribute; the literal
        moves one indent and nothing else about it changes. DCS answers with a
        property over a list built in `__init__`, because its needs are a
        function of the aircraft. A property is the honest way to say derived.
        """

    @abc.abstractmethod
    def build(self) -> corneeds.Layout:
        """The whole plan, in the one shape every adapter returns."""

    @abc.abstractmethod
    def catalogue(self) -> list[cactions.Action]:
        """Everything this game can be told to do, in the core's shape.

        The vocabulary a harvest cached, translated once here so that every
        reader above -- a screen, a listing, a sheet -- asks the same
        question of all six games. `NEEDS` is a hand-picked slice of this.
        """


    @abc.abstractmethod
    def describe(self, placement) -> list[tuple[str, str]]:
        """[(part of the control, what it does)], for core.review."""

    @abc.abstractmethod
    def show(self, layout, why: bool = False) -> list[str]:
        """The lines a bare run prints. `--why` annotates them."""

    # ---- optional, with a working default ------------------------------

    def arguments(self, parser) -> None:
        """Flags this game has and the others do not."""

    def unknown(self) -> list[tuple[str, str, str]]:
        """[(what, kind, id)] the game's vocabulary does not contain."""
        return []

    def paths(self, args) -> list[tuple[str, str]]:
        """[(label, path)] for the review screen's map."""
        return []

    def free(self, layout) -> list[str]:
        return [f'  {role:9} {c.label:34} {c.kind:10} {c.reach or ""}'
                for role, c in layout.free]

    def extra(self, args, layout) -> list[str] | None:
        """A verb only this game has. -> lines, or None if none was asked for.

        `main()` is final so that the common verbs mean one thing everywhere,
        which leaves nowhere for `--write-axes`, `--reseed`, `--audit` and
        `--check` to go. This is that place: one hook, dispatched after the
        common verbs and before the default listing, so a game may add to the
        surface without being able to reinterpret any of it.
        """
        return None

    # ---- the shell, which nobody overrides -----------------------------

    @property
    @typing.final
    def here(self):
        """The directory this adapter and its cache live in.

        Read off the module the class was defined in, which means that module
        has to be in `sys.modules` -- a module executed from a path is not,
        unless whoever executed it put it there. `load()` and `sidecar()` do;
        anything else that loads an adapter by hand has to as well, and this
        says so rather than raising KeyError three frames down.
        """
        mod = sys.modules.get(type(self).__module__)
        path = getattr(mod, '__file__', None)
        if not path:
            raise RuntimeError(
                f'{type(self).__name__} was defined in a module that is not '
                f'in sys.modules ({type(self).__module__!r}), so it cannot '
                'find its own directory -- register it under spec.name '
                'before exec_module, the way core.adapter.load does')
        return os.path.dirname(os.path.abspath(path))

    @typing.final
    def cache(self, filename, key=None, build=None):
        """This adapter's cache for `filename`, through `core.vocab`.

        `key` picks one section where `CACHE` names several: BMS reads its
        callbacks and its device table out of the same file.
        """
        want = self.CACHE.get(filename)
        if isinstance(want, tuple):
            if key not in want:
                raise TypeError(f'{filename} holds {want}; asked for {key!r}')
            want = key
        return vocab.load(self.here, filename, key=want, build=build)

    @typing.final
    def sidecar(self, name):
        """A sibling script imported by path, with argv swapped.

        Three adapters carried a copy of these lines because War Thunder's
        `machine.blk`, Elite's `.binds` and DCS's results file are each owned
        by a separate script. Owning a format is a good reason for a second
        script; owning the *verb* is not, and `main()` below is why it no
        longer does.
        """
        return from_file(
            f'{self.game}_{name.replace("-", "_").removesuffix(".py")}',
            os.path.join(self.here, name), argv=[name])

    @typing.final
    def parser(self):
        """The one surface every planner answers.

        Every planner owns `--write` because this adds it. Before, `bind`'s
        dispatch table absorbed the difference, which made a gap in two
        adapters read as a fact about two games.
        """
        p = argparse.ArgumentParser(
            description=sys.modules[type(self).__module__].__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument('--why', action='store_true',
                       help='print why each control was chosen')
        p.add_argument('--free', action='store_true',
                       help='list controls left unbound')
        # `nargs='?'` because two adapters already took a path here and
        # standardising on the poorer of the two spellings would have been a
        # regression dressed as a contract.
        p.add_argument('--sheet', nargs='?', const='', metavar='PATH',
                       help='write KNEEBOARD.md, or to PATH')
        p.add_argument('--html', nargs='?', const='', metavar='PATH',
                       help='write kneeboard.html, or to PATH')
        p.add_argument('--tui', action='store_true',
                       help='review the layout, write what you keep')
        p.add_argument('--write', action='store_true',
                       help='write the whole layout into the game')
        backup.add_argument(p, self.game)
        self.arguments(p)
        return p

    @typing.final
    def main(self, argv=None):
        """Everything that was asked for, in one order.

        X4 returned after `--sheet`, so `--sheet --write` wrote a kneeboard
        and silently did not write the game. War Thunder had the same bug
        between `--sheet` and `--html` and fixed it locally. Asking for two
        things gets two things here.
        """
        args = self.parser().parse_args(argv)

        bad = self.unknown()
        if bad:
            for what, kind, ident in bad:
                print(f'!! {what}: the game has no {kind} called {ident}',
                      file=sys.stderr)
            raise SystemExit(f'the vocabulary disagrees with NEEDS; '
                             f'run ./bind {self.game} harvest')

        layout = self.build()
        asked = False

        # `is not None`, not truthiness: `--sheet` with no path is the
        # empty string, which is falsy and would silently do nothing.
        if args.sheet is not None or args.html is not None:
            self.write_sheets(layout, markdown=args.sheet, html=args.html)
            asked = True
        if args.tui:
            self.review(args)
            return 0
        if args.write:
            for line in self.write_all(layout):
                print(line)
            return 0
        said = self.extra(args, layout)
        if said is not None:
            for line in said:
                print(line)
            return 0
        if args.free:
            for line in self.free(layout):
                print(line)
            return 0
        if asked:
            return 0
        for line in self.show(layout, why=args.why):
            print(line)
        return 0

    # ---- what the two kinds of adapter each answer differently ----------

    @abc.abstractmethod
    def write_sheets(self, layout, markdown=None, html=None) -> list[str]:
        """Write the kneeboard, in whichever forms were asked for."""

    @abc.abstractmethod
    def write_all(self, layout) -> list[str]:
        """Put everything in `layout` into the game. -> lines to print."""

    @typing.final
    def lay_down(self, files, since=None) -> list[str]:
        """Back up, write, and prove nothing else was left behind.

        A writer returns contents and never touches the filesystem, and that
        is what makes two clauses of the contract unbreakable rather than
        merely tested. The copy goes through `core.backup` because this calls
        it -- nothing obliged a writer to before. And a writer cannot leave a
        stray sibling in the game's own directory, because it has no file
        handle to leave one with; four of the six carry a scar from exactly
        that.

        The check still runs, because two writers delegate to a script that
        owns their format and a sloppy conversion could let that script write.
        `since` is read before `write_layout` is called, so a file that
        appeared during it is caught too -- comparing directory listings alone
        would not, since by then the stray is already in the "before".
        """
        dirs = {os.path.dirname(os.path.abspath(p)) for p in files}
        before = {d: set(os.listdir(d)) for d in dirs if os.path.isdir(d)}

        when = backup.stamp()
        replace = [p for p, v in files.items() if v is not MOVE]
        # One `when` for the whole run, so a game that writes two files gets
        # one folder and a restore returns the pair together.
        dest, _kept = backup.save(self.game, *replace, into=self.backup_dir,
                                  when=when)
        gone, moved = backup.save(self.game,
                                  *[p for p, v in files.items() if v is MOVE],
                                  into=self.backup_dir, move=True, when=when)

        out = []
        for path, body in files.items():
            if body is MOVE:
                continue
            body = body if isinstance(body, Text) else Text(body)
            with open(path, 'w', encoding=body.encoding, newline='') as f:
                f.write(body.text)
            out.append(f'wrote {os.path.basename(path)} '
                       f'({len(body.text)} chars)')
        for name, _orig in moved:
            out.append(f'moved away {name}')
        if dest or gone:
            out.append(f'copies in {dest or gone}')

        declared = {os.path.abspath(p) for p in files}
        for d, was in before.items():
            now = set(os.listdir(d))
            strays = {os.path.join(d, n) for n in now - was}
            if since is not None:
                strays |= {os.path.join(d, n) for n in now
                           if os.path.getmtime(os.path.join(d, n)) >= since}
            strays -= declared
            if strays:
                raise RuntimeError(
                    f'{type(self).__name__} left files behind in {d}: '
                    + ', '.join(sorted(os.path.basename(s) for s in strays))
                    + ' -- what a writer replaces goes to core.backup, never '
                      'to a sibling file: the game reads that folder')
        return out

    @abc.abstractmethod
    def review(self, args) -> None:
        """Walk the layout on screen and write what was kept."""


class Planner(Adapter):
    """An adapter whose writer takes the placements it is handed."""

    @abc.abstractmethod
    def sheet(self, layout) -> csheet.Sheet:
        """The kneeboard, in the core's shape."""

    @abc.abstractmethod
    def write_layout(self, layout) -> dict:
        """What the game's files should now contain, for these placements.

        -> {path: Text or str, or MOVE for a file that must be gone}. It
        computes and returns; `lay_down` does the writing. Every one of the
        six already worked out its file's whole new text and then wrote it
        itself, so this takes the second half away rather than asking for
        anything new.

        `layout` is the only thing this is given. Which profile, which
        install, where backups go -- all of it was fixed when the adapter was
        constructed, so there is no second argument through which a writer
        could be handed something other than what the reviewer kept.

        Two writers used to call `build()` for themselves, and the review
        screen -- whose entire job is to write some of a plan and not the
        rest -- could not exist until they stopped. That one is not expressible
        as a signature, so `tests/test_contract.py` reads the compiled
        function for it.

        What this cannot say, in any language: that the text drops a binding
        cut from `NEEDS`. That is a fact about the contents, and only a
        fixture that writes a layout, removes a need and writes again can
        hold it.
        """

    @typing.final
    def write_all(self, layout) -> list[str]:
        since = time.time()
        return self.lay_down(self.write_layout(layout), since=since)

    @typing.final
    def write_sheets(self, layout, markdown=None, html=None) -> list[str]:
        """Each argument is None for "not asked", '' for the default path,
        or a path."""
        sh = self.sheet(layout)
        out = []
        if markdown is not None:
            out.append('wrote %s (%d rows, %d axes)' % sh.markdown(
                markdown or os.path.join(self.here, 'KNEEBOARD.md')))
        if html is not None:
            out.append('wrote %s (%d rows, %d axes)' % sh.html(
                html or os.path.join(self.here, 'kneeboard.html')))
        for line in out:
            print(line)
        return out

    @typing.final
    def review(self, args) -> None:
        """core.review, wired to this adapter.

        Final because the wiring *is* the clause: `write=` is handed the
        layout the screen kept and nothing wider, and it reaches the writer
        through `write_all`, so the review's output is backed up and checked
        for strays on exactly the same path as `--write`.
        """
        creview.run(self.build(), self.title, self.subtitle,
                    describe=self.describe, write=self.write_all,
                    paths=self.paths(args))


class Proposer(Adapter):
    """An adapter that seeds a file a capture wizard confirms.

    DCS cannot be handed a narrowed layout: its writer reads the wizard's
    results file, because a binding somebody confirmed at the stick is better
    evidence than one a planner proposed. That used to be a sentence in
    `bind`'s `GAPS` table. It is a type now.
    """

    @abc.abstractmethod
    def seed(self, layout) -> dict:
        """What the wizard's results file should now contain.

        -> {path: Text or str}, the same shape `Planner.write_layout`
        returns and laid down the same way, so a proposer is under the same
        two clauses as a planner even though nothing narrows its layout.
        """

    @abc.abstractmethod
    def write_game(self) -> dict:
        """-> {path: Text or str}: the game's own config.

        Built from what the wizard confirmed, not from a layout -- which is
        the whole reason this is not a `Planner`. A proposal that nobody has
        walked is a guess, and the file the wizard owns is the record of
        which guesses somebody accepted at the stick.
        """

    @typing.final
    def write_all(self, layout) -> list[str]:
        since = time.time()
        return self.lay_down(self.write_game(), since=since)

    @typing.final
    def write_seed(self, layout) -> list[str]:
        """The proposal into the wizard's file, on the same laid-down path."""
        since = time.time()
        return self.lay_down(self.seed(layout), since=since) + [
            f'seeded -- confirm it with ./bind {self.game} capture']

    @typing.final
    def review(self, args) -> None:
        raise SystemExit(f'its capture wizard already is one -- '
                         f'./bind {self.game} capture')


# ------------------------------------------------------------- the bridge

def _flags(cls):
    """[(flag names, parameter)] for this adapter's constructor.

    The constructor is the declaration of what a run of this game can be
    configured with, so the flags are read off it rather than written out a
    second time and left to drift.
    """
    out = []
    taken = inspect.signature(cls.__init__).parameters
    for name, p in list(taken.items())[1:]:            # [1:] drops self
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        names = ['--' + name.replace('_', '-'),
                 *cls.ALIASES.get(name, ())]
        out.append((names, name))
    return out


def run(cls, argv=None):
    """Construct this adapter from the command line, then hand over to it."""
    boot = argparse.ArgumentParser(add_help=False)
    for names, name in _flags(cls):
        boot.add_argument(*names, dest=name, default=None)
    known, rest = boot.parse_known_args(argv)
    return cls(**{n: getattr(known, n) for _f, n in _flags(cls)}).main(rest)


def games():
    """[game] -- every directory under games/ that holds an adapter.

    From the filesystem, because a game that exists only in a table in `bind`
    is a game the table can be wrong about.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games')
    return sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))
                  and not d.startswith('.'))


def planner(game):
    """Which file in this game's directory defines its adapter.

    `plan.py` in five games and `propose.py` in DCS, whose planner derives
    its needs from a module's own commands and was named for that. Found
    rather than tabulated, for the same reason `games()` reads the
    filesystem: a table is a second place for the truth to be wrong.

    The file is read, not imported, so nothing is executed to answer this.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games', game)
    names = sorted(n for n in os.listdir(root) if n.endswith('.py'))
    for name in ['plan.py'] + [n for n in names if n != 'plan.py']:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            text = f.read()
        if 'adapter.Planner' in text or 'adapter.Proposer' in text:
            return name
    return 'plan.py'


def load(game, script=None):
    """The module for a game's planner, imported the way `bind` runs it.

    `os.chdir` because an adapter resolves its data files against `HERE` and
    `bind` runs it with `cwd=games/<game>`. Nothing is swallowed: after this
    work an import defines classes and reads nothing, so a failure here is a
    failure of the contract rather than a fact about what is installed.
    """
    script = script or planner(game)
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games', game)
    was = os.getcwd()
    try:
        os.chdir(root)
        if root not in sys.path:
            sys.path.insert(0, root)
        return from_file(
            f'{game}_{script.replace("-", "_").removesuffix(".py")}',
            os.path.join(root, script))
    finally:
        os.chdir(was)


def adapters(game, script=None):
    """[class] -- the concrete Adapter subclasses a game's planner defines."""
    mod = load(game, script)
    return [v for v in vars(mod).values()
            if inspect.isclass(v) and issubclass(v, Adapter)
            and not inspect.isabstract(v) and v.__module__ == mod.__name__]


__all__ = ['Harvest', 'Adapter', 'Planner', 'Proposer',
           'Text', 'MOVE', 'run', 'games', 'planner', 'load', 'adapters',
           'from_file']

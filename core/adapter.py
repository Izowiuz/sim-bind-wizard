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
import subprocess
import sys
import time
import tomllib
import typing

from core import actions as cactions
from core import backup
from core import needs as corneeds
from core import overlay as coverlay
from core import solvers as csolvers
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
                    f'{cls.__name__}.{name} is marked @override. No base '
                    'class defines it. A typo here is silent otherwise.')
            continue
        if getattr(_func(base) or base, '__final__', False):
            raise TypeError(
                f'{cls.__name__}.{name} overrides a final member.')
        basefn = _func(base)
        if fn is not None and basefn is not None and not _accepts(fn, basefn):
            raise TypeError(
                f'{cls.__name__}.{name}{inspect.signature(fn)} cannot '
                f'take the arguments that '
                f'{name}{inspect.signature(basefn)} promised.')


# --------------------------------------------------------- what a writer says

def from_file(name, path, argv=None):
    """A module read from a file, under `name`, registered in `sys.modules`.

    Six places had these five lines and only three had the guard.
    `spec_from_file_location` answers None for a path Python will not treat
    as a module, and a spec with no loader for one it can see but cannot
    run; without the guard a missing or unreadable file came back as an
    AttributeError on None rather than a sentence naming the file.

    A file with no `.py` has to be handed its loader, which is the only way
    `bind-wizard.py` can be imported at all.

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
        raise RuntimeError(f'{path} cannot be loaded as a module.')
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
    """in: the game's files.  out: the vocabulary, as JSON.

    `--json` exists because this created it, and the cache goes through
    `core.vocab.save` because this calls it. Three harvests used to write
    unconditionally with their own `json.dump`, one of them without an
    `encoding`, and two more disagreed about whether `--vocab --json` writes
    anything. None of that is reachable from here.
    """

    #: The game, as `bind-wizard.py` dispatches on it and as the directory is
    #: named.
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
                f'{type(self).__name__} is not in sys.modules. It cannot '
                'find its own directory.')
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
                       help='Write the cache.')
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
                _path, said = vocab.save(self.here, filename, **sections)
                print(said)
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

    #: Where this game's description of its functions lives, relative to
    #: its own directory -- which band a thing is in, what shape it wants,
    #: whether you hold it down. Empty for a game that derives its needs
    #: instead: DCS reads them off the aircraft, so there is nothing to
    #: keep.
    #:
    #: Deliberately not in `CACHE`. That names what the harvest wrote, and
    #: a harvest cannot write a judgement.
    NEEDS_FILE: str = ''

    #: Which overlay this game is laid out with, from `overlays/`: which
    #: device a family belongs on, which control carries the shift, which
    #: two things your hand has to work at once. `--overlay` replaces it
    #: for one run and `--overlay none` runs without any, which is the
    #: allocator judging every control on reach and shape alone.
    OVERLAY: str = ''

    #: Where what sits where lives. The answer, not the question: one row
    #: per placed function saying which control took it and who decided.
    #: This used to be the same file as the description above, so one
    #: wrote the question and the answer into one line and a reader could
    #: not tell which half the planner had produced.
    BINDS: str = ''

    #: Which of `CACHE`'s files the catalogue is read out of. Named rather
    #: than guessed from the others: the vocabulary screen puts it on its
    #: top bar, and a plausible wrong filename there is worse than none --
    #: the question it answers is "is this the file I just re-harvested".
    CATALOGUE: str = ''

    #: constructor parameter -> extra flag spellings, for a game whose own
    #: word for something predates the common one.
    ALIASES: dict = {}

    #: constructor parameter -> what `--help` says about it. A flag with
    #: no line is a flag nobody finds.
    SAYS: dict = {}

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

    def says_button(self, role, index) -> str:
        """What this game calls one button of one device, or '' if nothing.

        Falcon says `DX17` and War Thunder a number off its own base; the
        map says 16, and which of the three you need depends on which
        screen of which game you are in front of. Each game worked this
        out for its kneeboard already -- this is that, where the shared
        listings can reach it too.
        """
        return ''

    @typing.final
    def free(self, layout) -> list[str]:
        """What nothing was put on. One shape for six games.

        Three of them answered this question in three layouts -- the same
        four facts in a different order with different brackets round them
        -- because `free` was overridable and two games overrode it rather
        than ask for the one thing the shared one lacked, which was their
        own numbering for a spare button.
        """
        out = [f'{len(layout.free)} controls left free:']
        for role, c in layout.free:
            says = ', '.join(x for x in
                             (self.says_button(role, b)
                              for b in c.bindable_buttons) if x)
            out.append(f'  {role:9} {c.label:34} {c.kind:10} '
                       f'{says:18} {corneeds.reach_said(c)}')
        return out

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
                f'{type(self).__name__} comes from a module that is not '
                f'in sys.modules ({type(self).__module__!r}). It cannot '
                'find its own directory. Register the module under '
                'spec.name before exec_module, as core.adapter.load '
                'does.')
        return os.path.dirname(os.path.abspath(path))

    @typing.final
    def reharvest(self) -> list[str]:
        """Read the game again, as `bind-wizard.py` would: a subprocess.

        The same script `./bind-wizard.py <game> harvest` runs, for the same
        reason `bind-wizard.py` shells out rather than importing -- a harvest
        reads a game directory, unpacks archives and writes files, and none of
        that wants to happen inside a curses loop with a half-drawn screen.

        What comes back is what it printed. The catalogue on screen is
        still the one loaded at start: picking the new one up means
        starting again, and saying so beats pretending otherwise.
        """
        where = os.path.join(self.here, 'harvest.py')
        if not os.path.exists(where):
            return [f'{self.game} has no harvest.py -- it reads the game '
                    'from inside its capture wizard']
        done = subprocess.run([sys.executable, where, '--json'],
                              cwd=self.here, capture_output=True, text=True)
        out = [line for line in (done.stdout + done.stderr).splitlines()
               if line.strip()]
        return out + ([] if done.returncode == 0 else
                      [f'!! harvest exited {done.returncode}'])

    @typing.final
    def drop_cache(self) -> list[str]:
        """Remove what the harvest wrote, and only that.

        `CACHE` names what the harvest wrote; `NEEDS_FILE` and `BINDS`
        are deliberately not in it. So this walk cannot reach the
        judgements however it is written -- which matters, because a
        harvest is one command away from coming back and a judgement is
        not.
        """
        out = []
        for name in sorted(self.CACHE):
            path = os.path.join(self.here, name)
            if not os.path.exists(path):
                out.append(f'{name} was not there')
                continue
            os.remove(path)
            out.append(f'removed {name}')
        return out or ['nothing to remove']

    @typing.final
    def rules(self) -> dict:
        """The scoring rules: the core's, with this game's over the top.

        A game that has nothing to say gets the core's unchanged, so
        dropping a `scoring.toml` in beside a planner is all it takes --
        no wiring, and nothing to remember to call.
        """
        mine = os.path.join(self.here, 'scoring.toml')
        if not os.path.exists(mine):
            return corneeds.RULES
        with open(mine, 'rb') as f:
            return corneeds.merge_rules(corneeds.RULES, tomllib.load(f))

    #: Whether the answers file has been read onto these needs yet. A
    #: class default so that a game with its own `__init__` does not have
    #: to remember to set it.
    _answered = False

    @typing.final
    def answers(self, needs) -> None:
        """Put what you decided last time onto these needs. Once.

        `build` runs again every time the screen replans -- a key, an
        overlay, a new aircraft -- and the file is the record of what you
        decided BEFORE this session. Read again mid-session it undoes the
        session: a row you cleared came back carrying its old `chose`, so
        the `chose` pass put it straight back on the control you had just
        taken it off, and the next save wrote the resurrected row to the
        file. Clearing a hand-placed binding was not possible at all.

        Measured on this desk: 32 of DCS's 32 rows and 32 of X4's 32 came
        back from one replan. The four games with no answers file yet
        read the same way and had nothing to resurrect.

        Once means once per adapter. Switching aircraft builds another
        one, and that one does read its own file.

        Once for the NEEDS. The axes are answered every time, because an
        axis plan is built fresh from the devices on every build while
        the needs are the same objects all session: `main` builds a
        layout for the plan and the review builds another, so a screen
        whose axes were only seeded on the first build opened with every
        one of them purple. What the session has decided about an axis
        survives this because `Review.relay` carries it over the top.
        """
        if self._answered:
            return
        self._answered = True
        corneeds.load_assignments(self.here, self.BINDS, needs)

    def save_needs(self, needs) -> str:
        """Write what the screen decided down.

        Not final: DCS keeps its decisions in the wizard's results file,
        per command rather than per function, because that is the
        granularity it captures at. The screen does not care -- it hands
        over needs and the adapter knows where its own answers live.

        The description and where things sit go to different files, and
        both are written together because one keystroke saves what you
        did: adding a function and putting it somewhere are the same
        evening's work.

        A judgement is derived from nothing: delete it and it is gone. So
        a screen that lets somebody make one has to be able to keep it,
        and until this existed, promoting an action lasted until `q`.

        In the order the file already has them. The review hands them over
        in PLACEMENT order, which is the screen's order and not the
        file's, so every save rewrote the whole list -- a diff of 32 moved
        blocks for one changed field, and the author's own grouping gone
        with it. Anything the file has never seen, which is what `a` makes,
        goes on the end.
        """
        if not self.NEEDS_FILE:
            raise RuntimeError(
                f'{self.game} makes its own list rather than keeping '
                'one. There is no file to write it to.')
        filed = self.as_filed(needs)
        corneeds.save_needs(self.here, self.NEEDS_FILE, filed)
        corneeds.save_assignments(self.here, self.BINDS, filed)
        return (f'wrote {len(needs)} to {self.NEEDS_FILE} and where '
                f'{sum(1 for n in needs if n.assignment)} of them sit to '
                f'{self.BINDS}')

    def as_filed(self, needs):
        """`needs` in the order the file on disk has them."""
        was = {n.what: i for i, n in enumerate(self.NEEDS)}
        end = len(was)
        return sorted(needs, key=lambda n: was.get(n.what, end))

    @typing.final
    def cache(self, filename, key=None, build=None):
        """This adapter's cache for `filename`, through `core.vocab`.

        `key` picks one section where `CACHE` names several: BMS reads its
        callbacks and its device table out of the same file.
        """
        want = self.CACHE.get(filename)
        if isinstance(want, tuple):
            if key not in want:
                raise TypeError(f'{filename} holds {want}. This asked for '
                            f'{key!r}.')
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

        Every planner owns `--write` because this adds it. Before,
        `bind-wizard.py`'s dispatch table absorbed the difference, which made a
        gap in two adapters read as a fact about two games.
        """
        p = argparse.ArgumentParser(
            description=sys.modules[type(self).__module__].__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        p.add_argument('--desk', metavar='NAME',
                       help='Which rig in the device map this is for.')
        p.add_argument('--why', action='store_true',
                       help='Print why each control was chosen.')
        p.add_argument('--free', action='store_true',
                       help='List the controls that stay unbound.')
        # `nargs='?'` because two adapters already took a path here and
        # standardising on the poorer of the two spellings would have been a
        # regression dressed as a contract.
        p.add_argument('--sheet', nargs='?', const='', metavar='PATH',
                       help='Write KNEEBOARD.md, or write it to PATH.')
        p.add_argument('--html', nargs='?', const='', metavar='PATH',
                       help='Write kneeboard.html, or write it to PATH.')
        p.add_argument('--tui', action='store_true',
                       help='Review the layout. Save what you keep.')
        p.add_argument('--write', action='store_true',
                       help='Write the whole layout into the game.')
        p.add_argument('--overlay', metavar='NAME',
                       help='Which layout to ask for, from overlays/: '
                            + (', '.join(coverlay.names()) or 'none written')
                            + f'. The default is {self.OVERLAY or "none"}. '
                              'Give none to ask for nothing.')
        p.add_argument('--solver', metavar='NAME',
                       choices=[n for n, _s, _w in csolvers.choices()],
                       help='Who decides which need takes which control: '
                            + '. '.join(f'{n} is {said}'
                                        for n, said, _w in
                                        csolvers.choices())
                            + '. The default is the best one that runs '
                              'here.')
        backup.add_argument(p, self.game)
        # The constructor's own flags, so `--help` lists them. They are
        # PARSED before this parser exists -- `run()` takes them off the
        # command line to build the adapter at all -- and so were missing
        # from every help text in the family: `./bind-wizard.py dcs plan
        # -a su-25T` is in the top-level README and `--help` had never
        # heard of it.
        self.arguments(p)
        for names, name in _flags(type(self)):
            if any(n in p._option_string_actions for n in names):
                # The game words this one itself, in `arguments`. Two
                # declarations of one flag is argparse's error, not a
                # choice to make here.
                continue
            p.add_argument(*names, metavar=name.split('_')[0].upper(),
                           help=self.SAYS.get(name, f'Which {name} this '
                                                    'is for.'))
        return p

    @typing.final
    def solver(self, name):
        """The solver this run uses, and one line saying which.

        The name alone. Which solver ran is the fact; which one did not
        and why is a road not taken, and a status line that lists what is
        absent makes a one-word answer into a sentence to parse.

        Said at all because it never was: the model was used when
        `ortools` imported and the list-walk when it did not, so the same
        command on the same desk produced two different kneeboards
        depending on which python found it, 77 lines apart.

        Naming one that cannot run here stops the run rather than quietly
        handing back the other. That absence IS worth a line, because it
        is the error -- you asked for an answer, not for whichever answer
        was available.
        """
        if name:
            who = csolvers.named(name)
            why = who.why_not()
            if why:
                raise SystemExit(f'--solver {name}: {why}')
        else:
            who = type(csolvers.best())
        print(f'solver: {who.name}', file=sys.stderr)
        return who()

    @typing.final
    def overlay_note(self, layout, why=False):
        """How much of the overlay the layout actually honours.

        The overlay is named on the way in; this is what came of it. A
        template is a lean rather than a law, so some of it loses to reach
        and to what is already taken, and without a count the only way to
        know how much was to read the whole layout with the file open
        beside it. This is the number two overlays are compared on.
        """
        got = corneeds.OVERLAY
        if got is None:
            return []
        kept, broken, lost = got.kept(layout)
        if not kept and not broken:
            return []
        out = [f'\n  {got.name}: {kept} of {kept + broken} place wishes kept']
        if why:
            # Only under --why. The count is the answer; the list is the
            # evidence, and printing evidence nobody asked for is how a
            # summary stops being read.
            for what, word, want, instead in lost:
                # Cut to the column rather than pushing it: DCS names its
                # controls as the jet does, so `Autopilot/Nosewheel
                # Steering Disengage (Paddle) Switch` walked the `wanted`
                # column off into the middle of the line.
                said = what if len(what) <= 28 else what[:27] + '…'
                out.append(f'    {said:28} wanted {word} {want}, '
                           f'got {instead or "nothing measured"}')
        return out

    @typing.final
    def overlay(self, name):
        """The overlay this run uses, and one line saying which.

        Said out loud for the reason the solver is: it changes where things
        land, so a layout you cannot explain is a layout you cannot trust.
        A name nothing answers to stops the run rather than quietly laying
        the desk out with no wishes at all -- that is the error, and it
        looks exactly like the planner ignoring you.
        """
        want = name or self.OVERLAY
        if not want or want == 'none':
            print('overlay: none', file=sys.stderr)
            return None
        got = coverlay.named(want, self.game)
        # Over the needs now, rather than leaving it to `allocate`. A game
        # reads the wishes itself before any allocation happens: BMS splits
        # its list into the plain layer and the shifted one, so a `shift`
        # nothing had set yet put all five shifted needs on the plain
        # layer and moved 44 bindings. `apply` sets the same values twice
        # if `allocate` runs it again, which is no change.
        got.apply(self.NEEDS)
        print(f'overlay: {got.name}', file=sys.stderr)
        return got

    @typing.final
    def main(self, argv=None):
        """Everything that was asked for, in one order.

        X4 returned after `--sheet`, so `--sheet --write` wrote a kneeboard
        and silently did not write the game. War Thunder had the same bug
        between `--sheet` and `--html` and fixed it locally. Asking for two
        things gets two things here.
        """
        args = self.parser().parse_args(argv)
        # Said before anything is read: which desk this is decides which
        # device is the stick, which hand is on it, and how far every
        # control is. The map will not guess, and neither will this.
        if args.desk:
            os.environ['SIM_DEVICE_PROFILE'] = args.desk
        corneeds.SOLVER = self.solver(args.solver)
        corneeds.OVERLAY = self.overlay(args.overlay)

        bad = self.unknown()
        if bad:
            for what, kind, ident in bad:
                print(f'!! {what}: the game has no {kind} called '
                      f'{ident}.', file=sys.stderr)
            raise SystemExit(
                'The vocabulary does not agree with the list. Run '
                f'./bind-wizard.py {self.game} harvest.')

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
        # Said once, here, rather than in six games' own headers: with
        # nothing measured every control scores the same on reach, so the
        # layout is real but not reach-aware, and nothing else on screen
        # would say so.
        note = layout.reach_note()
        if note:
            print(f'\n  {note}')
        for line in self.overlay_note(layout, why=args.why):
            print(line)
        return 0

    # ---- the kneeboard, for both kinds of adapter ----------------------

    @abc.abstractmethod
    def sheet(self, layout) -> csheet.Sheet:
        """The kneeboard, in the core's shape."""

    def offers(self) -> list:
        """[(key, word, what it does)] this game puts on the review screen.

        For a key only one game needs. DCS lays out one aircraft module at
        a time and had a menu of its own to change which, which is half of
        why it kept a whole screen; a game that needs one key asks for one
        key.

        The callable is handed the `Review` and the `tui`, and answers
        with a line for the status bar -- or with an `Adapter`, and then
        the screen reopens on that one. Changing module is a different list of
        needs, a different store and a different kneeboard, so it is a
        new screen rather than a redraw.
        """
        return []

    def sheet_suffix(self) -> str:
        """What tells this game's kneeboard from another of its own, if
        anything. DCS writes one per aircraft module: `-FA-18C`.

        The suffix rather than the whole stem, because the two files do
        not share a spelling -- `KNEEBOARD.md` shouts and
        `kneeboard.html` does not -- and a game overriding the stem would
        have to repeat that convention to keep it. DCS is the reason
        there is a hook at all: overriding the whole of `write_sheets` to
        change a filename is how its sheet drifted away from everybody
        else's, keeping its own writer and its own template while three
        fixes to the shared one never reached it.
        """
        return ''

    @typing.final
    def write_sheets(self, layout, markdown=None, html=None) -> list[str]:
        """Each argument is None for "not asked", '' for the default path,
        or a path."""
        sh = self.sheet(layout)
        # One place for six games: a kneeboard printed on a desk it was
        # not drawn for, or under an overlay you have since changed, reads
        # as the only layout there could be. Set here rather than asked of
        # every `sheet()` -- this method is final, so nothing can skip it.
        sh.desk = corneeds.desk_of(layout)
        if corneeds.OVERLAY is not None:
            sh.overlay = corneeds.OVERLAY.name
        tail = self.sheet_suffix()
        out = []
        if markdown is not None:
            out.append('wrote %s (%d rows, %d of them axes)' % sh.markdown(
                markdown or os.path.join(self.here, f'KNEEBOARD{tail}.md')))
        if html is not None:
            out.append('wrote %s (%d rows, %d of them axes)' % sh.html(
                html or os.path.join(self.here, f'kneeboard{tail}.html')))
        for line in out:
            print(line)
        return out

    # ---- what the two kinds of adapter each answer differently ----------

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
                    + '. A writer sends what it replaces to core.backup. '
                      'It must not write a sibling file: the game reads '
                      'that folder.')
        return out

    @typing.final
    def review(self, args) -> None:
        """core.review, wired to this adapter.

        Final because the wiring *is* the clause: `write=` is handed the
        layout the screen kept and nothing wider, and it reaches the writer
        through `write_all`, so the review's output is backed up and
        checked for strays on exactly the same path as `--write`.

        On `Adapter` and not on `Planner`, so a proposer gets it too. DCS
        had a screen of its own with `c C x X ↵` on it -- the same keys,
        the same three states -- because nothing offered it this one.

        The loop is for an `offers` key that answers with another adapter:
        DCS lays out one aircraft at a time, and changing which is a
        different list of needs, a different store and a different
        kneeboard. So the screen closes and opens on the new one rather
        than redrawing.
        """
        on = self
        while on is not None:
            on = creview.run(
                on.build(), on.title, on.subtitle,
                describe=on.describe, write=on.write_all,
                paths=on.paths(args), catalogue=on.catalogue(),
                source=os.path.join('games', on.game, on.CATALOGUE),
                save=on.save_needs, harvest=on.reharvest,
                drop=on.drop_cache, rules=on.rules(),
                rebuild=on.build, game=on.game, offers=on.offers())
            if not isinstance(on, Adapter):
                return


class Planner(Adapter):
    """An adapter whose writer takes the placements it is handed."""

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

    From the filesystem, because a game that exists only in a table in
    `bind-wizard.py` is a game the table can be wrong about.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games')
    return sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))
                  and not d.startswith('.'))


def planner(game):
    """Which file in this game's directory defines its adapter.

    `plan.py` in five games and `plan.py` in DCS, whose planner derives
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
    """The module for a game's planner, imported the way `bind-wizard.py` runs
    it.

    `os.chdir` because an adapter resolves its data files against `HERE` and
    `bind-wizard.py` runs it with `cwd=games/<game>`. Nothing is swallowed:
    after this work an import defines classes and reads nothing, so a failure
    here is a failure of the contract rather than a fact about what is
    installed.
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

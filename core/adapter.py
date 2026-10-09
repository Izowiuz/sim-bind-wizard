"""What the core may assume about a game's adapter, as classes.

A contract written as prose drifts. `build()` was in the contract from the
start and its shape was not, so five adapters reached five orders of the
same five values. A shape in the core is the cure, and these classes apply
it to the rest of the interface.

Three moments enforce it, and they are not one moment:

    class definition   __init_subclass__ rejects an override that cannot be
                       called the way the base promised, an override of a
                       @final member, and an @override that overrides
                       nothing
    instantiation      abc refuses a subclass with an abstract member left
                       unimplemented, and names every one of them
    pyright            return types, parameter types, and an @override
                       whose name no base defines

A clone can be without the third, so the first checks the argument list
itself.

None of the three reaches a writer that calls `self.build()` behind the
interface. Python has no `private`, so that clause is a test over the
compiled function in `tests/test_contract.py`. The same holds across the
sidecar seam: a script loaded by path is `Any` to pyright.

The adapters are classes because a module cannot be parameterised and an
instance can. DCS derives its needs from the aircraft it was asked about,
so `NEEDS` as a module constant holds the Hornet's list or the Su-25T's
and never both. Every other game paid a smaller version of the same price:
it threaded `--profile`, `--preset` or `--game-dir` down a call chain, and
one laundered a flag through `os.environ`. `__init__` is where per-run
configuration belongs.
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
from core import devmap
from core import guess as cguess
from core import needs as corneeds
from core import overlay as coverlay
from core import solvers as csolvers
from core import sheet as csheet
from core import review as creview
from core import vocab


# ------------------------------------------------------- the override guard

def _func(member):
    """The function inside whatever decorator wraps it, or None.

    A plain class attribute answers None on purpose. `NEEDS = [...]` is how
    five of the six games satisfy an abstract property, and an arity check
    has nothing to say about a list.
    """
    if isinstance(member, (classmethod, staticmethod)):
        return member.__func__
    if isinstance(member, property):
        return member.fget
    return member if inspect.isfunction(member) else None


def _calls(sig):
    """Every way a caller may invoke something with this signature.

    Every value is None. This is about the number of arguments and the
    keyword names. It is never about types. Types are pyright's half.
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

    This checks compatibility, not equality. An override may rename a
    parameter, and it may add one that has a default. Both are legal. An
    identical signature is too strong a rule: it rejects working code and
    teaches people to switch the guard off.

    An override may not need an argument the base never promised. It may
    not refuse one the base did.

    `*args, **kwargs` passes. Nothing can be told from it.
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
    """Reject a bad override at definition, where a compiler would.

    `abc` checks that a name exists. It never checks that the name can be
    called. So `describe(self)` where the base said `describe(self,
    placement)` reaches the call before anything notices, and in the review
    screen that call is inside a curses loop.
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
    """A module read from a file, under `name`, put in `sys.modules`.

    `spec_from_file_location` answers None for a path Python will not treat
    as a module. It answers a spec with no loader for a path it can see and
    cannot run. The guard turns both into a sentence naming the file.
    Without it a missing or unreadable file arrives as an AttributeError on
    None.

    A file with no `.py` has to be handed its loader. That is the only way
    `bind-wizard.py` can be imported at all.

    `argv` swaps `sys.argv` around the execution and swallows the
    SystemExit a script with its own argument parsing raises on the way
    past. That is the cost of importing a sibling SCRIPT rather than a
    module.
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

    The line endings are never translated. What the writer computed goes
    out as it is. Falcon BMS's key files are latin-1 with CRLF, and the
    platform default rewrites every line of one. A backup is then useless
    for seeing what changed.
    """

    def __init__(self, text, encoding='utf-8'):
        self.text = text
        self.encoding = encoding

    def __len__(self):
        return len(self.text)

    def __repr__(self):
        return f'<Text {len(self.text)} chars, {self.encoding}>'


#: What a writer returns: {path: Text or str, or None to move the file
#: aside}. `None` is for a file the game has to find GONE rather than
#: replaced. Falcon BMS's `axismapping.dat` is one. The game rebuilds that
#: file from the defaults only where it is missing.
MOVE = None

class Bound(typing.NamedTuple):
    """One binding, in the game's own words, ready to be written.

    This is what `Adapter.rows` hands a writer. A writer that walks
    `layout.placed`, then `placement.slots`, then the payload works out the
    same four things for itself: which device, which slot, which action and
    which of the game's buckets. Four writers then carry the same three
    nested loops, and the loop is where they drift. One of them re-derived
    the button order and disagreed with the review screen about which
    button a hat direction sat on.

    `slot` is already `says_slot`'s answer, in the game's own spelling.
    `role` and `device` come with it, because a format names the hardware
    as well as the control.
    """

    role: str
    device: typing.Any
    slot: str
    axis: bool
    action: str
    mode: str
    edge: str
    invert: bool
    what: str


#: The eight axes a stick or a throttle can report, in HID usage order.
#: `sim-device-map` names a lever by which of these it IS. Every game here
#: spells the same eight in the same order: X4's `X` to `SLIDER2`, Elite's
#: `Joy_XAxis` to `Joy_VAxis`, DCS's `JOY_X` to `JOY_SLIDER1`. So a game's
#: `AXES` is this list in the game's own words, and the position does the
#: mapping.
#:
#: Slider and Dial come last, because the report descriptor puts them
#: there. Falcon BMS needs that rule, and the order is written down once
#: here rather than keyed four times.
HID_AXES = ('X', 'Y', 'Z', 'Rx', 'Ry', 'Rz', 'Slider', 'Dial')


# ----------------------------------------------------------------- harvest

class Harvest(abc.ABC):
    """In: the game's files. Out: the vocabulary, as JSON.

    This base class owns `--json`, and the cache goes through
    `core.vocab.save` because this class calls it. A harvest therefore
    cannot write with its own `json.dump`, and it cannot disagree with
    another harvest about what `--vocab --json` writes.
    """

    #: The game, as `bind-wizard.py` dispatches on it and as its directory
    #: is named.
    game: str

    #: filename -> the section names `core.vocab.save` writes under.
    #: Declared rather than passed, so a test compares it with
    #: `Adapter.CACHE`. A harvest and a planner that disagree about a
    #: section name otherwise wait for somebody to run the game.
    files: dict

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        _guard(cls)

    @property
    @typing.final
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
        """This harvest's own flags. `--game-dir` belongs here.

        The one hook on this side. A harvest has no constructor to read
        flags off, which is what `Adapter` has. A declaration carrying
        argparse's types is an argument spec in data, and
        `core/overlay.py` refuses that kind of expression language for the
        same reason.
        """

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
        """Read, then print, then write where asked. In that order.

        The order is the point. One harvest that returns from `--vocab`
        before it reads `--json`, and another that does not, make the same
        two flags mean opposite things.
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

    #: Where copies of replaced files go. `__init__` sets it from the
    #: flag, so no writer takes it as an argument.
    backup_dir = None

    #: filename -> the section key `core.vocab.load` takes. None names a
    #: cache with no envelope. A tuple names a file that holds several
    #: sections, and `cache()` is told which one to take.
    CACHE: dict = {}

    #: Where this game's description of its functions lives, relative to
    #: the game's own directory. The description says which band a thing is
    #: in, what shape it wants, and whether you hold it down.
    #:
    #: Empty for a game that derives its needs. DCS reads them off the
    #: aircraft, so it keeps no file.
    #:
    #: This is not in `CACHE`. `CACHE` names what the harvest wrote, and a
    #: harvest cannot write a judgement.
    NEEDS_FILE: str = ''

    #: What a promoted action becomes. A game whose needs carry more than
    #: the core's names its own class here, the way it hands one to
    #: `read_needs(make=...)`. A core `Need` on such a game's list fails
    #: inside the planner, and `a` is the key that makes one.
    NEED: type = corneeds.Need

    #: Which overlay this game is laid out with, from `overlays/`. An
    #: overlay says which device a family belongs on, which control
    #: carries the shift, and which two things your hand works at once.
    #: `--overlay` replaces it for one run. `--overlay none` runs without
    #: one, and the allocator then judges every control on reach and shape
    #: alone.
    OVERLAY: str = ''

    #: Where what sits where lives. This is the answer, not the question:
    #: one row per placed function, saying which control took it and who
    #: decided. It is a separate file from the description above, so a
    #: reader can tell which half the planner produced.
    BINDS: str = ''

    #: Which of `CACHE`'s files the catalogue is read out of. Named, not
    #: guessed from the others. The vocabulary screen puts this on its top
    #: bar, where it answers "is this the file I just re-harvested". A
    #: plausible wrong filename there is worse than none.
    CATALOGUE: str = ''

    #: constructor parameter -> the other spellings of its flag, for a
    #: game whose own word for a thing predates the common one.
    ALIASES: dict = {}

    #: constructor parameter -> what `--help` says about it. A flag with
    #: no line is a flag nobody finds.
    SAYS: dict = {}

    #: Which device roles this game addresses, as `devmap.by_role` takes
    #: them. A game that reaches a third device says so here. Written into
    #: five `build()` bodies instead, the same two words have nothing
    #: holding them together.
    ROLES: tuple = ('stick', 'throttle')

    #: The game's own contexts, as the kneeboard's columns, in reading
    #: order. One control means a different thing in each one: Elite's
    #: ship and SRV, X4's ship, map and on foot, MSFS's aeroplane and
    #: helicopter, War Thunder's air and helicopter.
    #:
    #: WHICH context an action answers in is data on the action, in
    #: `actions.Action.mode`. The harvest writes it from the game's own
    #: naming. This declaration is the list of columns and nothing else.
    #:
    #: A private mechanism per game makes a caller upstairs know which
    #: game it is holding.
    MODES: tuple = ('',)

    #: What this game calls each axis, in `HID_AXES` order. The map says
    #: which HID axis a lever IS, so the position in this tuple is the
    #: whole mapping. There is nothing to key.
    #:
    #: A declaration, not a method. The same body over the same eight
    #: names with a different spelling is what four games write otherwise:
    #: `JOY_X`, `Joy_XAxis`, `INPUT_JOYAXIS_X`, `Joystick L-Axis X`. A
    #: declaration has nowhere to put a fifth copy.
    AXES: tuple = ()

    #: How this game spells a button: a pattern that takes `{n}`, and what
    #: the map's index 0 is called. `JOY_BTN{n}` from 1, `Joystick Button
    #: {n}` from 1, `INPUT_XBUTTON_{n}` from 1.
    BUTTON: str = ''
    BUTTON_FROM: int = 1

    #: Where a game names its first positions rather than numbering them.
    #: X4 writes `INPUT_XBUTTON_BACK` for the seventh and a number from the
    #: twelfth. So the first eleven are written out here and the rest
    #: follow `BUTTON`.
    BUTTON_NAMES: tuple = ()

    #: How many of a device's buttons this game can address, where it
    #: cannot address them all. Falcon BMS sees the first 32, so the
    #: VMAX's last nineteen are real to your hand and invisible to the
    #: sim. `allocate` takes this through `usable`.
    BUTTONS_SEEN: int = 0

    #: How to spell the USB pair where the map has no name for this game.
    #: `''` is `3344:8196` as the map holds it. `joined` is `33448196`.
    #: `upper` is `33448196` in capitals. `product` is `8196` alone.
    #:
    #: The map's `game_id` is asked first and it wins. What a game calls a
    #: device is a fact about the hardware, so it belongs beside the
    #: hardware. This declaration covers a game nobody has written into
    #: the map.
    DEVICE_ID: str = ''

    #: (label, this adapter's own attribute) for the review screen's map.
    #: A hook here is six copies of `getattr`, one per game.
    PATHS: tuple = ()

    #: The game's category -> a device role. `Throttle Grip` says the real
    #: aircraft keeps it on the throttle. The game's author says that in
    #: the game's own data. Measured against a hand-written list:
    #: `Throttle Grip` 14 of 14 and `Stick` 7 of 7.
    DEVICE_BY_CATEGORY: dict = {}

    #: The game's category -> a job, where a category names one. This
    #: holds a handful of entries. It is not a vocabulary. Measured: a
    #: category mostly names a PLACE in the cockpit, and `Throttle Grip`
    #: splits evenly between flight, comms and sensor.
    JOB_BY_CATEGORY: dict = {}

    #: The constructor parameter that names which variant this run is
    #: for, where a game lays out one variant at a time. DCS says
    #: `aircraft`. No other game has one.
    #:
    #: The core builds three things from this and `variants()`: the
    #: sentence that says which variant to describe, the kneeboard's
    #: filename, and the review screen's key for changing it.
    VARIANT: str = ''

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        _guard(cls)

    # ---- what the game knows ------------------------------------------

    #: The list, read once and held. `None` until something asks, so a
    #: game with no file costs nothing at import.
    _needs = None

    @property
    @typing.final
    def NEEDS(self) -> list:
        """[Need] -- what a pilot must be able to do, in this game's words.

        Read out of `NEEDS_FILE`. Empty where nobody has written one, and
        every game starts there. `a` adds a row and `J` says what a
        function is. A game that derived this list from its own vocabulary
        would derive a judgement from a name.

        Read once and held. `add_need` appends to this list, and `build()`
        runs again on every replan: a key, an overlay, another aircraft. A
        fresh list per access drops what `a` put on it and re-reads what
        the session already decided.
        """
        if self._needs is None:
            self._needs = corneeds.read_needs(self.filed(), make=self.NEED)
        return self._needs

    @typing.final
    def filed(self) -> list:
        """The rows of the needs file, or none where there is no file.

        An absent file is not an error. It is every game before somebody
        describes one function of it, and `undescribed_note` says so in
        words. `vocab.load` raises `Missing` for an absent cache, because
        a cache is one command away from coming back. A judgement is not.
        """
        if not self.NEEDS_FILE:
            return []
        path = os.path.join(self.here, self.NEEDS_FILE)
        if not os.path.exists(path):
            return []
        return list(vocab.load(self.here, self.NEEDS_FILE, key='needs'))

    @typing.final
    def build(self) -> corneeds.Layout:
        """The whole plan, in the one shape every adapter returns.

        One body, so there is one shape AND one way of arriving at it. Six
        bodies drift: five adapters reached five orders of the same five
        values, and nothing generic could be written over the top.

        A game varies this by declaring. `ROLES` names the devices.
        `usable` vetoes a control the sim cannot address. A
        `scoring.toml` beside the planner replaces a band's limits.
        """
        devs = devmap.by_role(*self.ROLES)
        self.answers(self.NEEDS)
        return corneeds.Layout(devs, *corneeds.allocate(
            self.NEEDS, devs, usable=self.usable, rules=self.rules()))

    @typing.final
    def catalogue(self) -> list[cactions.Action]:
        """Everything this game can be told to do, in the core's shape.

        The harvest wrote this shape, so this reads it and does nothing
        else. Translating on the way OUT of the cache is the same work
        done where it cannot see the game's own files, and the harvest is
        already parsing those.

        Empty where a game names no cache. That is not silent: `unknown()`
        then reports every action a need names, and `main()` stops with
        the harvest command in the message.
        """
        if not self.CATALOGUE:
            return []
        return cactions.read(self.cache(self.CATALOGUE, key='actions'))

    @typing.final
    def describe(self, placement) -> list[tuple[str, str]]:
        """[(part of the control, what it does)], for core.review.

        The catalogue answers this. A `Bind` names an action the catalogue
        knows, so the core says what a placement does without handing it
        back to the game for the words.
        """
        known = cactions.by_id(self.catalogue())
        return [(str(button), b.named(known))
                for button, payload in placement.slots for b in payload]

    @typing.final
    def unknown(self) -> list[tuple[str, str, str]]:
        """[(what, kind, id)] the game's vocabulary does not contain.

        Every action a need names has to be in the catalogue. A need that
        names one the game no longer has is a harvest away from being
        explained. `main()` says so and stops.
        """
        known = cactions.by_id(self.catalogue())
        out = []
        for need in self.NEEDS:
            for slot in need.bindings:
                for b in slot:
                    if b.action not in known:
                        out.append((need.what, need.takes, b.action))
        return out

    # ---- one hook, because it cannot be declared -----------------------

    def variants(self) -> dict:
        """{key: display name} where this game lays out one variant at a
        time. Empty where it does not.

        DCS is the only such game. A module's commands are its own, so the
        Hornet's needs are not the Su-25T's.

        This cannot be a declaration. The answer is which modules are
        INSTALLED, and that is read out of the game directory.

        The core builds three things from this and `VARIANT`: the review
        screen's key, the sentence that says which module to describe, and
        the kneeboard's filename.
        """
        return {}

    # ---- the slot, as the game spells it -------------------------------

    @typing.final
    def says_slot(self, role, slot, device) -> str:
        """What this game calls one slot of one device, or '' for nothing.

        The map says 16. Falcon BMS says `DX17`. War Thunder says a number
        off its own base. Which one you need depends on which screen of
        which game is in front of you.

        `slot` is a button index or a `needs.OnAxis`. A game spells the
        two differently and both land in the same column, so this answers
        both. The answer comes out of `AXES` and `BUTTON`, which are
        declarations.
        """
        if isinstance(slot, corneeds.OnAxis):
            if not self.AXES:
                return ''
            hid = device.axis(slot.index).hid
            at = HID_AXES.index(hid) if hid in HID_AXES else None
            return self.AXES[at] if at is not None \
                and at < len(self.AXES) else ''
        if slot < len(self.BUTTON_NAMES):
            return self.BUTTON_NAMES[slot]
        if not self.BUTTON:
            return ''
        return self.BUTTON.format(n=slot + self.BUTTON_FROM)

    @typing.final
    def usable(self, role, control) -> bool:
        """May this game put something on this control?

        This answers for hardware the sim cannot address. Falcon BMS sees
        a device's first 32 buttons, so the VMAX's last nineteen are real
        to your hand and invisible to the game.

        `allocate` takes this as its `usable` argument. Nothing else asks.
        `BUTTONS_SEEN` says how many, and that is all the one game that
        needs this has to say.
        """
        if not self.BUTTONS_SEEN:
            return True
        return all(b < self.BUTTONS_SEEN for b in control.bindable_buttons)

    @typing.final
    def paths(self, args) -> list[tuple[str, str]]:
        """[(label, path)] for the review screen's map.

        Read off `PATHS`, which names this adapter's own attributes. As a
        hook this is six copies of `getattr`, one per game.
        """
        return [(label, str(getattr(self, field, '') or ''))
                for label, field in self.PATHS]

    @typing.final
    def guess(self) -> str:
        """Propose what every function is, once. Returns one status line.

        One line. The frame's `unsaved` already says that nothing is saved
        yet, and a screen does not spell a fact twice.

        This runs on `Z` and nowhere else. Nothing on the way to a layout
        reaches it, and `allocate` cannot see it. The planner reads the
        needs FILE.

        Every field it writes lands in `Need.guessed`. A field NOT in
        there is one somebody decided, so a second run leaves your answers
        alone and fills in what is still blank. Without both halves a
        proposal is derived on every run, with no way to tell its answer
        from yours and no way to correct one.

        It fills the rows that exist and it adds none. Which functions get
        a row is yours, and `a` adds one.
        """
        maker = self.guesser()
        known = cactions.by_id(self.catalogue())
        filled = 0
        for need in self.NEEDS:
            # A need can carry several actions. Four directions of a hat
            # are four ids in one record. So what they say is merged, and
            # the last one with something to say wins. They are the same
            # switch, so they agree about the device. Where they disagree
            # about the job, `J` is where you settle it.
            said = {}
            for slot in need.bindings:
                for b in slot:
                    if b.action in known:
                        said.update(maker.about(known[b.action]))
            for field, value in said.items():
                # Yours, so leave it. A field with a value and no mark is
                # one somebody wrote down.
                if getattr(need, field, None) and field not in need.guessed:
                    continue
                setattr(need, field, value)
                need.guessed.add(field)
                filled += 1
        return (f'{filled} field(s) filled on {len(self.NEEDS)} '
                'function(s). Correct what is wrong with J.')

    @typing.final
    def rows(self, layout) -> list:
        """[Bound] -- every binding this layout asks for, in the game's
        own words, most urgent first.

        The one loop. A writer takes these rows and turns them into its
        format's text, and that text is the whole of what is irreducibly
        the game's. Four writers that walk the layout themselves walk it
        identically.

        An axis and a button are one list in one order. `Bound.axis` says
        which of the two a row is, and a format that spells them
        differently splits on that.
        """
        out = []
        for p in layout.placed:
            device = layout.devices[p.role]
            for slot, payload in p.slots:
                said = self.says_slot(p.role, slot, device)
                for b in payload:
                    out.append(Bound(
                        role=p.role, device=device, slot=said,
                        axis=isinstance(slot, corneeds.OnAxis),
                        action=b.action, mode=b.mode or '',
                        edge=b.edge, invert=bool(p.need.invert),
                        what=p.need.what))
        return out

    @typing.final
    def device_id(self, device) -> str:
        """What this game calls one device.

        The map answers this. `game_id` is a per-game name on a device's
        identity, so "what DCS calls this stick" is a fact about the
        hardware and it lives where the hardware is described. DCS writes
        `Device {GUID}` as a filename and War Thunder writes `3344:43E8`.
        The map holds both.

        `DEVICE_ID` is the fallback spelling of the USB pair, for a game
        the map does not name yet. It is a declaration, so three games
        cannot derive it from `usb` three ways.
        """
        said = device.game_id(self.game)
        if said:
            return said
        usb = device.usb or ''
        if self.DEVICE_ID == 'joined':
            return usb.replace(':', '')
        if self.DEVICE_ID == 'upper':
            return usb.replace(':', '').upper()
        if self.DEVICE_ID == 'product':
            return usb.split(':')[-1]
        return usb

    @typing.final
    def free(self, layout) -> list[str]:
        """What nothing was put on. One shape for six games.

        An overridable `free` gives three layouts of the same four facts,
        in a different order with different brackets round them. The one
        thing a game needs from it is its own numbering for a spare
        button, and this answers that.
        """
        out = [f'{len(layout.free)} controls left free:']
        for role, c in layout.free:
            says = ', '.join(x for x in
                             (self.says_slot(role, b, layout.devices[role])
                              for b in c.bindable_buttons) if x)
            out.append(f'  {role:9} {c.label:34} {c.kind:10} '
                       f'{says:18} {corneeds.reach_said(c)}')
        return out

    @typing.final
    def show(self, layout, why: bool = False) -> list[str]:
        """The lines a bare run prints. `--why` annotates them.

        Grouped by device, and inside a device by the control the
        allocator chose, most urgent first. `allocate` returns that order,
        and it is the order you read a layout in.

        What each binding does comes from `describe`, so the catalogue
        answers it and no game has to.

        `--why` puts the account beside the row and not under it. The
        question is "why THAT control", and the row is the control.
        """
        out = []
        for role in self.ROLES:
            mine = [p for p in layout.placed if p.role == role]
            if not mine:
                continue
            dev = layout.devices.get(role)
            out.append(f'\n{role}  {getattr(dev, "product", "")}'.rstrip())
            for p in mine:
                out.append(f'  {p.need.what:40} {p.ctrl.label:24} '
                           f'{p.need.first_shape}'.rstrip())
                for part, does in self.describe(p):
                    if does != p.need.what:
                        out.append(f'      {part:>4}  {does}')
                if why:
                    for bit in corneeds.why_bits(p):
                        out.append(f'        {bit}')
        if layout.unplaced:
            out.append(f'\n{len(layout.unplaced)} found no control:')
            for need in layout.unplaced:
                out.append(f'  {need.what:40} wanted {need.takes}')
        return out

    @typing.final
    def sheet(self, layout) -> csheet.Sheet:
        """The kneeboard, in the core's shape.

        One body over `MODES`. A row is a control and a column is a
        context. Which context a binding answers in is read off the action
        the catalogue knows.
        """
        known = cactions.by_id(self.catalogue())
        sh = csheet.Sheet(
            self.title, self.subtitle, ident='Code', contexts=self.MODES,
            devices={r: getattr(d, 'product', '')
                     for r, d in layout.devices.items()})
        for p in layout.placed:
            for slot, payload in p.slots:
                axis = isinstance(slot, corneeds.OnAxis)
                ident = self.says_slot(
                    p.role, slot, layout.devices[p.role])
                for b in payload:
                    does = b.named(known)
                    mode = b.mode or (known[b.action].mode
                                      if b.action in known else '') or ''
                    if axis:
                        # One physical lever is one row with a column per
                        # context, and `add_axis` merges them. This takes
                        # the group's label and not the axis's. The VMAX's
                        # two levers travel as a pair, and the page says
                        # that once.
                        sh.add_axis(p.role, self._lever(layout, p, slot),
                                    ident, does, context=mode)
                    else:
                        sh.add(csheet.Row(
                            p.role, p.ctrl.label,
                            part=p.ctrl.direction(slot) or 'press',
                            ident=ident, does=does,
                            bindings={mode: [does]}))
        for role, ctrl in layout.free:
            sh.add_free(role, ctrl.label,
                        self.says_slot(role, ctrl.bindable_buttons[0],
                                       layout.devices[role])
                        if ctrl.bindable_buttons else '')
        for need in layout.unplaced:
            sh.add_unplaced(need.what, need.first_shape)
        return sh

    @staticmethod
    def _lever(layout, placement, slot):
        """What to call the lever a binding went on.

        The axis group where the map has one, so two axes that travel
        together read as the one input they are. The axis itself where it
        moves alone.
        """
        dev = layout.devices[placement.role]
        axis = dev.axis(slot.index)
        group = dev.axis_group(axis.index)
        return group.label if group else axis.label

    # ---- the shell, which nobody overrides -----------------------------

    @property
    @typing.final
    def here(self):
        """The directory this adapter and its cache live in.

        Read off the module the class was defined in. That module has to be
        in `sys.modules`. A module executed from a path is not there unless
        whoever executed it put it there. `load()` and `sidecar()` do put
        it there. Anything else that loads an adapter by hand has to as
        well, and this says so rather than raising a KeyError three frames
        down.
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
        """Read the game again, as `bind-wizard.py` does: a subprocess.

        The same script `./bind-wizard.py <game> harvest` runs. A harvest
        reads a game directory, unpacks archives and writes files. None of
        that belongs inside a curses loop with a half-drawn screen.

        What comes back is what the script printed. The catalogue on screen
        is still the one loaded at start. Picking the new one up means
        starting again, and the screen says so.
        """
        where = os.path.join(self.here, 'harvest.py')
        done = subprocess.run([sys.executable, where, '--json'],
                              cwd=self.here, capture_output=True, text=True)
        out = [line for line in (done.stdout + done.stderr).splitlines()
               if line.strip()]
        return out + ([] if done.returncode == 0 else
                      [f'!! harvest exited {done.returncode}'])

    @typing.final
    def drop_cache(self) -> list[str]:
        """Remove what the harvest wrote, and only that.

        `CACHE` names what the harvest wrote. `NEEDS_FILE` and `BINDS` are
        not in it, on purpose. So this walk cannot reach the judgements,
        however it is written. A harvest is one command away from coming
        back. A judgement is not.
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

        A game with nothing to say gets the core's rules unchanged. A game
        with something to say drops a `scoring.toml` beside its planner.
        There is no wiring, and nothing to remember to call.
        """
        mine = os.path.join(self.here, 'scoring.toml')
        if not os.path.exists(mine):
            return corneeds.RULES
        with open(mine, 'rb') as f:
            return corneeds.merge_rules(corneeds.RULES, tomllib.load(f))

    #: Whether the answers file has been read onto these needs yet. A
    #: class default, so a game with its own `__init__` does not have to
    #: remember to set it.
    _answered = False

    @typing.final
    def answers(self, needs) -> None:
        """Put what you decided last time onto these needs. Once.

        `build` runs again every time the screen replans: a key, an
        overlay, a new aircraft. The file records what you decided BEFORE
        this session.

        Read again mid-session, the file undoes the session. A row you
        cleared comes back carrying its old `chose`, the `chose` pass puts
        it on the control you just took it off, and the next save writes
        the resurrected row. Clearing a hand-placed binding is then
        impossible.

        Measured on this desk: 32 of DCS's 32 rows and 32 of X4's 32 came
        back from one replan.

        Once means once per adapter. Switching aircraft builds another
        adapter, and that one reads its own file.

        Once for the NEEDS. The axes are answered on every build, because
        an axis plan is built fresh from the devices each time while the
        needs are the same objects all session. `main` builds one layout
        and the review builds another, so axes seeded on the first build
        only would open purple on the screen. `Review.relay` carries what
        the session decided about an axis over the top.
        """
        if self._answered:
            return
        self._answered = True
        corneeds.load_assignments(self.here, self.BINDS, needs)

    @typing.final
    def add_need(self, action, category=''):
        """Put one of the game's actions on the list. Returns the need.

        The game's own class, appended to the game's OWN list, so the next
        `build()` plans for it. A need the screen holds and the adapter
        does not is a need the next allocation drops.

        The need arrives carrying what the game says about the action,
        marked as proposed. A row `a` adds therefore looks like a row `Z`
        made, because it is made the same way.

        The band and the flags are NOT filled. No game's files record when
        you reach for a thing or whether a mistake hurts. A proposal with
        no evidence behind it is worse than a gap.
        `undescribed_note` counts the gaps and `J` fills one in.
        """
        need = corneeds.from_action(action, category, self.NEED)
        for field, value in self.guesser().about(action).items():
            setattr(need, field, value)
            need.guessed.add(field)
        self.NEEDS.append(need)
        return need

    @typing.final
    def guesser(self):
        """This game's proposer, built from its own declarations.

        One per call, and cheap. It holds three dicts and reads nothing.
        """
        return cguess.Guess(self.DEVICE_BY_CATEGORY,
                            self.JOB_BY_CATEGORY)

    @typing.final
    def save_needs(self, needs) -> str:
        """Write down what the screen decided: the description, and where
        things sit, in the two files that hold them.

        Final. A game that writes half of this writes half a save: `J`
        says `unsaved`, `s` writes where things sit, and the description
        goes nowhere.

        Both files on one keystroke. Adding a function and putting it
        somewhere are the same evening's work.

        Written in the order the file already has. The review hands them
        over in PLACEMENT order, and that order rewrites the whole list:
        a diff of 32 moved blocks for one changed field. Anything the file
        has never seen, which is what `a` makes, goes on the end.
        """
        if not self.NEEDS_FILE:
            raise RuntimeError(
                f'{self.game} makes its own list rather than keeping '
                'one. There is no file to write it to.')
        filed = self.as_filed(needs)
        corneeds.save_needs(self.here, self.NEEDS_FILE, filed)
        # The template goes in with the placements. Which one was on
        # decides where every one of them landed, so a file that holds
        # the answer and not the template cannot be read back.
        on = corneeds.OVERLAY
        corneeds.save_assignments(self.here, self.BINDS, filed,
                                  on.called if on else '')
        return (f'wrote {len(needs)} to {self.NEEDS_FILE} and where '
                f'{sum(1 for n in needs if n.assignment)} of them sit to '
                f'{self.BINDS}')

    @typing.final
    def as_filed(self, needs):
        """`needs` in the order the file on disk has them."""
        was = {n.what: i for i, n in enumerate(self.NEEDS)}
        end = len(was)
        return sorted(needs, key=lambda n: was.get(n.what, end))

    @typing.final
    def cache(self, filename, key=None, build=None):
        """This adapter's cache for `filename`, through `core.vocab`.

        `key` picks one section where `CACHE` names several. Falcon BMS
        reads its callbacks and its device table out of one file.
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

        A separate script may own a format: War Thunder's `machine.blk`,
        Elite's `.binds` and DCS's results file each do. A separate script
        may not own the VERB. `main()` below owns that.
        """
        return from_file(
            f'{self.game}_{name.replace("-", "_").removesuffix(".py")}',
            os.path.join(self.here, name), argv=[name])

    @typing.final
    def parser(self):
        """The one surface every planner answers.

        Every planner owns `--write`, because this adds it. A dispatch
        table in `bind-wizard.py` absorbs the difference instead, and a
        gap in two adapters then reads as a fact about two games.
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
        # `nargs='?'`, because two adapters take a path here. The poorer
        # of the two spellings as the standard is a regression dressed as
        # a contract.
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
        # PARSED before this parser exists, because `run()` takes them off
        # the command line to build the adapter at all. Listed nowhere,
        # they are missing from every help text: `./bind-wizard.py dcs
        # plan -a su-25T` is a documented command that `--help` has never
        # heard of.
        #
        # A constructor parameter is a flag this loop adds. An `arguments`
        # hook here is six implementations that add what the declarations
        # already add.
        for names, name in _flags(type(self)):
            if any(n in p._option_string_actions for n in names):
                # Already declared above: `backup_dir` is a constructor
                # parameter on every adapter AND the flag
                # `core.backup.add_argument` writes, so it comes round
                # twice and argparse refuses the second.
                continue
            p.add_argument(*names, metavar=name.split('_')[0].upper(),
                           help=self.SAYS.get(name, f'Which {name} this '
                                                    'is for.'))
        return p

    @typing.final
    def solver(self, name):
        """The solver this run uses, and one line saying which.

        The name alone. Which solver ran is the fact. Which one did not
        run is a road not taken, and a status line that lists what is
        absent turns a one-word answer into a sentence to parse.

        Said at all, because the choice changes the layout. The model
        runs where `ortools` imports and the list-walk runs where it does
        not, so the same command on the same desk gives two different
        kneeboards, 77 lines apart.

        A named solver that cannot run here stops the run. The program
        does not hand back the other one. That refusal is worth a line,
        because it is the error: you asked for an answer, not for
        whichever answer was available.
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
        """How much of the overlay the layout honours.

        The overlay is named on the way in. This is what came of it. A
        template is a lean and not a law, so some of it loses to reach and
        to what is already taken. Without this count you read the whole
        layout with the file open beside it. This is the number two
        overlays are compared on.
        """
        got = corneeds.OVERLAY
        if got is None:
            return []
        kept, broken, lost = got.kept(layout)
        if not kept and not broken:
            return []
        out = [f'\n  {got.name}: {kept} of {kept + broken} place wishes kept']
        if why:
            # Only under --why. The count is the answer and the list is
            # the evidence. Evidence nobody asked for is how a summary
            # stops being read.
            for what, word, want, instead in lost:
                # Cut to the column rather than push it. DCS names its
                # controls as the jet does, and `Autopilot/Nosewheel
                # Steering Disengage (Paddle) Switch` walks the `wanted`
                # column into the middle of the line.
                said = what if len(what) <= 28 else what[:27] + '…'
                out.append(f'    {said:28} wanted {word} {want}, '
                           f'got {instead or "nothing measured"}')
        return out

    @typing.final
    def filed_overlay(self) -> str:
        """Which template the binds file says this game was laid out to.

        '' where the file says nothing, which is a game nobody has saved
        and a game saved before the field existed. Both read as "ask the
        declaration".
        """
        if not self.BINDS:
            return ''
        return corneeds.filed_overlay(self.here, self.BINDS)

    @typing.final
    def overlay(self, name):
        """The overlay this run uses, and one line saying which.

        Said out loud for the reason the solver is said: it changes where
        things land. A layout you cannot explain is a layout you cannot
        trust.

        A name nothing answers to stops the run. Laid out with no wishes
        instead, the desk looks like the planner ignoring you.

        Three places can say which, and they are read in this order:

            --overlay NAME   this run, whatever is on file. `none` too.
            the binds file   what `o` last kept, per game
            `OVERLAY`        the planner's own declaration

        The flag wins, so one run under another template costs nothing
        that is written down. The file beats the declaration, because
        which template you want is a judgement and the declaration is
        source.
        """
        want = name or self.filed_overlay() or self.OVERLAY
        if not want or want == 'none':
            print('overlay: none', file=sys.stderr)
            return None
        got = coverlay.named(want, self.game)
        # Applied over the needs here, not left to `allocate`. A game
        # reads the wishes itself before any allocation: Falcon BMS splits
        # its list into the plain layer and the shifted one, and a `shift`
        # nothing has set yet puts all five shifted needs on the plain
        # layer and moves 44 bindings. `allocate` running `apply` again
        # sets the same values twice, which changes nothing.
        got.apply(self.NEEDS)
        print(f'overlay: {got.name}', file=sys.stderr)
        return got

    @typing.final
    def main(self, argv=None):
        """Everything that was asked for, in one order.

        Ask for two things here and you get two things. A planner that
        returns after `--sheet` makes `--sheet --write` write a kneeboard
        and leave the game alone, and it says nothing about that.
        """
        args = self.parser().parse_args(argv)
        # Said before anything is read. Which desk this is decides which
        # device is the stick, which hand is on it, and how far every
        # control is. The map does not guess, and neither does this.
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

        # `is not None`, not truthiness. `--sheet` with no path is the
        # empty string, and the empty string is falsy.
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
        if args.free:
            for line in self.free(layout):
                print(line)
            return 0
        if asked:
            return 0
        for line in self.show(layout, why=args.why):
            print(line)
        # Said once here, not in six games' own headers. With nothing
        # measured every control scores the same on reach. The layout is
        # real and it is not reach-aware, and nothing else on the screen
        # says so.
        note = layout.reach_note()
        if note:
            print(f'\n  {note}')
        for line in self.overlay_note(layout, why=args.why):
            print(line)
        for line in self.undescribed_note():
            print(line)
        return 0

    @property
    @typing.final
    def variant(self):
        """Which variant this run is for, or '' where a game has none.

        Read off the constructor parameter `VARIANT` names. So a game says
        the one thing about its variant once.
        """
        return getattr(self, self.VARIANT, '') if self.VARIANT else ''

    @typing.final
    def naming(self):
        """The arguments that name THIS run, for a message that says what
        to type next.

        Empty for a game with one list of functions. DCS lays out one
        aircraft at a time, so a sentence that tells you to describe the
        module has to name the module. The flag it names is the one
        `VARIANT` points at.
        """
        if not self.variant:
            return []
        flag = next(iter(self.ALIASES.get(self.VARIANT, ())),
                    '--' + self.VARIANT.replace('_', '-'))
        return [flag, self.variant]

    @typing.final
    def undescribed_note(self):
        """How many functions say nothing about what they are for.

        `suits` is the one word an overlay takes hold of. A function
        without it is invisible to every template, and that looks like a
        template that did not apply.

        Said here, because a screen shows one row at a time and this is a
        fact about the whole list.

        It is a hole and not an error. A needs file is written by hand,
        and `J` on the review screen is where a hole gets filled in.

        A list with nothing on it at all gets the other message. That is a
        module nobody has described yet.
        """
        if not self.NEEDS:
            # Nothing to count. `0 controls proposed` on its own reads as
            # a desk with no room on it, not as a game nobody has
            # described.
            said = ' '.join(['./bind-wizard.py', self.game, 'tui']
                            + list(self.naming()))
            # The variant where a game has one, and the game otherwise.
            # `subtitle` is the hardware and the profile for five of the
            # six, and `Nothing describes VIRPIL · inputmap_3.xml` names
            # the wrong thing.
            what = self.subtitle if self.naming() else self.title
            return [f'\n  Nothing describes {what} yet. The planner has '
                    'no functions to place.',
                    f'    Describe it: {said}']
        blind = [n for n in self.NEEDS if not corneeds.described(n)]
        if not blind:
            return []
        if len(blind) == 1:
            return ['\n  1 function says nothing about what it is for.']
        return [f'\n  {len(blind)} functions say nothing about what they '
                'are for.']

    # ---- the kneeboard, for both kinds of adapter ----------------------

    @typing.final
    def offers(self) -> list:
        """[(key, word, what it does)] this game puts on the review screen.

        One key, and only where `variants()` answers with something.
        Changing the variant means a different list of needs, a different
        store and a different kneeboard, so the key reopens the screen
        rather than redrawing it.

        `t` for the type. `a` and `A` are the family's keys, for browsing
        the vocabulary.
        """
        found = self.variants()
        if not found:
            return []

        def pick(_review, tui):
            keys = sorted(found, key=lambda k: found[k].lower())
            got = tui.choose(f'Which {self.VARIANT}',
                             [('plain', f'  {found[k]}') for k in keys],
                             index=keys.index(self.variant)
                             if self.variant in keys else 0)
            if got is None or keys[got] == self.variant:
                return f'the same {self.VARIANT}'
            return type(self)(**{self.VARIANT: keys[got],
                                 'backup_dir': self.backup_dir})

        return [('t', f'Select {self.VARIANT}.', pick)]

    @typing.final
    def sheet_suffix(self) -> str:
        """What tells this game's kneeboard from another of its own.

        `-FA-18C` where there is a variant. Nothing where there is not.

        The suffix, not the whole stem. The two files do not share a
        spelling: `KNEEBOARD.md` shouts and `kneeboard.html` does not. A
        game that set the stem would repeat that convention to keep it.

        A game that overrides the whole of `write_sheets` to change a
        filename keeps its own writer and its own template, and a fix to
        the shared one never reaches it.
        """
        return f'-{self.variant}' if self.variant else ''

    @typing.final
    def write_sheets(self, layout, markdown=None, html=None) -> list[str]:
        """Each argument is None for "not asked", '' for the default path,
        or a path."""
        sh = self.sheet(layout)
        # One place for six games. A kneeboard printed for another desk,
        # or under an overlay you have since changed, reads as the only
        # layout there could be. Set here and not asked of every
        # `sheet()`. This method is final, so nothing skips it.
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

        A writer returns contents and never touches the filesystem. Two
        clauses of the contract hold because of that, rather than being
        merely tested. The copy goes through `core.backup`, because this
        method calls it. And a writer cannot leave a stray file in the
        game's own directory, because it has no file handle to leave one
        with.

        The check still runs. Two writers delegate to a script that owns
        their format, and a sloppy conversion lets that script write.

        `since` is read BEFORE `write_layout` is called, so a file that
        appeared during the call is caught as well. Two directory listings
        compared afterwards would hold the stray in the "before".
        """
        dirs = {os.path.dirname(os.path.abspath(p)) for p in files}
        before = {d: set(os.listdir(d)) for d in dirs if os.path.isdir(d)}

        when = backup.stamp()
        replace = [p for p, v in files.items() if v is not MOVE]
        # One `when` for the whole run. A game that writes two files then
        # gets one folder, and a restore returns the pair together.
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

        Final, because the wiring IS the clause. `write=` takes the layout
        the screen kept and nothing wider, and it reaches the writer
        through `write_all`. So the review's output is backed up and
        checked for strays on the same path as `--write`.

        On `Adapter` and not on `Planner`, so a proposer gets it too.

        The loop is for an `offers` key that answers with another adapter.
        DCS lays out one aircraft at a time, and changing which one means
        a different list of needs, a different store and a different
        kneeboard. The screen closes and opens on the new adapter.
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
                rebuild=on.build, game=on.game, offers=on.offers(),
                add=on.add_need, guess=on.guess)
            if not isinstance(on, Adapter):
                return


class Planner(Adapter):
    """An adapter whose writer takes the placements it is handed."""

    @abc.abstractmethod
    def write_layout(self, rows, layout) -> dict:
        """What the game's files should now contain, for these bindings.

        -> {path: Text or str, or MOVE for a file that has to be gone}.
        This computes and returns. `lay_down` does the writing.

        `rows` is `[Bound]`, from `Adapter.rows`. Every binding is already
        in this game's own words, with the device, the slot and the bucket
        worked out. The walk down `layout.placed`, `slots` and the payload
        is the core's. What is left here is the format and only the
        format.

        `layout` comes too, for the devices and the free controls. A
        format that takes our hardware out of everything the plan no
        longer names needs the device list, and an empty `rows` carries no
        devices.

        Both arguments are the same layout, so a writer cannot be handed
        anything other than what the reviewer kept. That is the clause
        that matters. A writer that calls `build()` for itself breaks it,
        and `tests/test_contract.py` reads the compiled function for that
        one, because a signature cannot say it.

        A signature also cannot say that the text DROPS a binding cut from
        the list. That is a fact about the contents. Only a fixture that
        writes a layout, removes a need and writes again holds it.
        """

    @typing.final
    def write_all(self, layout) -> list[str]:
        since = time.time()
        return self.lay_down(
            self.write_layout(self.rows(layout), layout), since=since)

def _flags(cls):
    """[(flag names, parameter)] for this adapter's constructor.

    The constructor declares what a run of this game can be configured
    with. The flags are read off it. Written out a second time, they
    drift.
    """
    out = []
    taken = inspect.signature(cls.__init__).parameters
    for name, p in list(taken.items())[1:]:            # [1:] drops `self`
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

    Empty where there is no `games/` at all, which is a state and not a
    fault: the core is the thing that works, and a checkout with no game
    in it has to load, list nothing and say so.

    An adapter, not a directory. `games/falconbms` and `games/warthunder`
    hold a needs list and a binds file and no code: the lists are described
    and the planners are not written yet. A directory like that answers
    nothing, so `planner`, `load` and every caller that walks this list
    would fail on it.
    """
    root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'games')
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root)
                  if not d.startswith('.')
                  and os.path.isfile(os.path.join(root, d, 'plan.py')))


def planner(game):
    """Which file in this game's directory defines its adapter.

    Found, not tabulated, for the reason `games()` reads the filesystem: a
    table is a second place for the truth to be wrong.

    The file is read and not imported, so nothing is executed to answer
    this.
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
    """The module for a game's planner, imported the way `bind-wizard.py`
    runs it.

    `os.chdir`, because an adapter resolves its data files against `HERE`
    and `bind-wizard.py` runs it with `cwd=games/<game>`.

    Nothing is swallowed. An import defines classes and reads nothing, so
    a failure here is a failure of the contract. It is not a fact about
    what is installed.
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


__all__ = ['Harvest', 'Adapter', 'Planner',
           'Text', 'MOVE', 'Bound', 'HID_AXES',
           'run', 'games', 'planner', 'load', 'adapters', 'from_file']

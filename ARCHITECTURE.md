# Architecture

## The two repositories

| repository | what it holds |
|---|---|
| `sim-device-map` | what each physical control is |
| `sim-bind-wizard` | what each game action is, and which control takes it |

The device map describes hardware. It names no game. It is useful with no
game installed. This repository reads it and never writes it.

## The flow

    the game's own files
        |  harvest.py
        v
    games/<game>/<game>-actions.json        every action the game accepts
        |  core/vocab.py
        v
    [Action]  +  games/<game>/<game>-needs.json      what a pilot must do
              +  the device map                      what the controls are
              +  overlays/<name>.toml                where a family belongs
        |  core/needs.py allocate()
        v
    Layout
        |  core/review.py                   you answer, you save
        v
    games/<game>/<game>-binds.json          what you decided
        |  Adapter.rows() then plan.py write_layout()
        v
    the game's own files                    a backup first

A harvest reads the game. A planner writes the game. Three of the four
games read the file they write, because all four formats are
read-modify-write.

## The files

| file | what it does |
|---|---|
| `bind-wizard.py` | list the games. Run one verb of one game. |
| `core/adapter.py` | what the core may assume about a game |
| `core/actions.py` | one shape for a game action |
| `core/vocab.py` | load what a harvest wrote |
| `core/needs.py` | match needs against controls |
| `core/solvers.py` | which need takes which control |
| `core/overlay.py` | one way of laying a game out |
| `core/review.py` | the review screen |
| `core/guess.py` | what a function probably is |
| `core/sheet.py` | the kneeboard |
| `core/devmap.py` | find and load the device map |
| `core/game.py` | find the install and the settings folder |
| `core/capture.py` | read the sticks through `/dev/input/js*` |
| `core/tui.py` | the curses shell the screens are built on |
| `core/backup.py` | copy a file before a writer replaces it |
| `core/scoring.toml` | the weights, the bands and the vocabularies |
| `overlays/*.toml` | a cockpit template |
| `games/<game>/harvest.py` | read one game |
| `games/<game>/plan.py` | write one game |

## The shapes that cross the interface

    Action(id, name, kind, category, mode)      one thing the game accepts
    Bind(action, edge, mode)                    one action on one input
    Need(what, shape, bindings, ...)            one thing a pilot must do
    Placement(need, role, ctrl, slots, points, why)
    Layout(devices, placed, unplaced, free)
    Bound(role, device, slot, axis, action, mode, edge, invert, what)

`Action` is what the game says. `Need` is what somebody decided. `Bound`
is one line for the writer: the control in the game's own words, and the
action on it.

`core/adapter.py` holds `HID_AXES`:

    ('X', 'Y', 'Z', 'Rx', 'Ry', 'Rz', 'Slider', 'Dial')

A game declares `AXES` as that same list in the game's own words. The
position does the mapping. No game turns a HID name into a key, because
the core does that once for every game.

## What a game supplies

A game is declarations plus its own writer. The count is the rule: a thing
two games would implement the same way is a declaration.

### What a game must implement

| class | member | what it returns |
|---|---|---|
| `Harvest` | `read()` | `{filename: {section: data}}` |
| `Harvest` | `summary()` | the lines a bare run prints |
| `Planner` | `write_layout(rows, layout)` | `{path: contents}` |

### What a game may override

| class | member | why it cannot be a declaration |
|---|---|---|
| `Harvest` | `arguments()` | a harvest has no constructor to read a flag off |
| `Adapter` | `variants()` | which modules are installed is read off the disk |

`Planner` has none.

### What a game declares

| declaration | what it says |
|---|---|
| `game`, `title`, `subtitle` | the word you type, and the name |
| `ROLES` | which device kinds this game uses |
| `MODES` | the contexts one control can mean two things in |
| `AXES` | the game's word for each HID axis, in HID order |
| `BUTTON`, `BUTTON_FROM`, `BUTTON_NAMES` | how the game spells a button |
| `BUTTONS_SEEN` | how many buttons the game reads from a device |
| `DEVICE_ID` | which field of the map names the device to the game |
| `PATHS` | which paths `m` shows |
| `VARIANT`, `ALIASES`, `SAYS` | the flag for a module or an aircraft |
| `CACHE`, `CATALOGUE` | which file the harvest wrote |
| `NEEDS_FILE`, `BINDS` | where the judgements live |
| `OVERLAY` | which template this game asks for |
| `NEED` | the `Need` subclass, where the game has one |
| `DEVICE_BY_CATEGORY`, `JOB_BY_CATEGORY` | what the game's categories mean |

Everything else on `Adapter` is final. An override of a final member is a
`TypeError` at class definition.

## Where a mistake is caught

| moment | what it catches |
|---|---|
| class definition | an override that cannot take the arguments the base promised, an override of a final member, an `@override` that overrides nothing |
| instantiation | an abstract member left unimplemented, named |
| pyright | return types, parameter types, an `@override` whose name no base defines |
| the test suite | a writer that calls `build()`, a game that adds a public method, a writer that adds without removing |

A clone can be without pyright. The first moment therefore checks the
argument list itself.

Python has no `private`, so the clause "a writer never fetches a plan of
its own" is a test over the compiled function in
`tests/test_contract.py`. A script loaded by path is `Any` to pyright, so
nothing is checked across that seam either.

## Why the adapters are classes

A module cannot be parameterised. An instance can. DCS derives its needs
from the aircraft it was asked about, so `NEEDS` as a module constant could
hold the Hornet's list or the Su-25T's list, and never both. Every other
game paid a smaller version of the same price: it threaded `--profile`,
`--preset` or `--game-dir` down a call chain. `__init__` is where per-run
configuration belongs.

## The test suite

    ./tests/run.py

| file | what it covers |
|---|---|
| `test_contract.py` | what every game must answer, and how |
| `test_needs.py` | the matching and the scoring |
| `test_review.py` | the review screen |
| `test_formats.py` | what each writer does to the game's own text |
| `test_overlay.py` | the templates |
| `test_scoring.py` | the weights in `scoring.toml` |
| `test_actions.py` | the action shape |
| `test_vocabulary.py` | loading a harvest |
| `test_reason.py` | the words `why` prints |
| `test_listings.py` | what `plan` and `free` print |
| `test_box.py` | the curses shell |
| `test_backup.py` | the copies and the manifest |
| `test_types.py` | pyright over the repository |
| `fake.py` | hardware built from the device map's own classes |

The suite takes the standard library and the device map. It runs on a clone
with no game installed and nothing harvested. A test that needs a real
planner names a desk, because the map does not guess which desk you are at.

`test_formats.py` is the one place that tests removal. An interface can
state what a writer returns. It cannot state that the writer unbinds what
the layout dropped.

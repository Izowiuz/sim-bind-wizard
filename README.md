# sim-bind-wizard

This program puts a game's actions onto HOTAS controls.

It reads three things. The game says which actions accept a binding. The
device map says what each physical control is. A needs list says what a
pilot must be able to do. The program matches the needs against the
controls. Then it writes the game's own configuration file.

The device map is a separate repository,
[`sim-device-map`](../sim-device-map). It describes hardware. It is useful
with no game installed.

## Run it

    ./bind-wizard.py                    list the games
    ./bind-wizard.py GAME               open the review screen
    ./bind-wizard.py GAME VERB [ARG...] run one verb

The verbs:

| verb | what it does |
|---|---|
| `harvest` | read the game. Write the action vocabulary. |
| `plan` | print the layout |
| `why` | print the layout and the evidence for each control |
| `free` | print the controls that stay unbound |
| `sheet` | write `KNEEBOARD.md` and `kneeboard.html` |
| `tui` | review the layout. Save what you keep. |
| `write` | write the whole layout into the game |

`tui` is the default. Every argument after the verb goes to the script.
`./bind-wizard.py dcs plan -a su-25T` works.

Close the game before you write. The writers refuse to run while the game
is up.

## The games

| game | folder | state |
|---|---|---|
| DCS World | `games/dcs` | runs |
| Elite Dangerous | `games/elite` | runs |
| MSFS 2024 | `games/msfs` | runs |
| X4 Foundations | `games/x4` | runs |
| Falcon BMS | `games/falconbms` | a needs list, no code |
| War Thunder | `games/warthunder` | a needs list, no code |

A folder with no `plan.py` holds a needs list and a binds file. The front
door does not list it. `games/<game>/README.md` describes one game's own
file format.

Each game's needs list is an example, and it is yours to change. See
[`USING.md`](USING.md).

## The folders

    bind-wizard.py   the front door
    core/            the matching, the screens, the kneeboard
    games/           one folder per game
    overlays/        a cockpit template to lay a game out to
    backups/         a copy of every file a writer replaced
    tests/           the test suite

## The documents

| document | for |
|---|---|
| [`USING.md`](USING.md) | the commands, the review screen, the keys |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | the files, the interface, the contracts |
| [`ALLOCATION.md`](ALLOCATION.md) | how the matching decides |

## Test it

    ./tests/run.py              every test
    ./tests/run.py needs        only these
    ./tests/run.py -v           and name each one

The suite takes the standard library and the device map. It needs no game
installed and no harvest.

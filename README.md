# sim-bind-wizard

Generates HOTAS bindings for flight simulators from one description of the
hardware. A shared core does the matching; a folder per game knows that game's
file format and vocabulary.

Hardware lives in a separate repo, [`sim-device-map`](../sim-device-map): it
describes devices, not games, and is useful with no game installed.

## Documents

| | for |
|---|---|
| [`USING.md`](USING.md) | changing a binding, adding a game — commands |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | files, data flow, API, contracts |
| [`ALLOCATION.md`](ALLOCATION.md) | how the matching works: reach, scoring, the four passes |
| `games/<game>/README.md` | one game's paths, format and measurements |

## Layout

    core/       matching, device roles, game locations, kneeboards,
                reading the sticks directly and the curses shell for it
    games/      one folder per game

## Games

| game | folder | state |
|---|---|---|
| Falcon BMS | `games/falconbms` | on the core |
| War Thunder | `games/warthunder` | on the core |
| MSFS 2024 | `games/msfs` | on the core |
| X4 Foundations | `games/x4` | on the core |
| DCS World | `games/dcs` | on the core, own sheet template |
| Elite Dangerous | `games/elite` | on the core |

## Quick start

    cd games/falconbms
    ./harvest.py --json      read the game: vocabulary and ranking
    ./plan.py --why          what it would bind, and why
    ./plan.py --write        into the game (close the game first)
    ./plan.py --sheet --html the kneeboard

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

    bind        one front door: ./bind <game> <verb>
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

    ./bind                   the games, and what each one can do
    ./bind bms why           the layout, with the evidence for each choice
    ./bind bms sheet         the kneeboard
    ./bind bms write         into the game (close the game first)

    aliases   bms = falconbms   wt = warthunder   ed = elite

The verb is canonical, what it runs is not — a game may answer it with a
separate script, or need two writes for one layout. Anything after the verb is
forwarded, so `./bind dcs plan -a su-25T` works.

The scripts are still there to be run directly:

    cd games/falconbms
    ./harvest.py             read the game: vocabulary and ranking
    ./plan.py --why          what it would bind, and why
    ./plan.py --write --write-axes    into the game
    ./plan.py --sheet --html the kneeboard

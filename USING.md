# Using it

Four tasks. Find yours and stop reading.

---

## 1. Change what a control does

Configs the game reads are **outputs**. Edit `NEEDS` and regenerate.

    ./bind <game>              what it would bind, and where
    ./bind <game> why          and why each control was chosen
    ./bind <game> write        into the game
    ./bind <game> sheet        refresh the kneeboard

`./bind` with no arguments lists the games and which verbs each answers to.
The scripts under `games/<game>/` do the same work and take their own flags;
`./bind` forwards anything after the verb.

Close the game first. Writers refuse while it is running.

Everything a writer replaces is copied first, into `backups/<game>/<stamp>/`
in the repo — one folder per run, with a `MANIFEST` saying where each file came
from. `--backup-dir DIR` or `SIM_BIND_BACKUPS` puts them somewhere else; a
cloud folder or an external disk is a reasonable choice, the game's own
directory is not. Nothing prunes them.

    ./bind <game> write --backup-dir ~/OneDrive/backups/<game>

Putting one back is War Thunder's only, so far — the rest are a restore away
from having it, since the MANIFEST already says where every file belongs.

    ./bind wt write --restore                          the newest run
    ./bind wt write --restore --restore-from 20260918   an older one

Three fields decide placement:

**`urgency`** — when you touch it. Nothing at `ON_THE_RAMP` can take a control
your thumb rests on; nothing at `IN_A_TURN` can be given one you must let go of
the grip to reach.

    IN_A_TURN     with something on your tail
    ON_APPROACH   hands busy, but there is time
    IN_THE_AIR    somewhere in the cruise
    ON_THE_RAMP   canopy open, engine off

**`prefer`** — a control you have chosen, by its label in the device map. Placed
before urgency is considered, so it survives regeneration.

    Need('Gear', 'button', ['ID_GEAR'], prefer='Keyboard B1 button')

**`on`** — the directions a switch physically moves in.

    Need('Speedbrake', 'hat2', ['close', 'open'], on=('forward', 'back'))

---

## 2. Your hardware changed

    ../sim-device-map/capture.py

The capture lands in `captures/<maker>/` with a `kind` — `stick`, `throttle`.
Planners ask for a kind, so no game code changes. Matching is by USB id and
fingerprint, not by name, so a firmware update that renames the device still
matches.

Two devices of one kind: the connected one wins, otherwise you are asked.

    SIM_DEVICE_ROLES="stick=virpil-vpc-stick-warbrd-d" ./plan.py
    SIM_DEVICE_MAP=/path/to/map ./plan.py

---

## 3. Find out what a control physically is

    ../sim-device-map/probe.py

Touch one thing at a time. Every event prints live with the map's name on it;
Ctrl-C summarises what moved **together** — a button closing while an axis
travels, or two axes reporting the same value.

Ask before assuming an axis or button is free. *Nothing is bound to it* and
*nothing else moves with it* are different questions, and the map only answers
the first unless someone has measured the second.

---

## 4. Add a game

Two halves have to exist before a layout can:

    ../sim-device-map    what the hardware IS
    harvest.py           what the game can be TOLD

### What a harvest is

**In: the installed game's own files — archives, shipped profiles, configs.
Out: two JSON files next to `harvest.py` — every action the game will accept a
binding for, and how many factory profiles bind each one.**

The vocabulary is what `plan.py` may name. The ranking is what belongs on
hardware, counted rather than guessed.

### Steps

1. `games/<name>/harvest.py` — read and print; `--json` writes the cache. Find
   the game with `core.game`, write with `core.vocab.save`.

   Three of the five older harvests do not meet this: Falcon BMS, War Thunder
   and MSFS write their cache unconditionally and serialise it themselves
   rather than through `core.vocab.save`. `./bind <game> harvest` hides the
   difference; the contract is still owed.
2. Measure what the files do not say. Record it in the code with its evidence,
   and mark what is still inference.
3. `games/<name>/plan.py` — `NEEDS` of `core.needs.Need`, a writer, and
   `_sheet()` returning a `core.sheet.Sheet`. Read the vocabulary through
   `core.vocab.load`, copy what you replace through `core.backup.save`, and
   take the flag from `core.backup.add_argument`.
4. `games/<name>/README.md` — six headings: where it lives, how to run it, the
   format, measured, still a guess, gotchas.
5. A row in `bind`, naming which script and flags each verb maps to. A verb the
   game has no answer for is left out and the reason goes in `GAPS`, so a gap
   reads as a fact about the game rather than an omission.

A writer must remove as well as add and change: a binding dropped from `NEEDS`
has to disappear from the game's config.

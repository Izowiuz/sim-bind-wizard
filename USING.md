# Using it

Four tasks. Find yours and stop reading.

---

## 1. Change what a control does

Configs the game reads are **outputs**. Edit `NEEDS` and regenerate.

    cd games/<game>
    ./plan.py                  what it would bind, and where
    ./plan.py --why            and why each control was chosen
    ./plan.py --write          into the game
    ./plan.py --sheet --html   refresh the kneeboard

Close the game first. Writers refuse while it is running.

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
2. Measure what the files do not say. Record it in the code with its evidence,
   and mark what is still inference.
3. `games/<name>/plan.py` — `NEEDS` of `core.needs.Need`, a writer, and
   `_sheet()` returning a `core.sheet.Sheet`. Read the vocabulary through
   `core.vocab.load`.
4. `games/<name>/README.md` — six headings: where it lives, how to run it, the
   format, measured, still a guess, gotchas.

A writer must remove as well as add and change: a binding dropped from `NEEDS`
has to disappear from the game's config.

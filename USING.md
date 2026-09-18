# Using it

Four tasks.

---

## 1. Change what a control does

Configs the game reads are **outputs**. Edit `NEEDS` and regenerate.

    ./bind <game>              what it would bind, and where
    ./bind <game> why          and why each control was chosen
    ./bind <game> tui          walk it, keep what you want, write that
    ./bind <game> write        all of it, into the game
    ./bind <game> sheet        refresh the kneeboard

`./bind` with no arguments lists the games and the verbs each answers to.
Anything after the verb is forwarded to the script under `games/<game>/`,
which does the same work and takes its own flags.

Close the game first. Writers refuse while it is running.

### The review screen

`tui` is `write` with a say in it. Every need is a row, whether the planner
found it a home or not, and each row is in one of three states:

    (unset)   nothing on it
    ?         the planner put it there and you have not looked yet
    +         yours: you confirmed it, or you chose it yourself

    c / C   confirm this one / every proposal
    p / P   put the planner's choice on this one / into every gap
    RETURN  press the control you want it on
    l       or pick one from a list, with no hardware
    x / X   clear this one / drop every proposal, leaving yours
    m       the device map, and where the game was found
    w       write everything that has a control

`P` only fills gaps and `X` only drops proposals, so neither can undo a choice
of yours: both are safe to press at any point.

`?` is a note to yourself, not a switch. A proposal you never confirmed is
still written; clearing it is how you say no.

What `RETURN` does with the press depends on the need, and the screen says
which of the two you are in before you press anything:

    several bindings   the whole control, in its own order — press whichever
                       corner is under your thumb
    one binding        exactly where you pressed, so the second detent of a
                       trigger is the second detent

Which stick is which comes from the USB ids, so nothing asks you to identify
them, and nothing is opened until you press RETURN. A control that cannot take
the need says why: wrong shape, too few buttons, or which other need is
already sitting on it.

`l` picks from a list instead, for when the sticks are not plugged in. Neither
`l` nor RETURN applies the reach rules.

`m` shows where the game was found, which file will be written, and every
control the map knows about with what is on it. The header names the device
behind each role, because "stick" is a role and you may own two.

DCS answers `capture` instead of `tui`.

### Backups

Everything a writer replaces is copied into `backups/<game>/<stamp>/` in the
repo first — one folder per run, with a `MANIFEST` saying where each file came
from. Nothing prunes them.

    --backup-dir DIR      somewhere else; SIM_BIND_BACKUPS does the same
    --restore             put the newest run back
    --restore-from STAMP  an older one

    ./bind <game> write --backup-dir ~/OneDrive/backups/<game>
    ./bind wt write --restore --restore-from 20260918

A cloud folder or an external disk is a reasonable choice for `--backup-dir`;
the game's own directory is not.

Putting one back is War Thunder's only, so far. The `MANIFEST` already says
where every file belongs, so the rest are a restore away from having it.

### What decides placement

**`urgency`** — when you touch it. Nothing at `ON_THE_RAMP` can take a control
your thumb rests on; nothing at `IN_A_TURN` can be given one you must let go of
the grip to reach.

    IN_A_TURN     with something on your tail
    ON_APPROACH   hands busy, but there is time
    IN_THE_AIR    somewhere in the cruise
    ON_THE_RAMP   canopy open, engine off

**`prefer`** — a control you have chosen, by its label in the device map.
Placed before urgency is considered, so it survives regeneration.

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
   `core.vocab.load`, copy what you replace through `core.backup.save`, and
   take the flag from `core.backup.add_argument`.
4. `games/<name>/README.md` — six headings: where it lives, how to run it, the
   format, measured, still a guess, gotchas.
5. A test in `tests/test_formats.py` for whatever the writer does to the game's
   own text — what it must remove as well as add, and whatever the format will
   not forgive. Write the fixture, then break the writer and check the test
   notices.
6. A row in `bind`, naming which script and flags each verb maps to. A verb the
   game has no answer for is left out and the reason goes in `GAPS`, so a gap
   reads as a fact about the game rather than an omission.

The rest of what an adapter owes is in `ARCHITECTURE.md`.

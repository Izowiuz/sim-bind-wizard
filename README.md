# sim-bind-wizard

**Want to change a binding? [`USING.md`](USING.md).** This file is about why
the repo is shaped the way it is.

One repo, one shared core, a folder per game. It replaces four separate
wizards — DCS, War Thunder, MSFS 2024, Falcon BMS — that each grew their own
copy of the same ideas.

The hardware map stays where it is: [`sim-device-map`](../sim-device-map)
describes *devices*, not games, has its own capture tool, and is useful with no
game installed at all. That boundary works; pulling it in here would blur it.

## Why consolidate

Measured across the four repos before the move:

    score        written 4x      the allocator, four copies
    reach_tier   3x              and War Thunder was the copy without it
    devices      3x    build 3x    sheet 2x    html_sheet 2x    assign 2x

The duplication was not theoretical. Two defects came straight out of it:

- **War Thunder's allocator had no reach floor**, because the matcher was
  copy-pasted three times and only two copies got it. A command you touch once
  a flight could outbid the afterburner for a thumb button, and the workaround
  was hand-sorting the need list. It bit three times in one evening.
- **A writer that could add and change but never remove.** Fixed twice in War
  Thunder — once for buttons, then again for axes, because the first fix only
  covered half the file. The same hole is probably still open in the other
  three.

## Layout

    core/
      devmap.py   find and load sim-device-map, and pick a device per role
      game.py     Steam libraries, install dirs, Proton prefixes, is-it-running
      needs.py    Need, reach tiers, urgency, the allocator
    games/
      x4/         X4 Foundations

`Need` says WHAT and WHAT SHAPE. What a slot *means* is the game's business:
`bindings` is an opaque payload the core only indexes, so an entry can be a War
Thunder action id, a BMS callback or an X4 source/code pair without the
allocator knowing the difference. That is the seam.

The allocator places most-urgent-first and takes **the least precious control
that still does the job**, with a floor so nothing from the ramp can reach a
thumb position while something from a dogfight still needs one. A second pass
drops the floor for whatever is left over, because an unbound engine start is
worse than a canopy switch under the thumb.

`allocate(needs, devices, usable=...)` takes an optional veto, for a game that
cannot address hardware the map can see — BMS reads only a device's first 32
buttons, so the VMAX's last nineteen are real to your hand and invisible to the
sim.

## X4 Foundations

The friendliest target of the family: plain XML in the Proton prefix, one file
per named profile, every binding on one line.

    <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
            source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>

    <action>  fires once on press     <state>  true while held     <range>  an axis

`source` names the device by **slot**; `code` is **local to that device**. No
global numbering to undo, unlike War Thunder and BMS. Ids are self-describing,
so there is no language archive to crack either.

There is no device list anywhere in the config, so slots follow enumeration
order. `harvest.py` infers them from a profile's own bindings instead — a slot
whose codes are all Xbox names and which offers RZ is a gamepad; the slot with
THROTTLE on an axis is the throttle; what is left is the stick.

**Not yet measured:** which button index each `INPUT_XBUTTON_*` means. X4 mixes
Xbox names with bare numbers and whether those share one numbering is not
established. `CODES` in `harvest.py` is deliberately empty — filling it from a
plausible-looking XInput order would be a guess, and guessing what a control
physically is has already cost this project two wrong layouts.

## Core API

### `core.needs`

    Need(what, shape, bindings=(), push=None, urgency=IN_THE_AIR,
         suits=None, dev=None, prefer=None, on=None, note='')

| field | type | meaning |
|---|---|---|
| `what` | str | human name, used in output and kneeboards |
| `shape` | str or tuple | control shape; a tuple lists acceptable ones, first preferred |
| `bindings` | list | **opaque game payload**, one per direction/stage, in the control's own press order. `None` skips that direction |
| `push` | any | payload for the control's click, if it has one |
| `urgency` | 0-3 | `IN_A_TURN`, `ON_APPROACH`, `IN_THE_AIR`, `ON_THE_RAMP` |
| `suits` | str | matched against the control's `suits` in the map, +25 |
| `dev` | str | device kind it belongs on (`'stick'`); +40 on match, −50 off |
| `prefer` | str | pin to a control by its map label; +500 |
| `on` | tuple | direction names it physically moves in (`('forward','back')`) |

Derived: `slots` (len of bindings), `wanted` (slots + push), `shapes` (after
substitution), `first_shape`. `relaxed` is set by the allocator when it had to
reach past the floor.

`bindings` is the seam. The core only ever indexes it, so an entry can be a War
Thunder action id, a BMS callback string, or an X4 `(source, code)` pair.

    allocate(needs, devices, usable=None) -> (placements, unplaced, free)

`devices` is `{kind: Device}` from `devmap.by_role`. `usable(role, ctrl)` is an
optional veto for hardware the game cannot address — BMS reads only a device's
first 32 buttons, so the VMAX's last nineteen are real to your hand and
invisible to the sim.

A `Placement` carries `need`, `role`, `ctrl`, `points`, and `slots` as
`[(button index, binding)]` with the push appended when there is one.

Order of business inside: needs are sorted by `urgency`, then two passes. The
first honours `MIN_REACH`, the second drops it for whatever is left. A third
pass lets a one-slot need borrow the idle click of a control whose own need had
nothing for it.

    REACH_TIER   thumb/index 0 · without releasing 1 · needs letting go 3
    MAX_REACH    {0: 1, 1: 3, 2: 3, 3: 3}   worst reach an urgency accepts
    MIN_REACH    {0: 0, 1: 0, 2: 0, 3: 2}   best it may take

Scoring is `100 + 12 * tier`, so among controls that fit, the **least precious**
wins. Shapes and their substitutes live in `FITS`: `button` `dial` `encoder`
`hat2` `hat4` `latch` `ministick` `paddle` `selector` `trigger`.

### `core.devmap`

    load()                      the devicemap module, honouring SIM_DEVICE_MAP
    by_role(*required, pick=)   {kind: Device}, connected device wins a tie

`by_role` exits rather than guess when two devices share a kind and neither is
plugged in. Override with `pick={'stick': slug}` or `SIM_DEVICE_ROLES`.

### `core.game`

    libraries()                 every Steam library, main first
    install_dir(*names)         install path, first name that exists
    prefix(appid)               Proton prefix, or None for a native build
    in_prefix(appid, *parts)    a path under drive_c, or None
    userdata()                  Steam userdata dirs (Cloud saves live here)
    running(*patterns)          pgrep, for a writer's refusal to touch a
                                config the game will rewrite on exit

Each searches every library, because `compatdata` sits next to the library its
game is installed in — DCS is on the second disk here.

## What a game adapter owes

    games/<name>/harvest.py     read the game, print, write nothing
    games/<name>/plan.py        NEEDS: list[Need], and a writer
    games/<name>/README.md      six headings, below

The writer's one contract, because breaking it is invisible: **it must remove,
not only add and change.** Drop something from `NEEDS` and its old binding has
to go, or it stays live in the game fighting whatever took its place.

Per-game README headings, the same every time so any of them can be skimmed:
*where it lives · how to run it · the format · measured · still a guess ·
gotchas*.

`measured` and `still a guess` are separate headings on purpose. Every wrong
layout this family produced came from an inference filed as a fact — the
WarBRD's "paddle" that is the brake lever's contact, the throttle lever that
looked free and is clamped to its twin, a trim direction read off a command
name. The split is how a later session knows which claims it may lean on.

Reader map: [`USING.md`](USING.md) to change a binding, this file to add a
game, `games/<game>/README.md` for one game's specifics.

## Migrating the rest

One game at a time, verified against the live config each time, with the old
repo kept until the new path has written to the game and been flown. Each
migration should delete more than it adds; if one doesn't, the core is the wrong
shape and the migration gets to reshape it.

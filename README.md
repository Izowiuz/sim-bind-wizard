# sim-bind-wizard

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
      devmap.py   find and load sim-device-map (was duplicated 4x)
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

## Migrating the rest

One game at a time, verified against the live config each time, with the old
repo kept until the new path has written to the game and been flown. Each
migration should delete more than it adds; if one doesn't, the core is the wrong
shape and the migration gets to reshape it.

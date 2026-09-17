# War Thunder

## Where it lives

Native Linux build, no Proton prefix.

    ~/.local/share/Steam/steamapps/common/War Thunder/
      lang.vromfs.bin       lang/controls.csv — the vocabulary
      aces.vromfs.bin       config/hotkeys/*.blk — 29 factory HOTAS presets

    ~/.config/WarThunder/Saves/
      last/production/machine.blk           the file the game reads
      <account id>/production/machine.blk   written too, same content

`--game-dir` overrides the install lookup.

Only the `controls{}` block of `machine.blk` is rewritten; every other block is
left byte-identical.

## How to run it

    ./harvest.py              vocabulary and factory ranking
    ./plan.py                 the layout
    ./plan.py --why           and the evidence for each choice
    ./plan.py --unused        what is unbound
    ./plan.py --sheet --html  the kneeboard
    ./wt-bind-preset.py --dry-run   resolved ids, writes nothing
    ./wt-bind-preset.py --render PATH   a copy for review
    ./wt-bind-preset.py             into the game
    ./wt-bind-preset.py --restore   the most recent backup

## The format

`machine.blk` is text. Buttons sit in `controls{ hotkeys{ } }`, one block per
action, keyboard and joystick bindings side by side:

    ID_GEAR{ joyButton:i=66  joyButton:i=68 }
    ID_AGM_LOCK{ keyboardKey:i=56 }

Axes sit in `controls{ axes{ } }`:

    rudder{ axisId:i=9  innerDeadzone:r=0.1  nonlinearity:r=2.5 }

Axis properties: `innerDeadzone`, `nonlinearity`, `kMul`, `kAdd`, `relative`,
`relSens`, `inverse`. The plan owns whatever it names in `AXIS_DEADZONE` and
`AXIS_PROPS` and preserves the rest, so the game's own calibration survives.

The vocabulary and the factory presets are inside `*.vromfs.bin`: zstd, with
the first and last sixteen bytes of the packed body XORed against fixed keys,
then a flat filesystem of name pointers and (offset, size) pairs. Factory
presets are binary `.blk` (marker `0x05`), zstd against a shared dictionary,
with key names from an archive-wide nametable.

## Measured

**Numbering is global across devices** and comes from `deviceMapping` in
`machine.blk`:

    WT axisId   = axesOffset + local axis
    WT joyButton = buttonsOffset + local button

**The offsets move.** They depend on what is plugged in and in what order, and
a Steam Controller puck can appear as one or two phantom "Microsoft X-Box 360
pad" entries that shift everything after them. The game renumbers existing
bindings correctly when this happens; the tool reads the offsets live rather
than assuming them.

**Helicopter actions are named inconsistently.** Most carry an `_HELICOPTER`
suffix, a few an `ID_HELICOPTER_` prefix, and an action with no twin in either
form applies to aircraft *and* helicopters. `contexts()` is the only place that
knows this; a clash it reports stops the run rather than letting the game drop
one binding silently.

**`ID_TRIM` is auto-trim**, not a trim step: it converts the current stick
deflection into trim and re-centres the controls. The stepped actions are
`ID_TRIM_ELEVATOR_PLUS/MINUS` and friends, and they live in a different section
of the controls menu.

**Rudder deadzone is widened to 0.10** in `AXIS_DEADZONE` as a stopgap until
pedals arrive; `helicopter_pedals` is deliberately left at 0.02, because heli
yaw is held continuously where a plane's rudder is tapped.

## Still a guess

**Which way `ID_TRIM_ELEVATOR_PLUS` moves the nose.** The English is
"Positive", the Polish "Trym steru wysokości w górę", and the aileron strings
name the effect direction — so PLUS is probably nose up, which would make War
Thunder the odd one out against DCS and BMS. Swap PLUS and MINUS in `NEEDS` if
the nose rises when the hat goes forward.

## Gotchas

**The game rewrites `machine.blk` on exit.** The writer refuses while it is
running.

**`rudderMultiplier` and the other per-axis multipliers sit outside
`controls{}`**, so they are a slider in the game's own UI and survive
regeneration.

**Not every aircraft has trim.** The game has its own messages for it
(`No elevator trim control`, `Trim unavailable: elevator inoperative`), so a
trim binding doing nothing may be the airframe.

**The leading marker needs a locked target** in arcade, and the cockpit
gunsight suppresses the 2D HUD inside it. `ID_TOGGLE_COLLIMATOR` switches the
sight off and gives the plain crosshair back.

**Instructor settings override manual control.** `USEROPT_INSTRUCTOR_ENABLED`
and `enableInstructorSimpleJoy` make the game fly the aeroplane, and test
flights default to `USEROPT_DIFFICULTY:t="arcade"`; judge a layout in a
simulator battle.

# Elite Dangerous

Two tools on one writer:

    plan.py             lays a layout out from NEEDS and the device map
    ed-bind-wizard.py   a curses TUI that captures bindings off the devices

The plan hands its result to the TUI's own `generate()`, so there is one
implementation of the `.binds` format. They write different presets —
`Izowiuz-PLAN` and whatever you captured — so neither overwrites the other
and both can be selected in the game to compare.

## Where it lives

Steam app 359320, Proton. The vocabulary is a shipped preset; the output goes
into the prefix:

    ~/.local/share/Steam/steamapps/common/Elite Dangerous/
      Products/elite-dangerous-odyssey-64/ControlSchemes/
        KeyboardMouseOnly.binds     the base preset — every function's name

    ~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/
      steamuser/AppData/Local/Frontier Developments/Elite Dangerous/Options/
      Bindings/
        <preset>.4.2.binds          written
        StartPreset.4.start         which preset is selected — not written
        BindingLoadingErrors.log    the game's complaint if a preset is bad

    ED_DIR, --game-dir, --schemes-dir   the install; the Bindings folder is
                                        derived from it
    ED_PRESET, --preset                 which preset the plan writes
    -r FILE                             ed-bind-wizard-results.json, which
                                        remembers both paths after the first
                                        run

## How to run it

    ./harvest.py              vocabulary and the factory ranking
    ./harvest.py --grep word  functions matching a word
    ./harvest.py --json       cache it

    ./plan.py                 the layout
    ./plan.py --why           and the evidence for each choice
    ./plan.py --free          what stays unbound
    ./plan.py --sheet --html  the kneeboard
    ./plan.py --tui           walk the layout and write what you keep
    ./plan.py --write         all of it, into the Bindings folder

    ./ed-bind-wizard.py             the capture TUI
    ./ed-bind-wizard.py --reset     discard the results file
    ./ed-bind-wizard.py --generate  headless: write the captured preset

In the TUI: pick the base preset, then SHIP or SRV, then a mapping section or
ALL.

    arrows   move                    I     invert an axis
    RETURN   capture the next press  X     clear a binding
             or axis move, and step  ESC   back out
             to the next row

The results file is saved after every change.

Every function named in `NEEDS` is checked against the vocabulary before
anything runs. A function claimed by two needs is an error: Elite has one
element per function, so the second would quietly win.

## The format

`.binds` is plain XML, one element per function, named by the function rather
than by a hash:

    <Root PresetName="Izowiuz-VIRPIL" MajorVersion="4" MinorVersion="2">
      <KeyboardLayout>en-US</KeyboardLayout>
      <YawAxisRaw>
        <Binding Device="334443E8" Key="Joy_ZAxis" />
        <Inverted Value="0" />
        <Deadzone Value="0.00000000" />
      </YawAxisRaw>
      <UseBoostJuice>
        <Primary Device="33448196" Key="Joy_3" />
        <Secondary Device="Keyboard" Key="Key_Tab" />
      </UseBoostJuice>
    </Root>

Axes carry one `<Binding>`; buttons carry `<Primary>` and `<Secondary>`. The
file name must be `<PresetName>.4.2.binds` and match the `PresetName`
attribute.

Button keys are `Joy_<index+1>`. Axis keys use DirectInput's naming, not
Wine's HID one:

    ABS_X → Joy_XAxis       ABS_THROTTLE → Joy_UAxis
    ABS_RZ → Joy_RZAxis     ABS_RUDDER   → Joy_VAxis

## Measured

**`Device` is VID concatenated with PID**, uppercase hex, no separator —
VIRPIL's `3344` plus the product id, so the WarBRD is `334443E8` and the VMAX
`33448196`. Read from `/proc/bus/input/devices`, matched to the `js` handler.

**The base preset's keyboard binding is kept as a fallback.** Writing a HOTAS
binding moves whatever the base had onto `<Secondary>` rather than dropping
it, so keyboard control still works alongside.

**The vocabulary is the shipped `KeyboardMouseOnly.binds`** — every function
the game accepts a binding for is an element in it. There is no separate
action list to harvest.

**The ranking names the device too.** Of the thirty shipped presets, thirteen
are HOTAS rather than pad or keyboard, and five — X55, X56, Warthog, T16000M,
G940 — name the stick and the throttle as separate devices:

    13/13 on the throttle   boost, panel cycle, vertical thrusters
    13/13 on the stick      fire, target, the four power pips
    13/13 either            roll, pitch and throttle axes

**Several functions share one axis on purpose.** All four split HOTAS presets
bind `RollAxisRaw`, `BuggyRollAxisRaw` and `SteeringAxis` to the same stick
axis, and `ThrottleAxis` with `DriveSpeedAxis` to the same throttle axis. The
game decides by mode; a checker that flags it is wrong.

**The vocabulary is wider than the base preset.** `KeyboardMouseOnly.binds`
carries 369 bindable functions, the other presets name 24 more (`Humanoid*`,
the FSS camera buttons), and `NightVisionToggle` appears in none of the thirty
although the game accepts it. A function bound and verified by hand counts as
vouched for as well.

**SRV functions do not all say so.** Most carry a `_Buggy` suffix or a `Buggy`
prefix, but `SteeringAxis`, `DriveSpeedAxis` and `ToggleDriveAssist` are
SRV-only and name nothing. The context is declared in `AXIS_NEEDS` and in each
`Need`, never read off the name.

## Still a guess

**Whether the plan flies better than what was captured by hand.** The two
presets sit side by side in the game and have not been compared in flight. The
plan follows the factory ranking; the captured one differs — secondary fire on
the throttle rather than the stick, the panels left on the keyboard.

## Gotchas

**The preset is not selected by writing it.** `StartPreset.4.start` is the
game's record of the active preset and nothing here touches it, so a newly
written preset is chosen once in the game's own control options.

**The game's own backups cover only presets it wrote itself**,
as `<preset>.4.2.binds.<number>.backup` beside the file. Ours is copied into
`<repo>/backups/elite/<stamp>/` before it is regenerated; `--backup-dir` or
`SIM_BIND_BACKUPS` moves that elsewhere.

**`4.2` is the binds schema version**, not the game version. A game update
that bumps it makes existing presets invisible, and the filename suffix in the
writer has to follow.

**`BindingLoadingErrors.log` is the only diagnostic.** A preset the game
rejects is silently ignored in the UI; that file says why.

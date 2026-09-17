# Elite Dangerous

Two tools on one writer. `plan.py` lays a layout out from `NEEDS` and the
device map, the way the rest of the family does; `ed-bind-wizard.py` is a
curses TUI that captures bindings off the physical devices. The plan hands its
result to the TUI's own `generate()` in the shape the TUI produces, so there is
one implementation of the `.binds` format and not two.

They own different presets — the plan writes `Izowiuz-PLAN`, the TUI whatever
you captured — so neither overwrites the other and both can be selected in the
game to compare.

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

`--game-dir` sets the install and the Bindings folder is derived from it; both
are remembered in `ed-bind-wizard-results.json` (`-r` points elsewhere), so
they are passed once.

## How to run it

    ./harvest.py              vocabulary and the factory ranking
    ./harvest.py --grep word  functions matching a word
    ./harvest.py --json       cache it

    ./plan.py                 the layout
    ./plan.py --why           and the evidence for each choice
    ./plan.py --free          what stays unbound
    ./plan.py --sheet --html  the kneeboard
    ./plan.py --write         into the Bindings folder

    ./ed-bind-wizard.py             the capture TUI
    ./ed-bind-wizard.py --reset     discard the results file
    ./ed-bind-wizard.py -r other.json
    ./ed-bind-wizard.py --generate  headless: write the captured preset

`ED_PRESET` and `--preset` change which preset the plan writes; `ED_DIR` and
`--schemes-dir` override the install lookup. Every function named in `NEEDS`
is checked against the vocabulary before anything runs, and a function claimed
by two needs is an error — Elite has one element per function, so the second
would quietly win.

In the TUI: pick the base preset, then SHIP or SRV, then a mapping section or
ALL. Arrows move, RETURN captures the next press or axis movement and steps to
the next row, `I` inverts an axis, `X` clears a binding, ESC backs out. The
results file is saved after every change.

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
Wine's HID one: `ABS_X → Joy_XAxis`, `ABS_RZ → Joy_RZAxis`,
`ABS_THROTTLE → Joy_UAxis`, `ABS_RUDDER → Joy_VAxis`.

## Measured

**`Device` is VID concatenated with PID**, uppercase hex, no separator —
VIRPIL's `3344` plus the product id, so the WarBRD is `334443E8` and the VMAX
`33448196`. Read from `/proc/bus/input/devices`, matched to the `js` handler.

**The base preset's keyboard binding is kept as a fallback.** Writing a HOTAS
binding moves whatever the base had onto `<Secondary>` rather than dropping it,
so keyboard control still works alongside.

**The vocabulary is the shipped `KeyboardMouseOnly.binds`** — every function
the game accepts a binding for is an element in it. There is no separate action
list to harvest.

**The ranking is real, and it says which device too.** Elite ships thirty
presets. Thirteen are HOTAS rather than pad or keyboard, and five of those —
the X55, X56, Warthog, T16000M and G940 — name the stick and the throttle as
separate devices, so they answer both "does this matter" and "where does it
go". Roll, pitch and throttle axes are 13/13; boost, the panel cycle and
vertical thrusters are 13/13 on the throttle; fire, target and the four power
pips are 13/13 on the stick.

**Several functions share one axis on purpose.** All four split HOTAS presets
bind `RollAxisRaw`, `BuggyRollAxisRaw` and `SteeringAxis` to the same stick
axis, and `ThrottleAxis` with `DriveSpeedAxis` to the same throttle axis. The
game decides by mode, so this is the design rather than a clash — a checker
that flags it is wrong.

**The vocabulary is wider than the base preset.** `KeyboardMouseOnly.binds`
carries 369 bindable functions, the other presets name 24 more (`Humanoid*`,
the FSS camera buttons), and `NightVisionToggle` appears in none of the thirty
although the game accepts it and it works. So a function bound and verified by
hand counts as vouched for as well.

**SRV functions do not all say so.** Most carry a `_Buggy` suffix or a `Buggy`
prefix, which is War Thunder's rule exactly — but `SteeringAxis`,
`DriveSpeedAxis` and `ToggleDriveAssist` are SRV-only and name nothing. So the
context is declared in `AXIS_NEEDS` and in each `Need`, never read off the
name.

## Still a guess

**Whether the plan flies better than what was captured by hand.** The two
presets sit side by side in the game and have not been compared in flight. The
plan follows the factory ranking; the captured one follows what felt right,
and it differs — secondary fire on the throttle rather than the stick, the
panels left on the keyboard.

## Gotchas

**The preset is not selected by writing it.** `StartPreset.4.start` is the
game's record of the active preset and the wizard does not touch it, so a
newly written preset is chosen once in the game's own control options.

**The game keeps its own backups** as `<preset>.4.2.binds.<number>.backup`
next to the file.

**A button pressed while the wizard asked for an axis used to be stored as a
button.** Elite's copy of `wait_input` had lost the `and not want_axis` gate
the DCS one kept, so the record came back `{"type": "button"}` against an
axis-kind function and the generator wrote `<Primary Key="Joy_N">` under an
axis element — which the game silently ignores. The merged
`core.capture.wait_input` keeps DCS's gate and Elite's `sign`.

**`4.2` is the binds schema version**, not the game version. A game update that
bumps it makes existing presets invisible, and the filename suffix in the
writer has to follow.

**`BindingLoadingErrors.log` is the only diagnostic.** A preset the game
rejects is silently ignored in the UI; that file says why.

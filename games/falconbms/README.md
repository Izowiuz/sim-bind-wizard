# Falcon BMS

## Where it lives

BMS installs *inside* Falcon 4.0's Proton prefix, not as a Steam app:

    ~/.local/share/Steam/steamapps/compatdata/429530/pfx/
      drive_c/Falcon BMS 4.38/
        User/Config/BMS - Full.key        shipped, the vocabulary
        User/Config/BMS - VIRPIL.key      written by --write
        User/Config/DeviceDefaults.txt    axis mapping, per device GUID
        User/Config/DeviceSorting.txt     device order, fixes DX numbering
        User/Config/Viper.pop             holds the selected keyfile's name
        User/Config/axismapping.dat       binary; rebuilt from DeviceDefaults
        Hotas/Archive/*.key               22 vendor profiles, the ranking
        Launcher/FalconBMS_Alternative_Launcher.exe   axes and keymapping UI
        Launcher.exe                      Play / Config only, no bindings

    BMS_DIR, --bms-dir   the install, instead of the lookup

Launch with `~/.local/bin/falcon-bms` (`game`, `launcher`, `mainlauncher`,
`config`).

## How to run it

    ./harvest.py             vocabulary, ranking, device DX offsets
    ./plan.py                the layout
    ./plan.py --why          and the evidence for each choice
    ./plan.py --audit        ranked callbacks not placed
    ./plan.py --free         what is unbound
    ./plan.py --sheet --html the kneeboard
    ./plan.py --tui          walk the layout and write what you keep
    ./plan.py --write        writes BMS - VIRPIL.key
    ./plan.py --write-axes   writes DeviceDefaults.txt, moves the binary aside

    --backup-dir DIR   where both writes copy what they replace, one folder
                       for the pair (default <repo>/backups/falconbms/<stamp>/;
                       SIM_BIND_BACKUPS does the same)

`axismapping.dat` is *moved* into the backup, not renamed in place: BMS
rebuilds it from `DeviceDefaults.txt` only if it is gone.

Then in the game: Setup → Controllers → LOAD → "BMS - VIRPIL", and leave with
**OK** or **APPLY**.

## The format

Key files are plain text, latin-1, CRLF. A full line is nine fields:

    SimRingCommMenu -1 0 0X2B 0 0 0 1 "UI: Ring Comm Menu"
    callback  sound  -  key  mod  combo  combo_mod  flag  "description"

    flag   1  a real binding          -1  a SimDoNothing section header
          -0  hardcoded or REM:       -2  developer-only

DX bindings are separate, shorter lines appended to the same file:

    SimTriggerFirstDetent 0 -1 -2 0 0x0 -1
    callback  dx  sound  kind  press  hex  sound2

    kind  -2  a button    -3  a POV hat

Nothing here writes `-3`: VIRPIL firmware reports no HID hat usages, so every
hat is a set of plain buttons.

Press and release are separate bindings. `-2` in the sound field opts in, and
the sixth field selects the edge:

    SimSelectMRMOverride  50 -2 -2 0    0x0 -1    entering the position
    SimDeselectOverride   50 -2 -2 0x42 0x0 -1    leaving it

Axes go through `DeviceDefaults.txt`, keyed by a GUID built from the USB id as
`{PID}{VID}-0000-0000-0000-504944564944`. HID `Slider` and `Dial` both land on
DirectInput's slider axes, numbered in report-descriptor order, so
`dinput_axis()` counts through the fingerprint rather than reading `hid` alone.

## Measured

32 DX numbers per device, assigned by `DeviceSorting.txt` order:

    DX  0-31   3344:43e8   R-VPC Stick WarBRD-D
    DX 32-63   3344:8196   L-VPC VMAX Prime Throttle

The VMAX has 51 buttons, so its last nineteen — T2 down, T3–T5, APU, both
encoders, the mode selector — have no DX number, and `usable()` refuses to
place anything on them. `g_nButtonsPerDevice` raises the limit to as much as
128 for every device at once, renumbering all DX ids; not set here.

**The pinky-shifted layer** adds `g_nHotasPinkyShiftMagnitude` (256) to a DX
number. Used for seven needs that do not fit unshifted.

**The Alternative Launcher, not `Launcher.exe`**, holds Axis Assignment and
Keymapping. It is a WPF application and renders a black window under Wine
without:

    [HKEY_CURRENT_USER\Software\Microsoft\Avalon.Graphics]
    "DisableHWAcceleration"=dword:00000001

**The selected keyfile** is a plain string in the pilot profile:
`strings Viper.pop | grep "BMS -"`.

## Still a guess

**Master arm sits on the trigger lever**, whose two contacts are one per
position. Which contact is the closed lever was not measured; if the jet arms
with the lever down, swap `SimSafeMasterArm` and `SimArmMasterArm` in `NEEDS`.

**Trim direction.** BMS names trim after the wheel, not the nose:
`AFElevatorTrimUp` is nose *down*. Untested in flight.

## Gotchas

**Only OK or APPLY persists.** Changes in the Controllers screen take effect
immediately in the session regardless, and Cancel rolls nothing back
(Technical Manual 10.7.5).

**The game writes the working copy.** Binding something in the menu lands in
whichever keyfile is loaded; check what changed before concluding anything.

**`DeviceDefaults.txt` cannot express direction.** Its syntax is
`AXIS_PITCH = Y` — which physical axis, never which way. Reverse, deadzone and
saturation are per-axis controls in Advanced Options only.

**SET AB.** Left-click sets the afterburner detent, right-click the idle
detent. Without the first there is no afterburner. CENTER, stick released,
zeroes pitch and roll.

**An axis already assigned disappears from every other dropdown**: BMS allows
one physical axis per in-game axis.

**Roll trim is not on the HOTAS.** The F-16 grip has four hats and the WarBRD
has three; TMS, DMS and CMS take them and trim gets the stick encoder, pitch
only.

**Eject is not bound.** Twenty of the twenty-two vendor profiles put it on the
shifted layer; no button here is awkward enough to be safe.

**Files are CRLF.** Writing LF rewrites the whole file and makes the backup
useless for seeing what changed. `read_keeping`/`write_keeping` preserve it.

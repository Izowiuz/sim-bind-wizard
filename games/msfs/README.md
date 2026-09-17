# MSFS 2024

## Where it lives

Profiles are Steam Cloud saves, not files in the install:

    ~/.local/share/Steam/userdata/<steam id>/2537590/remote/
      inputprofile_<n>        two per device

The install supplies the ranking:

    .../steamapps/common/MSFS2024/Packages/
      asobo-input-profiles-pc/InputProfiles/Categories/    551 shipped profiles

## How to run it

    ./harvest.py              vocabulary and per-category ranking
    ./plan.py                 the layout
    ./plan.py --why           and the evidence for each choice
    ./plan.py --sheet --html  the kneeboard
    ./plan.py --write         into the profiles (close Steam first)
    ./plan.py --write --backup-dir PATH

Backups default to `~/OneDrive/backups/save-backup/MSFS24`.

## The format

Plain XML. Each device has **two** profiles and which one an action belongs in
is decided by a single element:

    with    <AircraftInfo CategoryName="AIRPLANE"/>   flight controls, aeroplane
                                                      and helicopter actions
    without                                           global: camera, ATC, UI

A device is identified by `ProductID`, decimal, equal to the USB PID.

Writing is text surgery on the existing file, not XML reserialisation, so
untouched entries stay byte-identical.

## Measured

**Buttons are one-based in the label and zero-based in the code.**
`Joystick Button N` carries code `N-1`.

**Axis codes** are fixed per DirectInput axis:

    X   Joystick L-Axis X  1026      Rx  Joystick R-Axis X   770
    Y   Joystick L-Axis Y  1042      Ry  Joystick R-Axis Y   786
    Z   Joystick L-Axis Z  1058      Rz  Joystick R-Axis Z   802
    Slider  Joystick Slider X  514   Dial  Joystick Slider Y  530

`Dial` is `Slider Y`, code 530 — the VMAX's rotary, distinct from its slider.

## Still a guess

Nothing load-bearing.

## Gotchas

**Steam must be closed to write.** It syncs these files from the cloud and will
overwrite what the tool writes. `plan.py --write` refuses while it is running.

**Both profiles of a device matter.** An action put in the wrong one is
accepted and never fires; `find_profiles()` decides by the `AircraftInfo`
element rather than by filename.

**`Look around` binds nothing.** It exists to reserve the mini-stick so a
button need cannot take it; the head-look axes themselves come from
`axis_plan()`.

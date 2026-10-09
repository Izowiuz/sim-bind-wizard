# DCS World

What is peculiar to this game.

## One module at a time

A module's commands are its own. The Hornet's 849 are not the Su-25T's. A
cockpit command's id is per module, so the same name in another module
means something else.

`-a` picks the module. The default is `FA-18C`. Each module gets its own
cache, its own needs file, its own binds file and its own kneeboard.

## Two sources for the command list

| source | what it gives |
|---|---|
| the module's `default.lua` | every command, with its name, kind and category |
| the factory `*.diff.lua` | the engine commands' hashes |

`default.lua` goes through a `lua` or `luajit` binary with the game's
globals stubbed out. Without such a binary the list falls back to the
factory profiles. That gives fewer commands and whatever names their
authors used.

An engine command's id lives in the executable. The only place to find the
hash for `Gear Up` is therefore a profile that binds it. Those ids are
global, so any module's factory profiles will do.

A cockpit command is left out of that index on purpose. Its id is per
module.

## The save folder is not the module folder

A module's `entry.lua` spells both out side by side. They differ often
enough to matter. The Hornet reads its user profiles from
`Config/Input/FA-18C_hornet`. Its factory profiles sit under
`Input/FA-18C`.

## One diff.lua per device

The writer writes one `<device>.diff.lua`. The file name is the
`Device {GUID}` string DCS writes, and the device map holds it as the
device's `dcs` game id.

DCS writes that string into `dcs.log` as `created [...] with full id
[...]`. Put it on the device in `sim-device-map`. The writer refuses to
run without it.

The serializer is byte compatible with DCS's own: sorted keys, tab indent,
no trailing newline. A file the game rewrites therefore comes back
identical.

## DCS binds every joystick it sees

`DefaultAssignments.lua` and `base_joystick_binding.lua` put these on
every joystick device:

| command | key |
|---|---|
| Pitch | `JOY_Y` |
| Roll | `JOY_X` |
| Rudder | `JOY_RZ` |
| Thrust | `JOY_Z` |
| Weapon Fire | `JOY_BTN1` |
| Weapon Change | `JOY_BTN4` |
| Cannon | `JOY_BTN5` |

A stick and a throttle therefore fight over the same axis. The writer
removes these wherever they collide.

## Axis tuning

Three commands get a curvature and a deadzone. The values are Eagle
Dynamics' own, from their VPC WarBRD profile.

| command | curvature | deadzone |
|---|---|---|
| Pitch | 0.12 | 0.03 |
| Roll | 0.12 | 0.03 |
| Rudder | 0.15 | 0.05 |

Tune them in the game under Axis Tune.

A command whose name starts with `Thrust` is marked as a slider.

## The categories say two different things

A category is the module author's own word. Two kinds of word appear in
it.

Some name a place in the cockpit. `Instrument Panel` and `Left Console`
say where a switch is. They say nothing about what it does.

Some name the device the real aircraft keeps it on. Measured against a
hand-written Hornet list: `Throttle Grip` 14 of 14, `Stick` 7 of 7. `Z`
reads the device off those.

Eight categories name a job: `Communications`, `VHF Radio`,
`Countermeasures`, `Weapons`, `Autopilot`, `Rear Warning Radar`,
`Engine Control Panel` and `Fuel Control`.

## Gotchas

DCS rewrites `Config/Input` when it exits. Close the game before a write.

The cache is read rather than the game, so `plan.py` opens on a clone with
no game installed.

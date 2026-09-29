# Kneeboard Falcon BMS

Falcon BMS · F-16C · VIRPIL. Generated — do not edit, regenerate.

## Axes

| Control | DX | Does |
|---|---|---|
| Main stick | `X` | AXIS_ROLL |
| Main stick | `Y` | AXIS_PITCH |
| Main stick | `Z` | AXIS_YAW |
| Left throttle lever | `RX` | AXIS_THROTTLE |
| Analogue brake lever on the grip | `SLIDER0` | AXIS_BRAKE_LEFT |
| Side lever | `RZ` | AXIS_ANT_ELEV |
| Thumb mini-stick | `X` | AXIS_CURSOR_X |
| Thumb mini-stick | `Y` | AXIS_CURSOR_Y |
| Left side dial | `SLIDER0` | AXIS_FOV |

## Buttons

### R-VPC Stick WarBRD-D  (DX 0–31)

| DX | Control | Does | Binding |
|---|---|---|---|
| 0 | Trigger initial lever — press | Master arm | `SimArmMasterArm` |
| 1 | Trigger initial lever — press | Master arm | `SimSafeMasterArm` |
| 2 | Main trigger — first | Trigger | `SimTriggerFirstDetent` |
| 3 | Main trigger — second | Trigger | `SimTriggerSecondDetent` |
| 6 | Thumb top button — press | NWS / AR DISC / MSL STEP | `SimMissileStep` |
| 7 | Top thumb hat — push | Stores config (CAT I / III) | `SimCATSwitch` |
| 8 | Top thumb hat — up | TMS — target management | `SimTMSUp` |
| 9 | Top thumb hat — left | TMS — target management | `SimTMSLeft` |
| 10 | Top thumb hat — down | TMS — target management | `SimTMSDown` |
| 11 | Top thumb hat — right | TMS — target management | `SimTMSRight` |
| 12 | Thumb bottom button — press | Paddle — AP / trim disconnect | `SimAPOverride` |
| 14 | Bottom thumb hat — up | CMS — countermeasures | `SimCMSUp` |
| 15 | Bottom thumb hat — left | CMS — countermeasures | `SimCMSLeft` |
| 16 | Bottom thumb hat — down | CMS — countermeasures | `SimCMSDown` |
| 17 | Bottom thumb hat — right | CMS — countermeasures | `SimCMSRight` |
| 18 | Stick encoder and click — push | Trim — pitch | `AFResetTrim` |
| 20 | Stick encoder and click — cw | Trim — pitch | `AFElevatorTrimUp` |
| 21 | Stick encoder and click — ccw | Trim — pitch | `AFElevatorTrimDown` |
| 23 | Grip thumb hat — up | DMS — display management | `SimDMSUp` |
| 24 | Grip thumb hat — left | DMS — display management | `SimDMSLeft` |
| 25 | Grip thumb hat — down | DMS — display management | `SimDMSDown` |
| 26 | Grip thumb hat — right | DMS — display management | `SimDMSRight` |
| 30 | Grip pinky button — press | Weapon release (Pickle) | `SimPickle` |
| 276 | Stick encoder and click — cw | MAN RANGE knob | `SimRangeKnobUp` |
| 277 | Stick encoder and click — ccw | MAN RANGE knob | `SimRangeKnobDown` |

### L-VPC VMAX Prime Throttle  (DX 32–63)

| DX | Control | Does | Binding |
|---|---|---|---|
| 32 | Pinky button — press | Laser arm | `SimLaserArmToggle` |
| 33 | Left side dial — push | Slap switch (ECM) | `SimSlapSwitch` |
| 34 | Middle finger button — press | Look closer | `FOVToggle` |
| 35 | Middle finger hat — push | DX shift (pinky) | `SimHotasPinkyShift` |
| 36 | Middle finger hat — up | SPD BRAKE switch | `AFBrakesIn` |
| 38 | Middle finger hat — down | SPD BRAKE switch | `AFBrakesOut` |
| 40 | Right side dial — push | Landing / taxi lights | `SimLandingLightCycle` |
| 42 | Thumb two-way hat — fwd | DOGFIGHT / MRM override | `SimSelectMRMOverride<br>release: `SimDeselectOverride`` |
| 44 | Thumb two-way hat — aft | DOGFIGHT / MRM override | `SimSelectSRMOverride<br>release: `SimDeselectOverride`` |
| 46 | Thumb mini-stick — push | Radar cursor (slew) | `SimCursorEnable` |
| 47 | Thumb button — press | MAN RANGE knob — UNCAGE | `SimToggleMissileCage` |
| 48 | Bottom thumb button — press | Radar cursor zero | `SimRadarCursorZero` |
| 50 | Thumb hat — up | COMMS switch | `SimTransmitCom1` |
| 51 | Thumb hat — right | COMMS switch | `SimCommsSwitchRight` |
| 52 | Thumb hat — down | COMMS switch | `SimTransmitCom2` |
| 53 | Thumb hat — left | COMMS switch | `SimCommsSwitchLeft` |
| 54 | Keyboard B1 button — press | Air refuelling door | `SimFuelDoorToggle` |
| 55 | Keyboard B2 button — press | AVTR | `SimAVTRToggle` |
| 56 | Keyboard B3 button — press | Night vision | `ToggleNVGMode` |
| 57 | Keyboard B4 button — press | ICP — NAV mode | `SimICPNav` |
| 58 | Keyboard B5 button — press | Canopy | `AFCanopyToggle` |
| 59 | Keyboard B6 button — press | Visor | `SimVisorToggle` |
| 60 | Big red button — press | Recentre head tracking | `RecenterTrackIR` |
| 61 | T1 rocker — up | ICP — master mode | `SimICPAA` |
| 62 | T1 rocker — down | ICP — master mode | `SimICPAG` |
| 298 | Thumb two-way hat — fwd | Landing gear | `AFGearUp` |
| 300 | Thumb two-way hat — aft | Landing gear | `AFGearDown` |
| 317 | T1 rocker — up | Parking brake | `SimParkingBrakeUp` |
| 318 | T1 rocker — down | Parking brake | `SimParkingBrakeDown` |

## Check on the ramp

- **Master arm** — it is on the trigger lever, so the guard position IS the switch position. Which of the two contacts is the closed lever was never measured — if the jet arms with the lever down, swap the two names in NEEDS and regenerate.
- **Trim** — BMS names trim after the wheel, not the nose: <code>AFElevatorTrimUp</code> is nose DOWN.
- **DOGFIGHT switch** — hold it forward for MRM, back for dogfight, let go and it should cancel. The cancel is the release edge — no other sim of the four can express it.

## Where the hardware and the jet disagree

- **Roll trim** — the F-16 grip has four hats and the WarBRD has three, so TMS, DMS and CMS take them and trim gets the encoder: pitch only. Roll trim stays on the keyboard.
- **Eject** — not bound. Twenty of the twenty-two vendor profiles hide it on the pinky-shifted layer; we do not use that layer, and no button here is awkward enough to be safe.
- **Zoom** — on the dial, which rests centred rather than at zero — so the view may start part-zoomed. The price of the same dial carrying zoom in DCS and War Thunder too.
- **Axis direction** — not ours to set. <code>DeviceDefaults.txt</code> says <i>which</i> physical axis, never <i>which way</i> — so walk the four Advanced Options tabs, move each control, watch its value bar and hit <b>Reverse</b> where it runs backwards. Pitch almost certainly needs it.
- **SET AB** — on the Controllers page: left-click sets the afterburner detent, right-click the idle detent. Without the first there is no afterburner. <b>CENTER</b>, stick released, zeroes pitch and roll.
- **A missing axis** — is usually assigned already — BMS allows one physical axis per in-game axis, so an axis in use vanishes from every other dropdown. Check all four tabs before concluding a device is dead.

## Picking it up

falcon-bms launcher → Keyfile → "BMS - VIRPIL". Regenerate with ./plan.py --write; never hand-edit.

## Not placed

- JFS — engine start (wanted a `hat2`)
- Throttle idle detent (wanted a `hat2`)
- Radar gain (wanted a `encoder`)
- IFF MASTER knob (wanted a `selector`)

## Still free

- Main stick (stick) — no buttons
- Mini-stick (stick) — 5
- Analogue brake lever on the grip (stick) — no buttons
- Left throttle lever (throttle) — no buttons
- Right throttle lever (throttle) — no buttons
- Side lever (throttle) — no buttons
- T2 rocker (throttle) — 63, 64
- T3 rocker (throttle) — 65, 66
- T4 rocker (throttle) — 67, 68
- T5 rocker (throttle) — 69, 70
- APU button (throttle) — 71
- E1 encoder (throttle) — 73, 74, 72
- E2 encoder (throttle) — 77, 76, 75
- Mode selector (throttle) — 82, 81, 80, 79, 78


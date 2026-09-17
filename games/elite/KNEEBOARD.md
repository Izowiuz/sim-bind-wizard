# Kneeboard Elite Dangerous

Elite Dangerous · VIRPIL. Generated — do not edit, regenerate.

## Axes

| Control | Joy | Does |
|---|---|---|
| Main stick, left/right | `axis 0` | Ship: Roll axis raw |
| Main stick, fore/aft | `axis 1` | Ship: Pitch axis raw (inverted) |
| Stick twist | `axis 2` | Ship: Yaw axis raw |
| Left throttle lever | `axis 2` | Ship: Throttle axis |
| Thumb mini-stick | `axis 0` | Ship: Lateral thrust raw |
| Thumb mini-stick | `axis 1` | Ship: Vertical thrust raw |
| Main stick, left/right | `axis 0` | SRV: Buggy roll axis raw |
| Main stick, fore/aft | `axis 1` | SRV: Buggy pitch axis (inverted) |
| Main stick, left/right | `axis 0` | SRV: Steering axis |
| Left throttle lever | `axis 2` | SRV: Drive speed axis |
| Mini-stick | `axis 3` | Ship: Cam translate x axis |
| Mini-stick | `axis 4` | Ship: Cam translate y axis |

## Buttons

### R-VPC Stick WarBRD-D

| Joy | Control | Ship | SRV |
|---|---|---|---|
| Joy_15 | Bottom thumb hat — up | Cycle fire group next | — |
| Joy_17 | Bottom thumb hat — down | Cycle fire group previous | — |
| Joy_14 | Bottom thumb hat — push | Galaxy map open | Galaxy map open buggy |
| Joy_18 | Bottom thumb hat — right | System map open | System map open buggy |
| Joy_31 | Grip pinky button — press | Ship spot light toggle | Headlights buggy button |
| Joy_27 | Grip thumb hat — right | Cycle next target | — |
| Joy_25 | Grip thumb hat — left | Cycle previous target | — |
| Joy_3 | Main trigger — first | Primary fire | Buggy primary fire button |
| Joy_13 | Thumb bottom button — press | Select target | Select target buggy |
| Joy_7 | Thumb top button — press | Secondary fire | Buggy secondary fire button |
| Joy_9 | Top thumb hat — up | Increase systems power | Increase systems power buggy |
| Joy_12 | Top thumb hat — right | Increase weapons power | Increase weapons power buggy |
| Joy_11 | Top thumb hat — down | Reset power distribution | Reset power distribution buggy |
| Joy_10 | Top thumb hat — left | Increase engines power | Increase engines power buggy |
| Joy_8 | Top thumb hat — push | Select highest threat | — |

### L-VPC VMAX Prime Throttle

| Joy | Control | Ship | SRV |
|---|---|---|---|
| Joy_40 | APU button — press | Exploration FSS discovery scan | — |
| Joy_29 | Big red button — press | Eject all cargo | Eject all cargo buggy |
| Joy_17 | Bottom thumb button — press | Deploy heat sink | — |
| Joy_23 | Keyboard B1 button — press | Toggle flight assist | Toggle drive assist |
| Joy_24 | Keyboard B2 button — press | Landing gear toggle | — |
| Joy_25 | Keyboard B3 button — press | Toggle cargo scoop | Toggle cargo scoop buggy |
| Joy_26 | Keyboard B4 button — press | Toggle reverse throttle input | Buggy toggle reverse throttle input |
| Joy_27 | Keyboard B5 button — press | Hyper super combination | — |
| Joy_28 | Keyboard B6 button — press | Set speed zero | — |
| Joy_2 | Left side dial — push | Head look reset | — |
| Joy_3 | Middle finger button — press | Deploy hardpoint toggle | — |
| Joy_1 | Pinky button — press | Use boost juice | — |
| Joy_9 | Right side dial — push | Night vision toggle | — |
| Joy_30 | T1 rocker — up | Cycle next panel | — |
| Joy_31 | T1 rocker — down | Cycle previous panel | — |
| Joy_32 | T2 rocker — up | Cycle next page | — |
| Joy_33 | T2 rocker — down | Cycle previous page | — |
| Joy_34 | T3 rocker — up | Cycle next subsystem | — |
| Joy_35 | T3 rocker — down | Cycle previous subsystem | — |
| Joy_36 | T4 rocker — up | Radar increase range | — |
| Joy_37 | T4 rocker — down | Radar decrease range | — |
| Joy_16 | Thumb button — press | Cycle next hostile target | — |
| Joy_15 | Thumb mini-stick — push | Fire chaff launcher | — |
| Joy_10 | Thumb two-way hat — push | Use shield cell | — |

## Writing it

- **Preset** — Izowiuz-PLAN — the capture TUI owns whatever you bound by hand, so neither overwrites the other.
- **Selecting it** — Elite records the active preset in StartPreset.4.start, which nothing here writes: choose it once in the game's control options.
- **Contexts** — A function name carries its own context — an SRV binding is a `_Buggy` suffix or a `Buggy` prefix — so one control means both without clashing.
- **Ranking** — Counted from the 13 HOTAS presets Elite ships, five of which name the stick and the throttle separately and so say which device a function belongs on.

## Still free

- Mini-stick (stick) — no buttons
- Trigger initial lever (stick) — no buttons
- Stick encoder and click (stick) — no buttons
- Analogue brake lever on the grip (stick) — no buttons
- Middle finger hat (throttle) — no buttons
- Thumb hat (throttle) — no buttons
- T5 rocker (throttle) — no buttons
- E1 encoder (throttle) — no buttons
- E2 encoder (throttle) — no buttons
- Mode selector (throttle) — no buttons


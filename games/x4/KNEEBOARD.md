# Kneeboard X4

X4 Foundations · VIRPIL. Generated — do not edit, regenerate.

## Axes

| Control | Code | Does |
|---|---|---|
| Main stick, left/right | `X` | Ship: Steering primary |
| Main stick, fore/aft | `Y` | Ship: Steering pitch |
| Stick twist | `Z` | Ship: Steering secondary |
| Mini-stick | `RX` | Ship: Strafe left right |
| Mini-stick | `RY` | Ship: Strafe up down |
| Left throttle lever | `RX` | Ship: Throttle |
| Side lever | `RZ` | Map: Map zoom in |
| Thumb mini-stick | `X` | Map: Map pan left right |
| Thumb mini-stick | `Y` | Map: Map pan up down |
| Mini-stick | `RX` | On foot: FP yaw |
| Mini-stick | `RY` | On foot: FP pitch |
| Main stick, fore/aft | `Y` | On foot: FP walk |
| Main stick, left/right | `X` | On foot: FP strafe |

## Buttons

### R-VPC Stick WarBRD-D

| Code | Control | Ship | Map | On foot |
|---|---|---|---|---|
| 15 | Bottom thumb hat — up | Cycle next primary weapongroup | — | — |
| 17 | Bottom thumb hat — down | Cycle prev primary weapongroup | — | — |
| 14 | Bottom thumb hat — push | Open playership info | — | — |
| 18 | Bottom thumb hat — right | Open missions | — | — |
| 16 | Bottom thumb hat — left | Quicksave | — | — |
| 31 | Grip pinky button — press | Deselect target | Map back | — |
| 24 | Grip thumb hat — up | Next target action | — | — |
| 26 | Grip thumb hat — down | Prev target action | — | — |
| 23 | Grip thumb hat — push | Pause | — | — |
| X | Main trigger — first | Fire primary weapon | — | — |
| 13 | Thumb bottom button — press | Target next enemy | — | — |
| BACK | Thumb top button — press | Fire secondary weapon | — | — |
| LEFT_THUMB | Top thumb hat — up | Strafe up | — | — |
| RIGHT_THUMB | Top thumb hat — left | Strafe left | — | — |
| BIGBUTTON | Top thumb hat — down | Strafe down | — | — |
| 12 | Top thumb hat — right | Strafe right | — | — |
| START | Top thumb hat — push | Open cockpit menu | — | — |

### L-VPC VMAX Prime Throttle

| Code | Control | Ship | Map | On foot |
|---|---|---|---|---|
| 40 | APU button — press | Open map | — | — |
| 29 | Big red button — press | Toggle SETA mode | — | — |
| 17 | Bottom thumb button — press | Match speed | — | — |
| 23 | Keyboard B1 button — press | Toggle travel mode | — | — |
| 24 | Keyboard B2 button — press | Toggle flight assist | — | — |
| 25 | Keyboard B3 button — press | Toggle autopilot | — | — |
| 26 | Keyboard B4 button — press | Toggle scan mode | — | — |
| 27 | Keyboard B5 button — press | Toggle longrange scan mode | — | — |
| 28 | Keyboard B6 button — press | Scan action | — | — |
| B | Left side dial — push | Comm action | — | — |
| X | Middle finger button — press | Target next target | Map select | — |
| LEFT_SHOULDER | Middle finger hat — up | Cockpit view | Map reset position | — |
| RIGHT_SHOULDER | Middle finger hat — right | Target view | — | — |
| BACK | Middle finger hat — down | External view | Map reset rotation | — |
| START | Middle finger hat — left | Cycle view | — | — |
| 48 | Mode selector — 4 | — | — | — |
| 49 | Mode selector — 3 | — | — | — |
| 50 | Mode selector — 2 | — | — | — |
| 51 | Mode selector — 1 | — | Map pan to rotate | — |
| A | Pinky button — press | Boost | — | FP run |
| LEFT_THUMB | Right side dial — push | Zoomgoggles | — | — |
| 30 | T1 rocker — up | Dock action | — | — |
| 31 | T1 rocker — down | Undock | — | — |
| 32 | T2 rocker — up | Next subcomponent | — | — |
| 33 | T2 rocker — down | Prev subcomponent | — | — |
| 34 | T3 rocker — up | — | — | FP jump |
| 35 | T3 rocker — down | — | — | FP crouch |
| 16 | Thumb button — press | Deploy countermeasure | — | — |
| BIGBUTTON | Thumb two-way hat — forward | Cycle next secondary weapongroup | — | — |
| 13 | Thumb two-way hat — back | Cycle prev secondary weapongroup | — | — |

## Writing it

- **Profile** — inputmap_3.xml — X4 puts menu edits in inputmap.xml, so a named profile is the only place this survives.
- **Slots** — stick = 2, throttle = 3. Enumeration order, not stable: re-read after plugging something in.
- **Contexts** — X4 scopes a binding by which id it is — MAP_* answers only in the map, FP_* only on foot — so one button carries three without clashing.

## Still free

- Mini-stick (stick) — no buttons
- Trigger initial lever (stick) — no buttons
- Stick encoder and click (stick) — no buttons
- Analogue brake lever on the grip (stick) — no buttons
- Thumb mini-stick (throttle) — no buttons
- Thumb hat (throttle) — no buttons
- T4 rocker (throttle) — no buttons
- T5 rocker (throttle) — no buttons
- E1 encoder (throttle) — no buttons
- E2 encoder (throttle) — no buttons


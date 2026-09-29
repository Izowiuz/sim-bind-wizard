# Kneeboard X4

X4 Foundations · VIRPIL. Generated — do not edit, regenerate.

## Axes

| Control | Code | Does |
|---|---|---|
| Main stick | `X` | Ship: Steering primary |
| Main stick | `Y` | Ship: Steering pitch |
| Main stick | `Z` | Ship: Steering secondary |
| Mini-stick | `RX` | Ship: Strafe left right |
| Mini-stick | `RY` | Ship: Strafe up down |
| Left throttle lever | `RX` | Ship: Throttle |
| Side lever | `RZ` | Map: Map zoom in |
| Thumb mini-stick | `X` | Map: Map pan left right |
| Thumb mini-stick | `Y` | Map: Map pan up down |
| Mini-stick | `RX` | On foot: FP yaw |
| Mini-stick | `RY` | On foot: FP pitch |
| Main stick | `Y` | On foot: FP walk |
| Main stick | `X` | On foot: FP strafe |

## Buttons

### R-VPC Stick WarBRD-D

| Code | Control | Ship | Map | On foot |
|---|---|---|---|---|
| 15 | Bottom thumb hat — up | Cycle next primary weapongroup | — | — |
| 17 | Bottom thumb hat — down | Cycle prev primary weapongroup | — | — |
| 14 | Bottom thumb hat — push | Deploy countermeasure | — | — |
| 18 | Bottom thumb hat — right | Comm action | — | — |
| 16 | Bottom thumb hat — left | Zoomgoggles | — | — |
| 31 | Grip pinky button — press | Deselect target | Map back | — |
| 25 | Grip thumb hat — left | Prev subcomponent | — | — |
| 27 | Grip thumb hat — right | Next subcomponent | — | — |
| 23 | Grip thumb hat — push | Open playership info | — | — |
| X | Main trigger — first | Fire primary weapon | — | — |
| 13 | Thumb bottom button — press | Fire secondary weapon | — | — |
| BACK | Thumb top button — press | Target next enemy | — | — |
| LEFT_THUMB | Top thumb hat — up | Strafe up | — | — |
| RIGHT_THUMB | Top thumb hat — left | Strafe left | — | — |
| BIGBUTTON | Top thumb hat — down | Strafe down | — | — |
| 12 | Top thumb hat — right | Strafe right | — | — |
| START | Top thumb hat — push | Target next target | Map select | — |

### L-VPC VMAX Prime Throttle

| Code | Control | Ship | Map | On foot |
|---|---|---|---|---|
| 40 | APU button — press | Toggle scan mode | — | — |
| 29 | Big red button — press | Toggle longrange scan mode | — | — |
| 17 | Bottom thumb button — press | Match speed | — | — |
| 23 | Keyboard B1 button — press | Scan action | — | — |
| 24 | Keyboard B2 button — press | Toggle autopilot | — | — |
| 25 | Keyboard B3 button — press | Open cockpit menu | — | — |
| 26 | Keyboard B4 button — press | Pause | — | — |
| 27 | Keyboard B5 button — press | Open missions | — | — |
| 28 | Keyboard B6 button — press | Quicksave | — | — |
| B | Left side dial — push | Toggle travel mode | — | — |
| X | Middle finger button — press | Toggle flight assist | — | — |
| 51 | Mode selector — 1 | — | Map pan to rotate | — |
| A | Pinky button — press | Open map | — | — |
| LEFT_THUMB | Right side dial — push | Toggle SETA mode | — | — |
| 34 | T3 rocker — up | Next target action | — | — |
| 35 | T3 rocker — down | Prev target action | — | — |
| 36 | T4 rocker — up | Dock action | — | — |
| 37 | T4 rocker — down | Undock | — | — |
| 38 | T5 rocker — up | — | — | FP jump |
| 39 | T5 rocker — down | — | — | FP crouch |
| 16 | Thumb button — press | Boost | — | FP run |
| 19 | Thumb hat — up | Cockpit view | Map reset position | — |
| 20 | Thumb hat — right | Target view | — | — |
| 21 | Thumb hat — down | External view | Map reset rotation | — |
| 22 | Thumb hat — left | Cycle view | — | — |
| BIGBUTTON | Thumb two-way hat — fwd | Cycle next secondary weapongroup | — | — |
| 13 | Thumb two-way hat — aft | Cycle prev secondary weapongroup | — | — |

## Writing it

- **Profile** — inputmap_3.xml — X4 puts menu edits in inputmap.xml, so a named profile is the only place this survives.
- **Slots** — stick = 2, throttle = 3. Enumeration order, not stable: re-read after plugging something in.
- **Contexts** — X4 scopes a binding by which id it is — MAP_* answers only in the map, FP_* only on foot — so one button carries three without clashing.

## Still free

- Trigger initial lever (stick) — no buttons
- Main stick (stick) — no buttons
- Mini-stick (stick) — no buttons
- Stick encoder and click (stick) — no buttons
- Analogue brake lever on the grip (stick) — no buttons
- Left throttle lever (throttle) — no buttons
- Right throttle lever (throttle) — no buttons
- Side lever (throttle) — no buttons
- Middle finger hat (throttle) — no buttons
- Thumb mini-stick (throttle) — no buttons
- T1 rocker (throttle) — no buttons
- T2 rocker (throttle) — no buttons
- E1 encoder (throttle) — no buttons
- E2 encoder (throttle) — no buttons


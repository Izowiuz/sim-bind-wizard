# Allocation

How the program decides which control takes which need. The weights, the
bands and the vocabularies are in `core/scoring.toml`. The code is
`core/needs.py` and `core/solvers.py`.

## What the two sides are

A **need** is one thing a pilot must be able to do. It names the game's
actions, the shape of control it wants, when you reach for it, and what it
is for.

A **control** is one physical thing on a device, as the device map
describes it. The map gives its shape, its directions, how far your hand
travels to it, and whether you can hold it, tap it, find it by feel or hit
it by accident.

A **slot** is one bindable input of a control. A hat has four directions
and a press, so a hat is five slots.

## Reach

The device map measures how far the hand travels to each control. The
program reads five tiers.

| tier | what it means |
|---|---|
| 0 | your hand where it lives |
| 1 | one finger, the hand still on the grip |
| 2 | the hand off the grip, still on the device |
| 3 | the hand off the device |
| 4 | nobody measured it |

An unmeasured control counts as tier 4.

## The bands

A need's `urgency` says when you reach for it. The band gives a floor and
a ceiling on reach.

| band | takes tiers |
|---|---|
| in a turn | 0 to 1 |
| on approach | 0 to 3 |
| in the air | 0 to 3 |
| on the ramp | 2 to 3 |

The floor is what keeps something you do on the ramp off the control under
your thumb. The ceiling is what keeps something you do in a turn within
reach.

## The five passes

The program places a need in the first pass that takes it.

| pass | what it does |
|---|---|
| `yours` | you put it here. Nothing asks and nothing argues. |
| `pinned` | a control you named. It is taken before anything else. |
| `floored` | the ordinary try. Both limits hold. |
| `relaxed` | nothing was left inside the limits, so the far end opens. |
| `shared` | a spare button on a control that another function owns. |

Axes go first, best fit before the rest. Zoom wants a dial that rests at
zero. The antenna only wants one that stays put. So zoom has the better
claim on the one dial that rests at zero.

The result goes back into the needs file's own order. The order a pass
visits things in does not reach the layout.

`relaxed` runs over what `floored` left. A need placed in `relaxed`
reached past its floor, and the screen says so.

`shared` takes a spare button off a control another need already owns. A
hat's fourth direction and a rocker's spare half are the cases. Four
mechanisms lend nothing: a trigger, a selector, an encoder and a latch.
Each one's positions are one switch. Their click is a real button and is
fair game.

## The gates

A gate refuses a control outright.

| gate | why |
|---|---|
| `unusable` | the game cannot address it |
| `wrong_shape` | it is the wrong shape |
| `too_few` | it has too few bindable buttons |
| `stepped` | it reports its two extremes and nothing in between |
| `out_of_reach` | its reach is outside the band's limits |

`wrong_shape` does not apply in the `shared` pass. What a shared button
comes off is a control something else owns, and the shape of that control
is not the shape of the button.

One measured fact also refuses: a control the map marks as impossible to
hold cannot carry a modifier. Five of 41 controls qualify as a modifier,
so this is a constraint on where a shift can live.

## The score

Every candidate that passes the gates gets a number. The highest wins.
`--why` prints the parts.

| term | weight | when |
|---|---|---|
| `pinned` | 1000 | you named this control. It stops the scoring. |
| `fits` | 100 | the shape and the count fit |
| `lent` | 60 | still free in the last try (shared pass) |
| `device_right` | 40 | on the device it asked for |
| `exact_shape` | 20 | exactly the shape it asked for |
| `stayed` | 20 | where you left it |
| `click` | 15 | it has a click |
| `place_right` | 15 | for each of the overlay's place words it answers |
| `reach` | 12 | for each tier further from your hand |
| `left_over` | 12 | the best of what was left (shared pass) |
| `spare` | -4 | for each spare button it does not need |
| `directions_differ` | -8 | the directions differ |
| `opens` | -15 | it opens a control nothing has touched (shared pass) |
| `place_wrong` | -20 | for each of the overlay's place words it contradicts |
| `coupled` | -25 | this axis moves with another lever |
| `device_wrong` | -50 | on a different device |
| `no_directions` | -60 | no directions |

`reach` pays for distance. A control further from the hand scores higher,
so the closer controls stay free for the needs that must have them. The
band's floor and ceiling are what stop that running away.

## The measured facts

The device map answers five questions about each control. Four of them
move the score. The fifth refuses.

| question | yes | no |
|---|---|---|
| you can hold it down | 25 | -45 |
| you can tap it quickly | 25 | -45 |
| you can find it by feel | 0 | -20 a step |
| you can hit it by accident | 0 | -30 a step |
| you can hold it as a modifier | nothing | it refuses |

The first two are asymmetric on purpose. "You cannot hold this one" is a
fault, not the absence of a virtue.

The last two are charged as a shortfall, not paid as a bonus. 20 of the 22
controls a hand reaches without moving answer "find it by feel" at the
top. A bonus would pay nearly every candidate the same and decide nothing.
The information is in the minority answer.

A need gates the accident question. A control you can knock is a problem
only under something that hurts when you knock it.

An axis asks a sixth question. `rests` says where the axis sits when you
let go. The map's words are `centred`, `min`, `mid` and `max`. The same
word on the axis and the need pays 40. A different word costs 40. Pitch
has to spring back or the aircraft will not fly level. A throttle has to
stay or it returns to half power. A brake has to rest at the minimum or it
is part on from the moment the game starts.

## The solvers

| solver | what it does |
|---|---|
| `cp-sat` | the whole assignment as one model. It needs `ortools`. |
| `greedy` | walk the list. Each need takes the best control still free. |

`greedy` cannot take a control back. An early urgent need therefore keeps
a control a later need wanted more. `cp-sat` sees the whole assignment at
once and finds that trade.

`--solver NAME` names one. Without the flag the program takes the best
solver that runs. Every run prints the name. Name a solver that cannot run
and the program stops.

`cp-sat` can also run out of time with nothing feasible. Then the program
walks the list instead.

## The closed vocabularies

### Shapes

A need asks for a shape. The table says which kinds of control answer it.

| the need asks | a control of this kind answers |
|---|---|
| `axis` | axis, lever, slider, dial, pedal, wheel |
| `lever` | lever, slider |
| `button` | button, paddle, dial |
| `paddle` | paddle, button |
| `hat2` | hat2, switch2, switch3, hat4, selector |
| `hat4` | hat4, hat8, selector |
| `trigger` | trigger |
| `ministick` | ministick |
| `encoder` | encoder, dial |
| `dial` | dial, encoder |
| `latch` | latch |
| `selector` | selector |

### Directions

A need can name the directions a switch moves in. The map's words:

| the need says | the map says |
|---|---|
| `forward`, `up` | up, fwd |
| `back`, `down` | down, aft |
| `left` | left |
| `right` | right |
| `push` | push |

A pair of opposite actions belongs on a pair of opposite directions. Zoom
in and zoom out go on one hat, not on two buttons.

### Jobs

`suits` says what a function is for. The ten jobs:

| job | what it covers |
|---|---|
| `fire` | trigger, cannon, missiles, what is armed |
| `lock` | picking a target and holding it |
| `sensor` | radar, scan, sensor modes and cursors |
| `view` | looking around: cameras, head, sights |
| `trim` | trim and fine correction |
| `flight` | how the aircraft flies: modes, brakes, flaps, thrust |
| `systems` | gear, lights, power, the aircraft's own machinery |
| `defence` | flares, chaff, jammer, armour |
| `comms` | radio, missions, menus, panels |
| `nav` | maps, jumps, docking, course |

An overlay matches on the job. One line of a template therefore speaks for
a whole family of functions.

## Contexts

Two needs can hold the same axis when you are never doing both at once.
X4 steers with the stick's y axis and walks with it. Elite flies and
drives with the same lever. The context, not the axis, is what a need is
exclusive within.

The program counts a coupling group, not an axis. Two axes that travel
together are one input. The VMAX's throttle levers move as a pair until
you release the catch, so a function on the second lever moves with
whatever is on the first.

## What an overlay does

An overlay is a cockpit template in `overlays/`. It says where a family of
functions belongs, by job and by place on the hand. It wishes. It does not
decide.

`place_right` and `place_wrong` are how a wish reaches the score. The
screen says how many of a template's wishes got through. That number is
what two templates are compared on.

What you chose, accepted, filed and named survives an overlay. The overlay
decides where the program leans. It does not decide what you decided.

# How the allocator works

`core/needs.py`, about 340 lines. It answers one question: given a list of
things a pilot has to be able to do, and a description of the hardware, which
control gets which.

It knows nothing about any game. A need's payload is opaque to it — Falcon BMS
puts a callback there, War Thunder a `(air, heli)` pair, MSFS a
`(plane, heli, global)` triple, X4 a `(kind, id)` per context. The allocator
only ever indexes that list.

## What goes in

**Needs** come from the game's adapter, either written by hand (`NEEDS` in
`games/*/plan.py`) or derived from the game's own vocabulary (`families()` in
`games/dcs/propose.py`). Each carries:

| field | means |
|---|---|
| `what` | the human name, for the sheet and `--why` |
| `shape` | `button`, `hat2`, `hat4`, `trigger`, `latch`, `encoder`, `selector`, `ministick`, `lever`… widened through `FITS` |
| `bindings` | one payload per slot, in the control's own press order; `None` leaves that direction alone |
| `push` | payload for a control that also clicks; `None` leaves the click free |
| `urgency` | `IN_A_TURN` 0, `ON_APPROACH` 1, `IN_THE_AIR` 2, `ON_THE_RAMP` 3 |
| `suits` | one word matched against the map's own `suits` list |
| `dev` | which device kind it belongs on |
| `prefer` | pin to a control by its label in the map |
| `on` | the directions it physically moves in |
| `rank` | how many factory profiles bind it — a tiebreak, never a promotion |

**Devices** come from `core/devmap.py` → `sim-device-map`, keyed by the map's
own `kind`. The allocator sees each device as a flat list of `groups` —
physical controls, each with `kind`, `label`, `reach`, `suits`, `buttons`,
`push` and `bindable_buttons`.

## Reach: how precious a control is

Read out of the map's own English about how you get to it.

    thumb / index finger                 tier 0    without letting go of anything
    without releasing (grip)             tier 1    a finger stretches
    needs letting go                     tier 3    hand leaves the grip

On this hardware that is 14 controls at tier 0, 4 at tier 1, 19 at tier 3 and
none at tier 2.

Each urgency declares the band it may take:

    MAX_REACH = {0: 1, 1: 3, 2: 3, 3: 3}    the worst it can live with
    MIN_REACH = {0: 0, 1: 0, 2: 0, 3: 2}    the best it may take

The floor is what stops a canopy switch grabbing a thumb position the moment
one is free. Both are **preferences**, not laws: the relaxed pass lifts them.

## Scoring

`score(ctrl, need, role)` returns `None` when a control cannot do the job at
all — wrong shape, too few buttons, outside the reach band, vetoed by the
game's `usable()` — and otherwise:

    1000                        the need is pinned here, and it fits
    ────────────────────────────────────────────────────────────────
     100 + 12 × tier            prefer the LEAST precious that still works
    + 40 / − 50                 right device / explicitly the wrong one
    + 20                        exactly the shape asked for
    + 25                        the map says this control suits it
    + 15                        both have a click to put something on
    −  4 × surplus buttons      do not burn a four-way hat on one action

`100 + 12 × tier` rewarding the *worse* reach is deliberate: needs are placed
most-urgent-first, so anything still waiting is less urgent than what has
already chosen, and taking the cheapest adequate control leaves the good ones
for whatever is still coming.

A pin short-circuits everything except shape and capacity. It used to be a
+500 bonus applied after the reach checks, which meant a pinned control the
ceiling excluded scored `None` and the bonus never ran — BMS's pinky shift
scored 721 with a loose ceiling and nothing with a tight one, and moved
silently to the thumb mini-stick. A pin is a decision, so it outranks the
tables and not just the ranking.

## Four passes

Needs are ordered `(pinned first, then urgency, then −rank)` and walked four
times. Each pass takes whole controls out of the pool as it places them.

**1 — pinned.** Anything with `prefer` goes before urgency is consulted at
all. `prefer` used only to tip the scales, which is no use once something more
urgent has already taken the control.

**2 — floored.** Everything else, honouring both floor and ceiling. Most of a
layout lands here.

**3 — relaxed.** Whatever is left, with the floor dropped — an unbound engine
start is worse than a canopy switch under the thumb, and by now everything
urgent has chosen. The **ceiling** lifts here too, but *only for a need that
wants more than one button*, because:

- a multi-button need has no other fallback, and every encoder and selector on
  this hardware needs letting go of the grip, so without the lift BMS's MAN
  RANGE knob, radar gain, ICP master mode and IFF MASTER had nowhere to go at
  all;
- a single-button need *does* have one — pass 4 — and a borrowed thumb press
  beats a whole control you must let go of the grip to reach. Lifting the
  ceiling for those made it lose: War Thunder's radar ACM and sight
  stabilisation, both `in a turn`, left the thumb for the side dials.

**4 — borrowed.** A control carries more than the need that took it: a hat has
four directions *and* a press, a rocker nobody claimed has two positions. What
counts as spare is tracked per `(device, button)`, not per control. A
single-slot need with nowhere else to go takes one spare button, scored

    60 + 12 × (3 − tier) + 30 if the right device − 15 if the control is untouched

Two things to notice. The tier polarity is **flipped** against the main passes:
nothing is coming after this pass, so a leftover need should get the best
leftover rather than the cheapest. And opening a control nothing has touched is
penalised, so four idle two-way rockers do not sit there while a cold-start
switch goes homeless — but neither is one broken open while a real spare
exists.

Controls in `ONE_MECHANISM` — `latch`, `trigger`, `selector`, `encoder` — lend
their **click only**. Their buttons are one physical thing rather than
independent positions: a trigger's stages are the gun, a selector's positions
are one switch, an encoder's two contacts are one more/less pair, and a latch
*holds* whichever position it is in, so a press action borrowed from one fires
for as long as the lever sits there. Bomb release landed on the master-arm
latch exactly that way.

## Which button each binding lands on

`slots_for(need, ctrl)` decides, in this order:

1. **One binding on a multi-button control goes on the click.** A lone action
   on `buttons[0]` reads as "push the hat left" when the obvious gesture is to
   press the hat, and it leaves the click idle.
2. **`need.on` is honoured when every direction can be found.** A speedbrake
   switch is fore/aft whatever hat it lands on, and putting it on "up" and
   "right" because those came first would be a lie about the hardware.
   `SAME_WAY` widens the match, because hats were captured with whichever word
   fitted at the time: a need asking for `forward` accepts `up` or `fwd`.
3. **Otherwise the first N in the control's own press order**, with the click
   appended to the pool when the need has nothing of its own for it.

## What comes out

    placed, unplaced, free = allocate(needs, devices, usable=None, reach=None)

`placed` is a list of `Placement(need, role, ctrl, slots, points)`, where
`slots` is `[(button index, payload)]` with the click appended when both sides
have one. That is what a writer iterates; it is the only place the button
arithmetic is done, and an adapter re-deriving it by hand loses `need.on`.

`unplaced` is the needs with no home. For a hand-written `NEEDS` that means a
function you asked for has nowhere to go. For a derived list like DCS's, where
the top of a ranked vocabulary is offered and the rest simply is not chosen,
it is normal.

`free` is `[(role, ctrl)]` for controls with **every** button still free, not
merely the ones no need chose.

`usable(role, ctrl)` is the game's hard veto, for a control the hardware has
but the game cannot address: BMS sees only a device's first 32 buttons, so the
VMAX's last nineteen are real to your hand and invisible to the sim.

`reach` replaces `MAX_REACH` for one run, because the same ceiling means
different things depending on where the needs came from. A hand-written list
saturates the good controls, so tightening displaces something more urgent.
A list derived from the game's own vocabulary and cut at a vote threshold has
room to spare. DCS passes `{0: 1, 1: 3, 2: 1, 3: 3}` and its sensor and radio
switches reach the borrow pass and get finger positions; the same table applied
globally took War Thunder's airbrake off the thumb.

## Reading a decision

`./plan.py --why` prints the urgency band, the score, whether the need was
relaxed, whether `suits` was hit, and the reach of the control it got. It is
more sensitive than the kneeboard: it catches a change that happened to land
on the same layout.

## Changing the policy

Three layers, and two of them are global:

- **`core/needs.py`** — `REACH_TIER`, `MAX_REACH`, `MIN_REACH`, `FITS`,
  `SAME_WAY`, `ONE_MECHANISM`, the score weights, the pass order. One edit
  moves every game.
- **`sim-device-map`** — `reach`, `suits`, `kind`, `moves_with`,
  `travel_contact`. One TOML edit moves every game. The WarBRD's "paddle"
  turned out to be the brake lever's travel contact; one correction there and
  three games stopped binding it, with no game code touched.
- **`games/*/plan.py`** — `urgency`, `prefer`, `on`, `dev`. These are claims
  about *a game's functions*. "Airbrake is used in a turn" is a statement about
  War Thunder and cannot be hoisted.

So a new trait keyed on vocabulary that already exists costs one edit and no
per-game work; one that needs a new `Need` field costs an edit in every game
that has an opinion about it.

A global knob moves six layouts at once, which is why every change here is
measured rather than argued. Regenerate the kneeboards and diff them: they
carry no timestamp, so any non-empty diff is a real move. Then classify the
moves by reach tier and urgency — `MAX_REACH[2] = 1` read like an obvious
improvement and measured as a five-for-five swap that put War Thunder's
airbrake on a dial you have to let go of the grip to reach.

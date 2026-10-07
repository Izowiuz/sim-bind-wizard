# How the allocator works

`core/needs.py`. It answers one question: given a list of things a pilot has
to be able to do, and a description of the hardware, which control gets
which.

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
game's `usable()`, or refused by a fact — and otherwise a sum of terms.

**The weights are not written here.** They live in `core/scoring.toml`, and
`y` on the review screen reads them out of it rather than out of a
transcription. A table in this document is a second copy that nobody edits
when the first one moves: this one said `+ 25 the map says this control suits
it` for months after that term was deleted, and omitted the two direction
penalties entirely.

Each weight carries a `note` in the file saying why it is what it is. Those
stay in the file. They were drawn on the `y` screen once and they read as
somebody else's working — half a page about a retune, under some rows and not
others — so the screen carries the numbers and the words they stand for, and
nothing else. Whoever is about to change a number is looking at the file.

Two halves. **Terms** — `[[term]]` — are named predicates over a control and a
need, written in `core/needs.py` because a file that could define one would
need an expression language. **Facts** — `[[fact]]` — are what the device map
measured about a control, weighed against what a need asks of it: can you hold
it down, tap it quickly, find it by feel, hit it by mistake, hold it as a
modifier. A fact counts only for a need marked as asking for it, and not at
all for a control nobody answered — an unanswered control is an unwalked desk,
not a middling one. Adding a sixth is a block in the file and nothing else.

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

## Five passes

Needs are ordered `(pinned first, then urgency, then −rank)` and walked five
times. Each pass takes whole controls out of the pool as it places them.

**1 — yours.** Anything carrying `Need.yours` with `how: chose` — a control
you put it on yourself, from the review screen. Placed before anything is
scored, and its control leaves the pool.

This is not `prefer`, and the difference is the point. A pin is an opinion: it
outranks the ordering, and the scoring still has to agree with it, so a gate
can refuse a pinned control — one did, and BMS's pinky shift left the button
it was pinned to. Nothing refuses this one. You sat at the desk with the stick
in your hand and put the thing where you wanted it; there is no opinion here
to overrule.

If the control is no longer on the desk, the need comes back **empty** and is
not offered to pass 5 either: borrowing it a spare button somewhere else is
moving it, which is the one thing writing the choice down was for. The review
screen says which kind of empty it is.

`how: accepted` — what `c` writes, when you look at where the allocator put
something and say yes — is deliberately *not* here. It records which control
you agreed to and changes no allocation, so if the desk or the needs change
and it lands elsewhere the row goes back to `?` and tells you. `c` over a full
list is one keystroke, and if it froze every row the allocator would never
speak again.

**2 — pinned.** Anything with `prefer` goes before urgency is consulted at
all. `prefer` used only to tip the scales, which is no use once something more
urgent has already taken the control.

**3 — floored.** Everything else, honouring both floor and ceiling. Most of a
layout lands here.

**4 — relaxed.** Whatever is left, with the floor dropped — an unbound engine
start is worse than a canopy switch under the thumb, and by now everything
urgent has chosen. The **ceiling** lifts here too, but *only for a need that
wants more than one button*, because:

- a multi-button need has no other fallback, and every encoder and selector on
  this hardware needs letting go of the grip, so without the lift BMS's MAN
  RANGE knob, radar gain, ICP master mode and IFF MASTER had nowhere to go at
  all;
- a single-button need *does* have one — pass 5 — and a borrowed thumb press
  beats a whole control you must let go of the grip to reach. Lifting the
  ceiling for those made it lose: War Thunder's radar ACM and sight
  stabilisation, both `in a turn`, left the thumb for the side dials.

**5 — borrowed.** A control carries more than the need that took it: a hat has
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

It honours the band's **floor** as well as its ceiling, which it used not to.
Only `on the ramp` has a floor above 0 — `takes = [2, 3]` — and the band's own
note says what for: *without it, something you do once with the canopy open
grabs a thumb position the moment one is free*. Every other pass obeyed that;
this one checked the ceiling only, and then paid the flipped tier bonus for
being **close**. So X4's `Pause` and `Cockpit menu` sat on the hat that cycles
weapon groups, and Elite's galaxy and system maps on a thumb hat. The trade is
explicit: two of the 147 — X4's `Player ship info` and Falcon's `AVTR`, both
ramp switches — now go unplaced rather than under a thumb.

Controls in `ONE_MECHANISM` — `latch`, `trigger`, `selector`, `encoder` — lend
their **click only**. Their buttons are one physical thing rather than
independent positions: a trigger's stages are the gun, a selector's positions
are one switch, an encoder's two contacts are one more/less pair, and a latch
*holds* whichever position it is in, so a press action borrowed from one fires
for as long as the lever sits there. Bomb release landed on the master-arm
latch exactly that way.

## Who gets what, once the scores are in

By the time a solver is asked the question is arithmetic: here are the things
to place, here is where each may go and what each would be worth, choose.
`core/solvers.py` has two answers to it and `--solver NAME` picks one.

**`greedy`** walks the list, each taking the best still free. It cannot undo a
choice, which is the whole of the difference: an early urgent need takes the
control a later one needed more, and passes 4 and 5 are what it does instead
of backtracking. Needs nothing, so every clone has it.

**`cp-sat`** states the whole assignment as one model and solves it together,
so it can give up a better control for one need to place two. The judgement is
unchanged — `score()` still says how well a control plays a part, and its
number is the objective coefficient — and only the search changes. So a
difference in the output is one greedy could not reach, not a difference of
opinion. Needs `ortools`.

It picks the best one that runs, and every run prints which. It used to pick
silently on whether the import worked, so the same command under two pythons
produced two different kneeboards for one desk, 77 lines apart, with nothing
on either saying so. Naming one that cannot run stops the run rather than
handing back the other.

The model runs one worker with a fixed seed. Eight workers race and whichever
reaches an optimum first is the answer — and most of a layout is ties, because
a dozen thumb buttons are worth exactly the same to a need asking for a
button. Three of the six games rebound 51 lines between two runs that differed
in nothing at all. These models solve in milliseconds, so the parallel search
was buying nothing.

Adding a third is a class and a line in `SOLVERS`. `device-map-v2.md` already
names the next one: the Hungarian algorithm, as a fast first answer to hand
the model as a hint.

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

   `score()` knows about this rather than letting the fallback happen
   silently: a control whose directions merely differ loses 8, and one with no
   directions at all loses 60. The second test is against the direction
   vocabulary and not "has any label", because a selector answers `1`..`5` and
   an encoder `ccw`/`cw` — positions, not directions. Reading those as
   directions put Elite's four panel-focus actions on a five-position switch
   that holds whichever position it is in.
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
- **`games/*/<game>-needs.json`** — `urgency`, `on`, `suits` and the ergonomic
  flags. `suits` is the **job**: the one word a game and an overlay can both
  say, from the closed `[jobs]` table in `core/scoring.toml`, and the thing
  that lets one template lay out six games. It was free text with eleven words
  on two different axes — `fire` and `view` saying what the job is, `toggle`
  and `reflex` saying how the control behaves — and 65 of the 147 functions
  said nothing at all, so a template had nothing to match for nearly half the
  list. These are claims about *a game's functions*. "Airbrake is used in a
  turn" is a statement about War Thunder and cannot be hoisted.
- **`overlays/*.toml`** — `device`, `finger`, `level`, `prefer`, `shift`,
  `modifier`, and the `[[pair]]` rules. These are claims about *how you like a
  cockpit laid out*, not about any game: "weapons on the stick" is the same
  wish in all six. One rule over a family replaces a field repeated per
  function — there were 86 such fields, which is one opinion written 86 times.

  `finger` and `level` are what make an overlay a **template** rather than a
  device preference. The Hornet's castle switch said as `finger = "thumb"`,
  `level = "HOME"` lands on whatever the desk in front of you has in that
  place, so `overlays/f-18.toml` works on hardware that is not a Hornet grip
  and in games that are not DCS. Both words are checked against the map's own
  `devicemap.FINGERS` and `devicemap.LEVELS` when the file loads.

  Scored, not pinned: `place_right` is +15 and `place_wrong` −20, per word, so
  a template tips a close call and loses to reach and to what is already
  taken. One that refused every control it had not named would place half an
  aircraft on a desk it was not drawn for. The layout prints how much got
  through — `Generic spaceship: 33 of 46 place wishes kept` — which is the
  number two overlays are compared on, and `--why` lists what broke.

`games/*/<game>-binds.json` is in neither list: it is the answer, not a
policy. It holds what sits where and who decided.

So a new trait keyed on vocabulary that already exists costs one edit and no
per-game work; one that needs a new `Need` field costs an edit in every game
that has an opinion about it.

A global knob moves six layouts at once, which is why every change here is
measured rather than argued. Regenerate the kneeboards and diff them: they
carry no timestamp, so any non-empty diff is a real move. Then classify the
moves by reach tier and urgency — `MAX_REACH[2] = 1` read like an obvious
improvement and measured as a five-for-five swap that put War Thunder's
airbrake on a dial you have to let go of the grip to reach.

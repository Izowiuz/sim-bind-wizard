# Using it

Four things you might be here to do. Find yours and stop reading.

---

## 1. Change what a control does

Never hand-edit a config the game reads. It is an **output**; the next
regeneration overwrites it.

    cd games/<game>
    ./plan.py                 what it would do, and where
    ./plan.py --why           and why each control was chosen
    ./plan.py --write         into the game
    ./plan.py --sheet --html  refresh the kneeboard

**Close the game first.** Every writer refuses while it is running, because
most of these sims rewrite their config on exit and would undo the work.

To move something, edit the game's `NEEDS` list and regenerate. Three knobs:

**`urgency`** — when you touch it. This is what stops a once-a-flight command
from taking a button your thumb rests on:

    IN_A_TURN     with something on your tail
    ON_APPROACH   hands busy, but there is time
    IN_THE_AIR    somewhere in the cruise
    ON_THE_RAMP   canopy open, engine off

Get this right and list order stops mattering.

**`prefer`** — your decision, by the control's label in the map. It beats the
ranking by a wide margin, so it survives regeneration instead of being argued
with every time:

    Need('Gear', 'button', ['ID_GEAR'], prefer='Keyboard B1 button')

**`on`** — the directions a switch physically moves in, when that matters. A
speedbrake is fore/aft whatever hat it lands on:

    Need('Speedbrake', 'hat2', ['close', 'open'], on=('forward', 'back'))

---

## 2. Your hardware changed

Capture the new device once, in the map:

    ../sim-device-map/capture.py

It lands in `captures/<maker>/` with `kind = "stick"` or `"throttle"`, and
**every planner picks it up with no code change** — they ask the map for a
kind, not for a model. Matching inside the map is by USB id and fingerprint,
never by name, so a firmware update that renames the device does not lose it.

Two devices of the same kind? The connected one wins. If that still does not
decide it, you are told rather than guessed at:

    SIM_DEVICE_ROLES="stick=virpil-vpc-stick-warbrd-d" ./plan.py

A map somewhere else entirely:

    SIM_DEVICE_MAP=/path/to/map ./plan.py

---

## 3. Something behaves oddly and you cannot see why

Start with the hardware, because that is where the surprises have been:

    ../sim-device-map/probe.py

Touch one thing at a time. It prints every event live with the map's own name
on it, and on Ctrl-C says what moved **together**. That is how we learned the
WarBRD has no paddle — js 31 is the brake lever's contact, and War Thunder was
firing flares for as long as you braked — and that the VMAX's two throttle
levers were clamped into one, which is why pitch trim on the spare one trimmed
on every power change.

**"Nothing is bound to it" and "nothing else moves with it" are different
questions,** and only the second one matters to your hand. Ask before assuming
an axis is free.

---

## 4. Add a game

Two halves have to exist before a layout can:

    the map        what the hardware IS          ../sim-device-map
    harvest.py     what the game can be TOLD     reads the game, writes nothing

### What a harvest is for

It reads the game's own files and extracts three things:

- **the vocabulary** — every action the game will accept a binding for, with a
  readable name. X4 has 229 actions, 99 held states and 29 axes; BMS has 1195
  callbacks; War Thunder 651.
- **the numbering** — how a button index in the map becomes whatever the game
  writes in its config. Each game differs and two of them renumber when you
  plug something in.
- **the ranking**, where the game ships profiles — how many of them bind each
  action. That is how we know what belongs on a stick instead of guessing.

Without it, a layout is written from memory. That is exactly how the first War
Thunder preset went wrong: it mirrored bindings that were already there, and
when asked what it was based on the honest answer was "nothing".

### The steps

1. `games/<name>/harvest.py` — read and print. Use `core.game` to find the
   install and the prefix; do not rediscover Steam's layout.
2. **Measure what the files do not say.** Write the measurement into the code
   with its evidence, and mark what is still inference. `games/x4/harvest.py`
   separates `MEASURED` from `INFERRED` in its comments and says what could not
   be used to measure and why.
3. `games/<name>/plan.py` — a `NEEDS` list of `core.needs.Need`, and a writer.
4. `games/<name>/README.md` — the same six headings as the others: where it
   lives, how to run it, the format, **measured**, **still a guess**, gotchas.

### The one rule for a writer

**It must be able to remove, not only add and change.** Drop something from
`NEEDS` and its old binding has to go, or it stays live in the game fighting
whatever took its place. That bug shipped twice in War Thunder — once for
buttons, then again for axes, because the first fix only covered half the file.

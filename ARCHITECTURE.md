# Architecture

## Repositories

| repo | holds | game-specific |
|---|---|---|
| `sim-device-map` | what the hardware physically is | no |
| `sim-bind-wizard` | the core, and games written against it | both |
| `<game>-bind-wizard` | one game's adapter | yes |

## Files

    sim-device-map/
      devicemap/__init__.py   Axis, Group, Device; load_all, by_usb, probe, find_connected
      devicemap/capture.py    curses TUI; writes captures/ (python -m devicemap)
      probe.py                live event monitor; what moves together
      captures/<maker>/*.toml

    sim-bind-wizard/
      bind                    verb -> (game, script, flags); forwards the rest
                              (the games come off the filesystem, not a list)
      core/adapter.py         the contract itself: Harvest, Adapter, Planner,
                              Proposer, the guard that rejects a bad override
                              at class definition, and from_file, which every
                              import of a sibling script by path goes through
      core/devmap.py          find the map; pick a device per role
      core/game.py            Steam libraries, install dirs, prefixes, is-it-running
      core/needs.py           Need, Placement, allocate; shapes, reach, urgency
                              (ALLOCATION.md describes what it does)
      core/solvers.py         Solver, Greedy, CpSat: who gets what, once the
                              scoring has said what each is worth
      core/vocab.py           load a harvest's output; save it
      core/overlay.py         Overlay: what you want of a layout, read from
                              overlays/ -- which device a family belongs on,
                              and the pair rules, which are the only claims
                              in the tool about two controls at once
      core/backup.py          copy what a writer is about to replace; put it back
      core/review.py          the plan on screen: keep or drop each binding
      core/sheet.py           Sheet, Row -> markdown and html
      core/sheet-template.html
      core/capture.py         the js protocol: Device, wait_input, detect_roles
      core/tui.py             the curses shell every screen draws in,
                              and Theme, which is what colour it draws in
      games/<game>/harvest.py     a Harvest subclass
      games/<game>/plan.py        an Adapter subclass (DCS: plan.py)
      games/<game>/<game>-needs.json   what each function is, and how you
                              use it. In the repo: nothing derives it
      games/<game>/<game>-binds.json   what sits where, and who decided.
                              Written by the review screen
      games/<game>/<game>-actions.json the harvest's cache. NOT in the repo
      games/<game>/README.md
      overlays/*.toml         how you like a cockpit laid out, as places on
                              the hand. Not per game and not per desk:
                              f-18.toml works in X4, on hardware that is
                              not a Hornet grip
      tests/run.py            every test; stdlib unittest, nothing to install
      tests/test_contract.py  the adapter contract, on a clone with no data
      tests/test_types.py     pyright, when it is installed
      tests/fake.py           hardware that does not exist, out of devicemap's
                              own classes
      tests/test_*.py

`games/dcs` builds its kneeboard from the RESULTS file rather than from a
layout, which is the one real difference in its sheet: half of what is bound by
the time you read a page was confirmed at the stick and half is still the
planner's proposal, so its rows carry `Row.mark` — `?` — and its "not placed"
list is ordered the way its own list is, by theme and then by name. Both of
those live in `core/sheet.py` now and any confirm-rather-than-invent game
gets them.

It used to own a writer and a 121-line template of its own, and that is how the
page drifted: the shared sheet learned to put axes inside their device, to split
the free controls per device and to drop two paragraphs of prose, and none of it
reached DCS. The reason recorded here for the split — per-device placeholders —
was not true: both templates used `__PANELS__`, and the `--air`/`--heli`
palettes coloured two static header cells rather than any row. `tests/
test_contract.py` now refuses a game that writes its own kneeboard.

DCS does still pass its own `reach` table to `allocate()`, and
`games/dcs/capture.py` is a curses capture TUI rather than a planner:
it writes the vocabulary `plan.py` reads, and of the core it uses only
`capture`, `game`, `tui` and `backup`.

Its binding table is gone -- `./bind-wizard.py dcs tui` is `core/review.py`, the screen
the other five open. It had the same keys over the same three states (`c C x X
↵` against proposed / confirmed / nothing) because nothing offered it this one;
`Adapter.review` is where that now lives, rather than `Planner.review`. What is
left of the wizard is finding the devices, picking the module and writing the
diff.lua.

Its bindings live in `games/dcs/dcs-<module>-binds.json`, the family's own
shape, one file per aircraft because an adapter is built for one. The wizard's
results file is left holding what it is actually about: where the game is, and
which joystick DCS calls what.

`Need.assignment` grew `buttons`, one per slot, on the way: DCS captures one
direction of a hat at a time, and that is now something every game can do
rather than DCS's private trick. The hand-placed pass reserves BUTTONS rather
than whole controls for the same reason -- four of DCS's commands share a hat,
and refusing the control to the second comer left three of them orphaned.

`games/elite` keeps `capture.py` for what only it does: picking a base
preset, naming which joystick is which, and writing the `.binds` format.
Binding is `./bind-wizard.py elite tui`, the screen the other five open -- it had a table
of its own with the same keys on it, and that went the way DCS's did.

Both wizards read `/dev/input/js*` themselves rather than asking the game what
it saw, because a binding has to be captured before the game has one.
`core/capture.py`'s `Device` is the raw kernel node -- unrelated to
`sim-device-map`'s `Device`, which says what a control physically IS. Both are
in scope in those two files.

## Flow

    the game's own files ──► harvest.py ──► <game>-*.json       (gitignored)
                                                │ vocabulary, numbering
                                                ▼
    captures/*.toml ──► devicemap ──► by_role ──► {kind: Device}
                                                │
                                                ▼
                            NEEDS  +  allocate(needs, devices, usable=)
                                                │
                                                ▼
                                          [Placement]
                                       need · role · ctrl
                                       slots = [(button, payload)]
                                                │
                              ┌─────────────────┼─────────────────┐
                              ▼                 ▼                 ▼
                           build()           writer            Sheet
                       game-shaped tables   game config      KNEEBOARD

## Who owns what

| concern | lives in |
|---|---|
| what a button or axis physically is | `sim-device-map/captures` |
| contacts that carry no binding (`rest_contact`, `travel_contact`, `transient`) | `devicemap.Group` |
| axes that move together (`moves_with`, `coupling`) | `devicemap.Axis` |
| which captured device plays which role | `core/devmap` |
| Steam libraries, install dirs, prefixes, is-it-running | `core/game` |
| shapes, reach tiers, urgency floor, scoring, passes | `core/needs` |
| choosing an assignment out of the options and their scores | `core/solvers` |
| loading a vocabulary, cached or reparsed | `core/vocab` |
| keeping a copy of what a writer replaces | `core/backup` |
| what the reviewer kept, and the table it is kept in | `core/review` |
| hardware that does not exist | `tests/fake` |
| kneeboard rendering | `core/sheet` |
| the action vocabulary and its readable names | `games/<g>/harvest` |
| device slots, button codes, global numbering | `games/<g>/harvest` |
| what a pilot must be able to do | `games/<g>/<g>-needs.json` |
| what a function is FOR, as one closed word | `core/scoring.toml` `[jobs]` |
| where on the hand you want it, and which two things your hand must work at once | `overlays/*.toml` |
| what sits where now, and who decided | `games/<g>/<g>-binds.json` |
| reading and writing the game's config | `games/<g>/plan` |
| what goes on the kneeboard | `games/<g>/plan._sheet()` |

## core.needs

    Need(what, shape, bindings=(), push=None, urgency=IN_THE_AIR,
         suits=None, dev=None, prefer=None, on=None,
         category=None, yours=None, held=False, rapid=False,
         by_feel=False, costly=False, modifier=False)

| field | meaning |
|---|---|
| `shape` | control shape; a tuple lists acceptable ones, first preferred |
| `bindings` | one game payload per slot, in the control's press order; `None` skips a direction |
| `push` | payload for the control's click |
| `urgency` | `IN_A_TURN` 0 · `ON_APPROACH` 1 · `IN_THE_AIR` 2 · `ON_THE_RAMP` 3 |
| `suits` | matched against the control's `suits` in the map |
| `dev` | device kind it belongs on |
| `prefer` | pin to a control by its map label |
| `on` | which parts of the control: a switch's direction names, or which axis of a multi-axis control (`['y']`) |
| `takes` | `BUTTON` or `AXIS` — which of a control's two kinds of input |
| `invert` | an axis binding's direction; the one thing `i` changes |
| `find` | a search only the game can answer, carried and not read |

Derived: `slots`, `wanted` (slots + push), `shapes` (after substitution),
`first_shape`. `relaxed` is set when the allocator reached past the floor.

`bindings` is the seam: the core only indexes it.

| game | one slot holds |
|---|---|
| Falcon BMS | callback, or `(on press, on release)` |
| War Thunder | `(aircraft action, helicopter action)` |
| MSFS 2024 | `(aeroplane, helicopter, global)` |

    allocate(needs, devices, usable=None) -> (placements, unplaced, free)

`devices` comes from `devmap.by_role`. `usable(role, ctrl)` vetoes hardware the
game cannot address — BMS reads only a device's first 32 buttons.

A `Placement` carries `need`, `role`, `ctrl`, `points`, and
`slots = [(button index, payload)]` with the push appended. An axis
placement's index is an `OnAxis(index)` rather than an integer: a
control's buttons and its axes are numbered separately -- the throttle's
mini-stick is button 23 and axes 0 and 1 -- so the slot has to say which
namespace it means, and a plain integer cannot.

`Layout.placed` holds both. `on_axes` and `on_buttons` are views for a
FORMAT that spells them differently -- DCS's `axisDiffs` against its
`keyDiffs`, X4's `INPUT_SOURCE_JOYAXES` against `INPUT_SOURCE_JOYBUTTONS`.

Passes, in order:

0. **yours** — `assignment.how == CHOSE`. What you put there by hand,
   taken before anything is scored; nothing refuses it.
0. **named** — `takes == AXIS`. Resolved rather than scored: the need says
   `device throttle, shape lever` or names one lever in `prefer`, and the
   map has one of it. It takes no control out of play, because two
   functions on one axis is the normal case -- X4 steers with the stick's
   y axis and walks with it, War Thunder has an aeroplane and a
   helicopter on every one.
1. **pinned** — `prefer` set, before urgency. A pin whose control is taken is
   reported and deferred.
2. **floored** — by `urgency`, honouring `MIN_REACH`.
3. **relaxed** — the rest, floor dropped, `relaxed` set.
4. **borrowed** — a one-slot need may take the idle click of a control whose
   own need had nothing for its press.

Rejections:

| test | meaning |
|---|---|
| `usable(role, ctrl)` | the game cannot address it |
| `ctrl.kind not in need.shapes` | wrong shape after substitution |
| `len(bindable_buttons) < need.wanted` | too few buttons |
| `tier > MAX_REACH[urgency]` | too far for how urgent it is |
| `tier < MIN_REACH[urgency]` | too good for how urgent it is (floored pass) |

    REACH_TIER   thumb, index finger 0 · without releasing 1 · needs letting go 3
    MAX_REACH    {0: 1, 1: 3, 2: 3, 3: 3}
    MIN_REACH    {0: 0, 1: 0, 2: 0, 3: 2}

Score `100 + 12*tier`, then `prefer` +500, `dev` ±40/−50, exact shape +20,
`suits` +25, has-a-push +15, −4 per surplus button. Highest wins, so among
controls that fit, the least precious one takes the need.

## core.sheet

    Sheet(title, subtitle, ident='#', contexts=('',), devices={role: name})
      .add(Row(role, control, part, ident, does, bindings={ctx: str|[str]}, edge))
      .add_axis(role, control, ident, does, context='')   # a Row with no part
      .note(heading, [(term, text)] | text)
      .free = [(role, control, ident, reach)]
      .unplaced = [(what, shape)]
      .markdown(path) / .html(path) -> (path, rows, how many are axes)

`ident` names the game's own numbering. One unnamed context renders the binding
as a second line under the plain-English name; several render a column each.

| game | ident | contexts |
|---|---|---|
| Falcon BMS | `DX` | one, unnamed |
| War Thunder | `WT` | Air, Helicopter |
| MSFS 2024 | `Button` | Aeroplane, Helicopter, Global |

## core.vocab

    load(directory, filename, key=None, build=None)
    save(directory, filename, **sections)

`load` returns the cache when it exists, otherwise calls `build` for a game
cheap enough to reparse, otherwise exits telling you to run the harvest.

## core.review

    run(layout, title, subtitle='', describe=, write=)

One screen for every game, and it is DCS's `run_table` generalised rather than
anything new. The shape is worth stating because none of it is the obvious
design:

| | |
|---|---|
| the rows are **needs**, not bindings | a need with nothing on it is still a row, and clearing one leaves it where it was |
| **three** states, not two | `(unset)` · `?` proposed · `+` yours |
| proposing fills the **gaps only** | it never overwrites what you chose, which is what makes `P` safe to press at any moment |
| choosing it yourself means **yours** | no confirming a decision you just made by hand |
| `?` is advisory, **not a filter** | a proposal nobody looked at is still written; the mark says you did not check it |
| a decision **outlasts the session** | written to the binds file as it is made; `Need.yours` records which control and how strongly |
| **two** strengths of yours | `chose` (RETURN) takes the control before scoring; `accepted` (`c`) records what you said yes to and still scores |

    c / C   confirm this one / every proposal
    p / P   put the planner's choice on this one / into every gap
    RETURN  press the control you want it on
    l       or assign from the free controls that fit, with no hardware
    x / X   clear this one / drop every proposal, leaving yours
    m       the device map, and where the game was found
    y       why a control is chosen: the weights, and what they are for
    s       write everything that has a control

The header names the device behind each role. `devmap.by_role` keys on the
map's `kind`, so two sticks make you choose one with `SIM_DEVICE_ROLES` -- and
once you have, a row reading "stick" no longer says which. `m` has the rest:
the paths a game supplies through `paths=`, then every control in the map with
its buttons, axes, reach and whatever need sits on it -- each control in
the colour of the need it is carrying, so the map answers "what is still
free" without being read.

Pressing a control reads `/dev/input/js*` through `core.capture`, the same way
the two capture wizards do. `Review.took()` is everything that happens once the
kernel says which button went down, so the only untestable part of it is the
read itself.

What a press resolves to depends on how much the need has to place, and
`Review.honours_press()` is the whole rule:

| the need | what it gets | why |
|---|---|---|
| several bindings | the whole control, in its own direction order | four directions are the control's business, not the corner you touched |
| `on` set | the direction `on` names | a speedbrake is fore/aft whatever hat it lands on — the lie `on` exists to stop |
| one binding | **the position you pressed** | `slots_for` picks for a need that said nothing; a press said something |

That last row was wrong until it was tried: pressing the second detent of a
trigger bound the first, because `slots_for` takes the click or the first
position when a need has one binding to place. Right for the allocator, which
is guessing; wrong the moment somebody presses a thing by hand. A contact that
carries no binding -- a rest or travel contact -- still falls back, and says
so rather than binding where you pressed.

Which `js` node is which role is settled by USB id rather than by asking you
to press something: `/proc/bus/input/devices` gives vendor and product per
node, and that pair is what `devicemap` matches on anyway. The wizards have to
ask because they run before anything knows what hardware you have; here the
map is already loaded. Nothing is opened until the first `RETURN`, so
reviewing a layout with the sticks unplugged costs nothing.

Pressing can land anywhere, so unlike the list every refusal says what was
wrong -- not in the map, carries no binding, wrong shape, too few buttons, or
carrying some other need by name. Shape is reported before occupancy: a hat
that is the wrong shape would not work even if it were free.

Rows group by urgency, not by device: urgency belongs to the need, so a row
keeps its place when you clear it or move it elsewhere. Grouping by device
made rows jump between sections while you worked.

A game supplies only what the core cannot know -- `describe(placement)`
returning `[(which part of the control, what it does)]`, because a payload is
a BMS callback, a War Thunder `(air, heli)` pair or an X4 `(kind, id)` per
context, and only the adapter can read its own.

`write` is handed a `Layout` narrowed to the needs that ended up with a
control. That is the whole reason `Layout.but()` exists and the reason BMS and
War Thunder had to stop deriving their writers' tables inside `build()`: a
table computed from the whole plan cannot be narrowed afterwards.

Writers report by printing, and some warn on stderr. Under curses that would
land on the screen being drawn, so the write call runs inside
`redirect_stdout`/`redirect_stderr` and the output is replayed as log lines --
cheaper than teaching six writers to return text they already print.

Colour is a `Theme` in `core/tui.py`, and its tones are named for what a
thing IS rather than for the colour it comes out as: `mine`, `proposed`,
`unset`, `head`, `subhead`, `meta`, `note`, `plain`, `sel`. A screen asks for
`theme.mine`, or `theme[name]` when the line it is drawing carries its own
tone.

`head`, `subhead` and `meta` are one ladder: the section, the thing it names,
the detail under it. On the map that is `WHERE` / `profile dir` / the path,
and `DEVICE MAP` / `stick R-VPC Stick WarBRD-D` / its ids and counts. All
three in the same blue is a listing you have to read from the top to know
where you are.

The three row states are tone names too, and that is the point rather than a
coincidence -- `mark[need]` can be handed straight to the theme, so the need
table and the device map cannot drift apart. A control on the map wears the
state of the need sitting on it, which makes green the same claim on both
screens. `map_lines()` therefore returns `(tone, text)` and not bare lines:
the pager cannot tell a device heading from a control carrying something, and
that is the one thing only the map knows.

Every control on the map also carries the table's own `?`/`+` mark, and the
map opens with a legend drawn in the four colours it explains -- one line per
tone, because a line carries one. Colour went in first and said nothing on
its own: some rows were simply a different colour from the others. The mark
says which, the legend says what the mark means, and the colour is left to do
the thing it is good at, which is being seen without being read.

Four base colours, and never yellow. They draw on the terminal's own
background -- `use_default_colors` hands the palette back rather than painting
one -- and these wizards run on a light terminal as often as a dark one;
yellow on white does not read. Without colour every tone falls back to bold,
dim or reverse, which is all `core/tui.py` ever used, so a terminal with no
colour and the capture wizards both look exactly as they did.

DCS is on this screen too now. Its own table is where the three states came
from -- a `proposed` flag in its results file -- and keeping a second screen to
draw them was the thing that made the flag look like DCS's own idea rather than
the family's.

## core.backup

    stamp()                     '20260918-214917'
    save(game, *paths, into=, move=, when=)  -> (directory, [(stored, from)])
    runs(game, into=)           -> [(stamp, directory, [(stored, from)])]
    restore(game, which=, into=) -> (directory, [paths written])
    add_argument(parser, game)  the shared --backup-dir flag

    backups/<game>/<stamp>/MANIFEST     stored name -> where it came from
    backups/<game>/<stamp>/<file>...

`backups/` in the repo by default, gitignored; `--backup-dir` or
`SIM_BIND_BACKUPS` moves it. Nothing is left in the game's own directories,
which is the point: MSFS finds its profiles by globbing `inputprofile_*` and
used to find its own backups that way too.

Pass one `when` to group several calls into one run — BMS writes two files
under `./bind-wizard.py bms write`, DCS's `--reseed` rewrites one file once per aircraft.
A name already stored under that stamp is kept, so a run folder holds the state
from before the run rather than a half-written intermediate.

The MANIFEST is what makes `restore` generic rather than per-game: War
Thunder's `--restore` used to sort sibling filenames, which only worked because
the copy sat beside the original.

## core.devmap

    load()                      the devicemap module; honours SIM_DEVICE_MAP
    by_role(*required, pick=)   {kind: Device}

Roles are the map's own `kind`, so new hardware needs no code change. Among
several devices of one kind the connected one wins; if that does not decide it,
`by_role` exits. Override with `pick={'stick': slug}` or `SIM_DEVICE_ROLES`.

## core.game

    libraries()                 every Steam library, main first
    install_dir(*names)         install path, first name that exists
    prefix(appid)               Proton prefix, or None for a native build
    in_prefix(appid, *parts)    a path under drive_c, or None
    userdata()                  Steam userdata directories
    running(*patterns)          pgrep

Each searches every library: `compatdata` sits beside the library its game is
installed in.

## Tests

    ./tests/run.py              all of them
    ./tests/run.py needs        one file
    ./tests/run.py -v           and say what each one was

Three things are mocked, and nothing else:

| mocked | how | why |
|---|---|---|
| the hardware | `fake.device()` builds a real `devicemap.Device` from a dict | a hand-written stub of a control is a second opinion about what a control IS, and drifts |
| the game's files | a few lines of synthetic config per format | a harvest's output is the publisher's — `.gitignore` keeps it out of the repo and so do the fixtures |
| where backups go | `into=` a temp directory | |

A game whose vocabulary has not been harvested cannot have its planner
imported, so those tests skip with the harvest command in the reason. Everything
in `test_needs` and `test_backup` runs on a fresh clone.

**Both ways in are covered, and they need different tests.** `./bind-wizard.py <game>
<verb>` is a table and is checked as one. A script run directly is a
*process*, so `RunDirectly` starts each planner and War Thunder's writer as
`__main__` in its own interpreter. Nothing else reaches that: `adapter.load`
imports a module and never runs its `main()`, so a script calling something
the core has moved is invisible to every other test here. The two capture
wizards open curses and read `/dev/input`, so only their import is covered --
which is all `harvest.wizard()` and `plan.wizard()` ever do with them.

**What is tested is what has a story.** Nearly every rule in `core/needs.py`
carries a comment saying what went wrong before it existed — the airbrake that
left the thumb, the pinky shift that lost its pin to the landing lights, the
bomb release that landed on a latch. Those comments are the specification.

**A test is not believed until the rule it covers has been broken in front of
it.** Deleting the reach floor, demoting the pin to a bonus, letting a latch
lend a position: each is an edit to the source that must turn the suite red.
Five tests written here passed against a deliberately broken allocator — the
ramp need avoided the thumb by scoring, not by the floor; the capacity check
was shadowed by the shape check — and each was rewritten until it failed for
the right reason.

`RunDirectly` was held to the same bar. `write.py` called
`plan.build()` after `build()` had become a method; the ABC commit converted
the second of the two call sites in that file and missed the one in `main()`,
which left the script dead on its first line that needed a plan while all 168
tests stayed green. Putting that one line back turns `RunDirectly` red with
the original `AttributeError` in the failure, and turns nothing else red —
which is the measurement that says the gap was real and that this test is
what closes it.

## Adapter contract

The contract is `core/adapter.py`, not this section. What used to be listed
here drifted from the code twice -- once into five shapes of `build()`, once
into three harvests that never met their own first line -- so the listing is
gone and the classes are the statement:

    Harvest(abc.ABC)          in: the game's files.  out: the cache
    Adapter(abc.ABC)          the planner surface
    ├── Planner(Adapter)      its writer takes the layout it is handed
    │   └── X4  Msfs  FalconBms  Elite  WarThunder
    └── Proposer(Adapter)     it seeds a file a capture wizard confirms
        └── Dcs

Three moments enforce it, and they are deliberately not one:

| when | what it catches |
|---|---|
| class definition | an override that cannot be called the way the base promised; an override of a `@final` member; an `@override` that overrides nothing |
| instantiation | a subclass with an abstract member left unimplemented, named |
| `pyright` | return types, parameter types, an `@override` naming nothing |

**Only the third can be absent from a clone**, which is why the first covers
arity on its own rather than leaving it to the checker. `tests/test_types.py`
runs it and skips when it is not installed.

A clause the base can *provide* it provides, and then there is nothing to
check: the common flags exist because `Adapter.parser` adds them, `--json`
exists because `Harvest.main` does, the cache goes through `core.vocab.save`
because that is what writes it, and a writer's output is backed up and laid
down by `Adapter.lay_down` -- which also refuses to finish if an undeclared
file appeared in the game's directory while the writer ran.

### What no interface can say

Two clauses are facts about *contents*, not about shape, and no language
expresses them. They are tests, and they would be tests in any language.

**A writer must remove as well as add.** A binding dropped from `NEEDS` has
to disappear from the game's config, or it stays live alongside whatever
replaced it -- and nothing says so, which is what makes this the one worth
holding. The six do it two ways: x4 and War Thunder own a region of the file
and replace it whole; BMS and Elite rebuild theirs from the one the game
shipped; MSFS strips our device from whatever the plan stopped naming, which
it did not do until `tests/test_formats.py` was made to say so. DCS is under it like
the rest: `write_layout` takes the layout the screen kept and `seed` turns it
into the per-command records `diff.lua` is built from. It used to read the
results file and ignore the argument, so anything cleared on the screen came
straight back.

**A writer must take the placements it is handed**, not call `build()` for
itself. Two did, and the review screen -- whose entire job is to write some
of a plan and not the rest -- could not exist until they stopped. Python has
no `private` to stop the call, so `tests/test_contract.py` reads the compiled
function for it: `'build' in fn.__code__.co_names` is a fact about the
emitted bytecode, where a grep over the source would trip on a comment.

`measured` and `still a guess` are separate headings in a game's README so a
reader knows which claims are load-bearing; that one is checkable and
checked.

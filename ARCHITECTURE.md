# Architecture

## Repositories

| repo | holds | game-specific |
|---|---|---|
| `sim-device-map` | what the hardware physically is | no |
| `sim-bind-wizard` | the core, and games written against it | both |
| `<game>-bind-wizard` | one game's adapter | yes |

## Files

    sim-device-map/
      devicemap.py            Axis, Group, Device; load_all, by_usb, probe, find_connected
      capture.py              curses TUI; writes captures/
      probe.py                live event monitor; what moves together
      captures/<maker>/*.toml

    sim-bind-wizard/
      bind                    verb -> (game, script, flags); forwards the rest
      core/devmap.py          find the map; pick a device per role
      core/game.py            Steam libraries, install dirs, prefixes, is-it-running
      core/needs.py           Need, Placement, allocate; shapes, reach, urgency
                              (ALLOCATION.md describes what it does)
      core/vocab.py           load a harvest's output; save it
      core/backup.py          copy what a writer is about to replace; put it back
      core/review.py          the plan on screen: keep or drop each binding
      core/sheet.py           Sheet, Row, AxisRow -> markdown and html
      core/sheet-template.html
      core/capture.py         the js protocol: Device, wait_input, detect_roles
      core/tui.py             the curses shell the capture wizards draw in
      games/<game>/harvest.py
      games/<game>/plan.py
      games/<game>/README.md
      tests/run.py            every test; stdlib unittest, nothing to install
      tests/fake.py           hardware that does not exist, out of devicemap's
                              own classes
      tests/test_*.py

`games/dcs` is on the core for the matching but keeps its own
`sheet-template.html`, whose placeholders are per-device (`__STICK__`,
`__THROTTLE__`) rather than the core's `__PANELS__`: the core sheet has no `?`
for a proposal and no vote-ordered "still unbound" panel, and both are
load-bearing for its confirm-rather-than-invent workflow. It also passes its
own `reach` table to `allocate()`. `games/dcs/dcs-bind-wizard.py` is a curses
capture TUI, not a planner: it writes the vocabulary `propose.py` reads, and of
the core it uses only `capture`, `game`, `tui` and `backup`.

`games/elite` has two tools on one writer: `plan.py` lays out from `NEEDS` like
the rest of the family, and hands the result to `ed-bind-wizard.py`'s own
`generate()` in the shape that capture TUI produces. One implementation of the
`.binds` format, two ways to fill it, and they write different presets so
neither overwrites the other.

The two capture wizards read `/dev/input/js*` themselves rather than asking the
game what it saw, because a binding has to be captured before the game has one.
`core/capture.py`'s `Device` is the raw kernel node -- unrelated to
`sim-device-map`'s `Device`, which says what a control physically IS. Both are
in scope in those two files.

## Flow

    the game's own files ──► harvest.py ──► <game>-*.json       (gitignored)
                                                │ vocabulary, ranking, numbering
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
| loading a vocabulary, cached or reparsed | `core/vocab` |
| keeping a copy of what a writer replaces | `core/backup` |
| what the reviewer kept, and the table it is kept in | `core/review` |
| hardware that does not exist | `tests/fake` |
| kneeboard rendering | `core/sheet` |
| the action vocabulary and its readable names | `games/<g>/harvest` |
| device slots, button codes, global numbering | `games/<g>/harvest` |
| what a pilot must be able to do | `games/<g>/plan.NEEDS` |
| reading and writing the game's config | `games/<g>/plan` |
| what goes on the kneeboard | `games/<g>/plan._sheet()` |

## core.needs

    Need(what, shape, bindings=(), push=None, urgency=IN_THE_AIR,
         suits=None, dev=None, prefer=None, on=None, note='')

| field | meaning |
|---|---|
| `shape` | control shape; a tuple lists acceptable ones, first preferred |
| `bindings` | one game payload per slot, in the control's press order; `None` skips a direction |
| `push` | payload for the control's click |
| `urgency` | `IN_A_TURN` 0 · `ON_APPROACH` 1 · `IN_THE_AIR` 2 · `ON_THE_RAMP` 3 |
| `suits` | matched against the control's `suits` in the map |
| `dev` | device kind it belongs on |
| `prefer` | pin to a control by its map label |
| `on` | direction names the switch physically moves in |

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
`slots = [(button index, payload)]` with the push appended.

Passes, in order:

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
      .add_axis(AxisRow(role, control, ident, does))
      .note(heading, [(term, text)] | text)
      .free = [(role, control, ident, reach)]
      .unplaced = [(what, shape)]
      .markdown(path) / .html(path) -> (path, rows, axes)

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

    c / C   confirm this one / every proposal
    p / P   put the planner's choice on this one / into every gap
    RETURN  press the control you want it on
    l       or pick one from a list, with no hardware
    x       clear it — the control goes back to the free list
    w       write everything that has a control

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

Colour is used where the terminal has it, in the four base colours that read
on a light background as well as a dark one, and never yellow. Without colour
the same meanings fall back to bold and dim. `core/tui.py` draws in bold and
reverse only, for a light-themed terminal; this keeps that intent without
keeping the letter of it.

DCS is not on this screen. Its bindings live in a results file where each one
carries a `proposed` flag, and its own table is where all of the above came
from. The generic one would have to invent the same state twice.

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
under `./bind bms write`, DCS's `--reseed` rewrites one file once per aircraft.
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

## Adapter contract

    harvest.py    in: the game's files.  out: vocabulary + ranking JSON
                  no arguments prints a summary; --json writes the cache
    plan.py       NEEDS: list[Need]
                  build() -> core.needs.Layout
                  a writer taking the placements it is given, not build()'s
                  _describe(placement) and --tui, for core.review
                  --sheet, --html, --why
                  a writer copies through core.backup.save and takes
                  --backup-dir from core.backup.add_argument
    README.md     where it lives · how to run it · the format ·
                  measured · still a guess · gotchas

A writer must **remove** as well as add and change: a binding dropped from
`NEEDS` has to disappear from the game's config, or it stays live alongside
whatever replaced it.

A writer must take **the placements it is handed**, not call `build()` for
itself. Two did, and the review screen -- whose entire job is to write some of
a plan and not the rest -- could not exist until they stopped.

A writer must leave **nothing behind** in the game's directories. What it
replaces goes to `core.backup`, never to a sibling file: the game reads that
folder, and four of the six writers here have a scar from it.

`measured` and `still a guess` are separate headings so a reader knows which
claims are load-bearing.

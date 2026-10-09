# Using it

Four tasks.

## The needs list is an example

Each game ships a needs list in `games/<game>/<game>-needs.json`. That
list is an example. It is the one input nothing can derive, and these
examples were not written by somebody who flies these aircraft.

| game | where its list came from |
|---|---|
| X4 | the owner's own saved profile |
| Elite | partly the presets Frontier ships, which are other people's layouts |
| MSFS | written by hand, by somebody who does not fly it |
| DCS | written by hand, by somebody who does not fly it |

So change it. A function you want is a function you add. A row you do not
want is a row you clear. Nothing here knows your aircraft better than you
do.

The review screen is where you do it. `a` adds a row from the game's own
vocabulary. `x` clears a row. `J` says what a function is for. `s` saves.

The program never overwrites what you decided. A field you answered stays
answered, and a control you chose holds its row against the scoring.

## 1. Change what a control does

The game's own configuration file is an output. Change the needs list, then
run the program again.

    ./bind-wizard.py GAME               review the layout. Save what you keep.
    ./bind-wizard.py GAME plan          print the layout
    ./bind-wizard.py GAME why           print the evidence for each control
    ./bind-wizard.py GAME free          print the controls that stay unbound
    ./bind-wizard.py GAME sheet         write the kneeboard
    ./bind-wizard.py GAME write         write the whole layout into the game

`./bind-wizard.py` with no argument lists the games. Every argument after
the verb goes to the script in `games/<game>/`. That script does the same
work and takes its own flags. Run `plan.py --help` for them.

Close the game first. A writer refuses to run while the game is up.

### Which solver

`--solver NAME` chooses who decides which need takes which control. Every
verb that plans takes the flag. Every run prints the name it used.

| name | what it does |
|---|---|
| `cp-sat` | the whole assignment as one model. It needs `ortools`. |
| `greedy` | walk the list. Each need takes the best control still free. |

Without the flag the program takes the best solver that runs under your
python. `greedy` places a need on the best control still free, and it
cannot take that control back. An early urgent need therefore keeps a
control that a later need wanted more. `cp-sat` finds that trade and
`greedy` cannot.

`ortools` is the only dependency outside the standard library. A python
without it runs `greedy`. Name a solver that cannot run and the program
stops. It does not hand you the other one.

### The review screen

`tui` is `write` with a say in it. Every need is a row. A row is in one of
three states.

| mark | state |
|---|---|
| (none) | nothing is on this row |
| `?` | the program put it here. You have not answered yet. |
| `+` | you put it here, or you accepted the proposal |

A row carries a second mark. `·` shows that the row's job is empty. Press
`J` to fill it. The two marks are independent, so a row can carry either,
both or neither.

The screen lists its own keys. Press `?` for them.

    ↑↓  j k     move to the previous or the next entry
    g  G        move to the first or the last entry
    f           filter by text
    h           show or hide the bindings under each entry
    ↵           assign by pressing a control
    l           assign from the free controls that fit
    c  C        accept this proposal, or every proposal
    SPACE       accept, then move down
    p  P        restore the proposal here, or in every gap
    x  X        unassign this row, or every row
    a           browse the game's vocabulary. Add entries.
    J           say what this function is
    Z           guess what every function is
    r  R        move this entry to another category, or rename the category
    i           invert an axis
    o           apply an overlay
    y           say why a control is chosen
    m           show the device map and the install paths
    s           save what you decided
    w           write the plan to the game
    q           quit

`P` fills gaps only. `X` drops proposals only. Neither undoes a choice of
yours. Press either at any point.

`?` is a note to yourself. The program writes a proposal you never
answered. Clear the row to refuse it.

`Z` fills two fields: which device a function belongs on, and what the
function is for. It reads the game's own category for the first. It reads
the category and then the words of the name for the second. It marks both
fields as proposals. It leaves a field you answered alone. It adds no row.

`a` opens the game's whole vocabulary. `↵` adds the selected action as a
row. `h` reads the game again. `D` forgets what the program read, and it
asks you to type `drop` first.

### Two strengths of a choice

Pressing `↵` and pressing `c` are not the same claim.

| key | what it claims |
|---|---|
| `↵`, `l` | you put it there. The control is taken before anything is scored. |
| `c`, `C` | you looked at the proposal and said yes. The row still scores. |

A control taken by `↵` holds the row against everything. Remove that
control from the device map and the row comes back empty. It says so.

A row accepted by `c` scores as it did before. Change the map or the needs
and the row can land somewhere else. It goes back to `?` to tell you.

`c` is the weak one on purpose. It is one keystroke over a whole list.

`x` forgets both and hands the row back to the program.

### What `↵` does with the press

The screen says which of two cases you are in before you press anything.

| the need | what the press takes |
|---|---|
| several bindings | the whole control, in its own order |
| one binding | exactly where you pressed |

So the second detent of a trigger is the second detent.

The USB ids say which stick is which. Nothing asks you to name them.
Nothing opens a device until you press `↵`. A control that cannot take the
need says why. The reason is the shape, the number of buttons, or the need
already sitting there.

`l` picks from a list instead. Use it when the sticks are not plugged in.
Neither `l` nor `↵` applies the reach rules.

### What outlasts the session

`s` writes two files in `games/<game>/`.

| file | what is in it |
|---|---|
| `<game>-binds.json` | which control each entry sits on, and who decided |
| `<game>-needs.json` | the list itself |

The frame says `unsaved` until you press `s`. `q` offers the same box.

`w` is the other thing. It writes the layout into the game's own
configuration file, and it keeps a backup. Nothing reaches the game until
you press `w`.

`o` lays the list out again to a template in `overlays/`. The choices are
`by-hand`, `f-18` and `generic-hotas-spaceship`. Give `none` to ask for
nothing. The screen says how many of the template's wishes got through.
What you chose, accepted, filed and named survives the overlay. The frame
names the template. `m` names it beside the desk.

A game may add one key for the one thing only it does. DCS adds `t`, which
picks the aircraft module. Each module is a different list of commands, a
different store and a different kneeboard. The sill shows the key beside
the rest. The screen refuses a key it already answers to.

### Backups

A writer copies every file it replaces into `backups/<game>/<stamp>/`
first. One folder holds one run. A `MANIFEST` file says where each file
came from. Nothing deletes old runs.

    --backup-dir DIR    copy them somewhere else
    SIM_BIND_BACKUPS    the same, from the environment

A cloud folder or an external disk is a reasonable choice. The game's own
directory is not.

No verb puts a backup back. `core/backup.py` holds `restore(game, which)`,
and nothing on the command line reaches it.

### What decides where a need lands

**`urgency`** says when you touch it. The four bands:

| band | what it means |
|---|---|
| `in a turn` | with something on your tail |
| `on approach` | hands busy, and there is time |
| `in the air` | somewhere in the cruise |
| `on the ramp` | canopy open, engine off |

A need at `on the ramp` cannot take a control your thumb rests on. A need
at `in a turn` cannot take a control you must leave the grip to reach.

**`prefer`** pins the need to one control, by its label in the device map.
The program applies it before it considers urgency.

    Need('Gear', 'button', ['ID_GEAR'], prefer='Keyboard B1 button')

**`device`** says which device the need belongs on, by the map's kind.

**`on`** says which directions a switch physically moves in.

    Need('Speedbrake', 'hat2', ['close', 'open'], on=('forward', 'back'))

**`suits`** says what the function is for. The ten jobs: `fire`, `lock`,
`sensor`, `view`, `trim`, `flight`, `systems`, `defence`, `comms`, `nav`.
An overlay matches on this.

**`rests`** says where an axis must sit when you let go. The words are
`centred`, `min`, `mid` and `max`. Pitch has to spring back. A throttle has
to stay. A brake has to rest at the minimum.

**`finger`** and **`level`** say where on the hand the need belongs, in the
map's own words.

`ALLOCATION.md` says how these turn into a score.

## 2. Your hardware changed

    python -m devicemap        in ../sim-device-map

The capture lands in `captures/<maker>/` with a kind, such as `stick` or
`throttle`. A planner asks for a kind, so no game code changes. The map
matches a device by its USB id and its fingerprint, not by its name. A
firmware update that renames the device still matches.

With two devices of one kind the connected one wins. The program asks you
when neither is connected.

    SIM_DEVICE_ROLES="stick=virpil-vpc-stick-warbrd-d" ./plan.py
    SIM_DEVICE_MAP=/path/to/map ./plan.py
    SIM_DEVICE_PROFILE=NAME ./plan.py

## 3. Find out what a control physically is

    ../sim-device-map/probe.py

Touch one thing at a time. Every event prints live with the map's name on
it. Ctrl-C prints what moved together. A button can close while an axis
travels. Two axes can report the same value.

Ask before you assume an axis or a button is free. *Nothing is bound to it*
and *nothing else moves with it* are different questions. The map answers
the first one only.

## 4. Add a game

Two halves must exist before a layout can.

| half | what it holds |
|---|---|
| `../sim-device-map` | what the hardware is |
| `games/<game>/harvest.py` | what the game accepts |

### What a harvest is

A harvest reads the installed game's own files. Those are archives,
configuration files, and whatever else enumerates the actions. It writes
one JSON file beside `harvest.py`. That file holds every action the game
accepts a binding for.

The vocabulary is what `plan.py` may name. That is all a harvest answers.
What belongs on a HOTAS is a judgement, and a judgement lives in the needs
file.

### Steps

1. Write `games/<game>/harvest.py`. Subclass `core.adapter.Harvest`.
   Implement `read()`, which returns `{filename: {section: data}}`, and
   `summary()`, which returns the lines a bare run prints. The base class
   gives you `--json` and the writing. Override `arguments()` for a flag of
   your own.
2. Measure what the files do not say. Record the measurement in the code
   with its evidence. Mark what is still inference.
3. Write `games/<game>/plan.py`. Subclass `core.adapter.Planner`.
   Implement `write_layout(rows, layout)`, which returns `{path:
   contents}`. Declare the rest: `NEEDS_FILE`, `BINDS`, `CATALOGUE`,
   `CACHE`, `AXES`, `BUTTON`, `MODES`, `PATHS`. Override `variants()` where
   the game has modules or aircraft. The base class gives you the flags,
   the backups and the writing.
4. Write a test in `tests/test_formats.py` for what the writer does to the
   game's own text. Test that it removes as well as adds. No interface can
   state that clause. Write the fixture first. Then break the writer and
   check that the test notices.
5. Write `games/<game>/README.md`. Describe what is peculiar to this game
   and nothing else. No code reads it.

`bind-wizard.py` needs no entry. It reads `games/` for the list, and it
lists a folder that holds a `plan.py`.

`tests/test_contract.py` checks the rest. It checks it on a clone with no
game installed and nothing harvested. `ARCHITECTURE.md` says what each
check catches.

# DCS World

Two tools, on the core for everything but the format:

    capture.py   harvests the module's vocabulary, names which
                         joystick DCS calls what, writes the diff.lua
    plan.py           derives needs from the module's own commands and
                         hands them to core.needs.allocate

`plan.py`'s kneeboard carries `?` where nobody has confirmed a row at the
stick — the one thing this page says that the other five do not. The page
itself is the core's — see `ARCHITECTURE.md`.

`./bind-wizard.py dcs tui` is the family's review screen. `./bind-wizard.py dcs capture` is what is
left of the wizard: find the devices, pick the module, write the diff.lua.

## Where it lives

Steam app 223750, Proton. The install can sit in any library:

    <steamapps>/common/DCSWorld/
      Mods/aircraft/<module>/
        entry.lua                   module name, and the folder DCS saves to
        Input/<unit>/joystick/default.lua   the vocabulary
        Input/<unit>/joystick/*.diff.lua    the sim's own command hashes

    <steamapps>/compatdata/223750/pfx/drive_c/users/steamuser/Saved Games/DCS/
      Config/Input/<unit>/joystick/<Device> {GUID}.diff.lua   written
      Logs/dcs.log                   device GUIDs are read from here

    --game-dir      the install; --saved-games derives from it unless given
    -r FILE         dcs-results.json, which remembers both paths
                    after the first run. plan.py takes --game-dir only and
                    reads the rest from that file

The current install is `/mnt/steam-library-b/SteamLibrary/steamapps`, a second
library — not the default one under `~/.local/share/Steam`.

## How to run it

    ./plan.py --write -a su-25T       into the game, via the wizard
    ./capture.py                 the TUI: pick an aircraft, then bind
    ./capture.py -g -a su-25T    the same write, from the wizard
    ./capture.py -s -a su-25T    sync: absorb changes made in DCS's UI
    ./capture.py --reset         discard the results file

    ./plan.py -a FA-18C                the layout
    ./plan.py -a FA-18C --why          and the evidence for each choice
    ./plan.py -a FA-18C --check        the layout against what is bound
    ./plan.py -a FA-18C --audit        bindings that no longer fit the
                                          hardware
    ./plan.py -a '' --audit            ...across every module
    ./plan.py -a FA-18C --sheet --html the kneeboard

Binding is `./bind-wizard.py dcs tui`, the family's review screen — `./bind-wizard.py` and
`USING.md` have its keys. The wizard's own results file holds where the game
is and which joystick DCS calls what, and is saved after every change.

## The format

One `.diff.lua` per device, a Lua table of two maps keyed by command hash:

    local diff = {
    	["axisDiffs"] = {
    		["a2001cdnil"] = {
    			["changed"] = {
    				[1] = {
    					["filter"] = {
    						["curvature"] = { [1] = 0.12, },
    						["deadzone"] = 0.03,
    						["invert"] = true,
    						["saturationX"] = 1,
    						["slider"] = false,
    					},
    					["key"] = "JOY_Y",
    				},
    			},
    			["name"] = "Pitch",
    		},
    	},
    	["keyDiffs"] = {
    		["d3003pnilu3003cd13vd1vpnilvu0"] = {
    			["added"] = { [1] = { ["key"] = "JOY_BTN13", }, },
    			["name"] = "Weapon Release Button",
    		},
    	},
    }
    return diff

    added     a binding the module did not ship
    changed   one it did
    removed   one taken away
    name      a comment — DCS matches on the hash

Axis hashes start with `a`, button hashes with `d`. `render_diff` reproduces
DCS's own serializer — sorted keys, tab indent, no trailing newline — so a
file the game rewrites comes back byte-identical.

Axis keys use Wine's HID-usage mapping: `ABS_X → JOY_X` … `ABS_RZ → JOY_RZ`,
`ABS_THROTTLE → JOY_SLIDER1`, `ABS_RUDDER → JOY_SLIDER2`.

## Measured

**The hashes come from the module's own `default.lua`**, run through a `lua`
or `luajit` binary with the game's globals stubbed out. It is data, not code
that touches the game.

**The sim's own commands carry ids that only the running exe knows** — gear,
thrust, views, pitch. Their hashes cannot be computed, so they are read out of
a factory profile that binds them, matched back by normalised name.

**What belongs on a HOTAS is written down, not counted.** `HINTS` in
`capture.py` says, per command, which device it lives on in the real
aircraft and when you touch it; a command it puts nowhere is a cockpit switch
the keyboard can have. That is what opens the Hornet on trigger, trim, sensor
control, TDC and gear rather than on 849 cockpit switches.

It used to be a vote: how many of the module's factory HOTAS profiles bound
each command, and which device they put it on. Those profiles are Eagle
Dynamics' layouts for a Warthog and an X56 — they say `throttle` because a
Warthog has buttons there, not because the F/A-18 does.

**The save folder is not the module folder.** DCS saves under the name in the
module's `entry.lua`: the Hornet ships `Input/FA-18C` and saves to
`Config/Input/FA-18C_hornet`.

**Switch direction is read off the module's symbols** where the display name
does not carry it — `STICK_WEAPON_SELECT_FWD` gives "forward, away from you".
Four-way hats are told from two-position toggles by counting the switch's
siblings.

**DCS assigns pitch, roll, rudder, thrust and fire/weapon-change/cannon to
*every* joystick it sees** (`DefaultAssignments.lua`,
`base_joystick_binding.lua`). Generation removes those wherever they would
make a stick and a throttle fight over one axis.

**Default filter values** are Eagle Dynamics' own, from their VPC WarBRD
profile: pitch and roll curvature 0.12, deadzone 0.03; rudder 0.15/0.05;
thrust as a slider.

**A tighter reach ceiling than the rest of the family.** `REACH` puts
`in the air` at tier 1 where the core's default is 3, and `plan.py` passes
it to `allocate()`. On this hardware it moved the Hornet's five COMM switches
and the Su-25T's chaff and flares from the middle-finger hat to the thumb hats.
Only DCS may do this — `ALLOCATION.md` has the reason.

**Which way each command points is read out of the module's prose**, in
`MOVE_TO_DIR`, and carried on `Need.on` -- one word per command, and nothing
for a command whose prose does not say. The core puts the named ones where
they belong and fills the rest in press order, so there is one answer to
which button a command lands on. `lay_out()` used to be that answer for the
writer while the core was it for the review screen, and a trim hat could be
shown one way round and written another.

**A stage named in a command is the stage it gets.** "Gun Trigger - SECOND
DETENT" was landing on the first detent -- the one that only runs the gun
camera -- because press order was all the core had to go on. Where two
commands want the trigger, as the Su-25T's cannon and selected weapon do,
they take a stage each: the need names the control and the stage, and the
allocator honours both rather than DCS placing them itself.

## Still a guess

**Master arm is still on the trigger's second detent.** The device map now
knows that contact is the trigger's own detent rather than a separate paddle,
so it wants moving; the change is `P` then `C` in the wizard, not yet applied.

**Per-engine thrust.** The VMAX throttle's two levers are coupled, so
`Thrust Left` and `Thrust Right` land on one axis. Uncoupling them in the
device's own configuration would make the split real, and would also make
`moves_with` in the device map untrue.

## Gotchas

**DCS overwrites `Config/Input` on exit.** Both tools refuse to write while
the game is running, and copy what they replace into
`<repo>/backups/dcs/<stamp>/` first — one folder per run. `--backup-dir` or
`SIM_BIND_BACKUPS` moves it.

**Device GUIDs come from `dcs.log`**, so the game has to have been started at
least once with the devices plugged in. Without them the tool falls back to
the stems of existing `.diff.lua` files.

**Without a `lua` binary** the vocabulary falls back to the factory profiles
alone: fewer commands, and whatever name the profile author used — sometimes
Russian.

**A handful of engine commands are never bound by any shipped profile**, so no
hash for them exists offline. Bind those in the game's own UI, then `--sync`.

**`--sync` is lossless by construction.** Everything it can model becomes a
regular binding; the rest is kept as a snapshot that generation overlays, and
the round-trip is verified per device with an OK/MISMATCH report.

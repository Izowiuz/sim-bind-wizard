# DCS World

Two tools, on the core for the matching:

    dcs-bind-wizard.py   a curses capture TUI: harvests the vocabulary,
                         captures bindings off the devices, writes the files
    propose.py           derives needs from the module's own commands, hands
                         them to core.needs.allocate, lays a layout over the
                         wizard's results

`propose.py` renders its kneeboard from a local `sheet-template.html` rather
than the core's — see `ARCHITECTURE.md`.

## Where it lives

Steam app 223750, Proton. The install can sit in any library:

    <steamapps>/common/DCSWorld/
      Mods/aircraft/<module>/
        entry.lua                   module name, and the folder DCS saves to
        Input/<unit>/joystick/default.lua   vocabulary and factory profiles

    <steamapps>/compatdata/223750/pfx/drive_c/users/steamuser/Saved Games/DCS/
      Config/Input/<unit>/joystick/<Device> {GUID}.diff.lua   written
      Logs/dcs.log                   device GUIDs are read from here

    --game-dir      the install; --saved-games derives from it unless given
    -r FILE         dcs-bind-wizard-results.json, which remembers both paths
                    after the first run. propose.py takes --game-dir only and
                    reads the rest from that file

The current install is `/mnt/steam-library-b/SteamLibrary/steamapps`, a second
library — not the default one under `~/.local/share/Steam`.

## How to run it

    ./propose.py --write -a su-25T       into the game, via the wizard
    ./dcs-bind-wizard.py                 the TUI: pick an aircraft, then bind
    ./dcs-bind-wizard.py -g -a su-25T    the same write, from the wizard
    ./dcs-bind-wizard.py -s -a su-25T    sync: absorb changes made in DCS's UI
    ./dcs-bind-wizard.py --reset         discard the results file

    ./propose.py -a FA-18C                the layout
    ./propose.py -a FA-18C --why          and the evidence for each choice
    ./propose.py -a FA-18C --check        the layout against what is bound
    ./propose.py -a FA-18C --audit        bindings that no longer fit the
                                          hardware
    ./propose.py -a '' --audit            ...across every module
    ./propose.py -a FA-18C --reseed       lay it out fresh
    ./propose.py -a FA-18C --sheet --html the kneeboard

In the TUI's table:

    P        seed every unbound row from the hardware map
    c / C    confirm the selected proposal / the whole section
    RETURN   capture a press, to overrule one
    I        invert an axis
    X        clear a binding

`P` needs `sim-device-map` cloned beside this repo, or `SIM_DEVICE_MAP`
pointing at it. The results file is saved after every change.

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

**Importance is counted, not guessed.** A command's rank is how many of the
module's factory HOTAS profiles bind it, and which device they put it on —
castle switch on the stick 8/8, TDC and cage/uncage on the throttle. That is
what opens the Hornet on trigger, trim, sensor control, TDC and gear rather
than on 849 cockpit switches.

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
`in the air` at tier 1 where the core's default is 3, and `propose.py` passes
it to `allocate()`. On this hardware it moved the Hornet's five COMM switches
and the Su-25T's chaff and flares from the middle-finger hat to the thumb hats.
Only DCS may do this — `ALLOCATION.md` has the reason.

**`lay_out()` assigns the buttons, not the core.** It matches a switch's
direction per member, out of the module's own prose. Where a need has one
command the core's choice wins: that is the control's click, or a borrowed
spare.

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

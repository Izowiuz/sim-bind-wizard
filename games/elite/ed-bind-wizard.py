#!/usr/bin/env python3
"""ed-bind-wizard.py - capture Elite bindings, and write the preset

DESCRIPTION
    Full-screen wizard by default: pick a base preset, pick SHIP or SRV, pick
    a section, then bind each function by pressing the control. Every change
    is saved at once, so quitting is safe at any point.
    With --generate, headless: build the .binds preset and exit.

KEYS
    arrows  move between functions
    RETURN  (re)bind the selected one, then press the button or move the axis
    I       invert an axis
    X       clear the binding, leaving the base preset's
    ESC     back, cancel, redo

FILES
    ed-bind-wizard-results.json   the bindings, and where the game is (-r)
    <preset>.4.2.binds            written by --generate

NOTES
    The base preset's bindings stay as the keyboard and mouse fallback.
    Writing a preset does not select it: choose it once in the game.
"""

# Interactive Elite Dangerous bindings wizard + .binds generator for HOTAS.
#
# TUI mode (default): full-screen terminal wizard. Flow:
#
#     1. game folder comes from --game-dir (remembered in the results file,
#        so you only pass it once); the Bindings folder is derived from it
#     2. pick the base preset (its bindings stay as keyboard/mouse fallback)
#     3. pick target: SHIP or SRV
#     4. pick a mapping section to (re)bind — or ALL
#
# Bindings are edited in a table: every function of the section is a row
# showing its current assignment straight from the results file. Keys:
#
#     arrows  move between functions
#     RETURN  (re)bind the selected function — then press the physical
#             button / move the axis; after accepting, the cursor moves
#             to the next row so you can chain RETURN-capture-RETURN
#     I       invert an axis (stored or freshly captured)
#     X       clear the binding (base preset fallback stays)
#     ESC     back / cancel / redo
#
# Results are saved after every change, so quitting any time is safe.
#
# Generator mode (--generate): headless; builds the .binds preset from the
# results file and writes it into the game's Bindings folder.
#
# Usage:
#     ed-bind-wizard.py                       # TUI wizard
#     ed-bind-wizard.py --reset               # wizard from scratch
#     ed-bind-wizard.py -r other.json         # use a different results file
#     ed-bind-wizard.py --generate            # write the .binds preset

import argparse
import curses
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RESULTS = os.path.join(SCRIPT_DIR, "ed-bind-wizard-results.json")

CORE = os.environ.get("SIM_BIND_WIZARD") or os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", ".."))
if not os.path.isdir(CORE):
    raise SystemExit("no shared core at %s\n"
                     "set SIM_BIND_WIZARD to the sim-bind-wizard checkout"
                     % CORE)
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import backup                                     # noqa: E402
from core import capture                                    # noqa: E402
from core import tui as ctui                                # noqa: E402
from core.game import install_dir                           # noqa: E402
from core.capture import (Device, axis_map, drain,           # noqa: E402
                          proc_joysticks, save, wait_input)

STEAMAPPS = os.path.expanduser("~/.local/share/Steam/steamapps")
DEFAULT_BASE = os.path.join(
    STEAMAPPS, "common/Elite Dangerous/Products/elite-dangerous-odyssey-64/"
               "ControlSchemes/KeyboardMouseOnly.binds")
DEFAULT_BINDINGS_DIR = os.path.join(
    STEAMAPPS, "compatdata/359320/pfx/drive_c/users/steamuser/AppData/Local/"
               "Frontier Developments/Elite Dangerous/Options/Bindings")

AXIS_THRESHOLD = capture.AXIS_THRESHOLD
DEBOUNCE = capture.DEBOUNCE

# ABS_* code -> DirectInput axis name as ED sees it (HID-usage order)
ABS_TO_DINPUT = {0: "Joy_XAxis", 1: "Joy_YAxis", 2: "Joy_ZAxis",
                 3: "Joy_RXAxis", 4: "Joy_RYAxis", 5: "Joy_RZAxis",
                 6: "Joy_UAxis", 7: "Joy_VAxis"}

# expected raw sign for the direction prompted in the wizard; ED's pitch
# convention is opposite to the other axes (pull back = negative = pitch up)
EXPECTED_SIGN = {"PitchAxisRaw": -1, "BuggyPitchAxis": -1}

DEFAULT_DEADZONE = "0.00000000"
AXIS_DEADZONES = {              # ministicks drift more than flight axes
    "LateralThrustRaw": "0.10000000",
    "VerticalThrustRaw": "0.10000000",
    "BuggyTurretYawAxisRaw": "0.10000000",
    "BuggyTurretPitchAxisRaw": "0.10000000",
}

# target -> [(section title, [(ED function, kind, prompt), ...]), ...]
SECTIONS = {
    "ship": [
        ("Flight axes — stick", [
            ("RollAxisRaw",  "axis", "STICK: push the stick firmly RIGHT (roll)"),
            ("PitchAxisRaw", "axis", "STICK: pull the stick firmly TOWARDS you (pitch up)"),
            ("YawAxisRaw",   "axis", "YAW: twist RIGHT (twist/rudder axis) — ESC if you have none"),
        ]),
        ("Flight axes — throttle", [
            ("ThrottleAxis",      "axis", "THROTTLE: set to MINIMUM, wait 2 s, then push to MAXIMUM"),
            ("LateralThrustRaw",  "axis", "ministick: push RIGHT (lateral thrust) — optional"),
            ("VerticalThrustRaw", "axis", "ministick: push UP (vertical thrust) — optional"),
        ]),
        ("Weapons", [
            ("PrimaryFire",           "button", "trigger: PRIMARY fire"),
            ("SecondaryFire",         "button", "SECONDARY fire"),
            ("CycleFireGroupNext",    "button", "next FIRE GROUP"),
            ("CycleFireGroupPrevious","button", "previous FIRE GROUP"),
            ("DeployHardpointToggle", "button", "deploy/retract HARDPOINTS"),
        ]),
        ("Flight", [
            ("UseBoostJuice",         "button", "BOOST"),
            ("HyperSuperCombination", "button", "FSD (supercruise/hyperjump combo)"),
            ("Supercruise",           "button", "SUPERCRUISE only — optional"),
            ("Hyperspace",            "button", "HYPERSPACE JUMP only — optional"),
            ("ToggleFlightAssist",    "button", "FLIGHT ASSIST on/off"),
            ("SetSpeedZero",          "button", "full stop (0% throttle) — optional"),
            ("LandingGearToggle",     "button", "LANDING GEAR"),
            ("ToggleCargoScoop",      "button", "CARGO SCOOP"),
            ("ShipSpotLightToggle",   "button", "ship LIGHTS"),
            ("NightVisionToggle",     "button", "NIGHT VISION — optional"),
        ]),
        ("Targeting", [
            ("SelectTarget",           "button", "target AHEAD"),
            ("CycleNextTarget",        "button", "NEXT target (cycle)"),
            ("CyclePreviousTarget",    "button", "PREVIOUS target"),
            ("CycleNextHostileTarget", "button", "next HOSTILE target"),
            ("CyclePreviousHostileTarget", "button", "previous HOSTILE target"),
            ("SelectHighestThreat",    "button", "HIGHEST THREAT"),
            ("CycleNextSubsystem",     "button", "next target SUBSYSTEM"),
            ("CyclePreviousSubsystem", "button", "PREVIOUS target SUBSYSTEM"),
            ("TargetNextRouteSystem",  "button", "next system in ROUTE"),
        ]),
        ("Headlook", [
            ("HeadLookReset",        "button", "HEADLOOK reset"),
            ("HeadLookPitchAxisRaw", "axis", "headlook: push UP (look up)"),
            ("HeadLookYawAxis",      "axis", "headlook: push RIGHT (look right)"),
        ]),
        ("Power distribution (pips)", [
            ("IncreaseSystemsPower",   "button", "PIPS: SYS (systems)"),
            ("IncreaseEnginesPower",   "button", "PIPS: ENG (engines)"),
            ("IncreaseWeaponsPower",   "button", "PIPS: WEP (weapons)"),
            ("ResetPowerDistribution", "button", "PIPS: reset/balance"),
        ]),
        ("Defence", [
            ("DeployHeatSink",    "button", "HEATSINK"),
            ("FireChaffLauncher", "button", "CHAFF"),
            ("UseShieldCell",     "button", "SHIELD CELL"),
        ]),
        ("UI & panels", [
            ("UI_Up",     "button", "UI: hat UP"),
            ("UI_Down",   "button", "UI: hat DOWN"),
            ("UI_Left",   "button", "UI: hat LEFT"),
            ("UI_Right",  "button", "UI: hat RIGHT"),
            ("UI_Select", "button", "UI: SELECT (e.g. hat press)"),
            ("UI_Back",   "button", "UI: BACK"),
            ("FocusLeftPanel",  "button", "LEFT panel (nav/contacts)"),
            ("FocusRightPanel", "button", "RIGHT panel (systems)"),
            ("FocusCommsPanel", "button", "COMMS panel — optional"),
            ("GalaxyMapOpen",   "button", "GALAXY MAP — optional"),
            ("SystemMapOpen",   "button", "SYSTEM MAP — optional"),
        ]),
    ],
    "srv": [
        ("SRV driving", [
            ("SteeringAxis",   "axis", "SRV STEERING: steer RIGHT"),
            ("DriveSpeedAxis", "axis", "SRV THROTTLE: set to MINIMUM, wait 2 s, then MAXIMUM"),
            ("BuggyRollAxisRaw", "axis", "SRV ROLL (airborne): push RIGHT — optional"),
            ("BuggyPitchAxis",   "axis", "SRV PITCH (airborne): pull TOWARDS you (nose up) — optional"),
            ("VerticalThrustersButton",        "button", "SRV vertical THRUSTERS"),
            ("ToggleDriveAssist",              "button", "DRIVE ASSIST on/off"),
            ("AutoBreakBuggyButton",           "button", "HANDBRAKE"),
            ("BuggyToggleReverseThrottleInput","button", "toggle REVERSE"),
            ("HeadlightsBuggyButton",          "button", "HEADLIGHTS"),
            ("RecallDismissShip",              "button", "RECALL/DISMISS ship"),
        ]),
        ("SRV turret & combat", [
            ("BuggyPrimaryFireButton",   "button", "SRV PRIMARY fire"),
            ("BuggySecondaryFireButton", "button", "SRV SECONDARY fire"),
            ("ToggleBuggyTurretButton",  "button", "TURRET mode toggle"),
            ("SelectTarget_Buggy",       "button", "select TARGET"),
            ("BuggyTurretYawAxisRaw",    "axis", "TURRET YAW: push RIGHT — optional"),
            ("BuggyTurretPitchAxisRaw",  "axis", "TURRET PITCH: pull TOWARDS you (up) — optional"),
        ]),
        ("SRV pips & cargo", [
            ("IncreaseSystemsPower_Buggy",   "button", "PIPS: SYS"),
            ("IncreaseEnginesPower_Buggy",   "button", "PIPS: ENG"),
            ("IncreaseWeaponsPower_Buggy",   "button", "PIPS: WEP"),
            ("ResetPowerDistribution_Buggy", "button", "PIPS: reset/balance"),
            ("ToggleCargoScoop_Buggy",       "button", "CARGO SCOOP"),
            ("EjectAllCargo_Buggy",          "button", "eject all cargo — optional"),
        ]),
        ("SRV UI & panels", [
            ("FocusLeftPanel_Buggy",  "button", "LEFT panel"),
            ("FocusRightPanel_Buggy", "button", "RIGHT panel"),
            ("FocusCommsPanel_Buggy", "button", "COMMS panel — optional"),
            ("GalaxyMapOpen_Buggy",   "button", "GALAXY MAP — optional"),
            ("SystemMapOpen_Buggy",   "button", "SYSTEM MAP — optional"),
        ]),
    ],
}


# ---------------------------------------------------------------- devices --

def describe(r):
    if not r:
        return "(skipped)"
    if r["type"] == "button":
        return f"{r['role']} button {r['index'] + 1}"
    return f"{r['role']} axis {r['index']} ({'+' if r['sign'] > 0 else '-'})"


def resolve_devices(results):
    """role -> {'id': 'VIDPID' uppercase hex (as ED writes it, e.g.
    '334443E8'), 'axmap': [ABS codes by js axis index]}."""
    out = {}
    joys = proc_joysticks()
    saved = results.get("_devices", {})
    for role in ("stick", "throttle"):
        info = dict(saved.get(role, {}))
        live = joys.get(info.get("name"))
        if not (info.get("vid") and info.get("pid")) and live:
            info["vid"], info["pid"] = live["vid"], live["pid"]
        if not info.get("axmap") and live:
            dev = Device(live["js"])
            info["axmap"] = axis_map(dev.fd, dev.n_axes)
            os.close(dev.fd)
        if info.get("vid") and info.get("pid"):
            out[role] = {"id": (info["vid"] + info["pid"]).upper(),
                         "axmap": info.get("axmap")}
    if len(out) < 2:
        # no _devices in the results file — classify what is plugged in now
        for name, j in joys.items():
            role = "throttle" if "throttle" in name.lower() else "stick"
            if role in out:
                continue
            dev = Device(j["js"])
            out[role] = {"id": (j["vid"] + j["pid"]).upper(),
                         "axmap": axis_map(dev.fd, dev.n_axes)}
            os.close(dev.fd)
    missing = {"stick", "throttle"} - set(out)
    if missing:
        raise RuntimeError(f"cannot resolve devices for: "
                           f"{', '.join(missing)} — plug the devices in "
                           f"or re-run the wizard")
    return out


def generate(results, base, bindings_dir, preset_name, backup_dir=None):
    """Build the .binds file. Returns human-readable summary lines."""
    devs = resolve_devices(results)
    lines = [f"device ids: stick={devs['stick']['id']} "
             f"throttle={devs['throttle']['id']}"]

    tree = ET.parse(base)
    root = tree.getroot()
    root.set("PresetName", preset_name)
    root.set("MajorVersion", "4")
    root.set("MinorVersion", "2")

    bound, created, skipped = [], [], []
    for func, r in results.items():
        if func.startswith("_"):
            continue
        if not r:
            skipped.append(func)
            continue
        device = devs[r["role"]]["id"]
        el = root.find(func)
        if el is None:
            el = ET.SubElement(root, func)
            created.append(func)
        if r["type"] == "button":
            key = f"Joy_{r['index'] + 1}"
            primary = el.find("Primary")
            secondary = el.find("Secondary")
            if primary is None:
                primary = ET.SubElement(el, "Primary")
            if secondary is None:
                secondary = ET.SubElement(el, "Secondary",
                                          Device="{NoDevice}", Key="")
            # keep the base (keyboard) binding as a fallback on Secondary
            if (primary.get("Device") not in (None, "{NoDevice}")
                    and secondary.get("Device") in (None, "{NoDevice}")):
                secondary.attrib.clear()
                secondary.attrib.update(primary.attrib)
            primary.attrib.clear()
            primary.set("Device", device)
            primary.set("Key", key)
        else:
            axmap = devs[r["role"]]["axmap"]
            if (not axmap or r["index"] >= len(axmap)
                    or axmap[r["index"]] not in ABS_TO_DINPUT):
                raise RuntimeError(f"{func}: cannot map {r['role']} axis "
                                   f"{r['index']} — axmap={axmap}")
            key = ABS_TO_DINPUT[axmap[r["index"]]]
            binding = el.find("Binding")
            if binding is None:
                binding = ET.SubElement(el, "Binding")
            binding.attrib.clear()
            binding.set("Device", device)
            binding.set("Key", key)
            inverted = el.find("Inverted")
            if inverted is None:
                inverted = ET.SubElement(el, "Inverted")
            expected = EXPECTED_SIGN.get(func, 1)
            inverted.set("Value", "0" if r["sign"] == expected else "1")
            deadzone = el.find("Deadzone")
            if deadzone is None:
                deadzone = ET.SubElement(el, "Deadzone")
            # never clobber a deadzone tuned in game / in the base preset
            if not deadzone.get("Value"):
                deadzone.set("Value",
                             AXIS_DEADZONES.get(func, DEFAULT_DEADZONE))
        bound.append(func)

    out = os.path.join(bindings_dir, f"{preset_name}.4.2.binds")
    # The game keeps its own numbered `.binds.N.backup` copies, but only of
    # presets IT wrote; ours was replaced in place with nothing kept, so a
    # deadzone tuned in game and then regenerated over was simply gone.
    dest, kept = backup.save("elite", out, into=backup_dir)
    if kept:
        lines.append(f"backed up the previous preset -> {dest}")
    ET.indent(tree, space="\t")
    tree.write(out, encoding="utf-8", xml_declaration=True)

    lines.append(f"wrote {len(bound)} bindings -> {out}")
    if created:
        lines.append(f"functions absent from the base preset (added fresh): "
                     f"{', '.join(created)}")
    if skipped:
        lines.append(f"skipped in wizard (base bindings only): "
                     f"{', '.join(skipped)}")
    lines.append(f"In game: Options -> Controls -> preset '{preset_name}'")
    return lines


# -------------------------------------------------------------------- TUI --

def resolve_config(args, cfg):
    """Validate --game-dir / remembered config; exits with a clear message.

    Returns cfg with game_dir, schemes_dir and bindings_dir filled in.
    """
    # core.game.install_dir searches every Steam library, so the install is
    # found on a second disk too and --game-dir is an override rather than a
    # requirement. It used to have no default at all.
    game = (args.game_dir or cfg.get("game_dir")
            or install_dir("Elite Dangerous"))
    if not game:
        sys.exit("Pass --game-dir /path/to/steamapps/common/'Elite "
                 "Dangerous' (remembered in the results file afterwards).")
    game = os.path.abspath(os.path.expanduser(game))
    schemes = os.path.join(
        game, "Products", "elite-dangerous-odyssey-64", "ControlSchemes")
    if not os.path.isdir(schemes):
        sys.exit(f"{game}\ndoes not look like an Elite Dangerous install "
                 f"(missing Products/elite-dangerous-odyssey-64/"
                 f"ControlSchemes).")
    # <steamapps>/common/<game> -> <steamapps>/compatdata/359320/...
    steamapps = os.path.dirname(os.path.dirname(game))
    derived = os.path.join(
        steamapps, "compatdata", "359320", "pfx", "drive_c", "users",
        "steamuser", "AppData", "Local", "Frontier Developments",
        "Elite Dangerous", "Options", "Bindings")
    bindings = args.bindings_dir or (cfg.get("bindings_dir")
                                     if not args.game_dir else None) or derived
    if not os.path.isdir(bindings):
        sys.exit(f"Bindings folder not found:\n{bindings}\n"
                 f"Run the game once so it creates it, or pass "
                 f"--bindings-dir.")
    cfg.update({"game_dir": game, "schemes_dir": schemes,
                "bindings_dir": bindings})
    return cfg


def screen_base_preset(tui, cfg):
    entries = []
    schemes = sorted(glob.glob(os.path.join(cfg["schemes_dir"], "*.binds")))
    for p in schemes:
        entries.append((os.path.basename(p), p))
    customs = sorted(glob.glob(os.path.join(cfg["bindings_dir"], "*.binds")))
    for p in customs:
        entries.append((f"custom: {os.path.basename(p)}", p))
    if not entries:
        tui.page("Base preset")
        tui.log(f"no .binds found in {cfg['schemes_dir']}")
        tui.wait_any_key()
        return False
    index = 0
    for i, (_, p) in enumerate(entries):
        if p == cfg.get("base") or (not cfg.get("base")
                                    and "KeyboardMouseOnly" in p):
            index = i
    choice = tui.menu("Base preset (its bindings stay as fallback)",
                      [label for label, _ in entries], index)
    if choice is None:
        return False
    cfg["base"] = entries[choice][1]
    return True


def detect_devices_screen(tui):
    tui.page("Device detection")
    devices = capture.detect_roles(tui, ("stick", "throttle"))
    if devices is None:
        tui.log("Need at least two joystick devices — check connections.")
        tui.wait_any_key()
        return None
    return devices


def section_stats(results, items):
    """(bound, skipped, total) for one section's items."""
    bound = sum(1 for f, _, _ in items if results.get(f))
    skipped = sum(1 for f, _, _ in items if f in results and not results[f])
    return bound, skipped, len(items)


def target_stats(results, target):
    bound = skipped = total = 0
    for _, items in SECTIONS[target]:
        b, s, n = section_stats(results, items)
        bound, skipped, total = bound + b, skipped + s, total + n
    return bound, skipped, total


def progress_label(title, bound, skipped, total):
    label = f"{title}  [{bound}/{total}"
    if skipped:
        label += f", {skipped} skipped"
    return label + "]"


def run_table(tui, devices, results, used, sections, path, heading):
    """Arrow-key table over all functions of the given sections."""
    rows = []                             # ("header", title) / ("item", ...)
    for sec_title, items in sections:
        rows.append(("header", sec_title, None, None))
        for func, kind, desc in items:
            rows.append(("item", func, kind, desc))
    item_rows = [i for i, r in enumerate(rows) if r[0] == "item"]
    if not item_rows:
        return
    sel = item_rows[0]
    state = {"top": 0}

    def move(step):
        nonlocal sel
        pos = item_rows.index(sel)
        pos = max(0, min(len(item_rows) - 1, pos + step))
        sel = item_rows[pos]

    def draw(status_lines):
        h, _ = tui.scr.getmaxyx()
        visible = max(4, h - 6)
        top = state["top"]
        if sel < top:
            top = sel
        elif sel >= top + visible:
            top = sel - visible + 1
        state["top"] = top
        tui.scr.erase()
        tui._put(0, 0, heading, curses.A_BOLD)
        for row, i in enumerate(range(top, min(len(rows), top + visible))):
            what, a, _, _ = rows[i]
            y = 2 + row
            if what == "header":
                tui._put(y, 0, f"--- {a} ---", curses.A_BOLD)
            else:
                current = (describe(results[a]) if a in results
                           else "(unset)")
                attr = curses.A_REVERSE if i == sel else curses.A_NORMAL
                tui._put(y, 2, f"{a:32s} {current}", attr)
        for j, line in enumerate(status_lines[:2]):
            tui._put(h - 3 + j, 0, line)
        tui._put(h - 1, 0, "arrows = move, RETURN = bind, I = invert, "
                           "X = clear, ESC = back")
        tui.scr.refresh()

    status = []
    while True:
        draw(status)
        k = tui.key(0.5)
        if k is None:
            continue
        if k == "esc":
            return
        if k == "up":
            move(-1)
            status = []
        elif k == "down":
            move(+1)
            status = []
        elif k in ("x", "X"):
            _, func, _, _ = rows[sel]
            results[func] = None
            save(results, path)
            status = [f"{func}: cleared (base preset binding stays)"]
        elif k in ("i", "I"):
            _, func, _, _ = rows[sel]
            r = results.get(func)
            if r and r["type"] == "axis":
                r["sign"] = -r["sign"]
                save(results, path)
                status = [f"{func}: inverted -> {describe(r)}"]
        elif k == "enter":
            _, func, kind, desc = rows[sel]
            while True:
                draw([f"-> {desc}", "   waiting for input...  (ESC = cancel)"])
                got = wait_input(devices, want_axis=(kind == "axis"), tui=tui)
                if got == "skip":                  # ESC = cancel capture
                    status = [f"{func}: unchanged"]
                    break
                d, etype, number, sign = got
                key_ = (d.role, etype, number)
                dup = (f"  WARNING: same as {used[key_]}!"
                       if key_ in used and etype == "button" else "")
                drain(devices, tui)
                accept = None
                while accept is None:
                    label = (f"button {number + 1}" if etype == "button"
                             else f"axis {number} "
                                  f"({'+' if sign > 0 else '-'})")
                    opts = ("[RETURN = accept, ESC = redo, I = invert]"
                            if etype == "axis"
                            else "[RETURN = accept, ESC = redo]")
                    draw([f"-> {desc}",
                          f"   captured: {d.role} {label}{dup}  {opts}"])
                    kk = tui.key(0.5)
                    if kk == "enter":
                        accept = True
                    elif kk == "esc":
                        accept = False
                    elif kk in ("i", "I") and etype == "axis":
                        sign = -sign
                if accept:
                    used.setdefault(key_, func)
                    results[func] = {"role": d.role, "type": etype,
                                     "index": number, "sign": sign}
                    save(results, path)
                    status = [f"{func}: {describe(results[func])}"]
                    move(+1)                       # the NEXT affordance
                    break
            drain(devices, tui)


def tui_main(scr, args, results, cfg):
    tui = ctui.setup(scr)

    if not screen_base_preset(tui, cfg):
        return
    results["_config"] = cfg
    save(results, args.results)

    active = detect_devices_screen(tui)
    if active is None:
        return
    joys = proc_joysticks()
    results["_devices"] = {
        d.role: {"name": d.name,
                 "vid": joys.get(d.name, {}).get("vid", ""),
                 "pid": joys.get(d.name, {}).get("pid", ""),
                 "axmap": axis_map(d.fd, d.n_axes)}
        for d in active}
    save(results, args.results)

    # duplicate detection seeded with what is already recorded
    used = {}
    for func, r in results.items():
        if not func.startswith("_") and r and r["type"] == "button":
            used.setdefault((r["role"], "button", r["index"]), func)

    while True:
        choice = tui.menu("ed-bind-wizard — main menu", [
            progress_label("Bind SHIP controls",
                           *target_stats(results, "ship")),
            progress_label("Bind SRV controls",
                           *target_stats(results, "srv")),
            "Generate .binds",
            "Quit",
        ])
        if choice in (None, 3):
            return
        if choice == 2:
            tui.page("Generate .binds")
            try:
                for line in generate(results, cfg["base"],
                                     cfg["bindings_dir"], args.preset_name,
                                     args.backup_dir):
                    tui.log(line)
            except (RuntimeError, OSError, ET.ParseError) as e:
                tui.log(f"ERROR: {e}")
            tui.wait_any_key()
            continue
        target = "ship" if choice == 0 else "srv"
        while True:
            secs = SECTIONS[target]
            labels = ([progress_label("ALL sections",
                                      *target_stats(results, target))]
                      + [progress_label(title, *section_stats(results, items))
                         for title, items in secs]
                      + ["<- back"])
            sc = tui.menu(f"{target.upper()} — mapping sections", labels)
            if sc is None or sc == len(labels) - 1:
                break
            chosen = secs if sc == 0 else [secs[sc - 1]]
            heading = (f"{target.upper()} — "
                       f"{'all sections' if sc == 0 else chosen[0][0]}")
            run_table(tui, active, results, used, chosen, args.results,
                      heading)


# -------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--results", default=DEFAULT_RESULTS,
                    help="results JSON: wizard state / generator input "
                         "(default: next to this script)")
    ap.add_argument("--reset", action="store_true",
                    help="delete the results file and start from scratch")
    ap.add_argument("-g", "--generate", action="store_true",
                    help="generate the .binds preset from results and exit")
    ap.add_argument("--preset-name", default="Izowiuz-VIRPIL",
                    help="preset name shown in the game dropdown")
    ap.add_argument("--game-dir", default=None,
                    help="Elite Dangerous game folder "
                         "(steamapps/common/Elite Dangerous); required on "
                         "first TUI run, remembered afterwards")
    ap.add_argument("--base", default=None,
                    help="base .binds preset to build on "
                         "(default: the one picked in the TUI)")
    ap.add_argument("--bindings-dir", default=None,
                    help="where to write the generated .binds "
                         "(default: the folder picked in the TUI)")
    backup.add_argument(ap, "elite")
    args = ap.parse_args()

    if args.reset and os.path.exists(args.results):
        os.remove(args.results)

    if args.generate:
        with open(args.results) as f:
            results = json.load(f)
        cfg = results.get("_config", {})
        base = args.base or cfg.get("base") or DEFAULT_BASE
        bindings_dir = (args.bindings_dir or cfg.get("bindings_dir")
                        or DEFAULT_BINDINGS_DIR)
        try:
            for line in generate(results, base, bindings_dir,
                                 args.preset_name, args.backup_dir):
                print(line)
        except (RuntimeError, OSError, ET.ParseError) as e:
            sys.exit(f"ERROR: {e}")
        return

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.exit("Run this in a regular terminal (the wizard is a TUI), "
                 "or use --generate for headless generation.")

    results = {}
    if os.path.exists(args.results):
        with open(args.results) as f:
            results = json.load(f)
        results.pop("_skip", None)         # from an older wizard version
    cfg = resolve_config(args, dict(results.get("_config", {})))
    curses.wrapper(tui_main, args, results, cfg)


if __name__ == "__main__":
    main()

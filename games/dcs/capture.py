#!/usr/bin/env python3
"""capture.py - find the devices, pick a module, write diff.lua

DESCRIPTION
    Full-screen wizard by default: name which joystick DCS calls what, pick an
    aircraft, and write one diff.lua per device.
    With --generate, headless: build them and exit.

    Binding is `./bind-wizard.py dcs tui` -- the review screen the other five
    games open. It reads and writes the same results file and shows what you
    confirmed here in green.

KEYS
    arrows  move between entries
    RETURN  select
    ESC     back, cancel, redo

FILES
    dcs-results.json    the bindings, and where the game is (-r)
    <module>/default.lua            read: the command list, via a lua binary
    Config/Input/<aircraft>/joystick/<device>.diff.lua   written by --generate

NOTES
    Close DCS first: it rewrites Config/Input on exit.
    Without a lua binary the command list falls back to the factory profiles:
    fewer commands, and whatever names their authors used.
    --generate also clears DCS's per-device defaults, which otherwise assign
    pitch, roll, rudder and thrust to every joystick at once.
"""

# Interactive DCS World bindings wizard + diff.lua generator for HOTAS on Linux.
#
# TUI mode (default): full-screen terminal wizard. Flow:
#
#     1. game folder comes from --game-dir (remembered in the results file,
#        so you only pass it once); the Saved Games folder inside the Proton
#        prefix is derived from it
#     2. pick the aircraft (installed modules are discovered automatically)
#     3. bind the essentials — or pick one of the game's own sections, or ALL
#
# 'Essentials' is the short list to set up first, and it tries to answer
# the question a new module actually raises — not 'which button do I
# press' but 'what is this thing and do I need it?':
#
#     * the list is the hint table's answer: every command it puts on a
#       HOTAS, so a Hornet opens on trigger, trim, sensor control and TDC
#       rather than on the 800-odd switches of its cockpit;
#     * they are grouped in the order you learn an aircraft — fly it,
#       take off and land, fight with it, sensors and radio;
#     * the selected row explains itself in the two lines above the key
#       legend: what the control does, and where it sits in the real
#       aircraft. Both stay on screen while you are capturing a button —
#       the prompt gets its own line — because that is when you need them.
#
# Commands are harvested from the game files themselves: the module's
# default.lua is run through a Lua interpreter (when one is installed) for
# the full list with today's names and categories, and the factory joystick
# profiles supply the hashes of the sim's own commands. Either way there is
# no hardcoded function list — the wizard works for any installed module.
#
# Bindings are edited in a table: every command of the section is a row
# showing its current assignment straight from the results file. Keys:
#
#     arrows  move between commands
#     RETURN  (re)bind the selected command — then press the physical
#             button / move the axis; after accepting, the cursor moves
#             to the next row so you can chain RETURN-capture-RETURN
#     I       invert an axis (stored or freshly captured)
#     X       clear the binding (the DCS default, if any, comes back)
#     ESC     back / cancel / redo
#
# Results are saved after every change, so quitting any time is safe.
#
# Generator mode (--generate): headless; builds one diff.lua per device and
# writes them into Saved Games/DCS/Config/Input/<aircraft>/joystick/.
# DCS overwrites those files on exit, so generation refuses to run while
# the game is running. Whatever they replace is copied into the backup
# folder first (core.backup; --backup-dir moves it).
#
# The generator also cleans up DCS's per-device defaults (it assigns
# pitch/roll/rudder/thrust and fire/weapon-change/cannon to EVERY joystick
# device), so a stick and a throttle never fight over the same axis.
#
# Usage:
#     capture.py                      # TUI wizard
#     capture.py --reset              # wizard from scratch
#     capture.py -r other.json        # use a different results file
#     capture.py -g -a su-25T         # write the diff.lua files

import argparse
import collections
import copy
import curses
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RESULTS = os.path.join(SCRIPT_DIR, "dcs-results.json")

CORE = os.environ.get("SIM_BIND_WIZARD") or os.path.normpath(
    os.path.join(SCRIPT_DIR, "..", ".."))
if not os.path.isdir(CORE):
    raise SystemExit("There is no shared core at %s.\n"
                     "Set SIM_BIND_WIZARD to the sim-bind-wizard checkout."
                     % CORE)
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import backup                                     # noqa: E402
from core import capture                                    # noqa: E402
from core import game                                       # noqa: E402
from core.game import install_dir                           # noqa: E402
from core import tui as ctui                                # noqa: E402
from core.capture import (axis_map, drain, save,             # noqa: E402
                          wait_input)
#: The bands the hint table answers in. The scale is the core's -- six
#: games share it -- and only which band a command sits in is this
#: module's to say.
from core.needs import (IN_A_TURN, ON_APPROACH,              # noqa: E402
                        IN_THE_AIR, ON_THE_RAMP)

DCS_APPID = "223750"

AXIS_THRESHOLD = capture.AXIS_THRESHOLD
DEBOUNCE = capture.DEBOUNCE

# ABS_* code -> axis name as DCS sees it under Wine (HID-usage order)
ABS_TO_DCS = {0: "JOY_X", 1: "JOY_Y", 2: "JOY_Z",
              3: "JOY_RX", 4: "JOY_RY", 5: "JOY_RZ",
              6: "JOY_SLIDER1", 7: "JOY_SLIDER2"}

# DCS assigns these to EVERY joystick device it sees (DefaultAssignments.lua
# + base_joystick_binding.lua); the generator removes them wherever they
# would conflict with the wizard's bindings.
DEFAULT_AXIS_KEYS = {"Pitch": "JOY_Y", "Roll": "JOY_X",
                     "Rudder": "JOY_RZ", "Thrust": "JOY_Z"}
DEFAULT_BUTTON_KEYS = {"Weapon Fire": "JOY_BTN1", "Weapon Change": "JOY_BTN4",
                       "Cannon": "JOY_BTN5"}

# axis tuning applied by command name: (curvature, deadzone).  Values match
# Eagle Dynamics' own VPC WarBRD profile; tweak in-game via Axis Tune.
AXIS_FILTERS = {"Pitch": (0.12, 0.03), "Roll": (0.12, 0.03),
                "Rudder": (0.15, 0.05)}
SLIDER_PREFIX = "Thrust"       # Thrust / Thrust Left / Thrust Right

CATEGORY_ORDER = ["Axes", "Flight Control", "Systems", "Autopilot", "Modes",
                  "Weapons", "Sensors", "Countermeasures", "View", "Cockpit"]


# ---------------------------------------------------------------- devices --

def dcs_running():
    """DCS does not rewrite Config/Input while it runs, but it DOES on exit,
    which comes to the same thing for a generator."""
    return game.running("DCS.exe")


# --------------------------------------------------------- game data mining --

_NAME_RE = re.compile(r"name\s*=\s*_\('((?:[^'\\]|\\.)*)'\)")
_CATEGORY_RE = re.compile(r"category\s*=\s*(?:\{\s*)?_\('((?:[^'\\]|\\.)*)'\)")
_HASH_RE = re.compile(r'\["(a\d+[^"]*|d(?:\d+|nil)p[^"]*)"\]\s*=\s*\{')
_DIFF_NAME_RE = re.compile(r'\["name"\]\s*=\s*"([^"]+)"')
_LOG_DEVICE_RE = re.compile(r"created \[(.+?)\] with full id \[(.+?)\],JOYSTICK")


def _unescape(s):
    return s.replace("\\'", "'").replace('\\"', '"')


_INPUT_PROFILE_RE = re.compile(
    r"""\[\s*['"]([^'"]+)['"]\s*\]\s*=\s*[^,}]*?/Input/([^'"]+?)/?['"]""")


def input_profiles(module_dir):
    """Input folder name -> the unit name DCS saves that aircraft under.

    Straight out of the module's entry.lua, where the two are spelled out
    side by side — and they differ often enough to matter: the Hornet
    ships `["FA-18C_hornet"] = .. '/Input/FA-18C/'`, so its user profiles
    live in Config/Input/FA-18C_hornet while its factory ones are under
    Input/FA-18C.
    """
    entry = os.path.join(module_dir, "entry.lua")
    if not os.path.exists(entry):
        return {}
    text = open(entry, encoding="utf-8", errors="replace").read()
    block = text.split("InputProfiles", 1)
    if len(block) < 2:
        return {}
    block = block[1].split("}", 1)[0]
    return {os.path.basename(path): unit
            for unit, path in _INPUT_PROFILE_RE.findall(block)}


def discover_aircraft(cfg):
    """aircraft key (Input folder name) ->
    {'display', 'factory_dir', 'input_id'}."""
    out = {}
    pattern = os.path.join(cfg["game_dir"], "Mods", "aircraft", "*",
                           "Input", "*", "joystick", "default.lua")
    for default_lua in sorted(glob.glob(pattern)):
        joy_dir = os.path.dirname(default_lua)
        key = os.path.basename(os.path.dirname(joy_dir))
        display = key
        name_lua = os.path.join(os.path.dirname(joy_dir), "name.lua")
        if os.path.exists(name_lua):
            m = _NAME_RE.search("name = " +
                                open(name_lua, encoding="utf-8").read()
                                .replace("return", "", 1))
            if m:
                display = _unescape(m.group(1))
        module_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            joy_dir)))
        out[key] = {"display": display, "factory_dir": joy_dir,
                    "input_id": input_profiles(module_dir).get(key, key)}
    # aircraft the user has flown but whose module folder we did not match
    known = {a["input_id"] for a in out.values()} | set(out)
    for d in sorted(glob.glob(os.path.join(cfg["saved_games"], "Config",
                                           "Input", "*", "joystick"))):
        key = os.path.basename(os.path.dirname(d))
        if key not in known:
            out[key] = {"display": key, "factory_dir": None,
                        "input_id": key}
    return out


def input_id(cfg, aircraft):
    """The folder DCS itself reads this aircraft's user profiles from."""
    return (discover_aircraft(cfg).get(aircraft) or {}).get(
        "input_id", aircraft)


LUA_HARVEST = r"""
-- Dump every bindable command of a DCS module, one TSV row each:
--     <kind> <TAB> <hash> <TAB> <name> <TAB> <category>
-- kind is 'k'/'a' for key/axis commands whose ids are plain numbers (the
-- module's own cockpit commands) and 'K'/'A' for the ones wired to an
-- engine constant (iCommand...) that only the running game knows -- those
-- rows carry an empty hash and get matched back to one by name.
--
-- The module's default.lua is normal Lua, it just expects the game's
-- globals to exist; every unknown global becomes a sentinel table that
-- survives being called and indexed, so the file runs to completion.
local game_dir, folder_arg = ...
folder = folder_arg

local sentinel_mt
local function sentinel(sym)
    return setmetatable({__sym = sym}, sentinel_mt)
end
sentinel_mt = {
    __call = function(t, ...) return sentinel(t.__sym .. "()") end,
    __index = function(t, k)
        return sentinel(t.__sym .. "." .. tostring(k))
    end,
    __add = function(t, o) return sentinel("sum") end,
    __sub = function(t, o) return sentinel("diff") end,
    __unm = function(t) return sentinel("neg") end,
    __len = function(t) return 0 end,
    __tostring = function(t) return "<" .. t.__sym .. ">" end,
}
setmetatable(_G, {__index = function(t, k)
    local s = sentinel(k)
    rawset(t, k, s)
    return s
end})

_ = function(s) return s end
require = function(m) return sentinel("require:" .. tostring(m)) end
function join(dst, src)
    for _i, v in ipairs(src) do dst[#dst + 1] = v end
    return dst
end
function external_profile(rel)
    return assert(loadfile(game_dir .. "/" .. rel))()
end

-- DCS serializes the ids with Lua 5.1 number formatting: 1.0 -> "1"
local function num(v)
    if v == nil then return "nil" end
    if type(v) == "number" then return string.format("%.14g", v) end
    return nil                          -- an engine constant: unresolved
end
local function category(c)
    if type(c) == "table" then return tostring(c[1] or "") end
    return tostring(c or "")
end
local function clean(s)
    return (tostring(s):gsub("[\t\r\n]", " "))
end

local res = assert(loadfile(folder .. "default.lua"))()

for _i, c in ipairs(res.keyCommands or {}) do
    if c.name then
        local d, p, u = num(c.down), num(c.pressed), num(c.up)
        local cd = num(c.cockpit_device_id)
        local vd, vp, vu = num(c.value_down), num(c.value_pressed),
                           num(c.value_up)
        if d and p and u and cd and vd and vp and vu then
            print(("k\t%s\t%s\t%s"):format(
                "d" .. d .. "p" .. p .. "u" .. u .. "cd" .. cd ..
                "vd" .. vd .. "vp" .. vp .. "vu" .. vu,
                clean(c.name), clean(category(c.category))))
        else
            print(("K\t\t%s\t%s"):format(clean(c.name),
                                         clean(category(c.category))))
        end
    end
end
for _i, c in ipairs(res.axisCommands or {}) do
    if c.name then
        local a, cd = num(c.action), num(c.cockpit_device_id)
        if a and cd then
            print(("a\t%s\t%s\t%s"):format("a" .. a .. "cd" .. cd,
                                           clean(c.name),
                                           clean(category(c.category))))
        else
            print(("A\t\t%s\t%s"):format(clean(c.name),
                                         clean(category(c.category))))
        end
    end
end
"""


def lua_binary():
    for name in ("lua", "luajit", "lua5.4", "lua5.3", "lua5.2", "lua5.1"):
        found = shutil.which(name)
        if found:
            return found
    return None


def lua_commands(cfg, factory_dir):
    """[(hash or None, name, category, kind)] from the module's default.lua.

    Returns None when there is no Lua interpreter on the box or the file
    refuses to run — the caller then falls back to the factory profiles
    alone.
    """
    binary = lua_binary()
    if not binary or not factory_dir:
        return None
    if not os.path.exists(os.path.join(factory_dir, "default.lua")):
        return None
    fd, script = tempfile.mkstemp(suffix=".lua")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(LUA_HARVEST)
        out = subprocess.run([binary, script, cfg["game_dir"],
                              factory_dir + os.sep],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        os.unlink(script)
    if out.returncode != 0:
        return None
    rows = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 4 or parts[0] not in ("k", "a", "K", "A"):
            continue
        kind = "axis" if parts[0] in ("a", "A") else "button"
        rows.append((parts[1] or None, parts[2], parts[3], kind))
    return rows or None


def _is_latin(name):
    """DCS ships Russian-language factory profiles too — a Latin name for
    the same command always wins over a Cyrillic one."""
    return not re.search("[\u0400-\u04ff]", name)


def _norm(name):
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def scan_profiles(dirs):
    """hash -> name, read off the factory joystick profiles.

    The one thing the shipped profiles are read for, and it is an
    IDENTIFIER, not advice: the sim's own commands (Pitch, Thrust, gear,
    the views) carry ids that live in the exe, so a profile that binds
    one is the only offline place its hash can be found -- and a hash is
    what `diff.lua` is written against. Twelve of the Hornet's 59
    bindings have no other source.

    Nothing about a profile's LAYOUT is read any more: which device it
    was written for, and how many of them bound a command, used to pick
    the list and the device for every command in the module. See the note
    on HINTS for why that went.
    """
    names = {}
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "*.diff.lua"))):
            text = open(path, encoding="utf-8", errors="replace").read()
            for m in _HASH_RE.finditer(text):
                h = m.group(1)
                block = text[m.end():m.end() + 3000]
                nm = _DIFF_NAME_RE.search(block)
                if nm and (h not in names or (_is_latin(nm.group(1))
                                              and not _is_latin(names[h]))):
                    names[h] = nm.group(1)
    return names


_ENGINE_INDEX = {}


def engine_hash_index(cfg):
    """normalized name -> hash, for the sim's own commands only.

    Their ids live in the exe, so the only place a hash for, say, 'Gear
    Up' can be found is a profile that binds it — and since those ids are
    global, any module's factory profiles will do. Cockpit commands are
    left out on purpose: their ids are per-module, so an identical name
    in another module would mean something else entirely.
    """
    key = cfg["game_dir"]
    if key not in _ENGINE_INDEX:
        dirs = [a["factory_dir"] for a in discover_aircraft(cfg).values()
                if a["factory_dir"]]
        names = scan_profiles(dirs)
        _ENGINE_INDEX[key] = {_norm(n): h for h, n in names.items()
                              if "cdnil" in h and _is_latin(n)}
    return _ENGINE_INDEX[key]


# Which way the switch goes, for the commands that live on a hat. The
# name wins over the symbol where it is explicit, because it describes
# the movement ('PULL(CLIMB)') while the symbol only names the function
# ('STICK_TRIMMER_UP') — you pull a trim hat back to climb.
HAT_MOVES = [
    # diagonals need the two words next to each other, so that a roll
    # trim ('LEFT WING DOWN') does not read as one
    (r"\bup[ -]+left\b|\bleft[ -]+up\b", "UP-LEFT, the diagonal"),
    (r"\bup[ -]+right\b|\bright[ -]+up\b", "UP-RIGHT, the diagonal"),
    (r"\bdown[ -]+left\b|\bleft[ -]+down\b", "DOWN-LEFT, the diagonal"),
    (r"\bdown[ -]+right\b|\bright[ -]+down\b", "DOWN-RIGHT, the diagonal"),
    # explicit next: 'LEFT WING DOWN' is a roll trim, not a nose-down one
    (r"nose ?up|climb|pull\b", "PULL back (nose up)"),
    (r"nose ?down|descend|push\b", "PUSH forward (nose down)"),
    (r"\bfwd\b|forward", "FORWARD, away from you"),
    (r"\baft\b", "AFT, towards you"),
    (r"left", "LEFT"),
    (r"right", "RIGHT"),
    (r"trim.*\bup\b", "PULL back (nose up)"),
    (r"trim.*\bdown\b", "PUSH forward (nose down)"),
    (r"\bup\b", "UP"),
    (r"\bdown\b", "DOWN"),
    (r"\bin\b", "INBOARD (towards your left)"),
    (r"\bout\b", "OUTBOARD"),
    (r"depress|press", "PRESS the hat in"),
]


def hat_move(name, symbol_dir):
    for text_ in (name, symbol_dir):
        for pattern, move in HAT_MOVES:
            if text_ and re.search(pattern, text_, re.I):
                return move
    return ""


_SYMBOL_RE = re.compile(r"_commands\.([A-Z][A-Z0-9_]*)")
DIRECTION_WORDS = ("FWD", "FORWARD", "AFT", "UP", "DOWN", "LEFT", "RIGHT",
                   "IN", "OUT", "DEPRESS", "PRESS")


def symbol_directions(factory_dir):
    """command name -> the direction its own symbol ends in.

    default.lua writes the switch out as e.g. STICK_WEAPON_SELECT_FWD on
    the same line as the name 'Select Sparrow' — which is the only place
    in the game files where that switch's physical direction is spelled
    out at all. Aircraft whose commands live in the exe (the FC3-era
    ones) have no symbols, but their names carry the direction instead.
    """
    out = {}
    path = os.path.join(factory_dir or "", "default.lua")
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8", errors="replace"):
        nm = _NAME_RE.search(line)
        if not nm:
            continue
        for sym in _SYMBOL_RE.findall(line):
            head, _, tail = sym.rpartition("_")
            if tail in DIRECTION_WORDS:
                out.setdefault(_unescape(nm.group(1)), (tail, head))
                break
    return out


def switch_family(name, symbol_head):
    """The physical switch a directional command belongs to.

    Its siblings are what tell a four-way hat (Fwd/Aft/Left/Right) from a
    plain two-position panel switch (Up/Down) — the module's symbols group
    them when it has any (STICK_WEAPON_SELECT_*), the names when it does
    not ('Trim Hat - NOSE UP' and friends).
    """
    if symbol_head:
        return symbol_head
    base = name.split(" - ")[0] if " - " in name else name
    return _norm(re.sub(r"\b(%s)\b" % "|".join(DIRECTION_WORDS), "", base,
                        flags=re.I))


def catalogue(cmds):
    """[Action] -- one module's commands in the shape every game shares.

    Beside `harvest_commands`, which builds the records this reads, for the
    same reason the other five build theirs in their harvests: what a field
    is called is a fact about the format, and it is settled where the
    format is parsed.

    Unlike the other five, nothing of this is written to the cache. A DCS
    command record already carries `ways`, `dir` and `family` -- how a
    switch moves, which way, and what it groups with -- which the shared
    record has no room for and seven places in `plan.py` read. Writing
    the shared spelling beside it would put name, kind and category twice
    in every one of ~2500 records, for no reader. The record stays one
    record; only the reading of it is settled here.

    Keyed by the wizard's command hash, because that is what every DCS
    record uses and what the results file is written against.
    """
    return [cactions.Action(h, c.get('name') or h,
                            kind=('axis' if c.get('kind') == 'axis'
                                  else 'button'),
                            category=c.get('category'))
            for h, c in sorted(cmds.items())]


def harvest_commands(cfg, aircraft_key, factory_dir):
    """hash -> {'name', 'kind', 'category', 'dir', 'family', 'ways'} for
    one aircraft: what the module says about itself, and nothing else.

    Two sources, and the wizard needs both:

    * the module's default.lua, run through a Lua interpreter with the
      game's globals stubbed out — it lists *every* bindable command with
      the name and category the game shows today, and for cockpit
      commands it carries the ids the diff.lua hash is built from;
    * the factory joystick profiles shipped with the module, which supply
      the hashes of the commands wired to engine constants (the sim's own
      pitch/thrust/gear/view commands, whose numbers live in the exe).
      That is all they supply — `scan_profiles` says why.

    With no Lua interpreter around the profiles are the only source, i.e.
    exactly what this did before: fewer commands, and whatever name and
    category the profile author happened to use.
    """
    user_dirs = glob.glob(os.path.join(cfg["saved_games"], "Config",
                                       "Input", input_id(cfg, aircraft_key),
                                       "*"))
    names = scan_profiles([factory_dir] if factory_dir else [])
    user_names = scan_profiles(user_dirs)
    for h, name in user_names.items():
        names.setdefault(h, name)
    commands = {h: {"name": name} for h, name in names.items()}

    categories = {}
    cat_files = []
    if factory_dir:
        cat_files.append(os.path.join(factory_dir, "default.lua"))
    cat_files += sorted(glob.glob(os.path.join(
        cfg["game_dir"], "Config", "Input", "Aircrafts", "*.lua")))
    for path in cat_files:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="replace"):
            if line.lstrip().startswith("--"):
                continue
            nm, cat = _NAME_RE.search(line), _CATEGORY_RE.search(line)
            if nm:
                categories.setdefault(
                    _unescape(nm.group(1)),
                    _unescape(cat.group(1)) if cat else "Other")

    def tokens(name):
        return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", name.lower())}

    token_map = [(tokens(n), c) for n, c in categories.items()]

    def category_for(name):
        """Exact match first; factory profiles often carry outdated labels
        (e.g. 'Trim Hat - NOSE UP' vs today's 'Trim: Nose Up'), so fall
        back to the best token-subset match against current game names."""
        if name in categories:
            return categories[name]
        mine = tokens(name)
        best, best_n = None, 1
        for toks, cat in token_map:
            if len(toks) > best_n and toks <= mine:
                best, best_n = cat, len(toks)
        if best:
            return best
        # last resort: strongest token overlap, but only when every
        # equally-good candidate agrees on the category
        best_n, cats = 1, set()
        for toks, cat in token_map:
            n = len(toks & mine)
            if n > best_n:
                best_n, cats = n, {cat}
            elif n == best_n:
                cats.add(cat)
        return cats.pop() if len(cats) == 1 else "Other"

    for h, info in commands.items():
        info["kind"] = "axis" if h.startswith("a") else "button"
        info["category"] = ("Axes" if info["kind"] == "axis"
                            else category_for(info["name"]))

    # default.lua on top: current names and categories for the commands we
    # already have, plus every command no factory profile ever bound
    by_name = {}
    for h, name in names.items():
        by_name.setdefault(_norm(name), h)
    for hash_, name, category, kind in lua_commands(cfg, factory_dir) or []:
        if hash_ is None:                  # engine command: hash by name
            hash_ = (by_name.get(_norm(name))
                     or engine_hash_index(cfg).get(_norm(name)))
            if hash_ is None or hash_.startswith("a") != (kind == "axis"):
                continue
        info = commands.setdefault(hash_, {})
        info["name"] = name
        info["kind"] = kind
        info["category"] = ("Axes" if kind == "axis"
                            else category or info.get("category", "Other"))
    directions = symbol_directions(factory_dir)
    for info in commands.values():
        info["dir"], head = directions.get(info["name"], ("", ""))
        info["family"] = switch_family(info["name"], head)
    families = {}
    for info in commands.values():
        move = hat_move(info["name"], info["dir"])
        if move:
            families.setdefault(info["family"], set()).add(move)
    for info in commands.values():
        info["ways"] = len(families.get(info["family"], ()))
    return commands


def build_sections(commands):
    """[(category, [(hash, name, kind), ...]), ...] in a sensible order."""
    by_cat = {}
    for h, info in commands.items():
        by_cat.setdefault(info["category"], []).append(
            (h, info["name"], info["kind"]))
    for items in by_cat.values():
        items.sort(key=lambda x: x[1].lower())

    def order(cat):
        return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER
                else len(CATEGORY_ORDER), cat.lower())
    return [(cat, by_cat[cat]) for cat in sorted(by_cat, key=order)]


THEMES = [
    ("fly", "FLY IT — nothing else matters until these work"),
    ("land", "TAKE OFF AND LAND"),
    ("fight", "FIGHT WITH IT"),
    ("sensors", "SENSORS AND RADIO"),
    ("cockpit", "COCKPIT AND VIEWS"),
]

#: What a command is, said twice on purpose: in words for whoever is
#: reading the screen, and as data for the layout.
#:
#: `on` puts a command on the HOTAS -- it names the device role it belongs
#: to, or None for "anywhere the points like", and the band it is touched
#: in. `off` says it is a cockpit control the keyboard can have. The words
#: cannot carry that: "a handle on the right panel. A spare throttle
#: switch" and "a cockpit handle: keyboard is fine" are one sentence apart
#: and mean opposite things to a scorer.
#:
#: Being on the HOTAS is also what puts a command on the list to bind --
#: `essentials` below. That used to be a popularity contest: the module's
#: commands ranked by how many of its factory joystick profiles bound each
#: one, cut at a third of the busiest. The question it answered was "what
#: did Eagle Dynamics' profile authors put on a Warthog", which is not
#: "what does this aircraft have, and where does it live" -- a profile
#: says `throttle` because a Warthog has buttons there. So the judgement
#: is written down here, by hand, where it can be argued with.
#:
#: First match wins, so the specific rows sit above the general ones: the
#: tight row is the one that belongs on the HOTAS, and the broad row under
#: it explains the rest of the cockpit. `COMM Switch - MIDS A` is the
#: radio switch on the throttle; the 36 other Hornet commands with "comm"
#: in their name are panel knobs.
Hint = collections.namedtuple("Hint", "theme device band hint place")


def on(pattern, theme, device, band, hint, place):
    return pattern, Hint(theme, device, band, hint, place)


def off(pattern, theme, hint, place):
    return pattern, Hint(theme, None, None, hint, place)


# What a control actually does, for someone who has never flown the type:
# the command names come from the module, these are matched onto them by
# concept, so gear/flaps/trim/countermeasures/radio explain themselves in
# any aircraft.
HINTS = [
    # First, above everything: DCS ships a "(special)" twin of many cockpit
    # switches -- same switch, one of them written for a HOTAS toggle that
    # holds its position. Two bindings for one switch is one wasted button,
    # so the plain one gets it.
    off(r"\(special\)", "other",
        "The same switch as the command without `(special)`.",
        "Bind the plain one."),

    on(r"^pitch$", "fly", "stick", IN_A_TURN,
       "Stick fore and aft: pull = nose up.",
       "The stick itself — its Y axis."),
    on(r"^roll$", "fly", "stick", IN_A_TURN,
       "Stick left and right: banks the jet.",
       "The stick itself — its X axis."),
    on(r"^rudder$", "fly", "stick", IN_A_TURN,
       "Yaw. Keeps you straight on the runway and pulls the nose around.",
       "Pedals if you have them, otherwise the stick's twist axis."),
    on(r"^thrust|^throttle$", "fly", "throttle", IN_A_TURN,
       "Engine power.",
       "The throttle lever — both levers if the jet has Thrust Left/Right."),
    # The hat, and the pairs a propeller trimmer ships as two commands.
    # NOT the Hornet's RUD TRIM knob or its T/O TRIM button: those are
    # panel controls, and the knob is an axis that would go looking for a
    # lever.
    on(r"trimmer switch|^trim hat|^trim (aileron|elevator|rudder) "
       r"(left|right|up|down)$", "fly", "stick", IN_A_TURN,
       "Trims stick forces away so the jet flies hands-off. Used all day.",
       "On the jet: the TRIM hat on the front of the grip. Give it a "
       "4-way hat."),
    off(r"trim", "fly",
        "Trims stick forces away so the jet flies hands-off.",
        "A panel wheel or knob in this aircraft: keyboard is fine."),
    off(r"rudder", "fly",
        "Yaw, one keypress at a time.",
        "The rudder axis does this better: keyboard is fine."),
    on(r"paddle", "fly", "stick", IN_A_TURN,
       "Kicks the autopilot off. The 'get me out of this' switch.",
       "On the jet: the paddle behind the grip. Use a base or pinky lever."),
    on(r"atc |automatic throttle|autothrottle|auto throttle", "fly",
       "throttle", IN_A_TURN,
       "Autothrottle: holds your approach speed for you — a big help on "
       "the ball.",
       "On the jet: a button on the inboard side of the left throttle."),
    off(r"autopilot", "fly", "Autopilot master switch.",
        "A panel switch: keyboard is fine. The paddle is what you reach "
        "for in a hurry."),
    on(r"war emergency power", "fly", "throttle", IN_A_TURN,
       "WEP: emergency overboost. Minutes only, then the engine is scrap.",
       "On the jet: shove the throttle past the gate. Any throttle "
       "button."),
    on(r"engine rpm", "fly", "throttle", IN_A_TURN,
       "Propeller RPM — set together with the throttle.",
       "On the jet: the blue lever. A second throttle lever or a rotary."),

    off(r"parking brake|brake parking", "land",
        "Parking brake: set before start, release before you taxi.",
        "A cockpit handle: keyboard is fine."),
    on(r"wheel ?brake", "land", "stick", ON_APPROACH,
       "Wheel brakes: hold to slow down.",
       "On the jet: toe brakes. A brake lever on the stick base stands in."),
    off(r"anti ?skid", "land",
        "Anti-skid braking — and part of the Hornet's launch bar / hook "
        "logic.",
        "A console switch: keyboard is fine."),
    on(r"speed ?brake|air ?brake", "land", "throttle", ON_APPROACH,
       "Airbrake: slows you down. Out on approach, in for the go-around.",
       "On the jet: under your left thumb on the throttle. A 2-way there."),
    on(r"flap", "land", "throttle", ON_APPROACH,
       "Flaps — lift at low speed. HALF for takeoff, FULL in the landing "
       "pattern.",
       "On the jet: a lever on the left console. A spare 2-way switch on "
       "the throttle."),
    on(r"^landing gear (control handle - )?(up|down|up/down)$", "land",
       None, ON_APPROACH,
       "Landing gear up/down. Every jet has a gear limit speed — 250 kt in "
       "the Hornet.",
       "On the jet: the gear handle, left panel. A spare 2-way switch."),
    off(r"gear", "land",
        "Landing gear plumbing: emergency extension, the lights, the test "
        "switches.",
        "Panel handles and breakers: keyboard is fine."),
    on(r"nose ?wheel steer|undesignate", "land", "stick", IN_A_TURN,
       "Steers the nosewheel on the ground, undesignates a target in the "
       "air.",
       "On the jet: the small button on the front of the grip, under your "
       "thumb."),
    off(r"hook bypass", "land",
        "Tells the hook logic whether you are trapping at a FIELD or on the "
        "CARRIER.",
        "A cockpit switch: keyboard is fine."),
    on(r"arresting hook", "land", "throttle", ON_APPROACH,
       "Tailhook — down for a carrier trap or a field arrestment.",
       "On the jet: a handle on the right panel. A spare throttle "
       "switch."),
    off(r"hook", "land",
        "Hook wiring and breakers.",
        "Panel switches: keyboard is fine."),
    on(r"^launch bar control switch - ", "land", "throttle", ON_APPROACH,
       "Catapult launch bar: down to hook into the shuttle before the cat "
       "shot.",
       "On the jet: a switch on the left console. A spare throttle "
       "switch."),
    off(r"launch bar", "land",
        "Launch bar wiring and breakers.",
        "Panel switches: keyboard is fine."),
    off(r"catapult hook-?up", "land",
        "Hooks the jet onto the catapult shuttle on the boat.",
        "A ground-crew call: keyboard is fine."),
    off(r"ball|lso", "land",
        "The 'ball' call to the LSO, three quarters of a mile behind the "
        "boat.",
        "A radio call: keyboard is fine."),

    on(r"^\(\d+\) ", "fight", None, IN_A_TURN,
       "Master mode selector: navigation, air-to-ground, gun modes.",
       "Number keys in the real jet too — a stick hat if you have room."),
    on(r"gun trigger.*(first|1st)", "fight", "stick", IN_A_TURN,
       "Trigger's first detent: gun camera only, no rounds.",
       "On the jet: the trigger, halfway. Stage 1 of a two-stage "
       "trigger."),
    on(r"gun trigger|weapon fire|^cannon$", "fight", "stick", IN_A_TURN,
       "Fires the gun or the selected weapon — the trigger's full pull.",
       "On the jet: the trigger. Your stick's trigger."),
    on(r"weapon release|pickle", "fight", "stick", IN_A_TURN,
       "Pickle button: releases the selected air-to-ground weapon.",
       "On the jet: the red button on top of the grip, under your thumb."),
    on(r"select (gun|amraam|sidewinder|sparrow|missile)|weapon (select|"
       r"change)", "fight", "stick", IN_A_TURN,
       "Jumps straight to that missile or the gun without touching an MFD.",
       "On the jet: the four-way switch on the head of the grip. A stick "
       "hat."),
    # The one two-position switch worth the lever over the trigger: the
    # guard position becomes the switch position, so your own hand tells
    # you whether the jet is armed.
    on(r"master arm switch - (arm|safe)$", "fight", "stick", IN_A_TURN,
       "MASTER ARM — nothing leaves the jet until this says ARM.",
       "A guarded switch on the panel in the real jet. Give it the lever "
       "over the trigger."),
    off(r"master arm", "fight",
        "Master arm wiring: the combined toggle and the special variants.",
        "A panel switch: keyboard is fine."),
    on(r"master mode.*a/a|air.to.air mode", "fight", "throttle", IN_A_TURN,
       "A/A master mode: sets the whole jet up for air-to-air in one "
       "press.",
       "Panel buttons under the HUD — often moved to spare throttle "
       "buttons."),
    on(r"master mode.*a/g|air.to.ground mode", "fight", "throttle",
       IN_A_TURN,
       "A/G master mode: sets the jet up for bombing and strafing.",
       "Panel buttons under the HUD — often moved to spare throttle "
       "buttons."),
    on(r"^dispense switch - |^countermeasures (flares|chaff) dispense",
       "fight", "throttle", IN_A_TURN,
       "Countermeasures: chaff against radar missiles, flares against heat "
       "seekers.",
       "On the jet: the CMS switch, outboard side of the throttle. A "
       "4-way hat."),
    off(r"dispens|countermeasure|chaff|flare", "fight",
        "The dispenser's own panel: power, programme, bypass.",
        "A console switch: keyboard is fine."),
    off(r"jettison", "fight",
        "Jettison: throws stores off the jet. Emergency weight loss.",
        "A panel button: keyboard is fine."),
    off(r"ecm|jamm", "fight", "Jammer — noise against enemy radars.",
        "A panel switch: keyboard is fine."),
    off(r"gunsight|reticle|pipper|aiming", "fight",
        "Gunsight / aiming reticle setting.",
        "A panel knob: keyboard is fine."),

    on(r"sensor control switch", "sensors", "stick", IN_A_TURN,
       "The 'castle': hands control to the radar, the pod, helmet or MFD.",
       "On the jet: the hat on TOP of the grip. A 4-way hat that presses."),
    on(r"designator controller - (horizontal|vertical) axis$"
       r"|designator controller - depress$|^tdc", "sensors", "throttle",
       IN_THE_AIR,
       "TDC: drives the radar and targeting cursor. Depress = designate.",
       "On the jet: the thumb slew on the left throttle — a mini-stick "
       "or hat."),
    off(r"designator controller", "sensors",
        "Drives the cursor one step at a time — the digital half of the "
        "slew.",
        "The slew axes do this better: keyboard is fine."),
    on(r"^i-251 slew|shkval slew", "sensors", "throttle", IN_THE_AIR,
       "Slews the TV sensor's box over the target.",
       "On the jet: the slew controller on the throttle — a mini-stick."),
    on(r"cage/uncage button$", "sensors", "throttle", IN_THE_AIR,
       "Uncages a seeker so a Sidewinder or Maverick can look around on "
       "its own.",
       "On the jet: a button under your index finger on the throttle."),
    off(r"cage", "sensors",
        "Cages a gyro instrument so it can settle.",
        "A panel knob: keyboard is fine."),
    on(r"^radar elevation control$", "sensors", "throttle", IN_THE_AIR,
       "Tilts the radar beam — you aim it at the altitude you expect the "
       "target.",
       "On the jet: the antenna wheel on the throttle. A rotary or an axis."),
    off(r"radar elevation", "sensors",
        "Tilts the radar beam one step at a time.",
        "The antenna wheel does this better: keyboard is fine."),
    on(r"target lock|lock target", "sensors", "stick", IN_A_TURN,
       "Locks whatever sits under the aiming pipper.",
       "A thumb button on the grip in the real jet too."),
    on(r"target unlock", "sensors", "stick", IN_A_TURN,
       "Breaks the lock and goes back to searching.",
       "Next to the lock button — keep the pair together."),
    on(r"laser", "sensors", "throttle", IN_THE_AIR,
       "Laser ranger / designator: needed for guided bombs and accurate "
       "gun ranging.",
       "A console switch — a spare throttle button works."),
    on(r"raid|fov", "sensors", "throttle", IN_THE_AIR,
       "Field of view / raid expand for the sensor you are driving.",
       "On the jet: a button on the throttle grip."),
    on(r"display zoom", "sensors", None, IN_THE_AIR,
       "Zooms the sensor picture (not the camera) — the TV or radar "
       "display.",
       "Two spare buttons."),
    off(r"hmd|helmet", "sensors",
        "Helmet-mounted display: the brightness knob doubles as its "
        "on/off.",
        "A panel knob: keyboard is fine."),
    off(r"electro.optical|shkval|i-251|flir|night vision|goggle|lltv",
        "sensors",
        "TV or infrared sensor: the picture you aim with, and see at night.",
        "A console switch: keyboard is fine; the slew goes on the "
        "throttle."),
    off(r"recce|event mark", "sensors",
        "Marks a reconnaissance point. Safe to ignore while you are "
        "learning.",
        "A panel switch: keyboard is fine."),
    off(r"channel selector|preset", "sensors",
        "Dials the radio's preset channel.",
        "A panel knob: keyboard is fine."),
    on(r"^comm switch - ", "sensors", "throttle", IN_THE_AIR,
       "Radio: push-to-talk and the comms menu — ATC, wingmen, tankers.",
       "On the jet: the radio switch on the throttle. Two buttons will "
       "do."),
    on(r"communication menu$", "sensors", None, IN_THE_AIR,
       "Opens the comms menu — ATC, wingmen, tankers.",
       "Any spare button."),
    off(r"comm|radio|voip|intercom|mids", "sensors",
        "The radios' own panel: volumes, antennas, cipher, relay.",
        "Panel knobs and switches: keyboard is fine."),
    off(r"waypoint|steer ?point|navigation mode", "sensors",
        "Steps through your waypoints / picks the navigation mode.",
        "Panel or UFC: keyboard is fine."),

    on(r"^zoom view$", "cockpit", None, ON_THE_RAMP,
       "Zooms the view. You spot and read gauges with it.",
       "A spare axis (rotary or lever)."),
    off(r"zoom", "cockpit",
        "Zooms the view a step at a time.",
        "The zoom axis does this better: keyboard is fine."),
    off(r"kneeboard", "cockpit",
        "Kneeboard pages: checklists, charts and your own notes.",
        "Keyboard is fine."),
    on(r"master caution", "cockpit", None, ON_THE_RAMP,
       "Silences the master caution light once you have read what broke.",
       "On the jet: the light you punch on the panel. A spare button."),
    off(r"canopy", "cockpit", "Opens and closes the canopy.",
        "A cockpit handle: keyboard is fine."),
    off(r"wing fold", "cockpit", "Folds the wings — carrier deck parking.",
        "A cockpit handle: keyboard is fine."),
    # A cold start is the one time the HOTAS is worth switches nobody
    # touches in flight: both hands are already on it, and the alternative
    # is hunting the cockpit with a mouse.
    on(r"^throttle \((left|right)\).*off\(hold\)", "cockpit", "throttle",
       ON_THE_RAMP,
       "Engine cutoff: hold it to shut that engine down.",
       "On the jet: lift the throttle over the cutoff gate. A spare "
       "throttle button."),
    on(r"^engine crank switch - (left|right)$", "cockpit", None,
       ON_THE_RAMP,
       "Spins one engine up for the start. Left, then right.",
       "A console switch — a spare button saves a trip to the cockpit."),
    on(r"^engine (left|right) (start|stop)$", "cockpit", None, ON_THE_RAMP,
       "Starts or shuts down one engine.",
       "A console switch — a spare button saves a trip to the cockpit."),
    on(r"apu control sw|^electric power switch$", "cockpit", None,
       ON_THE_RAMP,
       "APU and battery: the first switches of a cold start.",
       "A console switch — a spare button saves a trip to the cockpit."),
    off(r"engine.*(start|stop|crank)|apu|electric power|battery|generator",
        "cockpit",
        "Startup switch, part of the cold-and-dark sequence.",
        "Console switches: keyboard is fine."),
    on(r"^exterior lights? switch - ", "cockpit", "throttle", ON_THE_RAMP,
       "External lights — on the boat this is also how you salute the "
       "catapult crew.",
       "On the jet: a fingertip switch on the throttle."),
    off(r"exterior light|external light|position light|formation light",
        "cockpit",
        "The exterior lights' dimmers and their per-lamp switches.",
        "Panel knobs: keyboard is fine."),
    off(r"light|illuminat|dimmer|brightness", "cockpit",
        "Lighting or display brightness.",
        "Panel knobs: keyboard is fine."),
    off(r"hud", "cockpit", "HUD symbology or brightness.",
        "A panel knob: keyboard is fine."),
    off(r"view|camera|snap", "cockpit",
        "Camera control — mostly redundant if you have head tracking.",
        "Head tracking, or the keyboard."),
    off(r"mode", "fight", "Master mode / weapon mode selector.",
        "A panel switch: keyboard is fine."),
]

#: nothing in the table fits, so there is nothing to say and nowhere to
#: put it
NO_HINT = Hint("other", None, None, "", "")


def hint_for(name):
    """What the table says about this command."""
    for pattern, said in HINTS:
        if re.search(pattern, name, re.I):
            return said
    return NO_HINT


def build_guide(commands):
    """hash -> {'theme', 'hint', 'place', 'device', 'band'} — what the
    table says about a command besides its name.

    Never cached. It is this module's own judgement applied to the
    command names, not something read off the install, and a copy in the
    cache would keep an edit to the table out of the next plan.
    """
    guide = {}
    for h, c in commands.items():
        said = hint_for(c["name"])
        guide[h] = {
            "theme": said.theme,
            "hint": said.hint or ("%s — no hint for this one yet"
                                  % c.get("category", "?")),
            "place": said.place,
            "device": said.device,
            "band": said.band,
        }
    return guide


def essentials(commands, guide):
    """[(theme title, [(hash, name, kind)])]: the list to bind first.

    Which commands those are is the hint table's answer and nothing
    else: a row the table puts on the HOTAS carries a band — when you
    touch it — and carrying one is what being on this list means. Inside
    a theme the name decides; the themes are the order you learn an
    aircraft in.

    It used to be a vote count, and the cut was relative to the busiest
    command because how many profiles a module ships varies wildly. Both
    are gone: see the note on HINTS.
    """
    sections = []
    for theme, title in THEMES:
        items = sorted(((h, commands[h]["name"], commands[h]["kind"])
                        for h, g in guide.items()
                        if g["band"] is not None and g["theme"] == theme),
                       key=lambda x: x[1].lower())
        if items:
            sections.append((title, items))
    return sections


def _int_keys(v):
    if isinstance(v, dict):
        return {(int(k) if isinstance(k, str) and k.isdigit() else k):
                _int_keys(x) for k, x in v.items()}
    return v


def parse_diff_lua(text):
    """Parse a DCS diff.lua into a Python dict (the format is regular
    enough for a regex translation to JSON)."""
    body = text.split("local diff =", 1)[1].rsplit("return diff", 1)[0]
    s = re.sub(r'\[\s*"((?:[^"\\]|\\.)*)"\s*\]\s*=', r'"\1":', body)
    s = re.sub(r"\[(\d+)\]\s*=", r'"\1":', s)
    s = re.sub(r",(\s*[}\]])", r"\1", s)
    return _int_keys(json.loads(s.strip()))


def dcs_device_ids(saved_games):
    """DCS short device name -> 'Name {GUID}' full id (diff.lua file stem).

    Read from the newest dcs.log; falls back to existing diff.lua names.
    """
    out = {}
    log = os.path.join(saved_games, "Logs", "dcs.log")
    if os.path.exists(log):
        for line in open(log, encoding="utf-8", errors="replace"):
            m = _LOG_DEVICE_RE.search(line)
            if m:
                out[m.group(1)] = m.group(2)
    for path in glob.glob(os.path.join(saved_games, "Config", "Input",
                                       "*", "joystick", "*.diff.lua")):
        stem = os.path.basename(path)[:-len(".diff.lua")]
        m = re.match(r"(.+?) \{[0-9A-Fa-f-]+\}$", stem)
        if m:
            out.setdefault(m.group(1), stem)
    return out


# --------------------------------------------------------------- generator --

def lua(v, indent=1):
    pad = "\t" * indent
    if isinstance(v, dict):
        lines = ["{"]
        for k in sorted(v):
            key = "[%d]" % k if isinstance(k, int) else '["%s"]' % k
            lines.append('%s%s = %s,' % (pad, key, lua(v[k], indent + 1)))
        lines.append("\t" * (indent - 1) + "}")
        return "\n".join(lines)
    if isinstance(v, list):
        return lua({i + 1: x for i, x in enumerate(v)}, indent)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"%s"' % v
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return repr(v)


def make_filter(name, invert):
    curvature, deadzone = AXIS_FILTERS.get(name, (0.0, 0.0))
    return {"curvature": [curvature], "deadzone": deadzone,
            "hardwareDetent": False, "hardwareDetentAB": 0,
            "hardwareDetentMax": 0, "invert": bool(invert),
            "saturationX": 1, "saturationY": 1,
            "slider": name.startswith(SLIDER_PREFIX)}


def vanilla_filter():
    return make_filter("", False)


def resolve_devices(results):
    """role -> {'dcs_id', 'axmap', 'name'}; refreshes axmap from live
    devices when missing."""
    out = {}
    saved = results.get("_devices", {})
    for role in ("stick", "throttle"):
        info = dict(saved.get(role, {}))
        # The old loop also ran when only dcs_id was missing, which it could
        # not supply -- that comes from dcs.log.
        if not info.get("axmap") and info.get("name"):
            got = capture.refresh_axmap(info["name"])
            if got:
                info["axmap"] = got
        if info.get("dcs_id") and info.get("axmap"):
            out[role] = info
    missing = {"stick", "throttle"} - set(out)
    if missing:
        raise RuntimeError(
            "Nothing resolves the devices for: %s. Run the TUI wizard "
            "once with the devices plugged in. DCS must also have seen "
            "them once, so that their ids are in dcs.log."
            % ", ".join(sorted(missing)))
    return out


def device_axis_keys(info):
    return {ABS_TO_DCS[c] for c in info["axmap"] if c in ABS_TO_DCS}


def build_diffs(bindings, snapshot, devs):
    """Modeled bindings overlaid on the last --sync snapshot (if any).

    `bindings` is {command hash: {name, role, type, index, invert}} -- what
    `plan.seed` makes out of a layout. It used to read the wizard's own
    results file and pick the aircraft out of it, which made the writer the
    one thing in the family that could not be handed a plan: the review
    screen narrowed a layout and this went to the file anyway.

    Returns {role: {'axisDiffs': ..., 'keyDiffs': ...}}.
    """
    if not bindings and not snapshot:
        raise RuntimeError("Nothing is bound yet.")
    diffs = {role: {"axisDiffs": {}, "keyDiffs": {}} for role in devs}

    def other(role):
        return "throttle" if role == "stick" else "stick"

    for h, r in bindings.items():
        role, name = r["role"], r["name"]
        table = "axisDiffs" if r["type"] == "axis" else "keyDiffs"
        entry = diffs[role][table].setdefault(h, {"name": name})
        if r["type"] == "axis":
            axmap = devs[role]["axmap"]
            if r["index"] >= len(axmap) or axmap[r["index"]] not in ABS_TO_DCS:
                raise RuntimeError(
                    "%s: nothing maps %s axis %d. The axis map is %s."
                    % (name, role, r["index"], axmap))
            key = ABS_TO_DCS[axmap[r["index"]]]
            filt = make_filter(name, r.get("invert"))
            default = DEFAULT_AXIS_KEYS.get(name)
            if key == default:
                if filt != vanilla_filter():
                    entry["changed"] = [{"key": key, "filter": filt}]
            else:
                entry["added"] = [{"key": key, "filter": filt}]
                if default and default in device_axis_keys(devs[role]):
                    entry.setdefault("removed", []).append({"key": default})
            if default and default in device_axis_keys(devs[other(role)]):
                oentry = diffs[other(role)]["axisDiffs"].setdefault(
                    h, {"name": name})
                oentry.setdefault("removed", []).append({"key": default})
        else:
            key = "JOY_BTN%d" % (r["index"] + 1)
            default = DEFAULT_BUTTON_KEYS.get(name)
            if key != default:
                entry["added"] = [{"key": key}]
                if default:
                    entry.setdefault("removed", []).append({"key": default})
            if default:
                oentry = diffs[other(role)]["keyDiffs"].setdefault(
                    h, {"name": name})
                oentry.setdefault("removed", []).append({"key": default})

    # drop entries that ended up empty (e.g. a pure-default axis)
    for role in diffs:
        for table in ("axisDiffs", "keyDiffs"):
            diffs[role][table] = {
                h: e for h, e in diffs[role][table].items()
                if set(e) - {"name"}}

    # overlay onto the snapshot of the installed state (--sync), so
    # bindings made in the DCS UI survive regeneration
    snapshot = snapshot or {}
    for role in diffs:
        if role not in snapshot:
            continue
        merged = copy.deepcopy(snapshot[role])
        for table in ("axisDiffs", "keyDiffs"):
            merged.setdefault(table, {})
            merged[table].update(diffs[role][table])
        diffs[role] = merged
    return diffs


def render_diff(diff):
    """diff dict -> file content, byte-compatible with DCS's serializer
    (sorted keys, tab indent, no trailing newline)."""
    body = lua({"axisDiffs": diff.get("axisDiffs", {}),
                "keyDiffs": diff.get("keyDiffs", {})}, 1)
    return "local diff = %s\nreturn diff" % body


def joystick_dir(cfg, aircraft):
    return os.path.join(cfg["saved_games"], "Config", "Input",
                        input_id(cfg, aircraft), "joystick")


def render_all(results, cfg, aircraft, bindings=None):
    """({path: the diff.lua text}, summary lines). Writes nothing.

    Split out of `generate()` so `plan.py` can hand the text to
    `core.adapter`, which owns the backing up and the writing for every game
    in the family. `generate()` remains the wizard's own path.

    `bindings` is the plan to write, as `plan.seed` makes it. Without
    one the results file is read, which is what `generate()` wants: the
    wizard has no reviewer to ask.
    """
    if dcs_running():
        raise RuntimeError("DCS is running. Quit the game first: it "
                           "overwrites Config/Input when it exits.")
    devs = resolve_devices(results)
    ac = results.get("aircraft", {}).get(aircraft, {})
    if bindings is None:
        bindings = {h: r for h, r in ac.items()
                    if r and not h.startswith("_")}
    diffs = build_diffs(bindings, ac.get("_snapshot"), devs)
    out_dir = joystick_dir(cfg, aircraft)
    files, lines = {}, []
    for role, info in devs.items():
        path = os.path.join(out_dir, info["dcs_id"] + ".diff.lua")
        files[path] = render_diff(diffs[role])
        n = (len(diffs[role]["axisDiffs"]) + len(diffs[role]["keyDiffs"]))
        lines.append("%s: %d entries -> %s" % (role, n, path))
    stale = os.path.join(cfg["saved_games"], "Config", "Input", aircraft,
                         "joystick")
    if os.path.normpath(stale) != os.path.normpath(out_dir) and \
            os.path.isdir(stale):
        lines.append("note: DCS does not read %s — leftovers from an "
                     "older run there can be deleted" % stale)
    return files, lines


def generate(results, cfg, aircraft, backup_dir=None):
    """Build and install the per-device diff.lua files. Returns summary."""
    files, lines = render_all(results, cfg, aircraft)
    os.makedirs(os.path.dirname(next(iter(files))), exist_ok=True)
    # One folder per run rather than a single `.bak` per file: the old one was
    # overwritten every time, so a run you wanted undone had already eaten the
    # copy of what came before it.
    dest, kept = backup.save("dcs", *files, into=backup_dir)
    for path, text in files.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    if kept:
        lines.append("backed up %d file(s) -> %s" % (len(kept), dest))
    lines.append("Start DCS and check Options -> Controls -> %s" % aircraft)
    return lines


def sync(results, cfg, aircraft):
    """Import the installed diff.lua files back into the results file.

    Every entry the wizard can model becomes a normal binding (so the TUI
    shows it); the full parsed files are kept as a snapshot that
    build_diffs() overlays, so nothing tuned in the DCS UI is ever lost.
    Safe to run while DCS is running (read-only on game files).
    """
    devs = resolve_devices(results)
    out_dir = joystick_dir(cfg, aircraft)
    new = {}
    snapshot = {}
    lines = []
    for role, info in devs.items():
        path = os.path.join(out_dir, info["dcs_id"] + ".diff.lua")
        if not os.path.exists(path):
            lines.append("%s: no installed diff.lua — skipped" % role)
            continue
        parsed = parse_diff_lua(open(path, encoding="utf-8").read())
        snapshot[role] = parsed
        rev = {ABS_TO_DCS[c]: i for i, c in enumerate(info["axmap"])
               if c in ABS_TO_DCS}
        n = 0
        for table, kind in (("axisDiffs", "axis"), ("keyDiffs", "button")):
            for h, e in parsed.get(table, {}).items():
                items = e.get("added") or e.get("changed") or {}
                first = items.get(1) if isinstance(items, dict) else None
                if not first:
                    continue
                key = first.get("key")
                if not key:
                    continue
                name = e.get("name", h)
                if kind == "axis":
                    if key not in rev:
                        continue
                    new[h] = {"name": name, "role": role, "type": "axis",
                              "index": rev[key],
                              "invert": bool((first.get("filter") or {})
                                             .get("invert"))}
                else:
                    m = re.match(r"JOY_BTN(\d+)$", key)
                    if not m:
                        continue          # keyboard-style combos stay
                    new[h] = {"name": name, "role": role, "type": "button",
                              "index": int(m.group(1)) - 1}
                n += 1
        lines.append("%s: %d bindings imported" % (role, n))
    # a device with no installed file says nothing about its bindings —
    # keep whatever the wizard already had for it rather than dropping it
    previous = results.setdefault("aircraft", {}).get(aircraft, {})
    kept = 0
    for h, r in previous.items():
        if r and not h.startswith("_") and r.get("role") not in snapshot:
            new.setdefault(h, r)
            kept += 1
    if kept:
        lines.append("kept %d binding(s) for devices with no installed "
                     "file" % kept)
    results["aircraft"][aircraft] = new
    new["_snapshot"] = snapshot

    # round-trip check: regenerating now must reproduce the files exactly
    diffs = build_diffs({h: r for h, r in new.items()
                         if r and not h.startswith("_")},
                        new.get("_snapshot"), devs)
    for role, info in devs.items():
        if role not in snapshot:
            continue
        path = os.path.join(out_dir, info["dcs_id"] + ".diff.lua")
        same = render_diff(diffs[role]) == open(path, encoding="utf-8").read()
        lines.append("%s: round-trip %s" % (role,
                                            "OK" if same else "MISMATCH!"))
    return lines


# -------------------------------------------------------------------- TUI --

# ----------------------------------------------------------- capture logic --

def detect_devices_screen(tui, cfg, results):
    tui.page("Device detection")
    devices = capture.detect_roles(tui, ("stick", "throttle"))
    if devices is None:
        tui.log("This needs two joystick devices. Check the "
                "connections.")
        tui.wait_any_key()
        return None
    stick = next(d for d in devices if d.role == "stick")
    throttle = next(d for d in devices if d.role == "throttle")

    # What stays here: joining a live device to the name DCS writes into
    # dcs.log, which is the stem of the diff.lua file it will be bound in.
    ids = dcs_device_ids(cfg["saved_games"])
    devinfo = {}
    for d in (stick, throttle):
        dcs_id = None
        for short, full in ids.items():
            if short in d.name:
                dcs_id = full
                break
        devinfo[d.role] = {"name": d.name, "dcs_id": dcs_id,
                           "axmap": axis_map(d.fd, d.n_axes)}
        if not dcs_id:
            tui.log("WARNING: there is no DCS id for '%s'. Start DCS "
                    "once, so that the id lands in dcs.log. Then run this "
                    "again." % d.name)
    results["_devices"] = devinfo
    if any(not v["dcs_id"] for v in devinfo.values()):
        tui.wait_any_key()
    return [stick, throttle]


# ------------------------------------------------------------------- flows --

def resolve_config(args, cfg):
    """Validate --game-dir / remembered config; exits with a clear message."""
    # core.game.install_dir searches EVERY Steam library, which the old
    # hardcoded ~/.local/share/Steam path did not -- and this DCS lives on a
    # second disk, so it was never found and --game-dir was mandatory once.
    game = (args.game_dir or cfg.get("game_dir")
            or install_dir("DCSWorld"))
    if not game:
        sys.exit("Pass --game-dir /path/to/steamapps/common/DCSWorld. "
                 "The results file remembers it afterwards.")
    game = os.path.abspath(os.path.expanduser(game))
    if not os.path.isdir(os.path.join(game, "Mods", "aircraft")):
        sys.exit("%s\nis not a DCS World install: it has no "
                 "Mods/aircraft folder." % game)
    # <steamapps>/common/DCSWorld -> <steamapps>/compatdata/223750/...
    steamapps = os.path.dirname(os.path.dirname(game))
    derived = os.path.join(steamapps, "compatdata", DCS_APPID, "pfx",
                           "drive_c", "users", "steamuser", "Saved Games",
                           "DCS")
    saved = args.saved_games or (cfg.get("saved_games")
                                 if not args.game_dir else None) or derived
    if not os.path.isdir(saved):
        sys.exit("There is no Saved Games folder at:\n%s\nRun the game "
                 "once, and it creates one. Or pass --saved-games."
                 % saved)
    cfg.update({"game_dir": game, "saved_games": saved})
    return cfg


def describe(results, r):
    if not r:
        return "(unset)"
    mark = "? " if r.get("proposed") else ""
    if r["type"] == "button":
        return "%s%s BTN%d" % (mark, r["role"], r["index"] + 1)
    axmap = results.get("_devices", {}).get(r["role"], {}).get("axmap")
    key = ""
    if axmap and r["index"] < len(axmap) and axmap[r["index"]] in ABS_TO_DCS:
        key = " " + ABS_TO_DCS[axmap[r["index"]]]
    return "%s%s axis %d%s%s" % (mark, r["role"], r["index"], key,
                                 " (inverted)" if r.get("invert") else "")


def section_stats(bindings, items):
    bound = sum(1 for h, _, _ in items if bindings.get(h))
    return bound, len(items)


def aircraft_stats(bindings, sections):
    bound = total = 0
    for _, items in sections:
        b, n = section_stats(bindings, items)
        bound, total = bound + b, total + n
    return bound, total


def progress_label(title, bound, total):
    return "%s  [%d/%d]" % (title, bound, total)


def tui_main(scr, args, results, cfg):
    tui = ctui.setup(scr)

    results["_config"] = cfg
    save(results, args.results)

    active = detect_devices_screen(tui, cfg, results)
    if active is None:
        return
    save(results, args.results)

    aircraft_all = discover_aircraft(cfg)
    if not aircraft_all:
        tui.page("Aircraft")
        tui.log("There are no aircraft modules under %s."
                % cfg["game_dir"])
        tui.wait_any_key()
        return

    aircraft = cfg.get("aircraft")
    while True:
        keys = sorted(aircraft_all, key=lambda k:
                      aircraft_all[k]["display"].lower())
        if aircraft not in aircraft_all:
            idx = tui.menu("Pick an aircraft",
                           [aircraft_all[k]["display"] for k in keys],
                           footer="Arrows move. RETURN selects. "
                                  "ESC quits.")
            if idx is None:
                return
            aircraft = keys[idx]
            cfg["aircraft"] = aircraft
            results["_config"] = cfg
            save(results, args.results)

        commands = harvest_commands(cfg, aircraft,
                                    aircraft_all[aircraft]["factory_dir"])
        sections = build_sections(commands)
        bindings = results.setdefault("aircraft", {}).setdefault(aircraft, {})
        bindings_clean = {h: r for h, r in bindings.items()
                          if r and not h.startswith("_")}
        display = aircraft_all[aircraft]["display"]

        used = {}
        for h, r in bindings_clean.items():
            if r["type"] == "button":
                used.setdefault((r["role"], "button", r["index"]), r["name"])

        guide = build_guide(commands)
        ess_sections = essentials(commands, guide)
        choice = tui.menu("DCS %s" % display, [
            progress_label("Bound so far",
                           *aircraft_stats(bindings_clean, ess_sections)),
            "Generate diff.lua files",
            "Change aircraft",
            "Quit",
        ])
        if choice in (None, 3):
            return
        if choice == 2:
            aircraft = None
            continue
        if choice == 0:
            # The table that used to be here is `./bind-wizard.py dcs tui` now
            # -- the same screen the other five open, with the same keys on
            # it. This wizard is what is left: find the devices, pick the
            # module, write the diff.lua.
            tui.page("Binding — %s" % display)
            tui.log("  The review screen does this now:")
            tui.log("")
            tui.log("      ./bind-wizard.py dcs tui")
            tui.log("")
            tui.log("  It reads and writes this same results file. It")
            tui.log("  shows what you confirmed here in green.")
            tui.wait_any_key()
            continue
        tui.page("Generate — %s" % display)
        try:
            for line in generate(results, cfg, aircraft, args.backup_dir):
                tui.log(line)
        except (RuntimeError, OSError) as e:
            tui.log("ERROR: %s" % e)
        tui.wait_any_key()


# -------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-r", "--results", default=DEFAULT_RESULTS,
                    help="The results JSON: the wizard state, and the "
                         "input the generator reads. The default is the "
                         "file next to this script.")
    ap.add_argument("--reset", action="store_true",
                    help="Delete the results file and start again.")
    ap.add_argument("-g", "--generate", action="store_true",
                    help="Write the diff.lua files, then exit.")
    ap.add_argument("-s", "--sync", action="store_true",
                    help="Read the installed diff.lua files into the "
                         "results file, then exit. This takes in what you "
                         "changed in the DCS UI.")
    ap.add_argument("-a", "--aircraft", default=None,
                    help="Which aircraft --generate writes, for example "
                         "su-25T. The default is the last one the TUI "
                         "used.")
    ap.add_argument("--game-dir", default=None,
                    help="The DCS World folder, under "
                         "steamapps/common/DCSWorld. This finds it, or "
                         "remembers it afterwards.")
    ap.add_argument("--saved-games", default=None,
                    help="The Saved Games/DCS folder inside the Proton "
                         "prefix. By default this is worked out from "
                         "--game-dir.")
    backup.add_argument(ap, "dcs")
    args = ap.parse_args()

    if args.reset and os.path.exists(args.results):
        os.remove(args.results)

    results = {}
    if os.path.exists(args.results):
        with open(args.results) as f:
            results = json.load(f)
    cfg = resolve_config(args, dict(results.get("_config", {})))

    if args.generate or args.sync:
        aircraft = args.aircraft or cfg.get("aircraft")
        if not aircraft:
            sys.exit("Pass --aircraft, for example -a su-25T.")
        try:
            if args.sync:
                lines = sync(results, cfg, aircraft)
                results["_config"] = cfg
                save(results, args.results)
            else:
                lines = generate(results, cfg, aircraft,
                                 args.backup_dir)
            for line in lines:
                print(line)
        except (RuntimeError, OSError, ValueError) as e:
            sys.exit("ERROR: %s" % e)
        return

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.exit("Run this in a terminal: the wizard is a full-screen "
                 "program. Or pass --generate, which needs no "
                 "terminal.")
    curses.wrapper(tui_main, args, results, cfg)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""harvest.py - read one DCS module's command vocabulary

DESCRIPTION
    Read what a module can be told to do, out of the game's own files. With
    no arguments, print a summary.

FILES
    Mods/aircraft/<module>/Input/<unit>/joystick/default.lua   read
    Mods/aircraft/<module>/Input/<unit>/joystick/*.diff.lua    read
    dcs-<aircraft>-actions.json    written by --json

OPTIONS
    --game-dir PATH     the DCS install
    -a, --aircraft KEY  which module (default: FA-18C)

NOTES
    A module's default.lua goes through a `lua` or `luajit` binary with the
    game's globals stubbed out. Without one the command list falls back to
    the factory profiles: fewer commands, and whatever names their authors
    used.
"""

# One file per module. A module's commands are its own: the Hornet's 849
# are not the Su-25T's, and a cockpit command's id is per module, so the
# same name in another module means something else.
#
# Cached rather than read live, so `plan.py` opens on a clone with no game
# installed. Every other game offers that.
#
# A factory profile's LAYOUT is not read. Which device Eagle Dynamics put
# a command on, and how many of their profiles bound it, is a layout
# somebody wrote for a Warthog. It is not a fact about the aircraft. The
# review screen is where what a command IS gets said.

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions                        # noqa: E402
from core import adapter                                    # noqa: E402
from core import game as cgame                              # noqa: E402

APPID = '223750'
DEFAULT_AIRCRAFT = 'FA-18C'

#: The cache, one per module. Spelled the same here and in `plan.py`'s
#: `CACHE`, so the contract test that the two agree has two strings to
#: compare.
CACHE_TEMPLATE = 'dcs-<aircraft>-actions.json'


def cache_name(aircraft):
    return CACHE_TEMPLATE.replace('<aircraft>', aircraft)


#: What DCS calls each axis, in `adapter.HID_AXES` order. Slider and Dial
#: land on its two sliders. That is the report descriptor's order, and X4,
#: Elite and Falcon BMS need the same rule.
#:
#: The planner declares this. Nothing here turns a HID name into a key,
#: because the core does that for every game in one place.
AXES = ('JOY_X', 'JOY_Y', 'JOY_Z', 'JOY_RX', 'JOY_RY', 'JOY_RZ',
        'JOY_SLIDER1', 'JOY_SLIDER2')

#: How DCS spells a button, as `Adapter.BUTTON` takes it.
BUTTON, BUTTON_FROM = 'JOY_BTN{n}', 1


_NAME_RE = re.compile(r"name\s*=\s*_\('((?:[^'\\]|\\.)*)'\)")
_CATEGORY_RE = re.compile(r"category\s*=\s*(?:\{\s*)?_\('((?:[^'\\]|\\.)*)'\)")
_HASH_RE = re.compile(r'\["(a\d+[^"]*|d(?:\d+|nil)p[^"]*)"\]\s*=\s*\{')
_DIFF_NAME_RE = re.compile(r'\["name"\]\s*=\s*"([^"]+)"')
_INPUT_PROFILE_RE = re.compile(
    r'\["([^"]+)"\]\s*=\s*[^,}]*?[\'"]([^\'"]*?/Input/[^\'"]*?)[\'"]')


def _unescape(s):
    return s.replace("\\'", "'").replace('\\"', '"')


def install(game_dir=None):
    """{'game_dir', 'saved_games'} -- where DCS is and where it saves.

    The saved-games folder sits inside the Proton prefix and is derived
    from the install, so one path settles both.
    """
    where = game_dir or os.environ.get('DCS_GAME_DIR') \
        or cgame.install_dir('DCSWorld')
    if not where:
        raise SystemExit('DCSWorld is not installed in any Steam library. '
                         'Pass --game-dir.')
    saved = cgame.in_prefix(APPID, 'users', 'steamuser', 'Saved Games',
                            'DCS')
    if not saved:
        raise SystemExit(f'The prefix for appid {APPID} has no Saved Games '
                         'folder. Run DCS once.')
    return {'game_dir': where, 'saved_games': saved}


def input_profiles(module_dir):
    """Input folder name -> the unit name DCS saves that aircraft under.

    Both names sit side by side in the module's entry.lua, and they
    differ. The Hornet ships this:

        ["FA-18C_hornet"] = current_mod_path .. '/Input/FA-18C/',

    So its factory profiles are under `Input/FA-18C` and its user
    profiles are under `Config/Input/FA-18C_hornet`.

    The path ends with a separator, so the trailing one comes off before
    the basename. `os.path.basename('/Input/FA-18C/')` is the empty
    string, and the empty key makes `discover_aircraft` fall back to the
    folder name. The writer then writes to `Config/Input/FA-18C`, which
    DCS does not read, and the save folder turns up in the aircraft list
    as a module of its own.
    """
    entry = os.path.join(module_dir, 'entry.lua')
    if not os.path.exists(entry):
        return {}
    with open(entry, encoding='utf-8', errors='replace') as f:
        text = f.read()
    block = text.split('InputProfiles', 1)
    if len(block) < 2:
        return {}
    block = block[1].split('}', 1)[0]
    return {os.path.basename(path.rstrip('/\\')): unit
            for unit, path in _INPUT_PROFILE_RE.findall(block)}


def discover_aircraft(cfg):
    """aircraft key (Input folder name) ->
    {'display', 'factory_dir', 'input_id'}."""
    out = {}
    pattern = os.path.join(cfg['game_dir'], 'Mods', 'aircraft', '*',
                           'Input', '*', 'joystick', 'default.lua')
    for default_lua in sorted(glob.glob(pattern)):
        joy_dir = os.path.dirname(default_lua)
        key = os.path.basename(os.path.dirname(joy_dir))
        display = key
        name_lua = os.path.join(os.path.dirname(joy_dir), 'name.lua')
        if os.path.exists(name_lua):
            with open(name_lua, encoding='utf-8') as f:
                m = _NAME_RE.search('name = '
                                    + f.read().replace('return', '', 1))
            if m:
                display = _unescape(m.group(1))
        module_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            joy_dir)))
        out[key] = {'display': display, 'factory_dir': joy_dir,
                    'input_id': input_profiles(module_dir).get(key, key)}
    # An aircraft somebody has flown whose module folder did not
    # match.
    known = {a['input_id'] for a in out.values()} | set(out)
    for d in sorted(glob.glob(os.path.join(cfg['saved_games'], 'Config',
                                           'Input', '*', 'joystick'))):
        key = os.path.basename(os.path.dirname(d))
        if key not in known:
            out[key] = {'display': key, 'factory_dir': None,
                        'input_id': key}
    return out


def input_id(cfg, aircraft):
    """The folder DCS itself reads this aircraft's user profiles from."""
    return (discover_aircraft(cfg).get(aircraft) or {}).get(
        'input_id', aircraft)


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
    for name in ('lua', 'luajit', 'lua5.4', 'lua5.3', 'lua5.2', 'lua5.1'):
        found = shutil.which(name)
        if found:
            return found
    return None


def lua_commands(cfg, factory_dir):
    """[(hash or None, name, category, kind)] from the module's
    default.lua.

    Returns None where there is no Lua interpreter on the machine, or
    where the file refuses to run. The caller then falls back to the
    factory profiles alone.
    """
    binary = lua_binary()
    if not binary or not factory_dir:
        return None
    if not os.path.exists(os.path.join(factory_dir, 'default.lua')):
        return None
    fd, script = tempfile.mkstemp(suffix='.lua')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(LUA_HARVEST)
        out = subprocess.run([binary, script, cfg['game_dir'],
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
    for line in out.stdout.decode('utf-8', 'replace').splitlines():
        parts = line.split('\t')
        if len(parts) != 4 or parts[0] not in ('k', 'a', 'K', 'A'):
            continue
        kind = 'axis' if parts[0] in ('a', 'A') else 'button'
        rows.append((parts[1] or None, parts[2], parts[3], kind))
    return rows or None


def _is_latin(name):
    """DCS ships Russian factory profiles as well. A Latin name for the
    same command wins over a Cyrillic one."""
    return not re.search('[Ѐ-ӿ]', name)


def _norm(name):
    return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


def scan_profiles(dirs):
    """hash -> name, read off the factory joystick profiles.

    This is the one thing the shipped profiles are read for, and what
    comes back is an IDENTIFIER. It is not advice.

    The sim's own commands carry ids that live in the executable. Pitch,
    Thrust, the gear and the views are among them. A profile that binds
    one is the only offline place its hash can be found, and a hash is
    what `diff.lua` is written against. Twelve of the Hornet's 59
    bindings have no other source.
    """
    names = {}
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, '*.diff.lua'))):
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read()
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

    Their ids live in the executable, so the only place to find the hash
    for 'Gear Up' is a profile that binds it. Those ids are global, so any
    module's factory profiles will do.

    A cockpit command is left out on purpose. Its id is per module, so an
    identical name in another module means something else.
    """
    key = cfg['game_dir']
    if key not in _ENGINE_INDEX:
        dirs = [a['factory_dir'] for a in discover_aircraft(cfg).values()
                if a['factory_dir']]
        names = scan_profiles(dirs)
        _ENGINE_INDEX[key] = {_norm(n): h for h, n in names.items()
                              if 'cdnil' in h and _is_latin(n)}
    return _ENGINE_INDEX[key]


def commands(cfg, aircraft, factory_dir):
    """hash -> {'name', 'kind', 'category'} for one aircraft.

    What the module says about itself, and nothing this repository thinks
    about it. Two sources, and both are needed.

    The module's `default.lua` runs through a Lua interpreter with the
    game's globals stubbed out. It lists every bindable command with the
    name and category the game shows today, and for a cockpit command it
    carries the id the diff.lua hash is built from.

    The factory joystick profiles shipped with the module supply the
    hashes of the commands wired to engine constants. They supply nothing
    else. `scan_profiles` says why.
    """
    user_dirs = glob.glob(os.path.join(cfg['saved_games'], 'Config', 'Input',
                                       input_id(cfg, aircraft), '*'))
    names = scan_profiles([factory_dir] if factory_dir else [])
    for h, name in scan_profiles(user_dirs).items():
        names.setdefault(h, name)
    out = {h: {'name': name} for h, name in names.items()}

    categories = {}
    cat_files = []
    if factory_dir:
        cat_files.append(os.path.join(factory_dir, 'default.lua'))
    cat_files += sorted(glob.glob(os.path.join(
        cfg['game_dir'], 'Config', 'Input', 'Aircrafts', '*.lua')))
    for path in cat_files:
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.lstrip().startswith('--'):
                    continue
                nm, cat = _NAME_RE.search(line), _CATEGORY_RE.search(line)
                if nm:
                    categories.setdefault(
                        _unescape(nm.group(1)),
                        _unescape(cat.group(1)) if cat else 'Other')

    def tokens(name):
        return {w.rstrip('s') for w in re.findall(r'[a-z0-9]+', name.lower())}

    token_map = [(tokens(n), c) for n, c in categories.items()]

    def category_for(name):
        """Which category this command is in.

        An exact match first. A factory profile often carries an outdated
        label, such as 'Trim Hat - NOSE UP' against today's 'Trim: Nose
        Up'. So this falls back to the best token-subset match against
        the current game names.
        """
        if name in categories:
            return categories[name]
        mine = tokens(name)
        best, best_n = None, 1
        for toks, cat in token_map:
            if len(toks) > best_n and toks <= mine:
                best, best_n = cat, len(toks)
        if best:
            return best
        # The last resort: the strongest token overlap, and only where
        # every equally good candidate agrees on the category.
        best_n, cats = 1, set()
        for toks, cat in token_map:
            n = len(toks & mine)
            if n > best_n:
                best_n, cats = n, {cat}
            elif n == best_n:
                cats.add(cat)
        return cats.pop() if len(cats) == 1 else 'Other'

    for h, info in out.items():
        info['kind'] = 'axis' if h.startswith('a') else 'button'
        info['category'] = ('Axes' if info['kind'] == 'axis'
                            else category_for(info['name']))

    # `default.lua` on top. It gives the current names and categories for
    # the commands already found, and every command no factory profile
    # bound.
    by_name = {}
    for h, name in names.items():
        by_name.setdefault(_norm(name), h)
    for hash_, name, category, kind in lua_commands(cfg, factory_dir) or []:
        if hash_ is None:                   # An engine command. Hash the
                                            # name.
            hash_ = (by_name.get(_norm(name))
                     or engine_hash_index(cfg).get(_norm(name)))
            if hash_ is None or hash_.startswith('a') != (kind == 'axis'):
                continue
        info = out.setdefault(hash_, {})
        info['name'] = name
        info['kind'] = kind
        info['category'] = ('Axes' if kind == 'axis'
                            else category or info.get('category', 'Other'))
    return out


def catalogue(cmds):
    """[Action] -- one module's commands in the shape every game shares.

    Keyed by DCS's command hash. That is what `diff.lua` is written
    against, and what every record here uses.
    """
    return [cactions.Action(h, c.get('name') or h,
                            kind=('axis' if c.get('kind') == 'axis'
                                  else 'button'),
                            category=c.get('category'))
            for h, c in sorted(cmds.items())]


@typing.final
class DcsHarvest(adapter.Harvest):
    """One DCS module's commands, read out of the game's own files."""

    game = 'dcs'
    files = {CACHE_TEMPLATE: ('actions',)}

    @typing.override
    def arguments(self, parser):
        parser.add_argument('--game-dir', help='Where DCS is installed.')
        parser.add_argument('-a', '--aircraft', default=DEFAULT_AIRCRAFT,
                            help='Which module to read.')

    @typing.override
    def read(self, args):
        self.cfg = install(args.game_dir)
        self.aircraft = args.aircraft
        found = discover_aircraft(self.cfg)
        if self.aircraft not in found:
            raise SystemExit(
                f'{self.aircraft} is not installed. These are: '
                + ', '.join(sorted(found)) + '.')
        self.found = found
        self.cmds = commands(self.cfg, self.aircraft,
                             found[self.aircraft]['factory_dir'])
        self.lua = lua_binary()
        return {cache_name(self.aircraft):
                {'actions': cactions.dump(catalogue(self.cmds))}}

    @typing.override
    def summary(self, data):
        out = [self.cfg['game_dir'], '',
               f'{self.found[self.aircraft]["display"]}  '
               f'{len(self.cmds)} commands',
               '']
        for key, info in sorted(self.found.items()):
            mark = '->' if key == self.aircraft else '  '
            out.append(f'  {mark} {key:<16} {info["display"]}')
        out.append('')
        if self.lua:
            out.append(f'lua  {self.lua}')
        else:
            out.append('There is no lua binary. The command list is the '
                       'factory profiles only: fewer commands, and '
                       'whatever names their authors used.')
        return out


if __name__ == '__main__':
    sys.exit(DcsHarvest().main())

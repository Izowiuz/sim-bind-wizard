#!/usr/bin/env python3
"""harvest.py - read BMS's callback vocabulary

DESCRIPTION
    Read BMS's shipped key file and report every callback. Also reports the
    DX offset each device gets, which decides its button numbering.

FILES
    BMS - Full.key      read: the callback vocabulary
    DeviceSorting.txt   read: device order, which fixes the DX offsets

ENVIRONMENT
    BMS_DIR             the BMS install
"""

# Read everything Falcon BMS already knows about bindings, and write it out as JSON.
#
# Nothing here touches the game.  Two things come off disk:
#
#   * the vocabulary  - every bindable callback in `BMS - Full.key`, with the
#     human description and the cockpit section it sits in.  BMS is the only sim
#     of the four that ships its action list already grouped by panel.
#   * the devices     - `DeviceSorting.txt` fixes the DX numbering: device N owns
#     DX numbers N*32 .. N*32+31, so the sorting order *is* the offset table.
#
# The 22 vendor HOTAS profiles in `Hotas/Archive` used to be counted too --
# how many of them bound each callback, and whether they put it on the stick,
# the throttle or the shifted layer. They are deprecated, and what they rank
# is somebody else's Warthog. Gone from the whole family.
#
# Outputs falconbms-actions.json next to this file.

import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_BMS = Path.home() / (
    ".local/share/Steam/steamapps/compatdata/429530/pfx/drive_c/Falcon BMS 4.38"
)

import typing                                                # noqa: E402

HERE = Path(__file__).resolve().parent
CORE = os.environ.get('SIM_BIND_WIZARD') or str(HERE.parent.parent)
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import actions as cactions
from core import adapter                                    # noqa: E402

# A full key line: callback, sound, <unused>, key, mod, combo key, combo mod, flag, "description"
KEY_LINE = re.compile(
    r'^(\w+)\s+(-?\w+)\s+(-?\w+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(-?\d+)\s+"(.*)"\s*$'
)
SECTION = re.compile(r"^(\d+)\.\s+(.*)$")
SUBSECTION = re.compile(r"^=+\s*(\d+\.\d+)\s+(.*?)\s*=+$")

BUTTONS_PER_DEVICE = 32


def bms_dir():
    env = os.environ.get("BMS_DIR")
    if env:
        return Path(env)
    return DEFAULT_BMS


def read_key(path):
    """BMS key files are latin-1 with the odd stray byte; never fail on one."""
    return path.read_text(encoding="latin-1").splitlines()


def harvest_actions(path):
    """Every bindable callback, tagged with the cockpit panel it lives under."""
    actions = {}
    section = subsection = ""
    for lineno, raw in enumerate(read_key(path), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = KEY_LINE.match(line)
        if not m:
            continue
        cb, sound, _, key, mod, combo, combo_mod, flag, desc = m.groups()

        if cb == "SimDoNothing":
            # Headers carry the taxonomy and nothing else.
            sub = SUBSECTION.match(desc)
            if sub:
                subsection = f"{sub.group(1)} {sub.group(2)}"
                continue
            sec = SECTION.match(desc)
            if sec:
                section, subsection = f"{sec.group(1)}. {sec.group(2)}", ""
            continue

        if flag != "1":  # -2 dev-only, -0 hardcoded or a REM: comment
            continue

        actions[cb] = {
            "callback": cb,
            "desc": desc,
            "section": section,
            "subsection": subsection,
            "sound": None if sound == "-1" else int(sound),
            "key": None if key.upper() == "0XFFFFFFFF" else key,
            "mod": int(mod) if mod.isdigit() else mod,
            "combo": None if combo in ("0", "0x0") else combo,
            "line": lineno,
        }
    return actions


def harvest_devices(path):
    """DeviceSorting.txt: order decides the DX offset, GUID carries VID:PID."""
    out = []
    if not path.exists():
        return out
    guid_re = re.compile(r"\{([0-9A-Fa-f]{8})-[0-9A-Fa-f-]+\}\s+\"(.*)\"")
    for i, raw in enumerate(read_key(path)):
        m = guid_re.search(raw.strip())
        if not m:
            continue
        data1, name = m.groups()
        pid, vid = int(data1[:4], 16), int(data1[4:], 16)
        out.append(
            {
                "index": i,
                "name": name,
                "usb": f"{vid:04x}:{pid:04x}",
                "dx_offset": i * BUTTONS_PER_DEVICE,
                "dx_range": [i * BUTTONS_PER_DEVICE, i * BUTTONS_PER_DEVICE + 31],
            }
        )
    return out


def catalogue(actions=None):
    """[Action] -- the whole vocabulary in the shape every game shares.

    The one harvest that already kept a full record per callback, so most
    of this is a rename. `subsection` is the finer of the two panels BMS
    names and the one worth grouping by; it is also the only `category`
    any game in the family ships besides DCS's module.

    What is left behind -- the stock keyboard key, its modifier, the sound
    id, the line number -- nothing reads. The cache is derived from the
    install, so a later use adds a section then rather than carrying six
    unread fields across 1195 rows until it does.
    """
    actions = actions or {}
    return [cactions.Action(call, rec.get('desc') or call, kind='button',
                            category=(rec.get('subsection')
                                      or rec.get('section')))
            for call, rec in sorted(actions.items())]


def action_rows(actions=None):
    """The section the cache holds."""
    return cactions.dump(catalogue(actions))


@typing.final
class FalconBmsHarvest(adapter.Harvest):
    """BMS's callback vocabulary."""

    game = "falconbms"
    files = {"falconbms-actions.json": ("devices", "actions")}

    @typing.override
    def read(self, args):
        self.bms = bms_dir()
        keyfile = self.bms / "User" / "Config" / "BMS - Full.key"
        sorting = self.bms / "User" / "Config" / "DeviceSorting.txt"

        if not keyfile.exists():
            raise SystemExit(f"There is no key file at {keyfile}. Set "
                             "BMS_DIR to the BMS install.")

        actions = harvest_actions(keyfile)
        # Kept for `summary()`, which wants the full record the key file
        # gave; what reaches the cache is the shared one.
        self.actions = actions
        return {"falconbms-actions.json": {"devices": harvest_devices(sorting),
                                     "actions": action_rows(actions)}}

    @typing.override
    def summary(self, data):
        actions = self.actions
        out = [f"BMS      {self.bms}",
               f"actions  {len(actions)} bindable callbacks",
               f"sections {len(set(a['section'] for a in actions.values()))}"
               f" / {len(set(a['subsection'] for a in actions.values()))}"
               " subsections",
               "devices"]
        for d in data["falconbms-actions.json"]["devices"]:
            out.append(f"  DX {d['dx_range'][0]:>3}-{d['dx_range'][1]:<3} "
                       f"{d['usb']}  {d['name']}")
        return out


if __name__ == "__main__":
    sys.exit(FalconBmsHarvest().main())

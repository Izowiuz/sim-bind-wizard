#!/usr/bin/env python3
"""Read everything Falcon BMS already knows about bindings, and write it out as JSON.

Nothing here touches the game.  Three things come off disk:

  * the vocabulary  - every bindable callback in `BMS - Full.key`, with the
    human description and the cockpit section it sits in.  BMS is the only sim
    of the four that ships its action list already grouped by panel.
  * the ranking     - the 22 vendor HOTAS profiles in `Hotas/Archive`.  They are
    deprecated and no longer maintained, but they are still 22 independent
    answers to "what belongs on a stick", which is exactly what we rank by
    everywhere else.
  * the devices     - `DeviceSorting.txt` fixes the DX numbering: device N owns
    DX numbers N*32 .. N*32+31, so the sorting order *is* the offset table.

Outputs bms-actions.json and bms-rank.json next to this file.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_BMS = Path.home() / (
    ".local/share/Steam/steamapps/compatdata/429530/pfx/drive_c/Falcon BMS 4.38"
)

HERE = Path(__file__).resolve().parent

# A full key line: callback, sound, <unused>, key, mod, combo key, combo mod, flag, "description"
KEY_LINE = re.compile(
    r'^(\w+)\s+(-?\w+)\s+(-?\w+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(-?\d+)\s+"(.*)"\s*$'
)
# A DX line is shorter and has no description: callback, dx, sound, kind, press, hex, sound2
DX_LINE = re.compile(r"^(\w+)\s+(-?\d+)\s+(-1|-2)\s+(-2|-3)\s+(\S+)\s+(\S+)\s+(-?\d+)\s*$")

SECTION = re.compile(r"^(\d+)\.\s+(.*)$")
SUBSECTION = re.compile(r"^=+\s*(\d+\.\d+)\s+(.*?)\s*=+$")

BUTTONS_PER_DEVICE = 32
SHIFT_MAGNITUDE = 256  # g_nHotasPinkyShiftMagnitude


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


def harvest_rank(archive):
    """Count how many vendor profiles put each callback on the hardware.

    Also record *where* they put it, because that carries as much information as
    the count: DX < 32 is the first device (a stick, in every one of these
    profiles), >= 32 the second (a throttle), and >= 256 is the pinky-shifted
    layer, i.e. deliberately demoted.
    """
    votes = Counter()
    placement = defaultdict(Counter)
    profiles = {}

    for path in sorted(archive.glob("*.key")):
        seen = set()
        per_profile = 0
        for raw in read_key(path):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = DX_LINE.match(line)
            if not m:
                continue
            cb, dx, sound, kind, press, _hex, _snd2 = m.groups()
            if cb == "SimDoNothing":
                continue
            dx = int(dx)
            per_profile += 1
            shifted = dx >= SHIFT_MAGNITUDE
            local = dx - SHIFT_MAGNITUDE if shifted else dx
            device = local // BUTTONS_PER_DEVICE

            where = "hat" if kind == "-3" else ("stick" if device == 0 else "throttle")
            if shifted:
                placement[cb]["shifted"] += 1
            placement[cb][where] += 1
            if cb not in seen:  # one vote per profile, not per line
                votes[cb] += 1
                seen.add(cb)
        if per_profile:
            profiles[path.name] = per_profile

    return votes, placement, profiles


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


def main():
    bms = bms_dir()
    keyfile = bms / "User" / "Config" / "BMS - Full.key"
    archive = bms / "Hotas" / "Archive"
    sorting = bms / "User" / "Config" / "DeviceSorting.txt"

    if not keyfile.exists():
        sys.exit(f"no key file at {keyfile} — set BMS_DIR to the BMS install")

    actions = harvest_actions(keyfile)
    votes, placement, profiles = harvest_rank(archive)
    devices = harvest_devices(sorting)

    for cb, a in actions.items():
        a["votes"] = votes.get(cb, 0)
        a["placement"] = dict(placement.get(cb, {}))

    unknown = sorted(set(votes) - set(actions))

    (HERE / "bms-actions.json").write_text(
        json.dumps({"devices": devices, "actions": actions}, indent=1, ensure_ascii=False)
    )
    (HERE / "bms-rank.json").write_text(
        json.dumps(
            {
                "profiles": profiles,
                "votes": votes.most_common(),
                "placement": {k: dict(v) for k, v in placement.items()},
                "not_in_keyfile": unknown,
            },
            indent=1,
            ensure_ascii=False,
        )
    )

    print(f"BMS      {bms}")
    print(f"actions  {len(actions)} bindable callbacks")
    print(f"sections {len(set(a['section'] for a in actions.values()))}"
          f" / {len(set(a['subsection'] for a in actions.values()))} subsections")
    print(f"ranking  {len(profiles)} vendor profiles, {len(votes)} callbacks ever on hardware")
    if unknown:
        print(f"         {len(unknown)} ranked callbacks no longer in the key file: "
              + ", ".join(unknown[:6]) + ("..." if len(unknown) > 6 else ""))
    print("devices")
    for d in devices:
        print(f"  DX {d['dx_range'][0]:>3}-{d['dx_range'][1]:<3} {d['usb']}  {d['name']}")
    print()
    print("top of the ranking")
    for cb, n in votes.most_common(15):
        a = actions.get(cb)
        where = ", ".join(f"{k} x{v}" for k, v in placement[cb].most_common(3))
        print(f"  {n:>3}  {cb:<28} {(a['desc'] if a else '(gone from key file)')[:44]:<46} {where}")


if __name__ == "__main__":
    main()

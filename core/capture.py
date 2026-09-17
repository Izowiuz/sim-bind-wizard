"""Reading the sticks directly: the Linux joystick protocol and the prompts.

Both capture wizards -- `games/dcs/dcs-bind-wizard.py` and
`games/elite/ed-bind-wizard.py` -- open `/dev/input/js*` themselves rather than
asking the game what it saw, because a binding has to be captured before the
game has one. This is the half of that they had byte for byte in common.

The device model here is the raw kernel one: a `js` node, its axis map and its
current axis values. It is unrelated to `sim-device-map`'s `Device`, which
describes what a control physically IS; these wizards use both, and one is
named `Device` while the other arrives as `devicemap.Device`.
"""

import fcntl
import glob
import json
import os
import select
import struct
import time

JS_EVENT_FMT = "IhBB"          # time, value, type, number
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FMT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

JSIOCGAXES = 0x80016A11
JSIOCGBUTTONS = 0x80016A12
JSIOCGNAME = 0x80806A13        # 128 bytes
JSIOCGAXMAP = 0x80406A32       # u8[64]: js axis index -> ABS_* code

AXIS_THRESHOLD = 14000         # out of +-32767
DEBOUNCE = 0.7


class Device:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        buf = bytearray(128)
        fcntl.ioctl(self.fd, JSIOCGNAME, buf)
        self.name = buf.split(b"\0", 1)[0].decode(errors="replace")
        self.n_axes = struct.unpack("B", fcntl.ioctl(self.fd, JSIOCGAXES, b"\0"))[0]
        self.n_buttons = struct.unpack("B", fcntl.ioctl(self.fd, JSIOCGBUTTONS, b"\0"))[0]
        self.axis_vals = {}
        self.role = None           # assigned during detection

    def read_events(self):
        events = []
        while True:
            try:
                data = os.read(self.fd, JS_EVENT_SIZE * 64)
            except BlockingIOError:
                break
            if not data:
                break
            for off in range(0, len(data) - JS_EVENT_SIZE + 1, JS_EVENT_SIZE):
                _, value, etype, number = struct.unpack_from(JS_EVENT_FMT, data, off)
                init = bool(etype & JS_EVENT_INIT)
                etype &= ~JS_EVENT_INIT
                if etype == JS_EVENT_AXIS:
                    self.axis_vals[number] = value
                    if not init:
                        events.append(("axis", number, value))
                elif etype == JS_EVENT_BUTTON and not init:
                    events.append(("button", number, value))
        return events


def axis_map(fd, n_axes):
    """js axis index -> ABS_* code, via JSIOCGAXMAP."""
    buf = bytearray(64)
    fcntl.ioctl(fd, JSIOCGAXMAP, buf)
    return list(buf[:n_axes])


def open_all(pattern="/dev/input/js*"):
    """Every joystick node that opens, in node order.

    A node that refuses to open is skipped rather than fatal: a stale
    `/dev/input/js3` from a device unplugged mid-session should not stop the
    wizard from seeing the two that are there.
    """
    out = []
    for path in sorted(glob.glob(pattern)):
        try:
            out.append(Device(path))
        except OSError:
            continue
    return out


def proc_joysticks():
    """name -> {vid, pid, js} for devices with a js handler."""
    out = {}
    with open("/proc/bus/input/devices") as f:
        for blk in f.read().split("\n\n"):
            name = vid = pid = jsdev = None
            for line in blk.splitlines():
                if line.startswith("I:"):
                    for part in line.split():
                        if part.startswith("Vendor="):
                            vid = part[7:]
                        elif part.startswith("Product="):
                            pid = part[8:]
                elif line.startswith("N: Name="):
                    name = line.split("=", 1)[1].strip('"')
                elif line.startswith("H: Handlers="):
                    for h in line.split("=", 1)[1].split():
                        if h.startswith("js"):
                            jsdev = "/dev/input/" + h
            if jsdev and name and vid and pid:
                out[name] = {"vid": vid, "pid": pid, "js": jsdev}
    return out


def refresh_axmap(name, pattern="/dev/input/js*"):
    """The axis map of the live device with this name, or None.

    A results file remembers the axis map so a layout can be regenerated with
    nothing plugged in, but it has to be filled the first time and refilled
    after a firmware update renumbers the axes.
    """
    for path in sorted(glob.glob(pattern)):
        try:
            d = Device(path)
        except OSError:
            continue
        try:
            if d.name == name:
                return axis_map(d.fd, d.n_axes)
        finally:
            os.close(d.fd)
    return None


def drain(devices, tui, seconds=DEBOUNCE):
    """Wait out the debounce and drop stray keypresses.

    A fixed wall clock, not "until quiet": the point is that letting go of a
    button must not read as the next answer. Events go through `read_events`
    rather than being discarded, so `axis_vals` stays current for the next
    `wait_input` baseline.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        r, _, _ = select.select([d.fd for d in devices], [], [], 0.05)
        for d in devices:
            if d.fd in r:
                d.read_events()
    while tui.key(0.0):
        pass


def wait_input(devices, want_axis, tui):
    """Wait for a joystick press / axis move, or ESC. No time limit.

    Returns `(dev, kind, index, sign)` or `"skip"`. `sign` is +1 for a button
    and the direction an axis moved in, which Elite writes into its `.binds`;
    DCS carries inversion as a separate flag and ignores it.

    `and not want_axis` gates the button arm. Elite's copy had lost it, so a
    button pressed while the wizard was asking for an axis was stored as a
    button against an axis-kind function -- and the generator then wrote
    `<Primary Key="Joy_N">` under an axis element, which the game silently
    ignores.
    """
    for d in devices:
        d.read_events()
    baseline = {d.path: dict(d.axis_vals) for d in devices}
    while True:
        r, _, _ = select.select([d.fd for d in devices], [], [], 0.05)
        if tui.key(0.0) == "esc":
            return "skip"
        for d in devices:
            if d.fd not in r:
                continue
            for kind, number, value in d.read_events():
                if kind == "button" and value == 1 and not want_axis:
                    return d, "button", number, 1
                if kind == "axis" and want_axis:
                    base = baseline[d.path].get(number, 0)
                    delta = value - base
                    if abs(delta) > AXIS_THRESHOLD:
                        return d, "axis", number, (1 if delta > 0 else -1)


def detect_device(devices, label, tui):
    tui.log(f"--> press any button on your {label}:")
    while True:
        got = wait_input(devices, want_axis=False, tui=tui)
        if got == "skip":
            continue                       # ESC is meaningless here
        d = got[0]
        if d.role is not None:
            tui.log(f"    that came from the {d.role} — try again on "
                    f"the {label}")
            drain(devices, tui)
            continue
        tui.log(f"    OK: {d.name}")
        tui.log("")
        drain(devices, tui)
        return d


def detect_roles(tui, roles=("stick", "throttle"), pattern="/dev/input/js*"):
    """Open every joystick, ask which is which, stamp `role` on each.

    Returns the full device list, or None when fewer than `len(roles)` nodes
    exist -- the caller says what to do about that, because the wizards word
    it differently.
    """
    devices = open_all(pattern)
    for d in devices:
        tui.log(f"  {d.path}  {d.name}  "
                f"({d.n_axes} axes, {d.n_buttons} buttons)")
    tui.log("")
    if len(devices) < len(roles):
        return None
    for role in roles:
        d = detect_device(devices, role.upper(), tui)
        d.role = role
    return devices


def save(results, path):
    with open(path, "w") as f:
        json.dump(results, f, indent=2)

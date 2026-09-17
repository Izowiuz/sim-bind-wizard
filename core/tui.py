"""The curses shell the capture wizards are built on.

A transcript model, not a frame model: `page()` starts a screen, `log()`
appends a line and repaints the tail. Every prompt in a capture wizard is a
line, including the ones `core/capture.py` writes from inside the event loop,
which is why the capture helpers take a `Tui`.

`sim-device-map/capture.py` has a Tui of its own and keeps it. That one is
stateless -- every screen erases and repaints itself -- with a fixed chrome, a
multi-select menu, free-text entry and a three-state confirm, and no
transcript at all. Only `key()` and `_put()` are the same code, and the
dependency arrow runs sim-bind-wizard -> sim-device-map, so it cannot import
this.
"""

import curses
import time


class Tui:
    def __init__(self, scr):
        self.scr = scr
        self.title = ""
        self.lines = []

    def key(self, timeout=0.0):
        """'enter' / 'esc' / 'up' / 'down' / printable char / None."""
        deadline = time.monotonic() + timeout
        while True:
            c = self.scr.getch()
            if c == -1:
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.02)
                continue
            if c in (10, 13, curses.KEY_ENTER):
                return "enter"
            if c == 27:
                return "esc"
            if c == curses.KEY_UP:
                return "up"
            if c == curses.KEY_DOWN:
                return "down"
            if 32 <= c < 127:
                return chr(c)
            # ignore resize and anything exotic

    def _put(self, y, x, text, attr=curses.A_NORMAL):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h:
            try:
                self.scr.addstr(y, x, text[:max(0, w - x - 1)], attr)
            except curses.error:
                pass

    def menu(self, title, items, index=0, footer="arrows = move, "
             "RETURN = select, ESC = back"):
        index = max(0, min(index, len(items) - 1))
        top = 0
        while True:
            h, _ = self.scr.getmaxyx()
            visible = max(3, h - 4)
            if index < top:
                top = index
            elif index >= top + visible:
                top = index - visible + 1
            self.scr.erase()
            self._put(0, 0, title, curses.A_BOLD)
            for row, i in enumerate(range(top,
                                          min(len(items), top + visible))):
                attr = curses.A_REVERSE if i == index else curses.A_NORMAL
                self._put(2 + row, 2, items[i], attr)
            self._put(h - 1, 0, f"{footer}  ({index + 1}/{len(items)})")
            self.scr.refresh()
            k = self.key(0.5)
            if k == "up":
                index = (index - 1) % len(items)
            elif k == "down":
                index = (index + 1) % len(items)
            elif k == "enter":
                return index
            elif k == "esc":
                return None

    def page(self, title):
        self.title = title
        self.lines = []
        self._redraw()

    def log(self, line=""):
        self.lines.append(line)
        self._redraw()

    def _redraw(self):
        h, _ = self.scr.getmaxyx()
        self.scr.erase()
        self._put(0, 0, self.title, curses.A_BOLD)
        for i, ln in enumerate(self.lines[-(h - 2):]):
            self._put(2 + i, 0, ln)
        self.scr.refresh()

    def wait_any_key(self):
        self.log("")
        self.log("-- press RETURN or ESC to continue --")
        while self.key(0.5) not in ("enter", "esc"):
            pass


def setup(scr):
    """A Tui on a screen ready for a capture wizard.

    `set_escdelay` is what makes ESC answer at once rather than after the
    terminal's escape timeout, and it is missing on older Pythons. Colour is
    started only so `use_default_colors` can hand the terminal's own palette
    back -- these wizards draw in bold and reverse, never in colour, because
    the terminal they run in is light-themed.
    """
    curses.curs_set(0)
    scr.nodelay(True)
    scr.keypad(True)
    try:
        curses.set_escdelay(50)
    except AttributeError:
        pass
    try:
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        pass
    return Tui(scr)

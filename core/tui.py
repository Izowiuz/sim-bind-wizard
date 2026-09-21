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


class Theme:
    """What each meaning on the screen looks like, worked out once.

    Tones are named for what a thing IS, never for the colour it comes out
    as. `mine` is green on a need's row in the review table and green again
    on the control that need is sitting on, and this class is the single
    place that decides so -- a screen asks for `theme.mine`, or `theme[name]`
    when the line it is drawing carries its own tone.

    `head`, `subhead` and `meta` are one ladder and are meant to be read as
    one: the section, the thing the section names, and the detail under it.
    A listing that puts all three in the same blue is a listing you have to
    read from the top to know where you are.

    Base colours only, and never yellow. These draw on the terminal's own
    background -- `use_default_colors` hands the palette back rather than
    painting one -- and the wizards in this family run on a light terminal as
    often as a dark one. Green, red, blue and magenta read on both; yellow on
    white does not.

    With no colour at all every tone falls back to bold, dim or reverse,
    which is all these screens ever had and is still what a terminal without
    colour gets.
    """

    #: The four that read on a light terminal and a dark one. Named here
    #: and nowhere else: past this point the code says what it means.
    BLUE, GREEN, RED, MAGENTA = (curses.COLOR_BLUE, curses.COLOR_GREEN,
                                 curses.COLOR_RED, curses.COLOR_MAGENTA)

    def __init__(self, colour=False):
        self.colour = colour
        self._pairs = 0
        norm, bold, dim, rev = (curses.A_NORMAL, curses.A_BOLD,
                                curses.A_DIM, curses.A_REVERSE)
        # Each tone reads: the colour it wants, what it adds where the
        # terminal has one, and what it falls back to where it has not.
        self.title = self._tone(None, bold, bold)
        self.head = self._tone(self.BLUE, bold, bold)
        self.subhead = self._tone(self.BLUE, norm, norm)
        self.mine = self._tone(self.GREEN, norm, bold)
        self.proposed = self._tone(self.MAGENTA, norm, norm)
        self.unset = self._tone(self.RED, norm, dim)
        self.note = self._tone(self.MAGENTA, norm, norm)
        self.meta = self._tone(None, dim, dim)
        self.plain = self._tone(None, norm, norm)
        self.sel = self._tone(None, rev, rev)

    def _tone(self, colour, lit, dull):
        """One tone: a colour pair where there is colour, else the fallback.

        Pairs are numbered in the order they are asked for, which is why no
        caller ever sees a pair number -- there is nothing useful to say
        about 3 that `theme.unset` does not say better.
        """
        if not self.colour:
            return dull
        if colour is None:
            return lit
        self._pairs += 1
        curses.init_pair(self._pairs, colour, -1)
        return curses.color_pair(self._pairs) | lit

    def __getitem__(self, tone):
        """A tone by its name, for a line that carries its own."""
        return getattr(self, tone)


class Tui:
    def __init__(self, scr, theme=None):
        self.scr = scr
        #: how this screen draws. A Tui built without one gets the colourless
        #: theme, which is what `setup` falls back to anyway on a terminal
        #: that has no colour.
        self.theme = theme or Theme()
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
    started so `use_default_colors` can hand the terminal's own palette back,
    and the `Theme` laid over it is where every screen gets its attributes.
    The capture wizards still come out in bold and reverse -- they ask for
    `title` and `meta` and that is what those tones are -- but the review
    screen, which has more than two things to say, gets colour for them.
    """
    curses.curs_set(0)
    scr.nodelay(True)
    scr.keypad(True)
    try:
        curses.set_escdelay(50)
    except AttributeError:
        pass
    colour = False
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            colour = True
    except curses.error:
        pass
    return Tui(scr, Theme(colour))

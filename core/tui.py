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


#: The frame a panel is drawn in. btop's idea: the chrome lives in the
#: border -- title, counts and key names all in the box edge -- so none of
#: it costs a row. Three lines of key names at the bottom of a 24-row
#: terminal is an eighth of the screen spent on something read once.
TL, TR, BL, BR, H, V = '╭', '╮', '╰', '╯', '─', '│'

#: Hints are joined with the separator the rest of the family uses. btop
#: notches each one into the border (`┘info ↵└`) because its hints are
#: buttons you can click; ours are labels, so the notches cost two columns
#: each for nothing -- at seven hints that is a hint and a half.
SEP = ' · '


def plural(n, one, many=None):
    """`3 bindings`, `1 binding`. Six places wrote `binding(s)` instead.

    A parenthesised s is a form nobody speaks, and on a screen that is
    otherwise man-terse it is the loudest thing on the line.
    """
    word = one if n == 1 else (many or one + 's')
    return f'{n} {word}'


def lid(width, title='', right=''):
    """The top edge: what this panel is, and what it is showing.

    Built as one string rather than drawn in pieces. The last two goes at
    chrome painted one thing over another and every test passed, because
    they asked what the text said rather than what reached the screen -- a
    string cannot do that to itself.

    Anything that will not fit is dropped whole: a border that has eaten
    half a title says less than a plain one.
    """
    if width <= 0:
        return ''
    if width < 4:
        return (TL + H * (width - 2) + TR) if width >= 2 else H * width
    inner = width - 2
    head = f'{H} {title} ' if title else H * 2
    if len(head) > inner:
        head = head[:inner]
    tail = f' {right} ' if right else ''
    if tail and len(head) + len(tail) + 1 > inner:
        tail = ''
    fill = H * max(0, inner - len(head) - len(tail))
    return TL + head + fill + tail + TR


def sill(width, keys=(), tail='', note=''):
    """The bottom edge: which keys do what, and where you are.

    `note` takes the left when there is one, and the keys give way to it.
    A status line is the one thing down here that changes, and the keys are
    the one thing that never does -- so it goes IN the edge rather than
    being drawn over it, which is what happened the first two times and
    what no test of the text could ever have caught.

    Keys are dropped from the end when they will not fit, because the list
    is written most-needed first: nothing else is reachable without moving.
    `tail` is kept before any of them.
    """
    if width <= 0:
        return ''
    if width < 4:
        return (BL + H * (width - 2) + BR) if width >= 2 else H * width
    inner = width - 2
    end = f' {tail} ' if tail else ''
    if len(end) > inner:
        end = ''
    room = inner - len(end)
    if note:
        said = f' {note} '
        return BL + said[:room].ljust(room, H) + end + BR
    out = ''
    for k in keys:
        piece = (SEP if out else ' ') + k
        if len(out) + len(piece) + 1 > room:
            break
        out += piece
    if out:
        out += ' '
    return BL + out + H * max(0, room - len(out)) + end + BR


def box_for(body, h, w, title, full=False, keys=(), tail=''):
    """(y, x, height, width) for a box holding `body` on an h x w screen.

    Sized to what it holds and no larger: a help box with three inches of
    blank border says the list is longer than it is. Capped at the screen,
    which is where `overflows` takes over.

    `keys` and `tail` widen it too. `sill` drops the keys that will not
    fit and keeps the tail before any of them, so a short list under a
    short title made a box too narrow to say `↵ choose` -- and the way out
    of it was the one thing it did not show.

    `full` takes the whole terminal instead. A notice you read wants to be
    the size of what it says; a list you WORK in -- the vocabulary, the
    device map -- wants every row it can get, and centring it in a margin
    costs two of them for nothing.
    """
    if full:
        return 0, 0, h, w
    inner = max((len(t) for t in body), default=0)
    across = sum(len(k) for k in keys) + len(SEP) * max(0, len(keys) - 1)
    across += len(tail) + 2 if tail else 0
    bw = min(w - 2, max(len(title) + 8, inner + 2 * GAP + 2,
                        across + 4 if keys else 0))
    bh = min(h - 2, len(body) + 2 + PAD)
    return (h - bh) // 2, (w - bw) // 2, bh, bw


#: A blank row between the last line and the sill. Text that runs into the
#: bottom edge reads as text that was cut off there.
PAD = 1

#: Blank columns between a box's border and what it says. Counted from
#: the inside of the edge, which is where somebody reading it counts from.
GAP = 2


def rows_in(bh):
    """How many lines of content a box of this height holds."""
    return bh - 2 - PAD



def overflows(body, h, w, title, full=False):
    """Is there more than the box can show at once?"""
    return len(body) > rows_in(box_for(body, h, w, title, full)[2])


#: What a box you pick from says it answers to. Named because `box_for`
#: has to know them to leave room for them, and a list that disagreed
#: with the sill would size the box for keys it does not show.
CHOOSE_KEYS = ('\u2191\u2193 move', '\u21b5 choose', 'ESC back')


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
            if c in (8, 127, curses.KEY_BACKSPACE):
                return "backspace"
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

    def box(self, title, lines, keys=(), tail='', top=0, sel=None,
            full=False):
        """Draw a framed box over the middle of the screen. Returns its page.

        Framed by the same `lid`/`sill` the panels use, so every box on this
        screen -- the help, the control list, the prompt to press something --
        reads as one kind of thing rather than three.
        """
        body = [t for _tone, t in lines]
        h, w = self.scr.getmaxyx()
        y, x, bh, bw = box_for(body, h, w, title, full, keys, tail)
        page = rows_in(bh)
        self._put(y, x, lid(bw, title), self.theme.head)
        for n in range(bh - 2):
            self._put(y + 1 + n, x, V + ' ' * (bw - 2) + V, self.theme.head)
        self._put(y + bh - 1, x, sill(bw, keys, tail), self.theme.head)
        for n, (tone, text) in enumerate(lines[top:top + page]):
            lit = (self.theme.sel
                   if sel is not None and top + n == sel
                   else self.theme[tone])
            self._put(y + 1 + n, x + 1 + GAP, text[:bw - 2 - 2 * GAP], lit)
        self.scr.refresh()
        return page

    def popup(self, title, lines, full=False):
        """A box you read and dismiss.

        Scrolls rather than truncates. It used to draw `lines[:bh - 2]` and
        stop, so on a short terminal the help simply ended -- and what fell
        off the bottom was the least-used half, which is the half somebody
        opening the help is most likely to be after.
        """
        body = [t for _tone, t in lines]
        top = 0
        while True:
            h, w = self.scr.getmaxyx()
            page = rows_in(box_for(body, h, w, title, full)[2])
            more = overflows(body, h, w, title, full)
            top = max(0, min(top, len(body) - page)) if more else 0
            self.box(title, lines,
                 ('↑↓ more', 'any other key closes') if more else (),
                 f'{top + page} of {len(body)}' if more else 'any key to close',
                 top, full=full)
            k = self.key(0.5)
            if k is None:
                continue
            if more and k in ('up', 'k'):
                top -= 1
            elif more and k in ('down', 'j'):
                top += 1
            elif more and k == ' ':
                top += page
            else:
                return

    def inner(self):
        """How wide a full-screen box's content may be."""
        return max(20, self.scr.getmaxyx()[1] - 4)

    def confirm(self, title, lines):
        """Show what is about to happen and wait for a yes. True if given.

        RETURN rather than a typed word: this is the thing the screen is for,
        it is pressed often, and every writer in the family backs the file up
        before it touches it. What was missing was not a gate -- it was seeing
        what the keystroke would do while there was still time to say no.
        """
        while True:
            self.box(title, lines, ('↵ do it', 'ESC cancel'), tail='')
            k = self.key(0.5)
            if k == 'enter':
                return True
            if k in ('esc', 'q', 'Q'):
                return False

    def ask(self, title, lines=(), value='', keys=('↵ accept',
                                                   'ESC back')):
        """A line of text. Returns it, or None on ESC.

        In the same frame as everything else, because a prompt drawn on a
        bare screen is a second set of rules: this one is read with the
        same eyes that just read a list.
        """
        while True:
            self.box(title, [('plain', t) for t in lines]
                     + ([('plain', '')] if lines else [])
                     + [('sel', f'{value}_')], keys)
            k = self.key(0.5)
            if k == 'enter':
                return value
            if k == 'esc':
                return None
            if k == 'backspace':
                value = value[:-1]
            elif k and len(k) == 1 and k.isprintable():
                value += k

    def choose(self, title, lines, tail='', head=(), skip=()):
        """A box you pick a line out of. Returns the index, or None on ESC.

        `head` is rows above the list that are not part of it -- where a
        list was read from, what it is counted out of. In the box rather
        than in the sill, because the sill's note pushes the keys off and
        the way out of a box is not the thing to trade away.

        `skip` names rows inside the list the cursor passes over: a blank
        one holding two kinds of thing apart. Landing on it would be
        landing on nothing, and `↵ choose` over a blank row is a key that
        does not mean anything.
        """
        head, skip = list(head), set(skip)
        pick = [n for n in range(len(lines)) if n not in skip]
        if not pick:
            return None
        at = top = 0
        while True:
            h, w = self.scr.getmaxyx()
            rows = head + list(lines)
            page = rows_in(box_for([t for _tone, t in rows], h, w, title,
                                   keys=CHOOSE_KEYS,
                                   tail=f'{len(pick)} of {len(pick)}')[2])
            at = max(0, min(at, len(pick) - 1))
            sel = pick[at]
            if len(head) + sel < top:
                top = len(head) + sel
            elif len(head) + sel >= top + page:
                top = len(head) + sel - page + 1
            # The widest the tail ever gets, so the box does not change
            # width as the cursor passes 9.
            self.box(title, rows, CHOOSE_KEYS,
                     f'{at + 1:>{len(str(len(pick)))}} of {len(pick)}',
                     top, len(head) + sel)
            k = self.key(0.5)
            if k in ('up', 'k'):
                at -= 1
            elif k in ('down', 'j'):
                at += 1
            elif k == 'g':
                at = 0
            elif k == 'G':
                at = len(pick) - 1
            elif k == 'enter':
                return sel
            elif k == 'esc':
                return None

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

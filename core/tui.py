"""The curses shell the screens are built on.

Every screen here is a box. `box`, `popup`, `confirm`, `ask` and `choose`
draw one, and each one erases and repaints itself. The chrome lives in the
border: `lid` holds the title and the counts, and `sill` holds the key
names and the status.

The device map's capture tool keeps a Tui of its own. That one has a fixed
chrome, a multi-select menu, free-text entry and a three-state confirm.
Only `key()` and `_put()` are the same code. The dependency runs
sim-bind-wizard -> sim-device-map, so that tool cannot import this one.
"""

import curses
import time


class Theme:
    """What each meaning on the screen looks like, worked out once.

    A tone is named for what a thing IS, never for the colour it comes out
    as. `mine` is green on a need's row and green again on the control that
    need sits on. This class is the one place that decides so. A screen
    asks for `theme.mine`, or for `theme[name]` where the line it draws
    carries its own tone.

    `head`, `subhead` and `meta` are one ladder: the section, the thing the
    section names, and the detail under it. Read them as one. All three in
    the same blue is a listing you read from the top to know where you are.

    Base colours only, and never yellow. These draw on the terminal's own
    background, because `use_default_colors` hands the palette back. These
    screens run on a light terminal as often as a dark one. Green, red,
    blue and magenta read on both. Yellow on white does not.

    With no colour every tone falls back to bold, dim or reverse.
    """

    #: The four colours that read on a light terminal and a dark one.
    #: Named here and nowhere else. Past this point the code says what it
    #: means.
    BLUE, GREEN, RED, MAGENTA = (curses.COLOR_BLUE, curses.COLOR_GREEN,
                                 curses.COLOR_RED, curses.COLOR_MAGENTA)

    def __init__(self, colour=False):
        self.colour = colour
        self._pairs = 0
        norm, bold, dim, rev = (curses.A_NORMAL, curses.A_BOLD,
                                curses.A_DIM, curses.A_REVERSE)
        # Each tone holds three things: the colour it wants, what it adds
        # where the terminal has colour, and what it falls back to where
        # the terminal has none.
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
        #: What the hand is on, ADDED to whatever tone a row already
        #: carries. Not a tone of its own: the row goes on saying what
        #: its state is, and this says the thumb is there now.
        #:
        #: Underline rather than bold or reverse. `mine` is already bold
        #: where the terminal has no colour and the cursor is already
        #: reverse, so either of those says two things with one mark.
        self.touched = curses.A_UNDERLINE

    def _tone(self, colour, lit, dull):
        """One tone: a colour pair where there is colour, else the fallback.

        Pairs are numbered in the order they are asked for. No caller sees
        a pair number. There is nothing to say about 3 that `theme.unset`
        does not say better.
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


#: The frame a panel is drawn in. The chrome lives in the border: the
#: title, the counts and the key names all sit in the box edge, so none of
#: them costs a row. Three lines of key names at the bottom of a 24-row
#: terminal spends an eighth of the screen on something read once. btop
#: does it this way.
TL, TR, BL, BR, H, V = '╭', '╮', '╰', '╯', '─', '│'

#: The same six, heavy, for a panel the arrows are pointed at. A shape
#: rather than a colour: these screens run on a terminal with no colour
#: as often as not, and `Theme` falls back to bold and dim there, which
#: a frame already uses for its own edge.
HEAVY = {TL: '┏', TR: '┓', BL: '┗', BR: '┛', H: '━', V: '┃'}


def weight(text, heavy):
    """`text` with the frame drawn heavy, or as it came.

    Applied to the finished string rather than threaded through `lid` and
    `sill` as six arguments. Both of them build one string on purpose, so
    this is one `translate` over the thing they already made.
    """
    return text.translate(str.maketrans(HEAVY)) if heavy else text

#: Hints are joined with the separator the rest of the family uses. btop
#: notches each hint into the border, as `┘info ↵└`, because its hints are
#: buttons you click. These are labels, so a notch costs two columns for
#: nothing. At seven hints that is a hint and a half.
SEP = ' · '


def plural(n, one, many=None):
    """`3 bindings`, `1 binding`.

    A parenthesised s is a form nobody speaks. On a screen that is
    otherwise man-terse it is the loudest thing on the line.
    """
    word = one if n == 1 else (many or one + 's')
    return f'{n} {word}'


def lid(width, title='', right=''):
    """The top edge: what this panel is, and what it shows.

    Built as one string. Chrome drawn in pieces paints one thing over
    another, and a test that asks what the text says does not catch that. A
    string cannot paint over itself.

    Anything that will not fit is dropped whole. A border that has eaten
    half a title says less than a plain border.
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


def lid_wants(title='', right=''):
    """The width at which `lid` keeps `right` beside `title`.

    `lid` drops the right-hand line whole, and a caller that chooses its
    own width has to know when that happens. The arithmetic lives beside
    the thing that does it, so one of them cannot drift from the other.

    Read off `lid`: two columns of corner, three for `─ ` and the space
    after the title, two for the spaces around `right`, and one for the
    gap the drop test insists on.
    """
    return len(title) + len(right) + 8


def sill(width, keys=(), tail='', note=''):
    """The bottom edge: which keys do what, and where you are.

    `note` takes the left where there is one, and the keys give way to it.
    The status is the one thing down here that changes. The keys never
    change. So the status goes IN the edge rather than over it.

    Keys are dropped from the end where they will not fit. The list is
    written most-needed first, and nothing else is reachable without
    moving. `tail` is kept before any key.
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

    Sized to what it holds and no larger. A help box inside three inches of
    blank border says the list is longer than it is. The size is capped at
    the screen, and `overflows` takes over there.

    `keys` and `tail` widen the box too. `sill` drops the keys that do not
    fit and keeps the tail before any of them, so a short list under a
    short title makes a box too narrow to say `↵ choose`. That is the way
    out of the box.

    `full` takes the whole terminal. A notice you read is the size of what
    it says. A list you WORK in, such as the vocabulary or the device map,
    takes every row it can get, and a margin costs two rows for nothing.
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
#: bottom edge reads as text cut off there.
PAD = 1

#: Blank columns between a box's border and what it says. Counted from the
#: inside of the edge. That is where a reader counts from.
GAP = 2


def rows_in(bh):
    """How many lines of content a box of this height holds."""
    return bh - 2 - PAD



def overflows(body, h, w, title, full=False):
    """Is there more than the box can show at once?"""
    return len(body) > rows_in(box_for(body, h, w, title, full)[2])


#: What a box you pick from says it answers to. `box_for` needs these to
#: leave room for them. A list that disagreed with the sill would size the
#: box for keys the box does not show.
CHOOSE_KEYS = ('\u2191\u2193 move', '\u21b5 choose', 'ESC back')


class Tui:
    def __init__(self, scr, theme=None):
        self.scr = scr
        #: How this screen draws. A Tui built without a theme gets the
        #: colourless one. `setup` falls back to that on a terminal with no
        #: colour.
        self.theme = theme or Theme()

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
            if c == 9:
                return "tab"
            if c == curses.KEY_BTAB:
                return "shift-tab"
            if 32 <= c < 127:
                return chr(c)
            # Ignore a resize and anything exotic.

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

        The frame is the same `lid` and `sill` the panels use. Every box
        then reads as one kind of thing: the help, the control list and the
        prompt to press something.
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

    def corner(self, title, lines):
        """A small box in the bottom right, over whatever is already there.

        Drawn after the screen it sits on, and not instead of it. It
        answers a question about what is behind it, so a box that hid the
        list would answer into an empty room.

        Nothing is drawn for an empty `lines`. The box is there while
        there is something to say and gone the rest of the time, which is
        what tells a reader it is about the moment.

        A blank column down its left, for the reason a dialog has one: the
        list behind runs up to the frame and is cut mid-word.

        The device map draws the same box for the same question. This is
        that box, on this family's `lid` and `sill`.
        """
        if not lines:
            return
        h, w = self.scr.getmaxyx()
        body = [t for _tone, t in lines]
        wide = max((len(t) for t in body), default=0)
        bw = min(w - 4, max(len(title) + 8, wide + 2 + 2 * GAP))
        bh = min(h - 2, len(body) + 2)
        y, x = h - bh - 1, w - bw - 2
        for row in range(y, y + bh):
            self._put(row, max(0, x - 1), ' ')
        self._put(y, x, lid(bw, title), self.theme.head)
        for n in range(bh - 2):
            self._put(y + 1 + n, x, V + ' ' * (bw - 2) + V, self.theme.head)
        self._put(y + bh - 1, x, sill(bw), self.theme.head)
        for n, (tone, text) in enumerate(lines[:bh - 2]):
            self._put(y + 1 + n, x + 1 + GAP,
                      text[:bw - 2 - 2 * GAP], self.theme[tone])

    def popup(self, title, lines, full=False):
        """A box you read and dismiss.

        It scrolls. It does not truncate. A box that draws `lines[:bh - 2]`
        and stops ends on a short terminal, and what falls off the bottom
        is the least-used half. That half is what somebody opening the help
        is looking for.
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

        RETURN, not a typed word. This is the thing the screen is for, it
        is pressed often, and every writer backs the file up before it
        touches it. What this adds is seeing what the keystroke does while
        there is still time to say no.
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

        In the same frame as everything else. A prompt drawn on a bare
        screen is a second set of rules, and this one is read by the eyes
        that just read a list.
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

    def choose(self, title, lines, tail='', head=(), skip=(), index=0):
        """A box you pick a line out of. Returns the index, or None on ESC.

        `head` holds rows above the list that are not part of it: where a
        list was read from, and what it is counted out of. They go in the
        box and not in the sill, because the sill's note pushes the keys
        off, and the way out of a box is not the thing to trade away.

        `skip` names rows inside the list that the cursor passes over. A
        blank row holding two kinds of thing apart is one. Landing on it is
        landing on nothing, and `↵ choose` over a blank row means nothing.
        """
        head, skip = list(head), set(skip)
        pick = [n for n in range(len(lines)) if n not in skip]
        if not pick:
            return None
        # `index` is where the cursor starts. Without it a form that asks
        # a field and comes back puts you at the top, which is nine
        # keystrokes from the row you were on.
        at = pick.index(index) if index in pick else 0
        top = 0
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
            # The widest the tail gets. The box then keeps its width as
            # the cursor passes 9.
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

def setup(scr):
    """A Tui on a screen ready for a caller.

    `set_escdelay` makes ESC answer at once rather than after the
    terminal's escape timeout. Older Pythons lack it.

    Colour is started here, so `use_default_colors` hands the terminal's
    own palette back. The `Theme` laid over it is where every screen gets
    its attributes.
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

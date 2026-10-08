"""Render a kneeboard: the same data as a layout, laid out to be read in flight.

Three adapters grew their own copy of this and two of them shared a template
by hand-copying it, which is how War Thunder's ended up with colour tokens
called `--air` and `--heli` in a file about a single-engine jet.

What they actually had in common is a table of rows, so that is the contract.
An adapter builds `Row` objects and hands them over; it does not
render anything.

    sheet = Sheet('Kneeboard Falcon BMS', 'F-16C · VIRPIL', ident='DX')
    sheet.add(Row('stick', 'Grip thumb hat', 'up', '23', 'CMS',
                  {'': 'SimCMSUp'}))
    sheet.markdown(path)
    sheet.html(path)

`contexts` is the one piece of policy here. A game with one context -- BMS has
only the F-16 -- puts the binding under the action's name as a second line. A
game with several -- War Thunder flies aircraft and helicopters, MSFS adds a
global layer -- gets a column each, because the whole point is seeing at a
glance that one button does two different things.
"""

import datetime
import os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, 'sheet-template.html')


def esc(t):
    return (str(t).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


def cell(text):
    """One markdown table cell: a pipe in the text would end it.

    DCS names a command `Radar | Display Zoom Out`, and that row came out
    with an extra column -- the table header says three and the row said
    four, so every renderer after it guessed. Nothing else in the family
    has a pipe in a name, which is why this went unnoticed until DCS's
    sheet moved onto this one.
    """
    return str(text).replace('|', '\\|')


def _mark(row):
    """A row's mark as the page draws it, or nothing."""
    return f' <em>{esc(row.mark)}</em>' if row.mark else ''


def wrap(text, width, indent):
    out, line = [], ''
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    if line:
        out.append(line)
    return f'\n{indent}'.join(out)


@dataclass
class Row:
    """One button, and what it does in each context."""
    role: str                       # device kind: 'stick', 'throttle'
    control: str                    # label from the device map
    part: str = ''                  # 'up', 'second', 'press'
    ident: str = ''                 # the game's own reference: DX 23, WT 130
    does: str = ''                  # the need's human name
    bindings: dict = field(default_factory=dict)   # context -> str or [str]
    edge: str = ''                  # e.g. BMS's release action, shown inline
    #: A word beside what this does, when the binding is not settled.
    #: DCS's `?`: its sheet is built from the results file, so half of it
    #: is what you confirmed at the stick and half is still the planner's
    #: proposal, and a page that does not say which is which invites you
    #: to trust the half nobody has pressed.
    mark: str = ''
    #: An axis rather than a button. The flight controls go at the top of
    #: the device's table, because they are what the rest is reached for
    #: while already holding.
    axis: bool = False



class Sheet:
    def __init__(self, title, subtitle, ident='#', contexts=('',),
                 heading='Kneeboard', devices=None):
        self.title = title
        self.heading = heading
        self.subtitle = subtitle
        #: Which rig it was laid out for, and to which overlay. Both
        #: decide where everything on the page landed, and a kneeboard
        #: that does not say reads as the only layout there could be --
        #: so printing one on a desk it was not drawn for is silent.
        #: Filled by `Adapter.write_sheets`, one place for six games.
        self.desk = ''
        self.overlay = ''
        self.ident = ident          # column header for the game's own numbering
        self.contexts = tuple(contexts)
        self.devices = devices or {}     # role -> product name, for panel titles
        self.rows = []
        self.notes = []             # (heading, [(term, text)]) or (heading, text)
        self.free = []              # (role, control, ident)
        #: (what, wanted). What has no control on this desk.
        self.unplaced = []
        #: What to say about the ORDER of that list, when the order means
        #: something. DCS lists its in the order you learn an aircraft,
        #: so the top of the list is the part worth reading. It used to
        #: sort by how many of the shipped profiles bound each thing,
        #: with the count on the page as `5 factory profiles` -- a number
        #: you can do nothing with. The order carries what there is to
        #: carry; this says the order is there.
        self.unplaced_note = 'nothing on the desk fits these'

    # ---- building ----
    def add(self, row):
        self.rows.append(row)

    def add_axis(self, role, control, ident, does, context=''):
        """One thing an axis does, merged onto that axis's row.

        Games hand these over one at a time, because that is how their
        own config reads them -- and one physical lever is one row, with
        what it does in each context as a column. So the same
        (role, control, ident) twice is not two rows.

        Collected into a list, never assigned. Elite's main stick answers
        the SRV with `Buggy roll axis raw` AND `Steering axis`, both on
        axis 0, and assigning kept whichever came last. Five games each
        merged this for themselves before it lived here; one of the five
        had the bug.

        An ordinary `Row` with no `part`: an axis has no press order and
        no direction, and that is the whole of the difference. It had a
        row type of its own and a table of its own, so one sheet answered
        the same question in two shapes.
        """
        for row in self.rows:
            if (row.role, row.control, row.ident) == (role, control, ident):
                break
        else:
            row = Row(role, control, ident=ident, axis=True)
            self.rows.append(row)
        row.bindings.setdefault(context, []).append(does)
        # And in `does`, for a game with one context: that is the column
        # the merged table reads, and `bindings` is what fills a column
        # per context where a game has several.
        row.does = row.does or does

    def add_free(self, role, control, ident=''):
        """One control nothing was put on.

        A method rather than four adapters each building the tuple: they
        did, and the tuple carried a fifth field -- how far the control is
        -- rendered as `index, the hand off the grip, still on the device`
        in a column beside a control's name. Fifteen rows of that is not a
        column, it is an essay nobody reads, and what it answered ("could
        I still use this?") the control's own name answers better.

        Taking it out meant changing the shape in five places at once,
        with nothing holding them together. Now there is: pass the wrong
        number here and it fails at the call, naming the caller.
        """
        self.free.append((role, control, ident))

    def add_unplaced(self, what, wanted=''):
        """One thing with no control. In the order you add them.

        A method rather than five adapters appending a tuple, for the
        reason `add_free` is one: the shape changed and nothing held the
        call sites together. Pass the wrong number here and it fails at
        the call, naming the caller.
        """
        self.unplaced.append((what, wanted))

    def marked(self):
        """Is anything on this page unsettled?

        What decides whether the legend is printed. A mark nobody has
        explained is some of the rows being slightly different, and a
        legend over a page that uses no marks is a line you learn to
        skip -- so it appears exactly when it is earned.
        """
        return any(r.mark for r in self.rows)

    def note(self, heading, body):
        self.notes.append((heading, body))

    # ---- shared shaping ----
    def _roles(self):
        """Every device with anything on it, in the order it turns up.

        Axes count. They used to have a panel of their own, off at the
        bottom with the leftovers, which is a fact about how this file
        grew and not about the hardware: an axis is part of a device the
        same way a button is, and the question a kneeboard answers is
        "what does this stick do", not "what do the buttons do".
        """
        seen = []
        for r in self.rows:
            if r.role not in seen:
                seen.append(r.role)
        return seen

    def _axes(self):
        return [r for r in self.rows if r.axis]

    def _axes_of(self, role):
        """The device's axis rows, which lead its table."""
        return [r for r in self.rows if r.role == role and r.axis]

    def _buttons_of(self, role):
        return [r for r in self.rows if r.role == role and not r.axis]

    def _free_roles(self):
        """Devices with something spare, the bound ones first.

        Not `_roles()`: a device nothing was put on has no panel, and
        grouping the leftovers by that list dropped its controls off the
        sheet altogether -- which is the one list they belonged on.
        """
        seen = [r for r in self._roles()
                if any(x == r for x, _c, _i in self.free)]
        for role, _c, _i in self.free:
            if role not in seen:
                seen.append(role)
        return seen

    def _cell(self, row, ctx):
        v = row.bindings.get(ctx)
        if not v:
            return ''
        return ' · '.join(v) if isinstance(v, (list, tuple)) else str(v)

    def _stamp(self):
        return (f'generated {datetime.date.today()} · '
                f'{len(self.rows)} rows'
                + self._for())

    def _for(self):
        """ · desk · overlay`, or as much of it as is known."""
        return ''.join(f' · {part}' for part in (self.desk, self.overlay)
                       if part)

    #: What a mark means, printed only where one is used. See `marked`.
    LEGEND = 'A `?` is proposed and nobody has confirmed it at the stick.'

    def _said(self, row, ctx=''):
        """What a row does in this context, with its mark after it."""
        got = self._cell(row, ctx)
        return f'{got} {row.mark}'.rstrip() if got else got

    # ---- markdown ----
    def markdown(self, path):
        named = [c for c in self.contexts if c]
        L = [f'# {self.title}', '',
             f'{self.subtitle}{self._for()}. '
             'This file is generated. Do not edit it. Write it again '
             'instead.'
             + (f' {self.LEGEND}' if self.marked() else ''), '']
        for role in self._roles():
            L += [f'## {self.devices.get(role, role)}', '']
            # One table: the axes lead it, because they are the flight
            # controls and the buttons are what you reach for while
            # already holding them. Two tables made one page answer the
            # same question in two shapes -- and an axis is an input like
            # the rest of them.
            mine = self._axes_of(role) + self._buttons_of(role)
            if not mine:
                continue
            # The binding column only where a game has one to show. DCS
            # binds a command BY its name, so the column repeated the
            # `Does` column verbatim down the whole page, and a column
            # that says the same as its neighbour is a column to leave
            # out rather than one to read twice.
            shows = any(self._cell(x, '') != x.does or x.edge for x in mine)
            if named:
                L += ['| ' + ' | '.join([self.ident, 'Control'] + named) + ' |',
                      '|' + '---|' * (2 + len(named))]
            elif shows:
                L += [f'| {self.ident} | Control | Does | Binding |',
                      '|---|---|---|---|']
            else:
                L += [f'| {self.ident} | Control | Does |', '|---|---|---|']
            for r in mine:
                ctrl = cell(r.control) + (f' — {cell(r.part)}' if r.part
                                          else '')
                if named:
                    cells = [self._said(r, c) or '—' for c in named]
                    L.append(f'| {r.ident} | {ctrl} | '
                             + ' | '.join(cell(c) for c in cells) + ' |')
                else:
                    does = cell(f'{r.does} {r.mark}'.rstrip())
                    if not shows:
                        L.append(f'| {r.ident} | {ctrl} | {does} |')
                        continue
                    # Per row, not per table. The rule is "only where
                    # the binding says something the name does not", and
                    # measured over the table it put `AXIS_THROTTLE`
                    # beside `AXIS_THROTTLE` on every axis row BMS has.
                    got = self._cell(r, '')
                    if got == r.does and not r.edge:
                        L.append(f'| {r.ident} | {ctrl} | {does} |  |')
                        continue
                    b = cell(got)
                    if r.edge:
                        b += f'<br>release: `{cell(r.edge)}`'
                    L.append(f'| {r.ident} | {ctrl} | {does} | `{b}` |')
            L.append('')
        for heading, body in self.notes:
            L += [f'## {heading}', '']
            if isinstance(body, (list, tuple)):
                L += [f'- **{k}** — {v}' for k, v in body]
            else:
                L.append(str(body))
            L.append('')
        if self.unplaced:
            L += ['## Not placed', '', f'{self.unplaced_note[0].upper()}'
                  f'{self.unplaced_note[1:]}.', '']
            for what, wanted in self.unplaced:
                # No article: the shapes are the map's words, and
                # `a axis` is what one of them came out as.
                L.append(f'- {what}' + (f' (wanted `{wanted}`)'
                                        if wanted else ''))
            L.append('')
        if self.free:
            L += ['## Still free', '']
            for role in self._free_roles():
                mine = [(c, i) for r, c, i in self.free if r == role]
                if not mine:
                    continue
                L += [f'### {self.devices.get(role, role)}', '']
                L += [f'- {c} — {i or "no buttons"}' for c, i in mine] + ['']
        open(path, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
        return path, len(self.rows), len(self._axes())

    # ---- html ----
    def _panel(self, role):
        named = [c for c in self.contexts if c]
        # The axes lead the table: they are the flight controls, and the
        # buttons are what you reach for while already holding them.
        mine = self._axes_of(role) + self._buttons_of(role)
        # The binding under the name only where it says something the
        # name does not. DCS binds a command BY its name, so every row
        # carried it twice: once as the heading and once in the small
        # mono line under it.
        shows = any(self._cell(x, '') != x.does or x.edge for x in mine)
        head = ['Control', self.ident] + (named or ['Does'])
        cls = ' class="a"'
        th = ''.join(f'<th{cls if named and i > 1 else ""}>{esc(h)}</th>'
                     for i, h in enumerate(head))
        out = []
        for r in mine:
            name = esc(r.control) + (f' <em>{esc(r.part)}</em>' if r.part else '')
            cells = [f'<td class="c">{name}</td>',
                     f'<td class="n">{esc(r.ident)}</td>']
            if named:
                for c in named:
                    v = self._cell(r, c)
                    cells.append(f'<td{"" if v else " class=\"none\""}>'
                                 f'{esc(v)}{_mark(r) if v else "—"}</td>')
            else:
                got = self._cell(r, '')
                b = esc(got)
                if r.edge:
                    b += f' / {esc(r.edge)}'
                does = esc(r.does) + _mark(r)
                if r.edge:
                    does += ' <span class="edge">+ release</span>'
                # Per row: a binding that repeats the name says nothing.
                under = (f'<span class="cb">{b}</span>'
                         if shows and (got != r.does or r.edge) else '')
                cells.append(f'<td>{does}{under}</td>')
            out.append('<tr>' + ''.join(cells) + '</tr>')
        title = esc(self.devices.get(role, role))
        # One table. There were two, on the argument that the columns are
        # not the same question -- an axis has no context split and no
        # press order -- which is a difference in two cells, not in what
        # the row IS.
        tables = (f'<table><tr>{th}</tr>' + ''.join(out) + '</table>'
                  if out else '')
        return f'<div class="panel"><h2>{title}</h2>{tables}</div>'

    def html(self, path, template=None):
        tpl = open(template or TEMPLATE, encoding='utf-8').read()
        # By device, like everything else on the sheet. One run of
        # fifteen control names made you work out which stick each was
        # on, which is the question the panels above already answer for
        # every control that got something.
        ftables = ''
        for role in self._free_roles():
            mine = [(c, i) for r, c, i in self.free if r == role]
            if not mine:
                continue
            frows = ''.join(f'<tr><td class="c">{esc(c)}</td>'
                            f'<td class="n">{esc(i) or "—"}</td></tr>'
                            for c, i in mine)
            ftables += (f'<table><tr><th>{esc(self.devices.get(role, role))}'
                        f'</th><th>{esc(self.ident)}</th></tr>'
                        f'{frows}</table>')
        free = (f'<div class="panel"><h2>Left free</h2>{ftables}</div>'
                if ftables else '')
        #: Eighteen and then a count. DCS's list is every essential the
        #: results file has nothing for -- forty-odd on a fresh module --
        #: and a panel that long stops being a panel. The markdown prints
        #: all of them, because a page you scroll can afford it.
        left = ''
        if self.unplaced:
            shown = self.unplaced[:18]
            # Two columns, like `Left free`: a panel is one of two or
            # three across the page, and a third column squeezed a short
            # phrase into one word per line. The reason goes under the
            # name, where the page already puts its small print.
            urows = ''.join(
                f'<tr><td class="c">{esc(w)}</td>'
                f'<td class="n">{esc(s) or "—"}</td></tr>' for w, s in shown)
            more = len(self.unplaced) - len(shown)
            if more:
                urows += (f'<tr><td colspan="2">and {more} more — '
                          f'see the markdown</td></tr>')
            left = ('<div class="panel"><h2>Not placed'
                    f'<small>{esc(self.unplaced_note)}</small></h2>'
                    f'<table><tr><th>Wanted</th><th>Shape</th></tr>'
                    f'{urows}</table></div>')
        notes = ''
        for heading, body in self.notes:
            if isinstance(body, (list, tuple)):
                items = ''.join(f'<li><b>{esc(k)}</b> — {v}</li>'
                                for k, v in body)
                inner = f'<ul>{items}</ul>'
            else:
                inner = f'<p>{body}</p>'
            notes += (f'<div class="panel"><h2>{esc(heading)}</h2>'
                      f'<div class="note">{inner}</div></div>')
        out = (tpl.replace('__TITLE__', esc(self.title))
                  .replace('__HEADING__', esc(self.heading))
                  # The legend only. Desk and overlay are on the
                  # stamp at the foot of the page, and printing them in
                  # both places says one fact twice.
                  .replace('__SUBTITLE__', self.subtitle
                           + (f'. {self.LEGEND}' if self.marked() else ''))
                  .replace('__PANELS__', ''.join(self._panel(r)
                                                 for r in self._roles()))
                  .replace('__UNPLACED__', left)
                  .replace('__FREE__', free)
                  .replace('__NOTES__', notes)
                  .replace('__STAMP__', esc(self._stamp())))
        open(path, 'w', encoding='utf-8').write(out)
        return path, len(self.rows), len(self._axes())

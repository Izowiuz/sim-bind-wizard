"""Render a kneeboard: a layout's own data, laid out to be read in flight.

The contract is a table of rows. An adapter builds `Row` objects and hands
them over. It renders nothing.

    sheet = Sheet('Kneeboard Falcon BMS', 'F-16C · VIRPIL', ident='DX')
    sheet.add(Row('stick', 'Grip thumb hat', 'up', '23', 'CMS',
                  {'': 'SimCMSUp'}))
    sheet.markdown(path)
    sheet.html(path)

`contexts` is the one piece of policy here. A game with one context puts
the binding under the action's name, as a second line. Falcon BMS has only
the F-16. A game with several contexts gets a column each: War Thunder
flies aircraft and helicopters, and MSFS adds a global layer. The point of
a column is seeing at a glance that one button does two things.
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
    """One markdown table cell. A pipe in the text would end the cell.

    DCS names a command `Radar | Display Zoom Out`. That row comes out
    with an extra column: the header says three columns and the row says
    four, so every renderer after it guesses. DCS is the only game here
    with a pipe in a name.
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
    role: str                       # the device kind: 'stick', 'throttle'
    control: str                    # the label from the device map
    part: str = ''                  # 'up', 'second', 'press'
    ident: str = ''                 # the game's own reference: DX 23, WT 130
    does: str = ''                  # the need's name, in words
    bindings: dict = field(default_factory=dict)   # context -> str or [str]
    edge: str = ''                  # a release action, shown inline
    #: A word beside what this does, where the binding is not settled.
    #: DCS prints `?` there. Its sheet is built from the results file, so
    #: half of it is what you confirmed at the stick and half is still a
    #: proposal. A page that does not say which is which invites you to
    #: trust the half nobody has pressed.
    mark: str = ''
    #: An axis rather than a button. The flight controls go at the top of
    #: the device's table. You hold those while you reach for the rest.
    axis: bool = False



class Sheet:
    def __init__(self, title, subtitle, ident='#', contexts=('',),
                 heading='Kneeboard', devices=None):
        self.title = title
        self.heading = heading
        self.subtitle = subtitle
        #: Which desk this was laid out for, and to which overlay. Both
        #: decide where everything on the page landed. A kneeboard that
        #: does not say reads as the only layout there could be, and a
        #: page printed for another desk then says nothing about it.
        #: `Adapter.write_sheets` fills both, in one place for six games.
        self.desk = ''
        self.overlay = ''
        self.ident = ident          # the header over the game's own numbering
        self.contexts = tuple(contexts)
        self.devices = devices or {}     # role -> product name, for a title
        self.rows = []
        self.notes = []             # (heading, [(term, text)]) or (heading, text)
        self.free = []              # (role, control, ident)
        #: (what, wanted). What has no control on this desk.
        self.unplaced = []
        #: What to say about the ORDER of that list, where the order
        #: means something. DCS lists its own in the order you learn an
        #: aircraft, so the top of the list is the part worth reading.
        #: The order carries the fact. This line says the order is
        #: there.
        self.unplaced_note = 'nothing on the desk fits these'

    # ---- building ----
    def add(self, row):
        self.rows.append(row)

    def add_axis(self, role, control, ident, does, context=''):
        """One thing an axis does, merged onto that axis's row.

        A game hands these over one at a time, because its own
        configuration reads them that way. One physical lever is one row,
        and what it does in each context is a column. So the same
        (role, control, ident) twice is one row.

        The things are collected into a list. They are never assigned.
        Elite's main stick answers the SRV with `Buggy roll axis raw` AND
        `Steering axis`, both on axis 0, and an assignment keeps whichever
        came last.

        An axis is an ordinary `Row` with no `part`. It has no press order
        and no direction, and that is the whole difference.
        """
        for row in self.rows:
            if (row.role, row.control, row.ident) == (role, control, ident):
                break
        else:
            row = Row(role, control, ident=ident, axis=True)
            self.rows.append(row)
        row.bindings.setdefault(context, []).append(does)
        # And in `does`, for a game with one context. That is the column
        # the merged table reads. `bindings` fills one column per context
        # where a game has several.
        row.does = row.does or does

    def add_free(self, role, control, ident=''):
        """One control nothing was put on.

        A method, not a tuple each adapter builds. Pass the wrong number
        of arguments here and it fails at the call, naming the caller. A
        tuple built in five places changes shape in five places, and
        nothing holds those together.
        """
        self.free.append((role, control, ident))

    def add_unplaced(self, what, wanted=''):
        """One thing with no control, in the order you add them.

        A method, for the reason `add_free` is one. Pass the wrong number
        of arguments here and it fails at the call, naming the caller.
        """
        self.unplaced.append((what, wanted))

    def marked(self):
        """Is anything on this page unsettled?

        This decides whether the legend is printed. An unexplained mark
        makes some rows look slightly different and says nothing. A legend
        over a page that uses no mark is a line you learn to skip.
        """
        return any(r.mark for r in self.rows)

    def note(self, heading, body):
        self.notes.append((heading, body))

    # ---- shared shaping ----
    def _roles(self):
        """Every device with anything on it, in the order it turns up.

        Axes count. An axis is part of a device the same way a button is.
        A kneeboard answers "what does this stick do", not "what do the
        buttons do".
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

        Not `_roles()`. A device nothing was put on has no panel, so
        grouping the leftovers by that list drops its controls off the
        sheet. The leftovers list is the one list they belong on.
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

    #: What a mark means. Printed only where a mark is used. See
    #: `marked`.
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
            # One table. The axes lead it, because they are the flight
            # controls and you hold those while you reach for a button.
            # Two tables make one page answer the same question in two
            # shapes, and an axis is an input like the rest.
            mine = self._axes_of(role) + self._buttons_of(role)
            if not mine:
                continue
            # The binding column, only where a game has one to show. DCS
            # binds a command BY its name, so that column repeats the
            # `Does` column down the whole page. Leave a column out
            # rather than read it twice.
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
                    # Per row, not per table. The rule is "print it only
                    # where the binding says something the name does
                    # not". Measured over the whole table instead, it put
                    # `AXIS_THROTTLE` beside `AXIS_THROTTLE` on every
                    # axis row Falcon BMS has.
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
                # No article. The shapes are the map's own words, and
                # one of them came out as `a axis`.
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
                L += [f'- {c} · {i or "no buttons"}' for c, i in mine] + ['']
        open(path, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
        return path, len(self.rows), len(self._axes())

    # ---- html ----
    def _panel(self, role):
        named = [c for c in self.contexts if c]
        # The axes lead the table. They are the flight controls, and you
        # hold those while you reach for a button.
        mine = self._axes_of(role) + self._buttons_of(role)
        # The binding goes under the name only where it says something
        # the name does not. DCS binds a command BY its name, so every
        # row carries it twice: once as the heading, once in the small
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
                # Per row. A binding that repeats the name says nothing.
                under = (f'<span class="cb">{b}</span>'
                         if shows and (got != r.does or r.edge) else '')
                cells.append(f'<td>{does}{under}</td>')
            out.append('<tr>' + ''.join(cells) + '</tr>')
        title = esc(self.devices.get(role, role))
        # One table. An axis has no context split and no press order, and
        # that is a difference in two cells. It is not a difference in
        # what the row IS.
        tables = (f'<table><tr>{th}</tr>' + ''.join(out) + '</table>'
                  if out else '')
        return f'<div class="panel"><h2>{title}</h2>{tables}</div>'

    def html(self, path, template=None):
        tpl = open(template or TEMPLATE, encoding='utf-8').read()
        # By device, like everything else on the sheet. One run of
        # fifteen control names makes you work out which stick each is
        # on. The panels above answer that for every control that got
        # something.
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
        #: Eighteen rows, and then a count. DCS's list holds every
        #: essential the results file has nothing for, which is forty-odd
        #: on a fresh module. A panel that long stops being a panel. The
        #: markdown prints all of them, because a page you scroll can
        #: afford it.
        left = ''
        if self.unplaced:
            shown = self.unplaced[:18]
            # Two columns, like `Left free`. A panel is one of two or
            # three across the page, and a third column squeezes a short
            # phrase into one word per line. The reason goes under the
            # name, where the page puts its small print.
            urows = ''.join(
                f'<tr><td class="c">{esc(w)}</td>'
                f'<td class="n">{esc(s) or "—"}</td></tr>' for w, s in shown)
            more = len(self.unplaced) - len(shown)
            if more:
                urows += (f'<tr><td colspan="2">and {more} more. '
                          f'See the markdown.</td></tr>')
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
                  # The legend only. The desk and the overlay are on the
                  # stamp at the foot of the page. In both places they
                  # say one fact twice.
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

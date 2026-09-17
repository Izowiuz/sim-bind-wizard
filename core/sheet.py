"""Render a kneeboard: the same data as a layout, laid out to be read in flight.

Three adapters grew their own copy of this and two of them shared a template
by hand-copying it, which is how War Thunder's ended up with colour tokens
called `--air` and `--heli` in a file about a single-engine jet.

What they actually had in common is a table of rows, so that is the contract.
An adapter builds `Row` and `AxisRow` objects and hands them over; it does not
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


@dataclass
class AxisRow:
    role: str
    control: str
    ident: str = ''                 # SLIDER1, WT 24, L-Axis X
    does: str = ''                  # the game's axis name
    note: str = ''


class Sheet:
    def __init__(self, title, subtitle, ident='#', contexts=('',),
                 heading='Kneeboard', devices=None):
        self.title = title
        self.heading = heading
        self.subtitle = subtitle
        self.ident = ident          # column header for the game's own numbering
        self.contexts = tuple(contexts)
        self.devices = devices or {}     # role -> product name, for panel titles
        self.rows = []
        self.axes = []
        self.notes = []             # (heading, [(term, text)]) or (heading, text)
        self.free = []              # (role, control, ident, reach)
        self.unplaced = []          # (what, wanted)

    # ---- building ----
    def add(self, row):
        self.rows.append(row)

    def add_axis(self, row):
        self.axes.append(row)

    def note(self, heading, body):
        self.notes.append((heading, body))

    # ---- shared shaping ----
    def _roles(self):
        seen = []
        for r in self.rows:
            if r.role not in seen:
                seen.append(r.role)
        return seen

    def _cell(self, row, ctx):
        v = row.bindings.get(ctx)
        if not v:
            return ''
        return ' · '.join(v) if isinstance(v, (list, tuple)) else str(v)

    def _stamp(self):
        return (f'generated {datetime.date.today()} · '
                f'{len(self.rows)} bindings · {len(self.axes)} axes')

    # ---- markdown ----
    def markdown(self, path):
        named = [c for c in self.contexts if c]
        L = [f'# {self.title}', '',
             f'{self.subtitle}. Generated — do not edit, regenerate.', '']
        if self.axes:
            L += ['## Axes', '',
                  f'| Control | {self.ident} | Does |', '|---|---|---|']
            for a in self.axes:
                L.append(f'| {a.control} | `{a.ident}` | {a.does} |')
            L.append('')
        L += ['## Buttons', '']
        for role in self._roles():
            L += [f'### {self.devices.get(role, role)}', '']
            if named:
                L += ['| ' + ' | '.join([self.ident, 'Control'] + named) + ' |',
                      '|' + '---|' * (2 + len(named))]
            else:
                L += [f'| {self.ident} | Control | Does | Binding |',
                      '|---|---|---|---|']
            for r in (x for x in self.rows if x.role == role):
                ctrl = f'{r.control}' + (f' — {r.part}' if r.part else '')
                if named:
                    cells = [self._cell(r, c) or '—' for c in named]
                    L.append(f'| {r.ident} | {ctrl} | ' + ' | '.join(cells) + ' |')
                else:
                    b = self._cell(r, '')
                    if r.edge:
                        b += f'<br>release: `{r.edge}`'
                    L.append(f'| {r.ident} | {ctrl} | {r.does} | `{b}` |')
            L.append('')
        for heading, body in self.notes:
            L += [f'## {heading}', '']
            if isinstance(body, (list, tuple)):
                L += [f'- **{k}** — {v}' for k, v in body]
            else:
                L.append(str(body))
            L.append('')
        if self.unplaced:
            L += ['## Not placed', ''] + \
                 [f'- {w} (wanted a `{s}`)' for w, s in self.unplaced] + ['']
        if self.free:
            L += ['## Still free', ''] + \
                 [f'- {c} ({role}) — {i or "no buttons"}'
                  for role, c, i, _reach in self.free] + ['']
        open(path, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
        return path, len(self.rows), len(self.axes)

    # ---- html ----
    def _panel(self, role):
        named = [c for c in self.contexts if c]
        head = ['Control', self.ident] + (named or ['Does'])
        cls = ' class="a"'
        th = ''.join(f'<th{cls if named and i > 1 else ""}>{esc(h)}</th>'
                     for i, h in enumerate(head))
        out = []
        for r in (x for x in self.rows if x.role == role):
            name = esc(r.control) + (f' <em>{esc(r.part)}</em>' if r.part else '')
            cells = [f'<td class="c">{name}</td>',
                     f'<td class="n">{esc(r.ident)}</td>']
            if named:
                for c in named:
                    v = self._cell(r, c)
                    cells.append(f'<td{"" if v else " class=\"none\""}>'
                                 f'{esc(v) or "—"}</td>')
            else:
                b = esc(self._cell(r, ''))
                if r.edge:
                    b += f' / {esc(r.edge)}'
                does = esc(r.does)
                if r.edge:
                    does += ' <span class="edge">+ release</span>'
                cells.append(f'<td>{does}<span class="cb">{b}</span></td>')
            out.append('<tr>' + ''.join(cells) + '</tr>')
        title = esc(self.devices.get(role, role))
        return (f'<div class="panel"><h2>{title}</h2><table>'
                f'<tr>{th}</tr>' + ''.join(out) + '</table></div>')

    def html(self, path, template=None):
        tpl = open(template or TEMPLATE, encoding='utf-8').read()
        arows = ''.join(
            f'<tr><td class="c">{esc(a.control)}</td>'
            f'<td class="n">{esc(a.ident)}</td><td>{esc(a.does)}</td></tr>'
            for a in self.axes)
        axes = (f'<div class="panel"><h2>Axes</h2><table><tr><th>Control</th>'
                f'<th>{esc(self.ident)}</th><th>Does</th></tr>'
                f'{arows}</table></div>') if self.axes else ''
        frows = ''.join(
            f'<tr><td class="c">{esc(c)}</td><td class="n">{esc(i) or "—"}</td>'
            f'<td class="h">{esc(reach)}</td></tr>'
            for _role, c, i, reach in self.free)
        free = (f'<div class="panel"><h2>Left free</h2><table><tr>'
                f'<th>Control</th><th>{esc(self.ident)}</th><th>Reach</th></tr>'
                f'{frows}</table></div>') if self.free else ''
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
                  .replace('__SUBTITLE__', self.subtitle)
                  .replace('__PANELS__', ''.join(self._panel(r)
                                                 for r in self._roles()))
                  .replace('__AXES__', axes)
                  .replace('__FREE__', free)
                  .replace('__NOTES__', notes)
                  .replace('__STAMP__', esc(self._stamp())))
        open(path, 'w', encoding='utf-8').write(out)
        return path, len(self.rows), len(self.axes)

"""Hardware that does not exist, built out of the classes that describe the
hardware that does.

`devicemap.Device` takes a parsed TOML table, not a path, so a synthetic device
is a dict away -- and it comes back a real `Device`, with the real `Group`, the
real `bindable_buttons` and the real `direction()`. That matters more than it
sounds: a hand-written stub of a control is a second opinion about what a
control IS, and the moment it drifts the tests pass against a fiction. The only
thing invented here is the hardware.

    stick = device('stick', [
        hat4('Thumb hat', 0, reach=THUMB, push=4),
        button('Pinky button', 5, reach=GRIP),
    ])
    placed, unplaced, free = allocate(NEEDS, {'stick': stick})

Button numbers are given explicitly rather than counted for you, because a test
about which button a binding landed on should say which buttons exist.

The reach strings are the map's own, copied from the captures: `reach_tier`
matches on substrings ('thumb', 'index finger', 'without releasing', 'needs
letting go'), so inventing new wording here would quietly test a tier nobody
ships.
"""

import os
import sys

CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import devmap                                      # noqa: E402

devicemap = devmap.load()

# ---------------------------------------------------------------- the reaches

#: tier 0 -- under the thumb, or the index finger on the grip
THUMB = 'thumb, without releasing grip'
INDEX = 'index finger, on the grip'
#: tier 1 -- another finger, still holding on
PINKY = 'pinky finger, without releasing grip'
MIDDLE = 'middle/ring finger, without releasing grip'
#: tier 3 -- let go of the grip to get there
PANEL = 'needs letting go'
#: tier 2 -- what an uncaptured control scores, by falling through the table
UNSAID = ''


# --------------------------------------------------------------- the controls

def control(kind, label, buttons=(), **kw):
    """One entry for a device's `[[group]]` table."""
    g = {'kind': kind, 'label': label, 'buttons': list(buttons)}
    g.update(kw)
    return g


def button(label, index, **kw):
    return control('button', label, [index], **kw)


def hat2(label, first, dirs=('forward', 'back'), **kw):
    return control('hat2', label, [first, first + 1], dirs=list(dirs), **kw)


def hat4(label, first, dirs=('up', 'right', 'down', 'left'), **kw):
    return control('hat4', label, list(range(first, first + 4)),
                   dirs=list(dirs), **kw)


def trigger(label, first, stages=('first detent', 'second detent'), **kw):
    return control('trigger', label, [first, first + 1],
                   stages=list(stages), **kw)


def encoder(label, first, **kw):
    return control('encoder', label, [first, first + 1],
                   dirs=['ccw', 'cw'], **kw)


def selector(label, first, positions=5, **kw):
    return control('selector', label, list(range(first, first + positions)),
                   positions=[str(i + 1) for i in range(positions)], **kw)


def latch(label, first, positions=('off', 'on'), **kw):
    return control('latch', label,
                   list(range(first, first + len(positions))),
                   positions=list(positions), **kw)


def ministick(label, first_axis, push=None, **kw):
    """Two axes and, usually, a click."""
    return control('ministick', label, [],
                   axes=[first_axis, first_axis + 1], push=push, **kw)


def axis(index, kind, label, hid='X', rest='centred', **kw):
    a = {'index': index, 'kind': kind, 'label': label, 'hid': hid,
         'rest': rest, 'source': 'measured'}
    a.update(kw)
    return a


# ---------------------------------------------------------------- the devices

def device(kind, controls=(), axes=(), slug=None, product=None, usb=None,
           serial=None, evdev=None, games=None):
    """A `devicemap.Device` that no one ever plugged in."""
    slug = slug or f'fake-{kind}'
    ident = {'usb': usb or '0000:0000', 'serial': serial or 'FAKE',
             'evdev': evdev or f'Fake {kind}'}
    if games:
        ident['games'] = dict(games)
    data = {
        'device': {'slug': slug, 'product': product or f'Fake {kind}',
                   'vendor': 'Fake', 'kind': kind,
                   'buttons': 1 + max([b for c in controls
                                       for b in _all(c)] or [-1]),
                   'axes': len(axes)},
        'identity': [ident],
        'fingerprint': {},
        'axis': list(axes),
        'group': list(controls),
    }
    return devicemap.Device(data, f'<fake:{slug}>')


def _all(group):
    out = list(group.get('buttons', []))
    for key in ('push', 'rest_contact', 'travel_contact'):
        if group.get(key) is not None:
            out.append(group[key])
    out.extend(group.get('transient', []))
    return out


def hotas(stick_controls=(), throttle_controls=(),
          stick_axes=(), throttle_axes=()):
    """The usual pair, in the shape `allocate()` and every planner expect."""
    return {'stick': device('stick', stick_controls, stick_axes),
            'throttle': device('throttle', throttle_controls, throttle_axes)}

"""Hardware that does not exist, built out of the classes that describe
the hardware that does.

`devicemap.Device` takes a parsed TOML table and not a path, so a
synthetic device is a dict away. It comes back a real `Device`, with the
real `Group`, the real `bindable_buttons` and the real `direction()`.

That matters. A hand-written stub of a control is a second opinion about
what a control IS, and the moment it drifts the tests pass against a
fiction. The only thing invented here is the hardware.

    stick = device('stick', [
        hat4('Thumb hat', 0, reach=THUMB, push=4),
        button('Pinky button', 5, reach=GRIP),
    ])
    placed, unplaced, free = allocate(NEEDS, {'stick': stick})

The button numbers are given, not counted for you. A test about which
button a binding landed on says which buttons exist.

The reaches are the map's own words, copied from the captures. New wording
here tests a tier nobody ships.
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
#
# A reach is a place a hand can be and not a sentence. It is `(level,
# finger)`, and the map turns that into a tier by how far the level is
# from flying. Matched on substrings instead, a typo here tests a tier
# nobody ships.

#: Tier 0. The hand where it lives, thumb or index finger.
THUMB = ('HOME', 'thumb')
INDEX = ('HOME', 'index')
#: Tier 1. Another finger stretching, with the hand still on the grip.
PINKY = ('EXTENDED', 'pinky')
MIDDLE = ('EXTENDED', 'middle')
#: Tier 3. Let go of the device to get there.
PANEL = ('OFF', '')
#: Nobody has measured it. Not tier 2: there is no answer at all, and a
#: number here is one nothing can tell from a measured one.
UNSAID = None


# --------------------------------------------------------------- the controls

def unwired(label, buttons=(), **kw):
    """Buttons the firmware reports with nothing behind them.

    A `status` and not a `kind`. A row that is not a control has no shape,
    and the word in `kind` is one nothing can check.
    """
    return control('', label, buttons, status='unwired', **kw)


def control(kind, label, buttons=(), names=(), dirs=(), stages=(),
            positions=(), push=None, rest_contact=None, travel_contact=None,
            transient=(), reach=UNSAID, **kw):
    """One entry for a device's `[[group]]` table.

    `reach` is not a field on a control. Where a thing sits is a fact
    about the desk, so it is carried here and `device` lays it out as the
    desk's `access`.
    """
    said = list(names or dirs or stages or positions)
    latching = kind in devicemap.LATCHING
    states = []
    for n, b in enumerate(buttons):
        name = said[n] if n < len(said) else ''
        states.append({'button': b}
                      | ({'direction': name} if name and dirs
                         else {'name': name} if name else {})
                      | ({'latching': True} if latching else {}))
    for role, b in (('push', push), ('rest', rest_contact),
                    ('travel', travel_contact)):
        if b is not None:
            states.append({'name': role, 'button': b, 'role': role}
                          | ({'latching': True} if role != 'push' else {}))
    for b in transient:
        states.append({'name': 'passing', 'button': b, 'role': 'transient'})
    g = {'kind': kind, 'label': label, 'id': devicemap.slug(label),
         'states': states}
    g.update(kw)
    g['reach'] = reach                  # `device` lifts this out again.
    return g


def button(label, index, **kw):
    return control('button', label, [index], **kw)


def hat2(label, first, dirs=('fwd', 'aft'), **kw):
    return control('hat2', label, [first, first + 1], dirs=list(dirs), **kw)


def hat4(label, first, dirs=('up', 'right', 'down', 'left'), **kw):
    return control('hat4', label, list(range(first, first + 4)),
                   dirs=list(dirs), **kw)


def trigger(label, first, stages=('first detent', 'second detent'), **kw):
    return control('trigger', label,
                   list(range(first, first + len(stages))),
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


def axis(index, hid='X', rest='centred', role='', **kw):
    """One axis, in the map's own fields.

    `kind` and `label` are NOT among them. What an axis is, and what it is
    called, belong to the control that carries it, and `Device.__init__`
    fills them in from there.
    """
    a = {'index': index, 'hid': hid, 'rest': rest, 'role': role}
    a.update(kw)
    return a


# ---------------------------------------------------------------- the devices

def device(kind, controls=(), axes=(), slug=None, product=None, usb=None,
           serial=None, evdev=None, games=None, hand=''):
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
        'group': [{k: v for k, v in c.items() if k != 'reach'}
                  for c in controls],
    }
    dev = devicemap.Device(data, f'<fake:{slug}>')
    return dev.under(desk(hand, (slug, controls)))


def desk(hand='', *devices):
    """A `Profile` laying these controls out under one hand.

    A reach is a fact about the desk, so it cannot be built into the
    device. Two devices in one test are under the same desk, or
    `compatible` has no pair of hands to compare.
    """
    said = []
    for slug, controls in devices:
        access = {}
        for c in controls:
            if c.get('reach') is None:
                continue
            level, finger = c['reach']
            # No `part`. The map works out which piece of the desk a
            # hand is on, from the device and the level.
            access[c['id']] = [{'level': level, 'finger': finger}]
        said.append({'slug': slug, 'hand': hand, 'access': access})
    return devicemap.Profile({'name': 'a desk in a test', 'device': said},
                             '<test-desk>')


def _all(group):
    return [st['button'] for st in group.get('states') or []
            if st.get('button') is not None]


def hotas(stick_controls=(), throttle_controls=(),
          stick_axes=(), throttle_axes=()):
    """The usual pair, in the shape `allocate()` and every planner expect."""
    return {'stick': device('stick', stick_controls, stick_axes),
            'throttle': device('throttle', throttle_controls, throttle_axes)}

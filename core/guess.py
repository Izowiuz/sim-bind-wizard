"""What a function probably is, from what the game already says about it.

A needs file is the one input nothing can derive. A record holds about
four and a half values, and two of them are irreducible: `suits` says what
a thing is FOR, and `urgency` says when you reach for it. No game records
either. That is about 90 decisions a game.

This proposes two fields. It does not decide which functions get a row.
The list is yours: `a` adds a row and `Z` fills the rows that exist.

Four clauses hold:

    it runs once          on `Z`, never on the way to a layout
    it is out of the      the planner reads the needs FILE. Nothing here
      decision path       is reachable from `allocate`.
    it marks itself       every field it writes lands in `Need.guessed`,
                          and the screen draws those with `MARK[PROPOSED]`
    it can be corrected   a field NOT in `guessed` is one you decided. A
                          second run leaves that field alone.

A guess you can see and correct is worth having. A guess that overwrites
your answer on the next run is not.

The word table lives in the core rather than in a game. `fire`, `trim`,
`gear`, `radar` and `chaff` mean the same thing in every flight simulator,
and `needs.JOBS` is a closed vocabulary of ten words. One table for six
games is knowledge about flying.

MEASURED against 197 hand-written `suits` values across four games. The
table was written once and was NOT tuned after the score was seen:

    right          111   56%
    wrong           36   18%
    nothing to say  50   25%

The misses are arguable. `Map` reads as `view` here and the owner filed it
under `nav`. `Landing gear` reads as `flight` and he filed it under
`systems`. Both readings defend themselves. The job is a judgement, and a
table cannot hold yours. That is what the mark is for.
"""

import collections
import re

from core import needs as corneeds

#: Words that name a job, per job. This is flight-simulator vocabulary and
#: not one game's. Every word here appears in at least two of the six games.
#:
#: Written once, from the ten job names and the plain words of flying. It is
#: not tuned against the owner's own answers. A table fitted to 197 known
#: values scores higher and means less.
WORDS = {
    'fire':    ('fire', 'trigger', 'gun', 'cannon', 'launch', 'release',
                'weapon', 'bomb', 'missile', 'rocket', 'pickle'),
    'lock':    ('lock', 'target', 'designate', 'tdc', 'uncage', 'cage',
                'hostile', 'threat', 'subsystem'),
    'sensor':  ('radar', 'sensor', 'scan', 'fov', 'zoom', 'tgp', 'flir',
                'raid', 'antenna', 'elevation', 'sight', 'ir', 'eo'),
    'view':    ('view', 'look', 'camera', 'head', 'snap', 'pan', 'cockpit',
                'kneeboard', 'map', 'menu', 'panel', 'ui'),
    'trim':    ('trim', 'trimmer'),
    'flight':  ('pitch', 'roll', 'yaw', 'rudder', 'throttle', 'thrust',
                'brake', 'speedbrake', 'airbrake', 'flap', 'gear',
                'steering', 'hook', 'boost', 'afterburner', 'wheel',
                'drive', 'speed', 'assist'),
    'systems': ('engine', 'start', 'crank', 'power', 'fuel', 'light',
                'canopy', 'master', 'battery', 'generator', 'pump',
                'apu', 'hydraulic', 'pip', 'cargo', 'scoop', 'hardpoint'),
    'defence': ('chaff', 'flare', 'countermeasure', 'dispense', 'jammer',
                'ecm', 'heatsink', 'shield', 'cell'),
    'comms':   ('comm', 'radio', 'mids', 'voip', 'wingman', 'atc',
                'intercom', 'datalink'),
    'nav':     ('nav', 'waypoint', 'autopilot', 'course', 'heading',
                'route', 'hyperspace', 'supercruise', 'fsd', 'jump',
                'galaxy', 'system'),
}

#: word -> job, built from the table above. The table stays the readable
#: half. A word in two jobs is a fault in `WORDS`, and `check_table` says
#: so.
AT = {w: job for job, ws in WORDS.items() for w in ws}

#: Where one word ends and the next begins in a name with no spaces in it.
#: Elite writes `RollAxisRaw` and X4 writes `INPUT_RANGE_MAP_ZOOM_IN`.
#: Lowering the name first and splitting on letters gives one token,
#: `rollaxisraw`, and every word inside it is invisible. Elite's own harvest
#: uses this same rule to make a name readable.
_CASE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_TOKENS = re.compile(r'[a-z0-9]+')


def _words(name):
    """[word] -- a name as the words in it, however it was spelled.

    Split on case BEFORE lowering. Take a trailing `s` off as well. A table
    that says `flap`, `brake`, `light` and `comm` has to answer to `Flaps`,
    `KEY_BRAKES`, `Exterior Lights Switch` and `Comms`. DCS's own harvest
    applies the same plural rule to match a category.
    """
    out = []
    for word in _TOKENS.findall(_CASE.sub(' ', name).lower()):
        out.append(word)
        if word.endswith('s') and len(word) > 2:
            out.append(word[:-1])
    return out


def check_table():
    """[complaint] -- what is wrong with `WORDS`, as sentences.

    The tests call this, the way they call `needs.check_rules`. A job
    nothing knows is a proposal no overlay can match. A word in two jobs
    is a vote that depends on dictionary order.
    """
    out = []
    for job in WORDS:
        if job not in corneeds.JOBS:
            out.append(f'{job!r} is not a job. These are: '
                       + ', '.join(corneeds.JOBS) + '.')
    seen = collections.Counter(w for ws in WORDS.values() for w in ws)
    for word, n in seen.items():
        if n > 1:
            out.append(f'{word!r} names {n} jobs. A word names one, or the '
                       'answer depends on the order of a dict.')
    return out


def job_of(name):
    """Which job this name reads as, or None where the table says nothing.

    Every word that names a job votes. The job with the most votes wins.
    One word is enough: `Countermeasures Dispense Switch - AFT` carries
    `countermeasure` and `dispense`, and both are `defence`. `Trim Hat -
    NOSE UP` carries `trim` alone.

    None, not a fallback. A quarter of the owner's own list reads as
    nothing here. A default for those is a judgement with no evidence.
    `undescribed_note` counts them, and `J` is where you answer one.
    """
    votes = collections.Counter(AT[w] for w in _words(name) if w in AT)
    return votes.most_common(1)[0][0] if votes else None


class Guess:
    """What the program proposes about one game's functions.

    Built from the adapter's own declarations. What a game contributes here
    is data: what its category words mean in ours. A method instead would
    be four games writing the same body.
    """

    def __init__(self, device_by_category=None, job_by_category=None):
        #: The game's category -> a device role. `Throttle Grip` says the
        #: real aircraft keeps it on the throttle. Eagle Dynamics say that
        #: in their own data. Measured against the owner's own answers:
        #: `Throttle Grip` 14 of 14 and `Stick` 7 of 7. This is not a
        #: guess, and it is marked as one anyway, because the program is
        #: still the one filling the field in.
        self.device_by_category = dict(device_by_category or {})
        #: The game's category -> a job, for the few categories that name
        #: one. Measured: a category mostly names a PLACE in the cockpit,
        #: and `Throttle Grip` splits evenly between flight, comms and
        #: sensor. So this holds a handful of entries. It does not map the
        #: whole vocabulary.
        self.job_by_category = dict(job_by_category or {})

    def about(self, action):
        """{field: value} this proposes for one action.

        Only what something SAYS. `urgency` is absent on purpose. No game's
        files record when you reach for a thing, so a proposed band invents
        the one judgement the scorer leans on hardest.
        """
        out = {}
        said = self.device_by_category.get(action.category or '')
        if said:
            out['device'] = said
        job = (self.job_by_category.get(action.category or '')
               or job_of(action.name))
        if job:
            out['suits'] = job
        return out

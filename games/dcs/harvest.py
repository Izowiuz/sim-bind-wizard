#!/usr/bin/env python3
"""harvest.py - read DCS's per-module command vocabulary

DESCRIPTION
    Read every module DCS has installed and report what each one can be
    told to do. With no arguments, print a summary.

FILES
    Mods/aircraft/<module>/Input/<unit>/joystick/default.lua   read
    dcs-actions.json    written by --json: the commands, per module

OPTIONS
    --game-dir PATH     the DCS install
    -a, --aircraft KEY  one module only (default: every one installed)

NOTES
    The reading itself lives in dcs-bind-wizard.py, which owns the format:
    a module's default.lua goes through a `lua` or `luajit` binary with the
    game's globals stubbed out. This caches what that produces.
"""

# Why this exists at all, when propose.py could read the install directly --
# and did until now:
#
# Running the vocabulary through a Lua interpreter costs a second or two per
# module and needs DCS on the machine. Cached, `propose.py` opens on a clone
# with no game installed, which is what every other game in the family
# already offered and what makes `tests/test_contract.py` able to check DCS's
# cache against its planner instead of skipping it.
#
# The round trip was measured before this was written: a command record holds
# only strings and ints, and `families()` produces an identical layout for
# FA-18C, TF-51D and su-25T whether it is fed live objects or the same data
# back out of JSON. A set or a tuple in there would not have survived, and
# the failure would have been silent -- a reordered member list lands a trim
# hat's directions on different buttons and nothing raises.

import json
import os
import sys
import typing

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.environ.get('SIM_BIND_WIZARD') or os.path.normpath(
    os.path.join(HERE, '..', '..'))
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from core import adapter                                    # noqa: E402


#: The wizard's own results file, which is also where it wrote down where
#: the game is. Read directly rather than through `propose.py`: a harvest
#: that imports the planner it feeds is a loop nobody needs.
RESULTS = os.path.join(HERE, 'dcs-bind-wizard-results.json')


def wizard():
    """The capture wizard, which owns the reading of a module."""
    return adapter.from_file('dcs_harvest_wizard',
                             os.path.join(HERE, 'dcs-bind-wizard.py'),
                             argv=['dcs-bind-wizard'])


def where_is_the_game(game_dir=None):
    """The install, from the flag or from what the wizard remembered."""
    cfg = {}
    try:
        with open(RESULTS, encoding='utf-8') as f:
            cfg = dict(json.load(f)['_config'])
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    if game_dir:
        cfg['game_dir'] = game_dir
    if not cfg.get('game_dir'):
        raise SystemExit('Pass --game-dir, or run the wizard once so '
                         'that it remembers where DCS is.')
    return cfg


def read_module(mod, cfg, key, factory_dir):
    """{'commands': ...} for one aircraft: what the module says about
    itself, and nothing this repo thinks about it.

    The guide used to be written here beside the commands. It is the
    wizard's own table applied to the command names, so a cached copy
    would keep an edit to that table out of the next plan; `propose.py`
    builds it on every run instead.
    """
    return {'commands': mod.harvest_commands(cfg, key, factory_dir)}


@typing.final
class DcsHarvest(adapter.Harvest):
    """Every installed module's commands, keyed by the module."""

    game = 'dcs'
    files = {'dcs-actions.json': ('aircraft',)}

    @typing.override
    def arguments(self, parser) -> None:
        parser.add_argument('--game-dir',
                            help='Where DCS is installed.')
        parser.add_argument('-a', '--aircraft',
                            help='Read one module only. The default is '
                                 'every module.')

    @typing.override
    def read(self, args) -> dict:
        mod = wizard()
        cfg = where_is_the_game(args.game_dir)
        ac = mod.discover_aircraft(cfg)
        keys = [args.aircraft] if args.aircraft else sorted(ac)
        for k in keys:
            if k not in ac:
                raise SystemExit(
                    f'There is no module called {k}. These are installed: '
                    f'{", ".join(sorted(ac))}.')
        self.where = cfg['game_dir']
        out = {k: read_module(mod, cfg, k, ac[k]['factory_dir'])
               for k in keys}
        return {'dcs-actions.json': {'aircraft': out}}

    @typing.override
    def summary(self, data) -> list[str]:
        out = [f'game: {self.where}']
        for key, got in sorted(data['dcs-actions.json']['aircraft'].items()):
            cmds = got['commands']
            axes = sum(1 for c in cmds.values() if c.get('kind') == 'axis')
            out.append(f'  {key:16s} {len(cmds):5d} commands, '
                       f'{axes} of them axes')
        return out


if __name__ == '__main__':
    sys.exit(DcsHarvest().main())

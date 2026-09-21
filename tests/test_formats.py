"""The parts of each writer that touch the game's own file format.

A writer is mostly one pure function -- rewrite the text, put one binding in,
keep the line endings -- wrapped in path-finding and argument parsing. Those
functions are where the format bugs live, and they can be tested on a few
lines of synthetic config instead of a game install.

The fixtures are written here rather than copied from a real game: what a
harvest produces is the publisher's, which is why `.gitignore` keeps it out of
the repo, and the same goes for their config files. Everything below is the
shape of the format and nothing of its content.

A game whose vocabulary has not been harvested cannot have its planner
imported at all, so those tests skip with a reason rather than fail -- on a
fresh clone that is the honest answer.
"""

import os
import tempfile
import typing
import unittest

import fake                                                  # noqa: F401
from core import adapter                                     # noqa: E402
from core import vocab                                       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def planner(game, script=None) -> typing.Any:
    """A game's writer, or None if this clone cannot import it.

    Typed `Any` on purpose. A module imported from a path is a bare
    `ModuleType` to a checker -- it cannot see `rewrite` or `blk_with` or
    any of the rest -- so the only thing a precise `ModuleType | None` buys
    is a complaint on every line of every test here, about the None that
    the class-level `skipUnless` has already answered for.

    Three jobs once: chdir into the game directory, put it on `sys.path`,
    and swallow the exit an import took when no harvest had been run here.
    The first two moved to `core.adapter.load`, which `bind` and the contract
    test want as well; the third is simply gone -- importing an adapter
    defines classes and reads nothing now, so the only thing left to catch is
    a game whose planner is not there at all.

    It also stops guessing filenames. `core.adapter.planner` reads the
    directory for the file that defines the adapter, so `games/dcs` being
    `propose.py` is not a special case anybody has to remember.
    """
    try:
        return adapter.load(game, script)
    except (FileNotFoundError, vocab.Missing):
        return None


X4 = planner('x4')
MSFS = planner('msfs')
BMS = planner('falconbms')
ED = planner('elite', 'ed-bind-wizard.py')
WT = planner('warthunder', 'wt-bind-preset.py')


@unittest.skipUnless(X4, 'x4: run ./bind x4 harvest first')
class X4Rewrite(unittest.TestCase):
    """`rewrite()` has to remove as well as add, without touching anything
    that is not ours."""

    #: Two joystick slots, a keyboard line, and an id that appears on both.
    PROFILE = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<inputmap>\n'
        '  <action id="INPUT_ACTION_OPEN_MAP" source="INPUT_SOURCE_KEYBOARD"'
        ' code="0x23"/>\n'
        '  <action id="INPUT_ACTION_OPEN_MAP"'
        ' source="INPUT_SOURCE_JOYBUTTONS_2" code="0x11"/>\n'
        '  <action id="INPUT_ACTION_STALE" source="INPUT_SOURCE_JOYBUTTONS_2"'
        ' code="0x12"/>\n'
        '  <range id="INPUT_RANGE_THROTTLE" source="INPUT_SOURCE_JOYAXES_3"'
        ' code="0x01"/>\n'
        '  <action id="INPUT_ACTION_MOUSE" source="INPUT_SOURCE_MOUSE"'
        ' code="0x02"/>\n'
        '</inputmap>\n')

    def rewrite(self, wanted):
        ours = {'INPUT_SOURCE_JOYBUTTONS_2', 'INPUT_SOURCE_JOYAXES_3'}
        return X4.rewrite(self.PROFILE, wanted, ours)

    def test_a_binding_dropped_from_the_plan_stops_answering(self):
        new, dropped = self.rewrite([])
        self.assertNotIn('INPUT_ACTION_STALE', new)
        self.assertEqual(3, len(dropped))

    def test_the_keyboard_keeps_an_id_the_joystick_also_uses(self):
        # Up to three lines share one id: INPUT_ACTION_OPEN_MAP is a keyboard
        # line AND a joystick line. Matching on the id would take the keyboard
        # binding with it -- so the plan is given that very id here, which is
        # the only arrangement in which the rule does anything.
        new, dropped = self.rewrite(
            [('action', 'INPUT_ACTION_OPEN_MAP', 'INPUT_SOURCE_JOYBUTTONS_2',
              '0x20')])
        self.assertIn('INPUT_SOURCE_KEYBOARD', new)
        self.assertEqual(2, new.count('INPUT_ACTION_OPEN_MAP'),
                         'the keyboard line and the new joystick line')
        self.assertNotIn('INPUT_SOURCE_KEYBOARD',
                         [src for _k, _i, src in dropped])

    def test_hardware_that_is_not_ours_is_never_touched(self):
        new, _dropped = self.rewrite([])
        self.assertIn('INPUT_SOURCE_MOUSE', new)

    def test_what_the_plan_wants_goes_in_before_the_closing_tag(self):
        new, _dropped = self.rewrite(
            [('action', 'INPUT_ACTION_NEW', 'INPUT_SOURCE_JOYBUTTONS_2',
              '0x20')])
        self.assertIn('INPUT_ACTION_NEW', new)
        self.assertLess(new.index('INPUT_ACTION_NEW'),
                        new.index('</inputmap>'))

    def test_the_file_is_still_the_file_it_was(self):
        new, _dropped = self.rewrite([])
        self.assertTrue(new.startswith('<?xml'))
        self.assertTrue(new.rstrip().endswith('</inputmap>'))

    def test_slot_one_carries_no_suffix(self):
        self.assertEqual('INPUT_SOURCE_JOYBUTTONS', X4.source(1))
        self.assertEqual('INPUT_SOURCE_JOYBUTTONS_2', X4.source(2))
        self.assertEqual('INPUT_SOURCE_JOYAXES_3', X4.source(3, axis=True))


@unittest.skipUnless(MSFS, 'msfs: run ./bind msfs harvest first')
class MsfsProfiles(unittest.TestCase):

    #: One joystick binding, one keyboard binding, one unbound action.
    PROFILE = (
        '<?xml version="1.0"?>\n<Device>\n'
        '  <Context ContextName="PLANE">\n'
        '    <Action ActionName="KEY_GEAR_TOGGLE">\n'
        '      <Primary>\n'
        '        <KEY Information="Joystick Button 5">22</KEY>\n'
        '      </Primary>\n    </Action>\n'
        '    <Action ActionName="KEY_KEYBOARD_ONLY">\n'
        '      <Primary>\n        <KEY Information="Key">65</KEY>\n'
        '      </Primary>\n    </Action>\n'
        '    <Action ActionName="KEY_FLAPS_UP"/>\n'
        '  </Context>\n</Device>\n')

    """Finding the real profiles, and putting a binding in one."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.was = MSFS.REMOTE
        MSFS.REMOTE = self.tmp

    def tearDown(self):
        MSFS.REMOTE = self.was

    def write(self, name, product_id, aircraft=True):
        body = (f'<?xml version="1.0"?>\n<SimBase.Document>\n'
                f'  <Device ProductID="{product_id}">\n'
                + ('    <AircraftInfo CategoryName="AIRPLANE"/>\n'
                   if aircraft else '')
                + '  </Device>\n</SimBase.Document>\n')
        with open(os.path.join(self.tmp, name), 'w', encoding='utf-8') as f:
            f.write(body)

    def devices(self):
        return {'stick': fake.device('stick', usb='3344:0001')}

    def test_a_backup_is_never_mistaken_for_a_profile(self):
        # `inputprofile_*` matched the copies write() used to leave behind, so
        # a second run bound into its own backup and backed THAT up again.
        # The copies are gone now; the ones from before that are not.
        self.write('inputprofile_0000000001', 1)
        self.write('inputprofile_0000000001.bak.20260912-221313', 1)
        self.write('inputprofile_0000000001.bak.20260912-221313'
                   '.bak.20260912-223432', 1)
        found = MSFS.find_profiles(self.devices())
        self.assertEqual(['inputprofile_0000000001'],
                         [os.path.basename(p) for p, _r, _b in found])

    def test_a_device_the_map_does_not_know_is_left_alone(self):
        self.write('inputprofile_0000000002', 999)
        self.assertEqual([], MSFS.find_profiles(self.devices()))

    def test_the_two_buckets_are_told_apart_by_the_aircraft_tag(self):
        self.write('inputprofile_0000000001', 1, aircraft=True)
        self.write('inputprofile_0000000002', 1, aircraft=False)
        buckets = sorted(b for _p, _r, b in
                         MSFS.find_profiles(self.devices()))
        self.assertEqual(['flight', 'global'], buckets)

    def test_an_unbound_action_gains_a_primary_block(self):
        text = ('\t\t<Action ActionName="KEY_GEAR_TOGGLE" Flag="1"/>\n')
        out, ok = MSFS.bind_into(text, 'KEY_GEAR_TOGGLE', 'Joystick', 'BTN_1')
        self.assertTrue(ok)
        self.assertIn('<Primary>', out)
        self.assertIn('<KEY Information="Joystick">BTN_1</KEY>', out)
        self.assertIn('Flag="1"', out, 'the attributes it had are kept')

    def test_an_already_bound_action_is_replaced_not_doubled(self):
        text = ('\t\t<Action ActionName="KEY_GEAR_TOGGLE">\n'
                '\t\t\t<Primary>\n'
                '\t\t\t\t<KEY Information="Joystick">BTN_9</KEY>\n'
                '\t\t\t</Primary>\n'
                '\t\t</Action>\n')
        out, ok = MSFS.bind_into(text, 'KEY_GEAR_TOGGLE', 'Joystick', 'BTN_1')
        self.assertTrue(ok)
        self.assertNotIn('BTN_9', out)
        self.assertEqual(1, out.count('<Primary>'))

    def test_a_binding_dropped_from_the_plan_stops_answering(self):
        """The clause no interface can state, and the one whose breakage is
        invisible: a need cut from NEEDS simply keeps working in the game.

        MSFS really did this. `bind_into` added and replaced and never
        removed, so an action the plan stopped naming kept its <Primary>
        block through every regeneration.
        """
        text = MSFS.unbind_ours(self.PROFILE, {'KEY_FLAPS_UP'})
        self.assertNotIn('Joystick Button 5', text,
                         'the dropped action is still on the stick')

    def test_what_is_not_ours_survives_the_stripping(self):
        # An MSFS profile is one device's, so every joystick binding in it is
        # one this tool wrote -- but a keyboard fallback in the same file is
        # not, and neither is an action the plan still names.
        text = MSFS.unbind_ours(self.PROFILE, {'KEY_GEAR_TOGGLE'})
        self.assertIn('Information="Key"', text)
        self.assertIn('Joystick Button 5', text)

    def test_an_action_the_profile_does_not_have_is_reported(self):
        out, ok = MSFS.bind_into('<Action ActionName="OTHER"/>\n',
                                 'KEY_MISSING', 'Joystick', 'BTN_1')
        self.assertFalse(ok)
        self.assertNotIn('KEY_MISSING', out)

    def test_the_rest_of_the_file_is_untouched(self):
        text = ('<Header>keep me</Header>\n'
                '\t\t<Action ActionName="KEY_GEAR_TOGGLE"/>\n'
                '<Footer>and me</Footer>\n')
        out, _ok = MSFS.bind_into(text, 'KEY_GEAR_TOGGLE', 'Joystick', 'BTN_1')
        self.assertIn('<Header>keep me</Header>', out)
        self.assertIn('<Footer>and me</Footer>', out)


@unittest.skipUnless(WT, 'warthunder: run ./bind wt harvest first')
class WarThunderBlock(unittest.TestCase):
    """The plan owns the whole `controls{}` block, so it removes by
    replacing it.

    Stripping only the PLANNED actions meant the plan could add and change
    but never remove: drop something from NEEDS and its old button stayed
    bound. Everything outside that block -- the keyboard half, the per-axis
    multipliers that are a slider in the game's own UI -- has to come back
    untouched, including the file's own line ending.
    """

    BLK = ('gameVersion:i=1\r\n'
           '  controls{\r\n'
           '    hotkeys{\r\n'
           '      ID_STALE{\r\n'
           '      }\r\n'
           '    }\r\n'
           '  }\r\n'
           'rudderMultiplier:r=1.0\r\n')

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), 'machine.blk')
        with open(self.path, 'w', encoding='utf-8', newline='') as f:
            f.write(self.BLK)

    def test_a_binding_dropped_from_the_plan_stops_answering(self):
        out = WT.blk_with(self.path, ['  controls{', '  }'])
        self.assertNotIn('ID_STALE', out)

    def test_everything_outside_the_block_comes_back(self):
        out = WT.blk_with(self.path, ['  controls{', '  }'])
        self.assertIn('gameVersion:i=1', out)
        self.assertIn('rudderMultiplier:r=1.0', out,
                      'a slider in the game own UI was eaten')

    def test_the_file_keeps_its_line_ending(self):
        out = WT.blk_with(self.path, ['  controls{', '  }'])
        # Every newline in the result is a CRLF, not just some of them:
        # writing LF rewrites the whole file and makes the backup useless
        # for seeing what actually changed.
        self.assertEqual(out.count('\n'), out.count('\r\n'))


class RebuiltFromScratch(unittest.TestCase):
    """Three writers remove by never carrying anything over.

    x4 and War Thunder edit a file in place, so they have to strip what is
    theirs before writing; BMS and Elite build their file from the one the
    game shipped every time, so a binding dropped from `NEEDS` is gone
    because it was never put back. Both are answers to the same clause, and
    the second is only true for as long as nobody adds an "update in place"
    shortcut -- which is what these hold.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    @unittest.skipUnless(BMS, 'falconbms: run ./bind bms harvest first')
    def test_bms_writes_only_what_the_plan_asks_for(self):
        import pathlib as pl
        cfg = pl.Path(self.tmp) / 'User' / 'Config'
        cfg.mkdir(parents=True)
        (cfg / 'BMS - Full.key').write_bytes(
            b'SimDoNothing -1 0 0 0 0 0 -1 "-- SECTION --"\r\n'
            b'SimStale 0 -1 -2 0 0x0 -1\r\n')
        # The device table is filled by FalconBms.__init__, and this calls
        # the writer without one. Naming it here is the point: the cache is
        # read when an adapter is built, not when the module is imported.
        BMS.DEVICES[:] = vocab.load(
            os.path.join(REPO, 'games', 'falconbms'),
            'bms-actions.json', key='devices')
        dst, text, _said = BMS.key_file(pl.Path(self.tmp), [])
        self.assertIn('SimDoNothing', text, 'the shipped file survives')
        self.assertEqual(1, text.count('SimStale'),
                         'a DX line in the shipped file is not duplicated')
        # The block we append carries a header comment whatever happens;
        # what an empty plan may not produce is a binding LINE.
        lines = text.splitlines()
        at = next(i for i, ln in enumerate(lines) if 'VIRPIL layout' in ln)
        self.assertEqual([], [ln for ln in lines[at:]
                              if ln.strip()
                              and not ln.lstrip().startswith('#')],
                         'an empty plan still wrote a binding')

    @unittest.skipUnless(ED, 'elite: run ./bind ed harvest first')
    def test_elite_reverts_to_the_base_preset(self):
        base = os.path.join(self.tmp, 'base.binds')
        with open(base, 'w', encoding='utf-8') as f:
            f.write('<Root PresetName="Base">'
                    '<UseBoostJuice>'
                    '<Primary Device="Keyboard" Key="Key_Tab"/>'
                    '</UseBoostJuice></Root>')
        out, text, _lines = ED.render({'_devices': {}}, base, self.tmp, 'Mine')
        self.assertTrue(out.endswith('Mine.4.2.binds'))
        self.assertNotIn('Joy_', text,
                         'an empty plan put a joystick binding in anyway')
        self.assertIn('Key_Tab', text, 'the base binding is the fallback')


@unittest.skipUnless(BMS, 'falconbms: run ./bind bms harvest first')
class BmsText(unittest.TestCase):
    """BMS config files are latin-1 and CRLF, and both matter."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def path(self, name, raw):
        import pathlib
        p = pathlib.Path(self.tmp) / name
        p.write_bytes(raw)
        return p

    def laid_down(self, path, text, nl):
        """What `core.adapter` writes for a BMS file of this shape.

        The writer no longer opens anything -- it hands back the text and the
        encoding, and the base lays it down. So the round trip that used to
        be `read_keeping` / `write_keeping` is now `read_keeping` and one
        `adapter.Text`, and it is that pairing which has to preserve the
        bytes.
        """
        body = adapter.Text(text.replace('\n', nl), encoding='latin-1')
        with open(path, 'w', encoding=body.encoding, newline='') as f:
            f.write(body.text)
        return path.read_bytes()

    def test_crlf_survives_a_round_trip(self):
        # Writing LF rewrites the whole file, which turns a one-line change
        # into a diff the size of the file and makes the backup useless for
        # telling what we actually did.
        p = self.path('x.key', b'one\r\ntwo\r\n')
        text, nl = BMS.read_keeping(p)
        self.assertEqual('\r\n', nl)
        self.assertEqual('one\ntwo\n', text)
        self.assertEqual(b'one\r\ntwo\r\n', self.laid_down(p, text, nl))

    def test_an_lf_file_stays_lf(self):
        p = self.path('x.key', b'one\ntwo\n')
        text, nl = BMS.read_keeping(p)
        self.assertEqual('\n', nl)
        self.assertEqual(b'one\ntwo\n', self.laid_down(p, text, nl))

    def test_latin1_bytes_are_not_mangled(self):
        p = self.path('x.key', b'caf\xe9\r\n')
        text, nl = BMS.read_keeping(p)
        self.assertEqual(b'caf\xe9\r\n', self.laid_down(p, text, nl))

    def test_the_games_own_stub_is_taken_out_so_the_device_appears_once(self):
        guid = '3344E843-0000-0000-0000-504944564944'
        txt = ('# R-VPC Stick WarBRD-D\n'
               '#GUID = {%s}\n'
               '# Now please add the axismappings for this controller here '
               'and remove the #\n'
               'SomethingElse = 1\n' % guid)
        out = BMS._strip_stub(txt, guid, 'R-VPC Stick WarBRD-D')
        self.assertNotIn(guid, out)
        self.assertNotIn('R-VPC Stick WarBRD-D', out)
        self.assertIn('SomethingElse = 1', out)

    def test_a_file_without_a_stub_is_returned_as_it_was(self):
        txt = 'SomethingElse = 1\nAndAnother = 2\n'
        self.assertEqual(txt.rstrip('\n'),
                         BMS._strip_stub(txt, 'NO-SUCH-GUID', 'Nothing'))


if __name__ == '__main__':
    unittest.main()

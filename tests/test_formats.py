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

import importlib.util
import os
import sys
import tempfile
import unittest

import fake                                                  # noqa: F401

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def planner(game, script='plan.py'):
    """A game's writer, or None if this clone cannot import it."""
    here = os.path.join(REPO, 'games', game)
    was = os.getcwd()
    try:
        os.chdir(here)
        if here not in sys.path:
            sys.path.insert(0, here)
        spec = importlib.util.spec_from_file_location(
            f'{game}_{script}', os.path.join(here, script))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except (SystemExit, ImportError, FileNotFoundError):
        return None
    finally:
        os.chdir(was)


X4 = planner('x4')
MSFS = planner('msfs')
BMS = planner('falconbms')


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

    def test_crlf_survives_a_round_trip(self):
        # Writing LF rewrites the whole file, which turns a one-line change
        # into a diff the size of the file and makes the backup useless for
        # telling what we actually did.
        p = self.path('x.key', b'one\r\ntwo\r\n')
        text, nl = BMS.read_keeping(p)
        self.assertEqual('\r\n', nl)
        self.assertEqual('one\ntwo\n', text)
        BMS.write_keeping(p, text, nl)
        self.assertEqual(b'one\r\ntwo\r\n', p.read_bytes())

    def test_an_lf_file_stays_lf(self):
        p = self.path('x.key', b'one\ntwo\n')
        text, nl = BMS.read_keeping(p)
        self.assertEqual('\n', nl)
        BMS.write_keeping(p, text, nl)
        self.assertEqual(b'one\ntwo\n', p.read_bytes())

    def test_latin1_bytes_are_not_mangled(self):
        p = self.path('x.key', b'caf\xe9\r\n')
        text, nl = BMS.read_keeping(p)
        BMS.write_keeping(p, text, nl)
        self.assertEqual(b'caf\xe9\r\n', p.read_bytes())

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

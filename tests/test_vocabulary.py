"""What a harvest counts as the game's whole vocabulary.

Four of the six read a source that ENUMERATES: Falcon BMS's key file, War
Thunder's unpacked archives, each DCS module's `default.lua`, and for MSFS
the profile the sim writes for you.

Two read a source that BINDS, and such a source shows what somebody chose.
MSFS's shipped defaults mention 699 actions, and a profile the sim
generates carries all 1710. Elite's thirty presets miss
`NightVisionToggle`, which is a real ship function that a written preset
accepts and the game answers.

The readers are pure functions over bytes and parsed XML, and that is the
point: a test that needs the game installed is not a test.

Whether the second source EXISTS on a given machine cannot be tested here.
That is the one thing a harvest finds out at run time.
"""

import json
import os
import sys
import tempfile
import typing
import unittest
import xml.etree.ElementTree as ET

from core import adapter
from core import vocab

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def harvest_of(game) -> typing.Any:
    try:
        return adapter.load(game, 'harvest.py')
    except (FileNotFoundError, vocab.Missing, SystemExit):
        return None


X4 = harvest_of('x4')
ED = harvest_of('elite')


@unittest.skipUnless(X4, 'the x4 harvest will not import here')
class X4Vocabulary(unittest.TestCase):
    """Where X4's LIST of ids comes from.

    X4's ids describe themselves, so that is the only question. Three of
    its four `inputmap*.xml` are the player's own saved profiles, so what
    they bind is a record of past choices. It is not a record of what the
    game accepts.
    """

    def test_ids_are_picked_out_of_a_blob_of_noise(self):
        blob = (b'\x00\x07garbage\x00INPUT_ACTION_DEPLOY_SATELLITE\x00'
                b'\xff\xfeINPUT_STATE_FP_USE\x00'
                b'nonsenseINPUT_RANGE_THROTTLE\x00')
        self.assertEqual({'INPUT_ACTION_DEPLOY_SATELLITE',
                          'INPUT_STATE_FP_USE',
                          'INPUT_RANGE_THROTTLE'}, X4.ids_in(blob))

    def test_a_word_that_merely_starts_the_same_is_not_an_id(self):
        self.assertEqual(set(), X4.ids_in(b'INPUT_SOURCE_JOYBUTTONS'))

    def test_the_kind_is_read_off_the_prefix_not_guessed(self):
        # `readable()` strips exactly these three, so the prefix is a
        # fact about the id and not an inference from it.
        got = X4.vocabulary({}, extra={'INPUT_ACTION_A', 'INPUT_STATE_B',
                                       'INPUT_RANGE_C'})
        self.assertEqual({'action': ['INPUT_ACTION_A'],
                          'state': ['INPUT_STATE_B'],
                          'range': ['INPUT_RANGE_C']}, got)

    def test_asking_for_nothing_extra_does_not_read_the_install(self):
        # `None` means "go and look" and `()` means "none". The two
        # collapsed, a caller that asked for nothing gets everything. The
        # test that would catch that compares against a handful of
        # synthetic ids, and it would then compare against four hundred
        # and fifty real ones.
        self.assertEqual({}, X4.vocabulary({}, extra=()))

    def test_what_a_profile_binds_survives_the_second_source(self):
        # The binary is not a superset. Nine ids the profiles carry are
        # absent from it: the mouse, VR and cutscene ones. So this is a
        # union and not a replacement.
        profs = {'inputmap.xml': {'rows': [
            ('action', 'INPUT_ACTION_MOUSEDBLCLICK', 'KEY', '1')]}}
        got = X4.vocabulary(profs, extra={'INPUT_ACTION_DEPLOY_MINE'})
        self.assertEqual(['INPUT_ACTION_DEPLOY_MINE',
                          'INPUT_ACTION_MOUSEDBLCLICK'], got['action'])


@unittest.skipUnless(ED, 'the elite harvest will not import here')
class EliteVocabulary(unittest.TestCase):
    """Where Elite's vocabulary comes from.

    Elite's shipped presets are thirty layouts, and their union is still
    not the vocabulary. The file the game writes for you carries every
    function it knows, bound or not.
    """

    def root(self, xml):
        return ET.fromstring(xml)

    def test_a_function_with_a_primary_block_is_a_button(self):
        got = ED.functions_in(self.root(
            '<Root><ToggleGear><Primary Device="Keyboard" Key="G"/>'
            '</ToggleGear></Root>'))
        self.assertEqual({'button': {'ToggleGear'}, 'axis': set()}, got)

    def test_a_function_with_a_binding_block_is_an_axis(self):
        got = ED.functions_in(self.root(
            '<Root><YawAxis><Binding Device="Joy" Key="Y"/></YawAxis>'
            '</Root>'))
        self.assertEqual({'button': set(), 'axis': {'YawAxis'}}, got)

    def test_a_setting_that_is_no_binding_is_left_out(self):
        # `MouseSensitivity` and `YawToRollMode` are numbers in the same
        # file. Elite's own written file holds 92 of them.
        got = ED.functions_in(self.root(
            '<Root><MouseSensitivity Value="1.0"/></Root>'))
        self.assertEqual({'button': set(), 'axis': set()}, got)

    def test_an_unbound_function_still_counts(self):
        # This is the reason for reading the written file. The game lists
        # what it accepts, with the binding left empty.
        got = ED.functions_in(self.root(
            '<Root><NightVisionToggle><Primary Device="{NoDevice}" Key=""/>'
            '</NightVisionToggle></Root>'))
        self.assertEqual({'NightVisionToggle'}, got['button'])

    def test_a_function_seen_as_both_is_an_axis(self):
        got = ED.merge([{'button': {'X'}, 'axis': set()},
                        {'button': set(), 'axis': {'X'}}])
        self.assertEqual({'axis': ['X'], 'button': []}, got)


EDPLAN = None
try:
    EDPLAN = adapter.load('elite')
except (FileNotFoundError, vocab.Missing, SystemExit):
    pass


@unittest.skipUnless(EDPLAN, 'the elite planner will not import here')
class EliteVouching(unittest.TestCase):
    """The workaround the second source retires.

    `vouched()` added every function the results file held. The thirty
    presets cannot see a function nobody bound, and the plan needed
    `NightVisionToggle`.

    THIS tool writes that file. So a function we misspelled went in, came
    back as vocabulary, and then validated against itself. The harvest
    avoids that loop by reading only the file the GAME keeps.
    """

    def harvest(self):
        """Elite's harvest module, loaded by path like the planner's."""
        return adapter.from_file(
            'edharvest_under_test',
            os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), 'games', 'elite', 'harvest.py'))

    def test_the_preset_this_tool_writes_is_not_read_back(self):
        """Only the file the GAME keeps.

        `WRITTEN` is the rule. It matches the name Elite writes and
        nothing else. A reader that takes every function a file of ours
        holds lets a function we misspelled in, and that function then
        validates against itself.

        Both files are laid down here, so this cannot pass by there being
        nothing to read. One is named the way the game names its own. The
        other is named the way this program names the preset it writes.
        """
        mod = self.harvest()
        with tempfile.TemporaryDirectory() as d:
            for name, function in (
                    ('Custom.4.2.binds', 'ToggleSomethingTheGameKeeps'),
                    ('Izowiuz-PLAN.4.2.binds', 'ToggleNonsenseWeWrote')):
                with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
                    f.write(f'<Root><{function}><Primary Device="Keyboard" '
                            f'Key="Key_X" /></{function}></Root>')
            seen = [mod.functions_in(r) for r in mod.written(d)]
            self.assertTrue(seen, 'nothing was read, so this proves nothing')
            names = set().union(*(one['button'] for one in seen))
        self.assertIn('ToggleSomethingTheGameKeeps', names)
        self.assertNotIn('ToggleNonsenseWeWrote', names,
                         'a preset this tool wrote became vocabulary')

    def test_the_function_it_was_there_for_comes_from_the_game_now(self):
        # `NightVisionToggle` is why `vouched()` existed. Elite's own
        # bindings file carries it, so that workaround has nothing to
        # do.
        made = adapter.adapters('elite')[0]()
        self.assertIn('NightVisionToggle', {a.id for a in made.catalogue()})


if __name__ == '__main__':
    unittest.main()

"""What a harvest counts as the game's whole vocabulary.

Four of the six read a source that ENUMERATES -- BMS's key file, War
Thunder's unpacked archives, each DCS module's `default.lua`, and for MSFS
the profile the sim writes for you. Two read a source that merely BINDS,
and so can only ever see what somebody already chose:

    MSFS, in its own harvest: "The shipped defaults only mention what
    somebody chose to bind, which is 699 of them -- a profile the sim
    generates carries all 1710."

Elite names its own blind spot in the same breath: `NightVisionToggle` is
"a real ship function, accepted in a written preset and working in game,
and it appears in none of the thirty."

The readers are pure functions over bytes and parsed XML, which is the
whole point -- a test that needs the game installed is not a test. What
cannot be tested here is whether the second source EXISTS on a given
machine, and that is the one thing a harvest is allowed to find out at
run time.
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
    """X4's ids are self-describing, so the only question is where the
    LIST of them comes from. Three of its four `inputmap*.xml` are the
    player's own saved profiles, so what they bind is a record of past
    choices, not of what the game accepts."""

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
        # `readable()` already strips exactly these three, so the prefix is
        # a fact about the id rather than an inference from it.
        got = X4.vocabulary({}, extra={'INPUT_ACTION_A', 'INPUT_STATE_B',
                                       'INPUT_RANGE_C'})
        self.assertEqual({'action': ['INPUT_ACTION_A'],
                          'state': ['INPUT_STATE_B'],
                          'range': ['INPUT_RANGE_C']}, got)

    def test_asking_for_nothing_extra_does_not_read_the_install(self):
        # `None` means "go and look", `()` means "none". Collapsing the two
        # makes a caller that asked for nothing get everything -- and the
        # test that would otherwise catch it is the one comparing against a
        # handful of synthetic ids, which would then be comparing against
        # four hundred and fifty real ones.
        self.assertEqual({}, X4.vocabulary({}, extra=()))

    def test_what_a_profile_binds_survives_the_second_source(self):
        # The binary is not a superset: nine ids the profiles carry are
        # absent from it -- the mouse, VR and cutscene ones. A union, not
        # a replacement.
        profs = {'inputmap.xml': {'rows': [
            ('action', 'INPUT_ACTION_MOUSEDBLCLICK', 'KEY', '1')]}}
        got = X4.vocabulary(profs, extra={'INPUT_ACTION_DEPLOY_MINE'})
        self.assertEqual(['INPUT_ACTION_DEPLOY_MINE',
                          'INPUT_ACTION_MOUSEDBLCLICK'], got['action'])


@unittest.skipUnless(ED, 'the elite harvest will not import here')
class EliteVocabulary(unittest.TestCase):
    """Elite's shipped presets are thirty layouts, and the union of them is
    still not the vocabulary. The file the game writes for you carries every
    function it knows, bound or not."""

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
        # This is the whole reason for reading the written file: the game
        # lists what it accepts, with the binding left empty.
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

    `vouched()` added every function the results file held, because the
    thirty presets cannot see a function nobody bound and the plan needed
    `NightVisionToggle` anyway. But that file is written by THIS tool, so a
    function we misspelled went in, came back as vocabulary, and then
    validated against itself -- the same loop the harvest avoids by reading
    only the file the GAME keeps.
    """

    def catalogue_with(self, saved):
        made = adapter.adapters('elite')[0]()
        # The module the ADAPTER came from, which `adapter.load` does not
        # hand back -- it imports its own copy. Patching that one instead
        # left this test passing against a planner it had not touched.
        # `Any` for the same reason `test_formats.planner` gives: a module
        # imported from a path is a bare ModuleType to a checker, which
        # knows neither `HERE` nor `RESULTS`.
        mod: typing.Any = sys.modules[type(made).__module__]
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, mod.RESULTS), 'w',
                      encoding='utf-8') as f:
                json.dump(saved, f)
            was, mod.HERE = mod.HERE, d
            try:
                self.assertTrue(
                    os.path.exists(os.path.join(mod.HERE, mod.RESULTS)),
                    'the results file is not where the planner looks, so '
                    'this test would pass without proving anything')
                return {a.id for a in made.catalogue()}
            finally:
                mod.HERE = was

    def test_a_function_only_this_tool_wrote_is_not_vocabulary(self):
        ids = self.catalogue_with(
            {'ToggleNonsenseThatIsNoFunction': {'role': 'stick'}})
        # Membership, not assertNotIn: the catalogue is 440 rows and a
        # failure should name the one that is wrong, not print all of them.
        self.assertFalse('ToggleNonsenseThatIsNoFunction' in ids,
                         'a function only this tool wrote became vocabulary')

    def test_the_function_it_was_there_for_comes_from_the_game_now(self):
        # `NightVisionToggle` is why `vouched()` existed. Elite's own
        # bindings file carries it, so the workaround has nothing left to do.
        self.assertIn('NightVisionToggle', self.catalogue_with({}))


if __name__ == '__main__':
    unittest.main()

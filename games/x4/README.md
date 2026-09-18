# X4 Foundations

## Where it lives

    ~/.local/share/Steam/steamapps/compatdata/392160/pfx/
      drive_c/users/steamuser/Documents/Egosoft/X4/<player id>/

    inputmap.xml     the working copy the game reads, and writes menu edits to
    inputmap_1.xml   "Izowiuz"
    inputmap_2.xml   "Izowiuz K&M"
    inputmap_3.xml   "Izowiuz VIrpil"  — what plan.py writes

Named profiles carry `name=` in their header; the working copy does not.

    X4_DIR       the profile directory, instead of the Proton lookup
    X4_PROFILE   which file plan.py writes
    X4_SLOTS     "stick=2,throttle=3", instead of inferring the slots

## How to run it

In: the four `inputmap*.xml` files. Out: printed, or `inputmap_3.xml`. No
cache.

    ./harvest.py             profiles, vocabulary, device slots, button codes
    ./harvest.py --vocab     everything X4 accepts a binding for
    ./harvest.py --grep map  vocabulary entries matching a word
    ./harvest.py --json      write the cache the other games keep

    ./plan.py                the layout
    ./plan.py --why          and the evidence for each choice
    ./plan.py --free         what stays unbound
    ./plan.py --sheet --html the kneeboard
    ./plan.py --tui          walk the layout, keep what you want, write that
    ./plan.py --write        all of it, into the game (close X4 first)

    --profile FILE     write somewhere other than inputmap_3.xml
    --backup-dir DIR   where the replaced profile is copied first
                       (default <repo>/backups/x4/<stamp>/; SIM_BIND_BACKUPS
                       does the same)

Every id in `NEEDS` is checked against the harvested vocabulary before
anything runs; an id the game does not know is an error, not a binding that
silently does nothing.

## The format

Plain XML, one line per binding, three element types:

    <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
            source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>

    <action>  fires once on press     229 in the vocabulary
    <state>   true while held         101
    <range>   an axis                  29

    source    the device, by slot
    code      local to that device — no global numbering to undo
    toggle    "1" on a latching <state>, between source and code
    sgn       "±1" after code, a VR axis driving a button
    <config>  per-axis invert flags, at the top of the file

Axis codes are DirectInput names (`INPUT_JOYAXIS_RX`). Ids are
self-describing, so there is no language archive to crack: `readable()` turns
`INPUT_ACTION_TOGGLE_TRAVEL_MODE` into `Toggle travel mode`.

## Measured

Button codes are the index plus one, positions 1..11 named:

    js 0..10   A B X Y LEFT_SHOULDER RIGHT_SHOULDER BACK START
               LEFT_THUMB RIGHT_THUMB BIGBUTTON
    js 11+     INPUT_XBUTTON_<index + 1>

2026-09-17, by binding isolated buttons in the game's own menu:

    js  6  ->  INPUT_XBUTTON_BACK          the name order
    js  9  ->  INPUT_XBUTTON_RIGHT_THUMB   confirmed it
    js 12  ->  INPUT_XBUTTON_13
    js 30  ->  INPUT_XBUTTON_31

A bare number is not accepted where a name belongs: `INPUT_XBUTTON_7` in
place of `INPUT_XBUTTON_BACK` leaves the binding blank in the game's own
menu. The name table is required.

The trigger cannot be measured this way. It is cumulative, and X4 closes its
binding dialog on the first input it catches.

## Still a guess

The eleven names, on two measured points, the absence of `_1`..`_11` in any
profile file, and a name count of exactly eleven once the four `DPAD_*` POV
directions are set aside. Nothing load-bearing. The derivation is in `CODES`
in `harvest.py`.

## Gotchas

**Device slots are not stable.** `JOYBUTTONS` / `_2` / `_3` follow
enumeration order and no device list exists in the config. `slots()` infers
them from a profile's own bindings, per profile: a slot number means nothing
outside the file that wrote it.

**X4 writes the working copy, not your named profile.** Menu edits land in
`inputmap.xml`. Check which file changed before concluding anything.

**Attribute order is not fixed, and there are more than three.** Match the
element, then the attributes.

**One id, several lines; the key is `(id, source)`.** Up to three lines share
an id, across keyboard and two joystick slots. The writer removes by `source`
and inserts fresh.

**The plan owns our slots completely.** Every line whose `source` is one of
them is removed before ours go in, which is how a binding dropped from `NEEDS`
stops answering. Keyboard, mouse, compass-menu and VR lines are never touched
— 311 keyboard lines in, 311 out.

**A third device is in the mix.** The Steam Controller puck enumerates as a
pad and holds slot 1 in `inputmap_3.xml`, so the VIRPIL pair are slots 2 and
3. Its 25 bindings are left alone.

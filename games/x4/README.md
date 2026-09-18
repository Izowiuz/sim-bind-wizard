# X4 Foundations

## Where it lives

Inside the Proton prefix, under the Steam player id:

    ~/.local/share/Steam/steamapps/compatdata/392160/pfx/
      drive_c/users/steamuser/Documents/Egosoft/X4/<player id>/
        inputmap.xml      the working copy the game actually reads
        inputmap_1.xml    "Izowiuz"
        inputmap_2.xml    "Izowiuz K&M"
        inputmap_3.xml    "Izowiuz VIrpil"

`X4_DIR` overrides the lookup. The named profiles carry `name=` in their header;
the working copy does not.

## How to run it

In: the four `inputmap*.xml` files. Out: printed only — X4 needs no cache,
because reparsing four 46 KB XML files costs nothing, unlike War Thunder's
zstd archives or BMS's 100 KB key file.

    ./harvest.py             profiles, vocabulary, device slots, button codes
    ./harvest.py --vocab     everything X4 accepts a binding for
    ./harvest.py --grep map  vocabulary entries matching a word
    ./harvest.py --json      cache it, the way the other games do

    ./plan.py                the layout
    ./plan.py --why          and the evidence for each choice
    ./plan.py --free         what stays unbound
    ./plan.py --sheet --html the kneeboard
    ./plan.py --write        into the game (close X4 first)

`plan.py` writes `inputmap_3.xml`; `--profile` and `X4_PROFILE` point it
elsewhere, `X4_SLOTS="stick=2,throttle=3"` overrides slot detection. The
profile is copied into `<repo>/backups/x4/<stamp>/` before it is replaced;
`--backup-dir` or `SIM_BIND_BACKUPS` puts that elsewhere.

Every id in `NEEDS` is checked against the harvested vocabulary before
anything runs, so a typo or an id a patch removed is an error rather than a
binding that silently does nothing.

## The format

Plain XML, one line per binding, three element types:

    <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
            source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>

    <action>  fires once on press     229 in the vocabulary
    <state>   true while held          99
    <range>   an axis                  29

`source` names the device by slot, `code` is local to that device — no global
numbering to undo, unlike War Thunder and BMS. Axis codes are DirectInput
names (`INPUT_JOYAXIS_RX`). `<config>` at the top of the file carries per-axis
invert flags, which BMS could not express at all.

Ids are self-describing, so there is no language archive to crack. `readable()`
turns `INPUT_ACTION_TOGGLE_TRAVEL_MODE` into `Toggle travel mode`.

## Measured

**Button codes are the index plus one, with the first eleven positions named.**

    js  6  ->  INPUT_XBUTTON_BACK          measured
    js  9  ->  INPUT_XBUTTON_RIGHT_THUMB   measured, confirmed the name order
    js 12  ->  INPUT_XBUTTON_13            measured
    js 30  ->  INPUT_XBUTTON_31            measured

    js 0..10   A B X Y LEFT_SHOULDER RIGHT_SHOULDER BACK START
               LEFT_THUMB RIGHT_THUMB BIGBUTTON
    js 11+     INPUT_XBUTTON_<index + 1>

**A bare number is not accepted where a name belongs.** Writing
`INPUT_XBUTTON_7` in place of `INPUT_XBUTTON_BACK` leaves the binding blank in
the game's own menu. The name table is required, not a convenience.

**The trigger cannot be measured this way.** It is cumulative, so reaching a
deeper detent means passing through the shallower ones, and X4 closes its
binding dialog on the first input it catches.

## Still a guess

Nothing load-bearing. The eleven names rest on two measured points (js 6 and
js 9), the absence of `_1`..`_11` in any profile file, and a name count of
exactly eleven once the four `DPAD_*` POV directions are set aside.

## Gotchas

**Device slots are not stable.** `JOYBUTTONS` / `_2` / `_3` follow enumeration
order, and there is no device list anywhere in the config to pin them. The
stick was slot 2 in an older profile and slot 1 when we measured. `slots()`
infers them from a profile's own bindings — a slot whose codes are all Xbox
names and which offers RZ is a gamepad; the slot with THROTTLE on an axis is
the throttle; what is left is the stick. **Infer per profile, never across them**: a slot number only means something
inside the file that wrote it.

**X4 writes the working copy, not your named profile.** Binding something in
the game's menu lands in `inputmap.xml`. Check which file changed before
concluding anything — and it is why `plan.py` writes a *named* profile, which
the menu leaves alone.

**Attribute order is not fixed and there are more than three.** `toggle="1"`
sits between `source` and `code` on a latching `<state>`, and `sgn="±1"` after
`code` where a VR axis drives a button. Matching the three positionally lost
3–18 rows a file and two ids outright — `INPUT_STATE_MATCH_SPEED` and
`INPUT_STATE_MAP_PAN_TO_ROTATE` were missing from the vocabulary although
match speed is bound on the throttle. Match the element, then the attributes.

**One id, several lines; the key is `(id, source)`.** Up to three lines share
an id — `INPUT_ACTION_OPEN_MAP` is a keyboard line *and* a joystick line, and
`INPUT_STATE_FIRE_PRIMARY_WEAPON` is two joystick lines on different slots.
Replacing an element by id alone would take the keyboard binding with it, so
the writer removes by `source` and inserts fresh.

**The plan owns our hardware completely.** Every line whose `source` is one of
our slots is removed before ours go in, which is how a binding dropped from
`NEEDS` stops answering. Keyboard, mouse, compass-menu and VR lines are never
touched — 311 keyboard lines in, 311 out.

**A third device is in the mix.** The Steam Controller puck enumerates as a pad
and holds slot 1 in `inputmap_3.xml`, which is why the VIRPIL pair are slots 2
and 3. Its 25 bindings are left alone.

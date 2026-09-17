# X4 Foundations

Every game folder in this repo uses these same headings, so you can open any of
them and know where to look without reading the whole thing.

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

    ./harvest.py            profiles, vocabulary, device slots, button codes
    ./harvest.py --vocab    everything X4 accepts a binding for
    ./harvest.py --grep map  vocabulary entries matching a word

There is no `plan.py` yet. The vocabulary, the slots and the button codes are
settled, which is everything a planner needs; the need list is the next job.

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

**A bare number is not accepted where a name belongs.** `OPEN_MAP` was moved
from `BACK` to `_7`; X4 parsed the file, failed to recognise it, and left the
binding blank in its own menu. So the name table is required, not a convenience.

**The trigger cannot be used for this kind of measurement.** It is cumulative,
so reaching a deeper detent means passing through the shallower ones, and X4
closes its binding dialog on the first input it catches.

## Still a guess

Nothing load-bearing. The eleven names rest on two measured points (js 6 and
js 9) plus the absence of `_1`..`_11` anywhere in four profile files and a name
count that matches exactly; a third point would be belt and braces.

## Gotchas

**Device slots are not stable.** `JOYBUTTONS` / `_2` / `_3` follow enumeration
order, and there is no device list anywhere in the config to pin them. The
stick was slot 2 in an older profile and slot 1 when we measured. `slots()`
infers them from a profile's own bindings — a slot whose codes are all Xbox
names and which offers RZ is a gamepad; the slot with THROTTLE on an axis is
the throttle; what is left is the stick. **Infer per profile, never across
them**: a slot number only means something inside the file that wrote it, and
reading all four together called two different slots the throttle.

**X4 writes the working copy, not your named profile.** Binding something in
the game's menu lands in `inputmap.xml`. Check which file changed before
concluding anything.

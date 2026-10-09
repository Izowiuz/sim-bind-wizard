# X4 Foundations

What is peculiar to this game.

## The id says what kind of binding it is

X4 keeps its bindings in plain XML. One binding is one line.

    <action id="INPUT_ACTION_TOGGLE_TRAVEL_MODE"
            source="INPUT_SOURCE_JOYBUTTONS_3" code="INPUT_XBUTTON_16"/>

The element name says the kind. The id carries the same fact in its
prefix.

| element | what it does | ids |
|---|---|---|
| `<action>` | fires once on press | 229 |
| `<state>` | true while held | 101 |
| `<range>` | an axis | 29 |

So nothing has to carry the kind beside the id.

Attributes are not always in the same order and not always only three.
`toggle="1"` sits between `source` and `code` on a latching `<state>`.
`sgn` sits after `code` on a VR axis used as a button. The reader matches
the element first and the attributes second.

## The context is in the id too

X4 puts no mode flag on a binding. A `MAP_` id answers in the map only. An
`FP_` id answers on foot only. One control therefore carries three
meanings. The harvest writes the context onto the action. The kneeboard
reads it as a column.

## A device is a slot number

`source="INPUT_SOURCE_JOYBUTTONS_3"` names the device by its position in
enumeration order. `code` is local to that device.

X4 keeps no device list anywhere in its configuration. The slot number
therefore means nothing outside the profile that wrote it.

`slots()` reads the slot back off an existing profile. The slot that
carries THROTTLE on RX is the throttle. The slot whose codes are all Xbox
names is a gamepad.

    X4_SLOTS="stick=2,throttle=3"       say it outright

## Button codes: eleven names, then numbers

Measured on 2026-09-17. Three isolated buttons on the WarBRD, bound in
X4's own menu, read back out of the file:

    js 12  ->  INPUT_XBUTTON_13
    js 30  ->  INPUT_XBUTTON_31
    js  6  ->  INPUT_XBUTTON_BACK

The code is the index plus one. Two points agree. The names share that
same numbering. `BACK` sits where `_7` would be.

Positions 1 to 11 come out as an Xbox name. Position 12 and upward come
out as a bare number.

A bare number does not work where a name belongs. Measured: `OPEN_MAP`
moved from `BACK` to `_7`. X4 parsed the file, failed to recognise the
code, and left the binding blank in its own menu. So the name table is
necessary.

The eleven names in order:

    A  B  X  Y  LEFT_SHOULDER  RIGHT_SHOULDER  BACK  START
    LEFT_THUMB  RIGHT_THUMB  BIGBUTTON

Confirmed: js 9 came back `RIGHT_THUMB`, which is where this order puts
it.

The trigger could not be used for any of this. The trigger is cumulative,
so reaching the second detent means passing through the first. X4 closes
its binding dialog on the first input it catches.

## Two sources for the vocabulary

The four `inputmap*.xml` files are layouts. Three of the four are the
player's own saved profiles. They say what somebody once chose, not what
the game accepts.

The executable carries the names. The harvest reads both files and
executable, because neither one is whole.

## Gotchas

X4 rewrites `inputmap.xml` when it stops. Close the game before a write. A
named profile is the only place a generated layout survives an edit in
X4's own menu.

The profile must exist first. X4 creates a numbered profile when you save
one in its own menu. A write to a name X4 has never written is refused.

One id appears on more than one line. `INPUT_ACTION_OPEN_MAP` is a
keyboard line and a joystick line. The writer therefore removes lines by
`source`. A writer that matched the id would take the keyboard binding
away too.

`plan.py` reparses the XML when the cache is missing. `--json` is
optional here and required for every other game in this repository.

# Elite Dangerous

What is peculiar to this game.

## The base preset is the template

A `.binds` file carries every function as an element. The binding inside
it can be empty. The writer therefore reads a base preset and edits it. It
does not build a file from nothing.

`KeyboardMouseOnly.binds` is the vocabulary. It holds 311 buttons, 58
axes, and 68 settings that are not bindings at all. `MouseSensitivity`,
the deadzones and `YawToRollMode` are numbers in the same file.

A function with no child element is a setting, not a binding. The reader
leaves it out.

A function the base preset does not carry is added. That is how the
functions only the game's own bindings file enumerates get a binding.

## The keyboard binding moves to Secondary

The writer puts our control on `Primary`. The base preset's keyboard
binding moves to `Secondary`. The function then still answers at the
keyboard.

## The harvest reads the game's file, not ours

Elite keeps its own bindings file in the Proton prefix. That file lists
every function Elite knows, with the binding left empty where there is
none.

The harvest reads that file only. It never reads every `.binds` in the
folder, because this program writes its own preset into the same folder. A
typo of ours would otherwise enter the vocabulary and then validate
itself.

The shipped presets are thirty layouts. Frontier wrote them for a
Warthog. They say what Frontier chose, not what Elite accepts.

## Pitch reads backwards

Pull the stick towards you and the value goes negative. Negative is nose
up. `Inverted` therefore means the opposite of what it means elsewhere for
two functions:

    PitchAxisRaw
    BuggyPitchAxis

What you set on the review screen is combined with this fact, not written
raw.

This is a fact about the game. It was found by flying it.

## The SRV context is in the name

Elite scopes a binding by which function it is. It uses no mode flag. One
control therefore carries the ship's meaning and the SRV's without a
clash.

Elite spells an SRV function `X_Buggy` or `BuggyX`. The reader checks the
suffix and the prefix. The suffix alone is not enough: `PitchAxisRaw`
looks shared until you see that its twin is `BuggyPitchAxis`.

Four SRV functions follow neither rule. No rule over the name will find
them:

    HeadlightsBuggyButton      the twin of ShipSpotLightToggle
    ToggleDriveAssist          the twin of ToggleFlightAssist
    SteeringAxis               the SRV's steering
    DriveSpeedAxis             the SRV's throttle

They are written out, because somebody who knows the game found them. That
is the only way to find them.

## Deadzones

A ministick drifts more than a flight axis. The writer sets a deadzone for
the lateral and vertical thrust axes. It leaves a deadzone you tuned in
the game alone.

## Gotchas

Elite rewrites its bindings when it exits. Close the game before a write.

The writer unbinds our devices from any function the layout dropped. A
writer that only set `Primary` would leave the old binding in place.

`4.2` in the file name is the schema version. It is not the game version.

A write does not select the preset. Choose it once in the game's own
menu.

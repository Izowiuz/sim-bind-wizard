# MSFS 2024

What is peculiar to this game.

## A profile belongs to one device

MSFS keeps its bindings in Steam Cloud, in
`userdata/*/2537590/remote/inputprofile_<number>`. One profile belongs to
one device. The writer matches a profile to a device by its USB product
id.

Every joystick binding in a profile is one this program wrote. The writer
therefore owns the file completely.

## Two profiles per device

| the file carries | it holds |
|---|---|
| `<AircraftInfo CategoryName="..."/>` | the flying actions |
| no `AircraftInfo` | cameras, radio, and whatever applies however you fly |

The label says aeroplane. The file holds the helicopter actions too.

The two context sets do not overlap, so every action belongs to exactly
one of the two files.

## The context is a property of the binding

Which file somebody put a binding in is not a fact about the action. It
rides on the binding. No rule over an action name will find it.

## The vocabulary comes from the shipped profiles

MSFS 2024 accepts about 1700 actions. It ships 551 default profiles
covering 101 devices, split by aircraft category. Between them they name
the vocabulary.

`msfs-actions.json` is derived from Asobo's own files. It does not belong
in version control.

## One-based names, zero-based codes

MSFS shows a button number that counts from one. It stores a code that
counts from zero. So the name is the index plus one and the code is the
index.

An axis carries a code of its own. The codes step by 16. The owner's own
profiles confirm X, Y, Z, Rx and Slider. The rest follow the same step and
want checking in the sim.

## The writer edits the text

An unbound action is a self-closing element. A bound one carries a
`<Primary>` block.

The writer edits the text. It does not reserialise the XML. That keeps the
170 KB of formatting MSFS wrote exactly as it was.

The writer also takes our joystick out of every action the plan no longer
names. Such an action goes back to self-closing, which is what the game
ships.

## Gotchas

Close Steam before a write. Steam syncs these files from the cloud and
puts the old ones back over anything written here.

The profile filter takes digits only. `inputprofile_*` also matched the
`.bak.<stamp>` copies an older writer left beside them, so a second run
bound into its own backups and backed those up again. Backups live outside
the folder now. The old copies still sit there, so the filter stays.

An action the profile does not contain is skipped. The run reports it.

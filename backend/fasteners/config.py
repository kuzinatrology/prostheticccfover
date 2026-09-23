"""Every number the fasteners are made of, and why it is that number.

The previous clamps were printed and broke.  The sizes below are the answer to
that, so each one says what it replaces.

Millimetres and degrees.
"""

from __future__ import annotations

import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
HARDWARE_NPZ = ASSETS / "hardware.npz"
HARDWARE_JSON = ASSETS / "hardware.json"

OVERLAP = 0.5
"""How far a part added to the shell reaches into it, mm.

Never zero.  A land or a boss whose outer face sits exactly on the cover's own
outer face gives the boolean two coincident surfaces to reconcile, and what
comes back is a body in five pieces rather than one.  Half a millimetre of
overlap is below the wall's own tolerance and leaves nothing to reconcile.
"""

# --- the seam ---------------------------------------------------------------

SEAM_CURVE = 18.0
"""How far the seam wanders fore and aft over the cover's height, mm.

The cut is not a plane.  A plane lets the halves slide up and down against each
other and nothing stops them: magnets hold across the cut and a tongue slides
in its own groove.  A curve cannot slide against itself, so this is what locks
the two halves together along the seam."""

SEAM_SHAPE = ((0.0, -1.0), (0.45, 0.6), (1.0, 0.0))
"""The curve, as (share of the height, share of SEAM_CURVE).

Most posterior at the bottom rim, forward through the calf, back to the centre
line at the top -- an S.  Neutral at the top on purpose: that is where the
cover goes on over the knee module, and a seam that leaned there would have to
be threaded on at an angle."""

MAX_SEAM_SLOPE = 0.45
"""Steepest the seam may lean, as dy/dz.

Past this the cut starts to overhang and the halves no longer come apart by
pulling them apart.  Well beyond anything SEAM_SHAPE asks for; it is here so a
slider cannot walk into it."""

LAND_DEPTH = 9.0
"""The most the land may reach inward past the inner face of the wall.

A ceiling, not a target.  How deep it actually goes follows from what lies in
it -- a magnet and a strut either side, or the tongue and the same -- less
whatever the wall already gives.  It was a fixed nine for a while, which is
right for a 3 mm wall holding a 6 mm magnet and half again too much for a 5 mm
wall holding a 4 mm one: on a small cover that land stands up inside as a pair
of columns down the seam."""

LAND_HALF_WIDTH = 6.5
"""Half the land's thickness across the seam plane.

A magnet pocket is sunk into the land's mating face along the seam normal, so
the land has to be deeper than the pocket: pocket depth (magnet + gap) plus
MAGNET_FLOOR behind it, and this is that for a 6 x 3 magnet with room over."""

STEP_DEPTH = 2.0
STEP_WIDTH = 3.5
"""A tongue on the front land, a groove in the back one, running the length of
the seam.

The magnets pull the halves together and nothing stops them sliding across each
other; a magnet loaded sideways lets go at a fraction of the force it holds at
in tension.  The step takes that load, so the magnets only ever pull."""

STEP_END_V = 0.03
"""How far short of each rim the tongue stops, as a share of the cover's own
height coordinate.

In v and not in millimetres because the rim is a curve on the anatomic cover --
it dips 40 mm at the back and none at the sides -- and a flat cut would stop
the tongue a long way below the edge on one side and at it on the other.  A
tongue run out to the rim would leave a knife edge exactly where the two halves
are handled."""

SEAM_FADE = 14.0
"""How far from the seam the pattern is faded out, mm."""

# --- magnets ----------------------------------------------------------------

MAGNET_STRUT = 1.6
"""Material round a magnet pocket in the land, mm.

Less than LUG_STRUT, and deliberately: a pocket holds a magnet, it is not
threaded and nothing is torqued against it, so four perimeters is enough.  It
is also what decides whether a magnet fits at all -- the land has to be the
magnet plus this twice, and the prosthesis is what limits the land."""

MAGNET_FLOOR = 1.2
"""Material left behind a magnet pocket, mm.  Three perimeters at 0.4."""

MAGNET_END_MARGIN = 25.0
"""How far the first and last magnet stand off the ends of a seam."""

MAGNET_MIN_PITCH = 30.0
"""Closest two magnets on one seam may be, centre to centre."""

# --- clamps -----------------------------------------------------------------

CLAMP_HEIGHT = 22.0
"""Height of a clamp along the tube, mm.  Was 10.

Ten millimetres of PLA around a 34 mm tube is a band, not a clamp: it grips
over a tenth of the tube's diameter and every load on the cover arrives at it
as a moment.  Twenty-two is a third of the diameter and enough for two rows of
perimeters above and below each bolt."""

CLAMP_RING = 6.0
"""Wall of the ring round the tube, mm.  Was as thin as 2.4.

2.4 mm is three perimeters and no infill: it has no core to speak of, and it
was the part in tension when the bolts were tightened."""

WEB_THICKNESS = 7.0
"""The web that joins a clamp to the shell, mm thick.

This is the repair.  The ring used to hang on two or three ribs 5 mm wide,
which are cantilevers loaded in bending across the print's layers, with no
fillet in the root; `mounts._rib` even stopped a rib as soon as it reached the
inner face of the wall, so it butted against the shell rather than merging
into it.  The web instead runs the whole arc of the half, so the load is spread
over the entire section rather than through two points."""

WEB_FLARE = 5.0
"""How far the web thickens where it meets the shell and where it meets the
ring, mm.  There is no fillet operation on a mesh, so the web is built as a
slab that grows towards both ends, which is the same thing where it matters:
no square re-entrant corner at the root."""

CLAMP_END_MARGIN = 10.0
"""How far a clamp keeps from either end of the tube, so its bore is all tube
and not half tube, half the fitting that holds it."""

CLAMP_MIN_GAP = 55.0
"""Closest two clamps on one tube may be, centre to centre.

Two clamps a long way apart hold the cover's tilt; two close together do not,
and the whole point of the second one is the tilt.  The tube is 115 mm long and
a clamp needs 21 mm of it, so 55 is most of what is left to spread them over."""

FREE_COLLAR = 14.0
"""How far a free clamp reaches past its ring, mm, when the cover leaves room.

It is a steady, not a fixing: the collar fills most of the gap between the tube
and the cover's wall so the lower end cannot swing, and stops a fitting gap
short of the wall so nothing rubs."""

FREE_COLLAR_GAP = 1.0
"""Gap a free clamp keeps from the cover's inner wall, mm.  Larger than the
printer's fitting gap: this one has to slide past the wall on assembly, and
past a wall that carries a pattern."""

BORE_CLEARANCE = 0.4
"""Gap between the bore and the tube, on the radius.

Not a fit: the two halves are pulled onto the tube by the bolts, so the bore is
a little over size and the grip comes from the split closing."""

SPLIT_GAP = 1.2
"""Gap between the two parts of a clamp at the split, mm.  Was 1.0.

What the bolts have left to pull through.  If the two parts meet before the
bore is tight, the clamp holds nothing."""

# --- the notch at the back --------------------------------------------------

FLEXION_ANGLE = 130.0
"""How far the cover has to let the knee bend, degrees.

The College Park Capital's own limit, from page 3 of the manual.  Nothing the
cover does buys more than that, and anything less is the cover taking away
movement the leg has."""

THIGH_SAMPLE_MM = 40.0
"""How far above the axis the thigh's girth is read off the scan."""

THIGH_RADIUS_FALLBACK = 50.0
"""Used only if the scan covers nothing above the axis."""

THIGH_START_MM = 17.0
"""Where the thigh begins, measured up the femur from the flexion axis.

The Capital's dome sits 17 mm above the knee centre (manual, page 4), and
below that is the module itself -- which is bolted to the shin and turns with
the cover, not against it.  A thigh modelled from the axis instead fills the
joint with a body no thigh ever reaches into, and the notch it asks for is
both too big and impossible to shroud."""

NOTCH_CLEARANCE = 2.0
"""Gap kept between the cover and the swept thigh, mm."""

# A panel standing in the notch was tried and dropped.  Measured, a rigid one
# cannot exist: a thigh turning through 130 degrees sweeps a slab 92 mm wide
# about the sagittal plane at every radius below the module's dome, and sinking
# a point inward leaves it in the same slab.  It is what happens to a real leg
# -- at deep flexion the calf lies against the back of the thigh and nothing
# rigid fits between them.  The joint shows through the opening, as it does on
# the covers this one is drawn from.

NOTCH_FADE = 35.0
"""How far from the notch the pattern is faded out, mm.

Wider than the 14 mm a rim gets, and for the reason the transfemoral tab found:
the notch is the edge people look at, and a pattern that stops abruptly there
reads as damage."""

# --- bolts, and what they thread into ---------------------------------------

BOLT_SIZES = (3.0, 4.0, 5.0)

HEAT_SET = {
    # bolt: (insert hole diameter, insert length)
    3.0: (4.6, 6.0),
    4.0: (5.6, 8.2),
    5.0: (6.4, 9.5),
}
"""Brass heat-set inserts, the common M-series.  The hole is the moulded-in
diameter the supplier asks for; the code adds nothing to it, since an insert is
melted in and an oversize hole is what makes it spin."""

HEX_NUT = {
    # bolt: (across flats, thickness)
    3.0: (5.5, 2.4),
    4.0: (7.0, 3.2),
    5.0: (8.0, 4.0),
}
"""ISO 4032 nuts, for the captive-nut option: a hexagonal pocket in the side of
the lug that the nut drops into and cannot turn in."""

SOCKET_HEAD = {
    3.0: (5.5, 3.0),
    4.0: (7.0, 4.0),
    5.0: (8.5, 5.0),
}
"""ISO 4762 socket heads: diameter and height."""

NUT_KINDS = ("heat_set", "hex")

LUG_STRUT = 2.6
"""Material round a bolt hole, an insert or a nut pocket, mm.

Three times MIN_STRUT and then some.  The old lugs were sized at one MIN_STRUT
round the head, which on a 0.4 nozzle is two perimeters that meet at the hole
with no core between them."""

NUT_POCKET_CLEARANCE = 0.25
"""Slip fit on a hex pocket: a nut has to drop in, not be pressed."""

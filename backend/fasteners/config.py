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

SEAM_PLANE_Y = 0.0
"""The cut is the frontal plane through the cover's own centre line, so the
halves are a front and a back.  Where a cosmetic cover is normally parted."""

LAND_DEPTH = 9.0
"""How far the land reaches inward past the inner face of the wall.

The wall is 3 mm on the anatomic cover and 5 on the Rhino one, and a magnet is
6 across: the seam face as cut is too narrow to hold one.  The land is a rib
along the inside of each seam that widens that face to wall + 9 mm, which is a
magnet, a strut either side of it, and the fitting gap."""

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

BORE_CLEARANCE = 0.4
"""Gap between the bore and the tube, on the radius.

Not a fit: the two halves are pulled onto the tube by the bolts, so the bore is
a little over size and the grip comes from the split closing."""

SPLIT_GAP = 1.2
"""Gap between the two parts of a clamp at the split, mm.  Was 1.0.

What the bolts have left to pull through.  If the two parts meet before the
bore is tight, the clamp holds nothing."""

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

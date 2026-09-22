"""Every number the anatomical-cover pipeline can be tuned by, in one place.

Stages read from here and nowhere else, so changing a value and re-running the
stage is the whole edit loop.  Lengths are millimetres, angles degrees.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
WORK = ROOT / "work"
RENDERS = ROOT / "renders"
DATA = ROOT.parent / "data"

# ---------------------------------------------------------------- stage 1 ---

SCAN_SOURCE = pathlib.Path.home() / "Downloads/Telegram Desktop/Leg+Prosthetic.stl"
"""The untouched original.  Stage 1 copies it to SCAN_COPY and never writes
back; every later stage reads the copy."""

SCAN_COPY = DATA / "Leg_Prosthetic.stl"

WELD_TOL_MM = 1e-3
"""Vertices closer than this are one vertex.  The scan stores float32, so
coincident vertices are bit-identical and this only guards against noise."""

JUNK_FACE_COUNT = 200
"""Connected components smaller than this are scanner debris and are dropped."""

# The scan is a whole seated person, not a bare prosthesis.  Two seed points
# picked off labelled renders of the scene pick the prosthetic limb out of it:
# one in the socket, one in the foot, both in raw scan coordinates.  Everything
# within LIMB_RADIUS of the segment between them is a candidate; the largest
# connected component of that is the limb.
LIMB_SEED_TOP = (-218.0, 286.0, -614.0)
LIMB_SEED_BOTTOM = (421.0, -25.0, -814.0)
LIMB_RADIUS = 110.0
LIMB_OVERSHOOT_TOP = 40.0
LIMB_OVERSHOOT_BOTTOM = 120.0

TARGET_FACES = 120_000
"""Working size after decimation.  The raw limb is ~1.4 M triangles of skin
noise; this keeps the silhouette and drops the rest."""

# Units are not stored in STL.  The pylon is the only part with a catalogue
# diameter, so it doubles as the ruler: find the long stretch of constant,
# round cross-section and compare it with PYLON_DIAMETER.
PYLON_DIAMETER = 34.0
PYLON_DIAMETER_TOL = 5.0
PYLON_ROUNDNESS_TOL = 8.0
"""How far the two section widths may differ and the section still count as
round."""
PYLON_MIN_LENGTH = 60.0

SECTION_STEP = 5.0
"""Spacing of the cross-sections used for the width profile."""

# Where one part of the prosthesis ends and the next begins, as cross-section
# width thresholds.  Read off the profile in the stage 1 report; change them
# there if the labels land wrong.
KNEE_MIN_WIDTH = 60.0
"""Above the pylon, the section grows; the knee module starts where it first
passes this."""
SOCKET_MIN_WIDTH = 95.0
"""...and the socket starts where it passes this."""
FOOT_MIN_WIDTH = 90.0
"""Below the pylon, the shoe starts where the section passes this."""

# ---------------------------------------------------------------- renders ---

RENDER_HEIGHT = 1100
RENDER_BACKGROUND = (233, 234, 230)
PART_COLOURS = {
    "socket": (196, 118, 102),
    "knee": (110, 142, 186),
    "pylon": (206, 176, 96),
    "foot_adapter": (124, 178, 128),
    "foot": (150, 132, 170),
    "unassigned": (176, 176, 172),
}

# ---------------------------------------------------------------- stage 2 ---

# College Park Capital, model with the 34 mm pylon receiver (assembly weight
# 980 g in the manual, which is the receiver variant).  Build-height table,
# page 4 of data/capital_knee.pdf.
KNEE_OVERALL_HEIGHT = 230.0
"""Proximal dome to the distal end of the assembly."""
KNEE_DOME_TO_CENTRE = 17.0
"""Dome down to the knee centre, i.e. the flexion axis."""
KNEE_CENTRE_TO_PYRAMID = 7.0
KNEE_DOME_TO_TUBE_END = 173.0
"""Dome down to where the top of the pylon bottoms out inside the receiver."""
KNEE_MAX_FLEXION = 130.0

SECTION_SPACING = 10.0
"""Step of the section table below the knee axis."""
SECTION_SLAB = 5.0
"""Half-thickness of the slab of surface each section is measured from."""
CONTOUR_BINS = 180
"""Angular resolution of a section contour: one radius every 2°."""

# ---------------------------------------------------------------- stage 3 ---

MAKEHUMAN_URL = (
    "https://raw.githubusercontent.com/makehumancommunity/makehuman/master"
    "/makehuman/data/3dobjs/base.obj"
)
"""The MakeHuman base mesh, released as CC0 in September 2020 (the licence note
is in the file's own header).  Found by probing the repository, not guessed."""
MAKEHUMAN_OBJ = DATA / "makehuman_base.obj"
MAKEHUMAN_BODY_GROUP = "body"
MAKEHUMAN_KNEE_JOINT = "joint-l-knee"
MAKEHUMAN_ANKLE_JOINT = "joint-l-ankle"
MAKEHUMAN_UNIT_MM = 100.0
"""Decimetres.  Checked against the model's height, which must land near 1.7 m."""
MAKEHUMAN_HEIGHT_RANGE_MM = (1500.0, 1950.0)

SUBDIVIDE_ITERATIONS = 2
"""The base mesh is ~19 k vertices and meant to be smoothed by subdivision, so
it is subdivided before any section is measured off it."""

KNEE_EXTENSION_MM = 110.0
"""How far above the knee joint the MakeHuman leg is sampled.

A cosmetic cover is a leg, not a sleeve on a shank: the standard foam cosmesis
covers the knee whole and is cut away only at the back, where the foam would
tear in flexion.  So the shape has to come from a stretch of the model that
includes the knee itself and the bottom of the thigh."""

SHANK_SLICES = 61
"""Sections along the sampled leg. t = 0 at the ankle joint, t = 1 at the top
of the sampled stretch; the knee joint lands at `knee_t`, reported by stage 3."""
SHANK_RADIUS_MM = 140.0
"""Everything further than this from the shank axis is the other leg."""

# The reference renders.  Stage 3 pulls the silhouette out of them; without the
# files it runs the anatomy half and says the reference half is missing.
REF_IMAGES = [DATA / "ref_1.png", DATA / "ref_2.png", DATA / "ref_3.png"]
REF_BACKGROUND_TOLERANCE = 28
"""How far a pixel may sit from the corner colour and still count as background."""

# ---------------------------------------------------------------- stage 4 ---

CLEARANCE_MM = 5.0
"""Gap between the prosthesis and the inside of the cover."""
WALL_THICKNESS_MM = 3.0
BOTTOM_CLEARANCE_MM = 10.0
"""How far above the top of the foot adapter the cover stops."""

COVER_TOP_Z = 20.0
"""Highest the rim may reach, in knee-axis coordinates.  Above 0, which is the
flexion axis: the cover goes over the knee, as a foam cosmesis does, and the
rim solver decides how much of that it can actually keep."""

COVER_TOP_LIMIT = 90.0
"""How far above the knee axis the surface is built at all."""
COVER_SECTION_STEP = 2.0
"""Spacing of the sections the surface is lofted through."""
COVER_ROWS = 180
"""Rows of the lofted grid.  Each column runs from the bottom to its own point
on the rim, so the rim comes out exactly on the curve rather than on a
triangle edge."""

ANATOMY_T_BOTTOM = 0.13
"""Where on the MakeHuman shank the bottom of the cover sits.  t = 0 is the
ankle joint, whose section still carries the heel; the narrowest point of the
ankle is a little above it and that is what the cover should copy."""

GIRTH_FROM_REFERENCE = True
"""Take the taper below the knee from the reference renders, not MakeHuman.

The three renders agree with each other to a per cent and they are markedly
slimmer than a MakeHuman leg: width over height 0.25 against 0.32, and a
bottom half that narrows to about half the widest section where MakeHuman only
reaches two thirds.  A cosmetic cover is a drawn leg, not a fleshy one, and
that difference is most of what makes one look elegant and the other look
swollen.  Above the knee the renders say nothing, so MakeHuman carries on."""

COVER_FULLNESS = 1.0
"""Overall girth of the anatomical silhouette, 1.0 = just enough to sit on the
prosthesis at the typical section.  Raise it for a fuller calf."""
CENTRE_BLEND_MM = 130.0
"""Over how much height below the knee the cover's centre line is brought back
onto the knee axis.

Below the knee it follows the prosthesis, which bench alignment puts about a
centimetre lateral of the joint. A leg has no such step: shank and thigh meet
at the knee. Carrying the offset up to the joint would also leave a centimetre
less room on the lateral side than the medial, and the flexion solver would
pay for it by cutting the cover away there."""

CENTRELINE_SMOOTH_MM = 60.0
"""The cover's centre line follows the prosthesis section centres, smoothed
over this much height."""
SHAPE_SMOOTH_MM = 6.0
"""How far up the cover the section shape is blended between MakeHuman slices."""

GIRTH_SMOOTH_ARC = 45.0
"""How far around the section the swelling is blended, in degrees."""

GIRTH_SMOOTH_MM = 35.0
"""Scale along the height is dilated and then blurred over this much, so the
surface has no steps and still never cuts into the clearance."""

# The rim, as a handful of control points (angle around the section, height in
# knee-axis mm) through a periodic spline.  0 deg is lateral, 90 is the front
# of the leg, 270 the back.  The back is cut deepest: that is the notch the
# knee flexes into, and stage 5 deepens it further if it has to.
RIM_FRONT_DIP_MM = 34.0
"""How far the rim dips at the front of the leg.  Style, from the reference."""
RIM_NOTCH_DEPTH_MM = 40.0
"""Starting depth of the notch at the back.  Stage 5 deepens it until the knee
clears, so this is only where the search begins."""


def rim_control(front_dip: float | None = None, notch_depth: float | None = None):
    """The rim as a handful of (angle, height) control points.

    0 deg is lateral, 90 the front of the leg, 270 the back.  The notch is one
    shape with one handle: as it is taken deeper it also opens sideways, since
    at deep flexion the thigh is not only behind the cover but beside it.
    """
    front = RIM_FRONT_DIP_MM if front_dip is None else front_dip
    depth = RIM_NOTCH_DEPTH_MM if notch_depth is None else notch_depth
    side = depth * min(max((depth - 60.0) / 200.0, 0.0), 0.8)
    mid = (depth + side) / 2
    return [
        (90.0, -front),
        (0.0, -side),
        (180.0, -side),
        (225.0, -mid),
        (270.0, -depth),
        (315.0, -mid),
    ]


RIM_CONTROL = rim_control()
RIM_PROVISIONAL = not all(p.exists() for p in REF_IMAGES)
"""True while the rim comes from these numbers rather than from the reference
renders.  Goes false on its own once both renders are in data/."""

# ---------------------------------------------------------------- stage 5 ---

FLEXION_STEP = 5.0
FLEXION_MAX = 100.0
"""How far the cover is required to let the knee bend.

The module itself reaches 130 (page 3 of the manual) and nothing the cover
does can buy more than that, but the cover can be asked for less, and the
asking is expensive: every five degrees past about 110 costs some fifteen
millimetres of notch, because that is where the calf starts meeting the back
of the thigh.  Flexible electrogoniometry puts level walking and slopes under
90 degrees, stairs and rising from a chair between 90 and 120, and getting
into a bath at about 135."""

THIGH_SAMPLE_Z = 60.0
"""Height above the knee axis at which the thigh's girth is measured off the
scan.  Only 17 mm of the knee module sits above the axis, so everything higher
belongs to the socket and turns with the thigh."""
THIGH_LENGTH_MM = 300.0
THIGH_EXTRA_MM = 2.0
"""Padding on the thigh cylinder, so the cover does not merely graze it."""

RIM_WALL_MARGIN_MM = 2.0
"""How far under the solved rim the cover is actually cut.

The rim is solved column by column on a grid of 180 angles, and the mesh
between two columns bows in a little from the surface they were read on. Two
millimetres covers that; it used to be five, to cover an inner wall that rode
above the rim, which is now fixed at its source in the offset."""

FLEXION_TOLERANCE_MM = 0.5
"""How far a point must be inside the thigh before it counts as a collision.
Both bodies are approximations — the thigh is a stand-in and the cover's inner
wall is an offset along smoothed normals, which overshoots the rim by a couple
of tenths — so a contact thinner than this is numerical, not physical."""

RIM_SMOOTH_WINDOW = 5
"""Columns the solved rim is rounded over. Every column it is widened by is a
column of cover thrown away, so this is as small as a smooth edge allows."""

NOTCH_SEARCH_STEP_MM = 2.0
NOTCH_SEARCH_LIMIT_MM = 220.0
"""How far down the back rim may be taken while hunting for clearance."""

# ---------------------------------------------------------------- stage 6 ---

MATERIAL_DENSITY_G_CM3 = 1.24
"""PLA, for the weight line in the report."""
OUTPUT_STL = ROOT.parent / "cover_anatomic.stl"
REFERENCE_VIEW = (0.62, 0.70, -0.14)
"""Camera direction that comes closest to the reference renders."""

# ---------------------------------------------------------------- stage 7 ---

REFERENCE_TOP_Z = -76.0
"""Where the cover from the reference renders sits, relative to the knee axis.

Found by search, not chosen: the rim traced off ref_2 is narrow, and a narrow
notch cannot clear the thigh at deep flexion however deep it is cut — the
thigh ends up beside the cover, not only behind it.  Sitting the whole cover
lower solves it with the reference's own shape untouched.  At this height it
reaches the full 130 degrees; two millimetres higher it stops at 125."""

REFERENCE_DEEPEN_MM = 0.0
"""Extra depth on the notch, if the seating height is overridden and the knee
needs more room than the reference leaves it."""
OUTPUT_REFERENCE_STL = ROOT.parent / "cover_reference.stl"

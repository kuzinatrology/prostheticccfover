"""Everything about the scan, the knee and the notch that is not a slider.

None of this reaches the interface. The person choosing a design never sees
the scan, the knee axis or the notch angle: those are properties of this
patient and this knee module, and they change when a new scan or a new
measurement arrives, not when someone drags a control.

Millimetres, degrees. Frame after `tools/prepare_scan.py`: +z up the shin with
the ankle at the bottom, +y anterior, +x completing a right-handed frame.
"""

from __future__ import annotations

import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
SURFACE_FILE = ASSETS / "leg_surface.npz"
REPORT_FILE = ASSETS / "leg_surface.json"
SCAN_FILE = pathlib.Path(__file__).resolve().parents[2] / "data" / "оболочка.stl"

# --- scan preparation ----------------------------------------------------

MIRROR_SCAN = False
"""Carry the healthy leg over to the prosthetic side.

Off for `data/оболочка.stl`: that file is already the mirrored copy of the
original scan (the two match to 0.000 mm after reflection), confirmed as the
prosthetic side. Turning this on for it would put the leg back on the healthy
side. A new scan needs this decided again."""

TRUST_CENTRES_BELOW_Z = 20.0
"""Above this the scan is the bent knee and section centres jump about. The
axis is extended straight from here, along the tangent measured below it."""

TANGENT_RUN = 80.0
"""Length of shin below TRUST_CENTRES_BELOW_Z the tangent is fitted over."""

CENTRE_STEP = 5.0
"""Spacing of the sections the centreline is fitted through."""

CENTRE_SMOOTHING = 3
"""Degree of the polynomial through the section centres. A cubic follows the
32 mm drift of the shin and cannot follow the noise of a single section."""

MAX_ORIENTATION_DISAGREEMENT = 20.0
"""Calf bulge and centre drift must point the same way within this, or the
scan is not what this script thinks it is and it stops."""

THIGH_RADIUS_FACTOR = 1.5
"""A vertex further than this times the local shin radius from the axis is
thigh, not shin."""

WORK_TRIANGLES = 60000
"""Working triangle count. The scan is decimated to this when it is larger;
this one has 5252 and is left alone."""

GRID_THETA = 360
"""Samples around the section in the stored surface: one per degree."""

GRID_DZ = 2.0
"""Height step of the stored surface, mm."""

SMOOTH_MAX_SHIFT = 0.5
"""Smoothing may move the surface by no more than this along its normal. The
cover is the scan; smoothing only takes the skin texture and the facets of a
coarse mesh off it."""

SMOOTH_SIGMA_MAX = 6.0
"""Gaussian width, mm, at the top of the smoothing slider."""

CURVATURE_BASELINE = 6.0
"""Arc length, mm, the surface's curvature is read over. The scan's triangles
are eight millimetres across and their corners are kinks; a wall a few
millimetres thick and a hole several across do not see them."""

SMOOTH_DEFAULT = 0.5
"""Where the smoothing slider starts, as a fraction of its travel."""

# --- the knee ---------------------------------------------------------------

KNEE_MODULE = "College Park Capital"

knee_axis_z = 70.0
"""Height of the flexion axis. Local minimum of the radius between calf and
thigh; the kink in the line of centres independently gave 62. To be replaced
by two measurements from the floor: to the knee centre on the module, and to
the bottom of the scan."""

knee_axis_y_offset = 0.0
"""Front-back position of the axis relative to the shin centre at
TRUST_CENTRES_BELOW_Z, the last height the section centres are trusted at."""

top_z = knee_axis_z + 35.0
"""Top of the cover: the top of the kneecap. The front half closes over the
knee and goes no higher."""

flexion_angle = 145.0
"""130 is the module's limit (Capital: 130 degrees). 15 more cover the
uncertainty in knee_axis_z: a centimetre there moves the whole notch a
centimetre. Back to 130 once the axis is measured."""

notch_split = 0.35
"""Set from the first renders: at 0.5 the notch runs down the calf almost to
the ankle and leaves the back half a thin U with nothing behind the upper
clamp. 0.35 ends it above the module's clamp, as in the reference.

Share of the notch angle laid below the posterior horizontal. A design
decision, not a measurement: every split is equally safe, it only decides
whether the material comes from above the axis or from the calf."""

notch_fillet = 4.0
"""Radius the notch's corner is rounded to, mm. The notch is the sector grown
by this, so the rounding only ever removes material and never puts any back
inside the sector."""

notch_clearance = 2.0
"""Gap kept between the cover and the swept thigh, mm."""

MODULE_KNEE_TO_TUBE = 173.0 - 17.0
"""Knee centre to the end of the tube in the pylon receiver (Capital manual:
dome to tube end 173 mm, dome to knee centre 17 mm). Below this is pylon,
above it is module."""

PYLON_DIAMETER = 30.0
"""The tube the lower clamp grips."""

# Both upper-clamp numbers are PRELIMINARY and not measurements.
# 65 mm is scaled off a side photograph against the 30 mm tube, with five to
# ten percent of perspective error in it. 60 mm is not measured at all: the
# width is not visible from the side; it needs a photograph from the front.
UPPER_HOLE_WIDTH = 60.0  # PRELIMINARY, unmeasured
UPPER_HOLE_DEPTH = 65.0  # PRELIMINARY, from a photograph
PRELIMINARY_MARGIN = 2.0
"""Extra room, beyond CLEARANCE, in the rectangular hole's defaults, because
neither of its numbers is a measurement."""

# --- attachment geometry derived from the bolt ------------------------------

BOLT_HEAD_RATIO = 1.75
"""Socket head diameter over bolt hole diameter (ISO 4762 M4: 7 mm head, 4.5
mm hole)."""

BOLT_HEAD_HEIGHT_RATIO = 1.0
"""Head height over hole diameter."""

MAGNET_END_MARGIN = 20.0
"""Magnets start this far from either end of a seam, mm."""

EXPLODE_MM = 70.0
"""How far the exploded view pulls the back parts away."""

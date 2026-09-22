"""Everything about the Rhino cover that is not a slider.

The shape of this tab is a file: `cover ready iteration 1.stl`, modelled in
Rhino and exported as a closed cover with a wall already on it.  Nothing here
reaches the interface.  A new iteration of that file changes these numbers and
nothing else.

Millimetres, degrees.  Frame after `prepare.py`: +z up the cover, the fitted
axis through (0, 0) at the bottom rim, which is z = 0.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
ASSETS = ROOT / "backend" / "assets"

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    """One Rhino export and the two files measured out of it.

    Everything else in this package is about reading an export, not about which
    export it is, so a new model is an entry here and a tab -- no second
    pipeline and no copied code.
    """

    key: str
    title: str
    source: pathlib.Path
    surface_file: pathlib.Path
    report_file: pathlib.Path


MODELS: dict[str, Model] = {
    "iteration1": Model(
        key="iteration1",
        title="Iteration 1",
        source=ROOT / "cover ready iteration 1.stl",
        surface_file=ASSETS / "iteration1.npz",
        report_file=ASSETS / "iteration1.json",
    ),
    "iteration2": Model(
        key="iteration2",
        title="Iteration 2",
        source=ROOT / "Cover new.stl",
        surface_file=ASSETS / "iteration2.npz",
        report_file=ASSETS / "iteration2.json",
    ),
}

DEFAULT_MODEL = "iteration1"


def model(key: str | None = None) -> Model:
    return MODELS.get(key or DEFAULT_MODEL, MODELS[DEFAULT_MODEL])


SOURCE_FILE = MODELS[DEFAULT_MODEL].source
"""The Rhino export, untouched.  Read once by `prepare.py` and never again."""

SURFACE_FILE = MODELS[DEFAULT_MODEL].surface_file
REPORT_FILE = MODELS[DEFAULT_MODEL].report_file

# --- preparation ---------------------------------------------------------

SAMPLES = 3_000_000
"""Points scattered over the Rhino mesh to measure it.

The mesh is a loft of 30 k triangles in rows, so its vertices alone leave most
of the grid below empty; scattering over the faces fills every cell of it."""

GRID_THETA = 360
"""Samples around the section in the stored surface: one per degree."""

GRID_DZ = 1.0
"""Height step of the stored surface, mm."""

MIN_HITS = 3
"""Points a cell needs before it counts as surface rather than as noise."""

CENTRE_STEP = 4.0
"""Spacing of the sections the centreline is fitted through."""

CENTRE_SMOOTH_MM = 24.0
"""Gaussian width the centreline is smoothed over.  The cover leans by 24 mm
over its height; nothing that happens faster than this is its axis moving."""

RIM_SMOOTH_DEG = 3.0
"""Gaussian width, degrees, the two rim curves are smoothed over.  The rims
come off a coverage mask read on a 1 degree grid, so they arrive a cell
ragged; the curves themselves are smooth in the file."""

# --- the cover -----------------------------------------------------------

ROWS = 220
"""Rows of the grid the solid is rebuilt from, bottom rim to top rim."""

DRAFT_ROWS = 90

SMOOTH_SIGMA_MAX = 5.0
"""Gaussian width, mm, at the top of the smoothing slider."""

SMOOTH_MAX_SHIFT = 0.6
"""Smoothing may move the surface by no more than this.  The cover is the
Rhino model; smoothing only takes the facets of a coarse export off it."""

RIM_SOLID = 8.0
"""Plain band along both rims, mm.  A hole opening onto a rim leaves a notch
in the edge rather than a hole in the cover."""

EDGE_FADE = 14.0
"""Width, mm, over which the pattern fades out toward a rim."""

FADE_KEEP = 0.5
"""How strong the edge mask must be for a cell to be cut at all.  Below it the
cell is left solid, so the pattern ends on holes near their full size instead
of crumbling into chips along the rim."""

MIN_TIDY_HOLE = 3.0
"""Smallest hole, mm across, the pattern may end on."""

TIDY_ASPECT = 0.35
"""How narrow a hole caught by the fade may be, as width over length."""

KEEP_MARGIN = 0.5
"""Added to every keep-out distance, to absorb reading the fields off a grid."""

WALL_PROBE = 3.0
"""How far inside a rim the wall's direction is read, mm.

The radius is held above the last measured row, so right at a rim the slope
of the surface is an artefact of that holding rather than the shape.  A few
millimetres in, it is the shape, and the wall at the rim is the wall just
below it carried up."""

WALL_LEAN_FLOOR = 0.7
"""How far from vertical the wall may lean before the correction stops.

A cover whose skin ran at 45 degrees would need its radius shortened by half
again to keep the wall; nothing on this model does, so a correction past this
is a reading gone wrong rather than a shape."""

WALL_LEAN_SMOOTH_DEG = 3.0
"""Gaussian width, degrees, the lean is smoothed around the section over."""

CURVATURE_BASELINE = 8.0
"""Baseline, mm, the curvature is read over.  The export is a mesh of several
millimetre triangles and every corner of it is a kink a millimetre across;
read point by point it would cap the wall and every hole at nothing."""

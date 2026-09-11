"""A picture becomes a hole, and the hole is still printable.

The rules are the ones the rest of the suite already states. What is new is
that nobody controls the shape any more: it comes out of a file. So the same
properties are asserted again over pictures chosen to break them - a whisker
thinner than the nozzle, prongs closer together than a strut, a crescent that
no cone of triangles can cover, and a sheet of white paper.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend import measure
from backend import motif as mo
from backend.fields import Fields
from backend.generator import DRAFT, audit, generate, placement_for
from backend.params import CoverParams
from backend.pattern import SPAN_VS_CURVATURE, build_cells, build_pattern
from backend.printer_profile import DEFAULT_PROFILE as PROFILE
from backend.surface import Surface
from tests import shapes
from tests.properties import PLANAR_TOLERANCE

SMOOTHING = CoverParams().motif_smoothing


def read(data: bytes, **kwargs) -> mo.Motif:
    settings = {"threshold_bias": 0.0, "invert": False, "smoothing": SMOOTHING}
    return mo.vectorise(data, **{**settings, **kwargs})


def params_for(data: bytes, **kwargs) -> CoverParams:
    digest = mo.LIBRARY.add(data)
    return CoverParams(hole_shape="image", motif_id=digest, **kwargs)


# --- 1. the vectoriser says what the picture said -----------------------


@pytest.mark.parametrize(
    ("name", "outlines", "holes"),
    [("square", 1, 0), ("circle", 1, 0), ("ring", 1, 1), ("two", 2, 0)],
)
def test_shapes_come_back_with_their_own_outlines(name, outlines, holes):
    motif = read(shapes.png(name))
    assert len(motif.shape.geoms) == outlines
    assert sum(len(p.interiors) for p in motif.shape.geoms) == holes


def test_a_ring_keeps_its_hole_and_loses_it_before_being_cut():
    """The picture said ring; the printer cannot hold the disc in the middle."""
    motif = read(shapes.png("ring"))
    assert len(next(iter(motif.shape.geoms)).interiors) == 1
    assert sum(len(p.interiors) for p in motif.solid.geoms) == 0
    assert motif.filled == 1
    assert any("Inner openings" in note for note in motif.notes)


def test_the_unit_square_is_the_unit_square():
    for name in ("square", "circle", "star"):
        x0, y0, x1, y1 = read(shapes.png(name)).solid.bounds
        assert max(x1 - x0, y1 - y0) == pytest.approx(1.0, abs=1e-6)
        assert (x0 + x1) / 2 == pytest.approx(0.0, abs=1e-6)
        assert (y0 + y1) / 2 == pytest.approx(0.0, abs=1e-6)


def test_an_alpha_channel_is_believed_before_any_threshold():
    cut_out = read(shapes.transparent("ring"))
    assert len(cut_out.shape.geoms) == 1
    assert len(next(iter(cut_out.shape.geoms)).interiors) == 1


def test_an_svg_is_read_like_any_other_picture():
    assert len(read(shapes.svg()).solid.geoms) == 1


def test_dust_is_dropped_and_a_crowd_is_trimmed():
    motif = read(shapes.png("specks"))
    assert len(motif.solid.geoms) <= mo.MAX_SHAPES
    if motif.found > mo.MAX_SHAPES:
        assert any("largest shapes" in note for note in motif.notes)


def test_smoothing_only_ever_takes_vertices_away():
    rough = read(shapes.png("star"), smoothing=0.0)
    smooth = read(shapes.png("star"), smoothing=1.0)
    assert len(next(iter(smooth.solid.geoms)).exterior.coords) <= len(
        next(iter(rough.solid.geoms)).exterior.coords
    )


# --- 2. a whisker thinner than the nozzle is gone -----------------------


def test_a_tendril_below_min_hole_is_not_cut():
    """The picture has a four pixel whisker. The opening deletes it, and what
    is left is the disc it hung off, nowhere near as tall."""
    motif = read(shapes.png("tendril"))
    _, y0, _, y1 = motif.solid.bounds
    tall = y1 - y0

    p = params_for(shapes.png("tendril"))
    holes = _holes(p)
    assert holes
    # Every hole is round enough to be the disc rather than the whisker: a
    # whisker that survived would show as a hole far taller than it is wide.
    for ring in holes:
        width = ring[:, 0].max() - ring[:, 0].min()
        height = ring[:, 1].max() - ring[:, 1].min()
        assert height / max(width, 1e-9) < 2.0 * tall


# --- 3. every picture, at every setting, is still printable -------------


def _holes(p: CoverParams) -> list[np.ndarray]:
    surface = Surface.from_params(p)
    f = Fields.from_params(p)
    wall = min(p.wall_thickness, surface.max_wall_thickness(PROFILE, 4.0))
    strut = max(p.strut_width, PROFILE.MIN_STRUT)
    cells = build_cells(
        surface,
        f.density,
        wall_thickness=wall,
        strut=strut,
        irregularity=p.irregularity,
        anisotropy=p.anisotropy,
        flow_angle=p.flow_angle,
        profile=PROFILE,
        rng=np.random.default_rng(p.seed),
    )
    return build_pattern(
        cells,
        f.mask,
        profile=PROFILE,
        corner_radius=p.corner_radius,
        quad_segs=DRAFT.quad_segs,
        chord_tolerance=0.05 * strut,
        placement=placement_for(p),
    ).holes


PICTURES = ["crescent", "comb", "dumbbell", "star", "specks", "tendril", "ring"]
SETTINGS = [
    {},
    {"strut_width": 0.8},
    {"strut_width": 4.0},
    {"motif_fill": 1.0, "motif_scale_jitter": 0.5},
    {"motif_fill": 0.3, "pattern_density": 0.0},
    {"pattern_density": 1.0, "wall_thickness": 1.5},
    {"motif_rotation": 137.0, "motif_rotation_jitter": 180.0},
    {"motif_align_flow": True, "flow_angle": 45.0, "anisotropy": 0.3},
    {"mask_mode": "panel", "mask_feather": 0.4},
    {"irregularity": 0.0},
]


@pytest.mark.parametrize("name", PICTURES)
@pytest.mark.parametrize("setting", SETTINGS, ids=lambda s: ",".join(s) or "defaults")
def test_a_picture_never_makes_an_unprintable_pattern(name, setting):
    p = params_for(shapes.png(name), **setting).clamped()
    surface = Surface.from_params(p)
    holes = _holes(p)
    if not holes:
        return

    gap = measure.min_strut(surface, holes)
    assert gap >= PROFILE.MIN_STRUT * PLANAR_TOLERANCE, f"strut down to {gap:.3f} mm"

    spans = measure.hole_spans(surface, holes)
    wall = min(p.wall_thickness, surface.max_wall_thickness(PROFILE, 4.0))
    a_max = min(
        PROFILE.max_hole_span(wall),
        SPAN_VS_CURVATURE * surface.min_curvature_radius(),
    )
    assert spans.min() >= PROFILE.MIN_HOLE * PLANAR_TOLERANCE
    assert spans.max() <= a_max / PLANAR_TOLERANCE


@pytest.mark.parametrize("name", ["crescent", "comb", "dumbbell", "ring"])
def test_a_picture_builds_a_closed_cover_in_one_piece(name):
    cover = generate(params_for(shapes.png(name)), quality=DRAFT)
    assert not audit(cover)
    assert cover.mesh.is_watertight
    assert cover.mesh.body_count == 1
    # One handle per hole, and the tube's own.
    assert cover.mesh.euler_number == -2 * cover.holes
    assert 0 < cover.volume_mm3 < cover.plain_volume_mm3


# --- 4. the same file and the same sliders give the same object ---------


def test_one_picture_and_one_set_of_sliders_give_one_mesh():
    p = params_for(shapes.png("crescent"), motif_rotation_jitter=180.0)
    first = generate(p, quality=DRAFT).mesh
    second = generate(CoverParams.from_dict(p.to_dict()), quality=DRAFT).mesh
    assert np.array_equal(first.vertices, second.vertices)
    assert np.array_equal(first.faces, second.faces)


def test_two_uploads_of_one_file_are_one_picture():
    data = shapes.png("star")
    assert mo.LIBRARY.add(data) == mo.LIBRARY.add(data)


# --- 5. a blank sheet is a cover with nothing cut out of it -------------


def test_a_blank_picture_perforates_nothing_and_raises_nothing():
    motif = read(shapes.png("blank"))
    assert motif.is_empty

    cover = generate(params_for(shapes.png("blank")), quality=DRAFT)
    assert cover.holes == 0
    assert not audit(cover)
    assert cover.mesh.is_watertight
    assert cover.volume_mm3 == pytest.approx(cover.plain_volume_mm3, rel=1e-6)


def test_a_file_that_is_not_a_picture_is_the_only_refusal():
    with pytest.raises(mo.MotifError):
        read(b"this is not a picture")
    with pytest.raises(mo.MotifError):
        read(b"x" * (mo.MAX_BYTES + 1))


def test_a_design_naming_a_picture_nobody_holds_falls_back_to_cells():
    p = CoverParams(hole_shape="image", motif_id="0123456789abcdef")
    cover = generate(p, quality=DRAFT)
    assert cover.holes > 0
    assert any("No picture" in note for note in cover.notes)

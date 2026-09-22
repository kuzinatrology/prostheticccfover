"""The cover built on the Rhino model.

Two kinds of claim.  The first is that the tab still describes the file it is
built on: the surface measured into `backend/assets/iteration1.npz` is the one
in `cover ready iteration 1.stl`, and the solid rebuilt from it is that cover.
The second is the one every tab makes — whatever the sliders say, what comes
out is one closed body whose holes stay off the rims.

Builds run at draft quality; a final one takes half a minute and none of these
claims are about the row count.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh

from backend.iteration1 import config as cfg
from backend.iteration1 import prepare
from backend.iteration1.generator import DRAFT, audit, generate
from backend.iteration1.params import ITER_RANGES, IterParams
from backend.iteration1.presets import as_json as preset_json
from backend.iteration1.presets import params as preset_params
from backend.iteration1.surface import NEUTRAL, IterSurface, Shape

pytestmark = pytest.mark.skipif(
    not cfg.SURFACE_FILE.exists(),
    reason="run `python -m backend.iteration1.prepare` first",
)


@pytest.fixture(scope="module")
def surface() -> IterSurface:
    return IterSurface.default(0.0)


@pytest.fixture(scope="module")
def model() -> trimesh.Trimesh:
    return prepare.load()


def _outer_skin(surface: IterSurface, model: trimesh.Trimesh, count: int = 200_000):
    """Points of the model's outer skin, clear of both rims, with the radius
    the stored surface gives at the same angle and height."""
    points, _ = trimesh.sample.sample_surface(model, count)
    points = points - np.asarray(surface.data.meta["shift_mm"])
    offset = points[:, :2] - surface.centre(points[:, 2])
    radius = np.hypot(offset[:, 0], offset[:, 1])
    theta = np.arctan2(offset[:, 1], offset[:, 0])
    stored = surface.radial(theta, points[:, 2])
    u = (theta % (2 * np.pi)) / (2 * np.pi)
    keep = (
        (radius > stored - surface.wall / 2.0)
        & (points[:, 2] > surface.foot(u) + 5.0)
        & (points[:, 2] < surface.rim(u) - 5.0)
    )
    return radius[keep], stored[keep]


def test_the_stored_surface_is_the_modelled_one(surface, model):
    """Every point of the file's outer skin is where the grid says it is.

    A tenth of a millimetre is the size of the mesh's own triangles; being
    inside that is the difference between reading the model and redrawing it.
    """
    radius, stored = _outer_skin(surface, model)
    error = np.abs(radius - stored)
    assert np.median(error) < 0.05
    assert np.percentile(error, 99) < 0.5


def test_the_rims_are_the_modelled_rims(surface, model):
    """The top rim runs from the back of the knee up to the sides, and the
    bottom one is level: both as the file has them, within a millimetre."""
    vertices = np.asarray(model.vertices) - np.asarray(surface.data.meta["shift_mm"])
    assert abs(float(vertices[:, 2].max()) - surface.rim(np.linspace(0, 1, 720)).max()) < 1.0
    assert abs(float(vertices[:, 2].min()) - surface.foot(np.linspace(0, 1, 720)).min()) < 1.0
    assert np.ptp(surface.rim(np.linspace(0, 1, 720))) > 100.0


def test_the_plain_shell_is_the_modelled_cover():
    """Rebuilt with the wall the model was drawn with, it is the same solid:
    the file holds 676 cm3."""
    cover = generate(IterParams.from_dict({"operation": "none"}), quality=DRAFT)
    assert cover.mesh.is_watertight
    # A tube with two openings and nothing else: genus one.
    assert cover.mesh.euler_number == 0
    assert 0.95 < cover.volume_mm3 / 1000.0 / 676.3 < 1.05


@pytest.mark.parametrize("operation", ["cut", "emboss", "engrave", "none"])
def test_every_operation_gives_one_closed_body(operation):
    cover = generate(IterParams.from_dict({"operation": operation}), quality=DRAFT)
    assert not audit(cover)
    assert cover.mass_g > 0


def test_holes_keep_clear_of_the_rims():
    """No hole opens onto an edge: every outline stays the plain band plus a
    strut away from both rims."""
    params = IterParams.from_dict({"operation": "cut"})
    cover = generate(params, quality=DRAFT)
    assert cover.rings
    strut = max(params.strut_width, cover.profile.MIN_STRUT)
    for ring in cover.rings:
        distance = cover.surface.edge_distance(ring[:, 0], ring[:, 1])
        assert float(distance.min()) >= params.rim_solid + strut


def test_the_wall_is_the_one_asked_for():
    """Measured across the skin by rays through the solid, on a cover asked
    for a wall the model was not drawn with.

    The wall is laid down the radius rather than along the normal, so what a
    ray across the skin finds is that offset shortened by the lean of the
    surface; the point of the test is that the shortening happened.
    """
    from backend import mesh_build as mb

    wanted = 3.0
    cover = generate(
        IterParams.from_dict({"operation": "none", "wall_thickness": wanted}), quality=DRAFT
    )
    assert cover.wall == pytest.approx(wanted, abs=1e-6)
    solid = mb.to_manifold(cover.mesh)
    surface = cover.surface
    rng = np.random.default_rng(7)
    u = rng.random(120)
    v = rng.uniform(0.1, 0.6, 120)
    point, normal = surface.frame(u, v)
    found = []
    for start, direction in zip(point + normal * 6.0, -normal):
        hits = solid.ray_cast(start.tolist(), (start + direction * 40.0).tolist())
        d = sorted(h.distance * 40.0 for h in hits)
        crossings = []
        for x in d:
            if crossings and x - crossings[-1] < 0.05:
                crossings.pop()
                continue
            crossings.append(x)
        if len(crossings) >= 2:
            found.append(crossings[1] - crossings[0])
    assert len(found) > 100
    assert np.median(found) == pytest.approx(wanted, abs=0.25)
    assert np.percentile(found, 2) > wanted * 0.85


def test_no_slider_setting_refuses_a_cover():
    """At the ends of the ranges this tab owns, a cover still comes out."""
    for wall in (ITER_RANGES["wall_thickness"].lo, ITER_RANGES["wall_thickness"].hi):
        for rim in (ITER_RANGES["rim_solid"].lo, ITER_RANGES["rim_solid"].hi):
            cover = generate(
                IterParams.from_dict(
                    {"wall_thickness": wall, "rim_solid": rim, "surface_smoothing": 1.0}
                ),
                quality=DRAFT,
            )
            assert not audit(cover)


@pytest.mark.parametrize("key", [p["key"] for p in preset_json()])
def test_every_preset_holds(key):
    """The six starting points the other tabs offer build here too."""
    cover = generate(preset_params(key), quality=DRAFT)
    assert not audit(cover)
    assert cover.mass_g > 0


def test_a_preset_carries_over_whole():
    """Nothing a preset sets is dropped on the way to this tab: every value in
    it is a design value, and this cover has all of them."""
    from backend.presets import as_json as full_json

    for mine, theirs in zip(preset_json(), full_json()):
        assert mine["key"] == theirs["key"]
        assert mine["values"] == theirs["values"]


def test_a_preset_leaves_the_shape_alone():
    """A preset moves the pattern; where the shape sliders were put is where
    they stay."""
    for entry in preset_json():
        assert preset_params(entry["key"]).shape == NEUTRAL


def test_the_shape_knobs_each_move_the_cover_their_own_way():
    """Fuller is heavier, squashed is lighter, a trim is shorter, and a turn
    is neither: every knob does what its label says and nothing else."""
    plain = generate(IterParams.from_dict({"operation": "none"}), quality=DRAFT)
    height = float(np.ptp(plain.mesh.vertices[:, 2]))

    def shaped(**knobs):
        return generate(
            IterParams.from_dict({"operation": "none", **knobs}), quality=DRAFT
        )

    fuller = shaped(fullness=1.18)
    assert fuller.mass_g > plain.mass_g * 1.1

    squashed = shaped(ovality=0.82)
    assert squashed.mass_g < plain.mass_g

    turned = shaped(twist=20.0)
    # A turn moves material round the axis, it does not add or remove any.
    assert turned.mass_g == pytest.approx(plain.mass_g, rel=0.02)

    trimmed = shaped(top_trim=30.0, bottom_trim=40.0)
    assert float(np.ptp(trimmed.mesh.vertices[:, 2])) == pytest.approx(height - 70.0, abs=2.0)

    shorter = shaped(height_scale=0.9)
    assert float(np.ptp(shorter.mesh.vertices[:, 2])) == pytest.approx(height * 0.9, abs=2.0)


def test_a_deeper_notch_only_deepens_the_notch(surface):
    """The back notch goes down by the whole of the slider and the high sides
    of the rim do not move at all."""
    deeper = IterSurface.default(0.0, Shape(notch_deepen=40.0))
    u = np.linspace(0.0, 1.0, 360, endpoint=False)
    drop = surface.rim(u) - deeper.rim(u)
    assert drop.min() >= -1e-6
    assert drop.max() == pytest.approx(40.0, abs=0.5)
    # Where the rim is at its highest it is untouched.
    assert drop[np.argmax(surface.rim(u))] < 0.5


@pytest.mark.parametrize(
    "knobs",
    [
        {"fullness": 0.85, "ovality": 0.8, "posterior_bias": 1.0},
        {"fullness": 1.2, "ovality": 1.25, "twist": 20.0},
        {"twist": -20.0, "height_scale": 0.85, "bottom_trim": 60.0},
        {"height_scale": 1.15, "top_trim": 90.0, "notch_deepen": 90.0},
    ],
)
def test_no_shape_setting_refuses_a_cover(knobs):
    """At the ends of every shape range, cut through, a cover still comes out."""
    cover = generate(IterParams.from_dict({"operation": "cut", **knobs}), quality=DRAFT)
    assert not audit(cover)
    assert cover.holes > 0


def test_neutral_knobs_are_the_file(surface):
    """All eight at rest, the surface is the measurement and nothing else."""
    assert surface.shape == NEUTRAL
    u = np.linspace(0.0, 1.0, 200, endpoint=False)
    v = np.linspace(0.05, 0.95, 40)
    uu, vv = np.meshgrid(u, v)
    point = surface.point(uu, vv)
    z = surface.z_of_v(vv)
    offset = point[..., :2] - surface.centre(z)
    radius = np.hypot(offset[..., 0], offset[..., 1])
    stored = surface.radial(2 * np.pi * uu, z)
    assert np.abs(radius - stored).max() < 1e-9


def test_smoothing_never_moves_the_model_far():
    """The cover is the file: the smoothing slider takes facets off it and is
    not allowed to restyle it."""
    assert IterSurface.default(1.0).smoothing_shift <= cfg.SMOOTH_MAX_SHIFT + 1e-9

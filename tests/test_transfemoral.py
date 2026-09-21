"""The transfemoral cover, generated over random attachment and design settings.

The same arrangement as the transtibial suite: hypothesis picks the sliders,
`tf_properties` states the rules, and any failure is written to its own
corpus and re-run from then on.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.presets import PRESETS
from backend.transfemoral import config as cfg
from backend.transfemoral.knee import Knee
from backend.transfemoral.params import TF_ENUMS, TF_RANGES, TFParams
from backend.transfemoral.presets import params as preset_params
from tests import corpus
from tests import tf_properties as tp

EXAMPLES = int(os.environ.get("TF_EXAMPLES", "4"))
CORPUS = pathlib.Path(__file__).parent / "regressions" / "tf_corpus.jsonl"


def _num(key: str):
    r = TF_RANGES[key]
    return st.floats(min_value=r.lo, max_value=r.hi, allow_nan=False, allow_infinity=False)


tf_params = st.builds(
    TFParams,
    surface_smoothing=_num("surface_smoothing"),
    wall_thickness=_num("wall_thickness"),
    pattern_density=_num("pattern_density"),
    irregularity=_num("irregularity"),
    anisotropy=_num("anisotropy"),
    strut_width=_num("strut_width"),
    operation=st.sampled_from(list(TF_ENUMS["operation"])),
    mask_mode=st.sampled_from(list(TF_ENUMS["mask_mode"])),
    seam_offset=_num("seam_offset"),
    seam_solid_width=_num("seam_solid_width"),
    magnet_diameter=_num("magnet_diameter"),
    magnet_height=_num("magnet_height"),
    magnet_count=st.integers(min_value=1, max_value=8).map(float),
    lower_clamp_z=_num("lower_clamp_z"),
    upper_clamp_z=_num("upper_clamp_z"),
    lower_hole_diameter=_num("lower_hole_diameter"),
    upper_hole_width=_num("upper_hole_width"),
    upper_hole_depth=_num("upper_hole_depth"),
    bolt_diameter=_num("bolt_diameter"),
    back_leaves=st.booleans(),
    leaf_count=st.integers(min_value=1, max_value=7).map(float),
    leaf_size=_num("leaf_size"),
    leaf_tilt=_num("leaf_tilt"),
    seed=st.integers(min_value=0, max_value=2**16),
)


@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(params=tf_params)
def test_every_transfemoral_cover_holds(params: TFParams):
    faults = tp.check(params)
    if faults:
        corpus.record(params.clamped().to_dict(), "; ".join(faults), CORPUS)
    assert not faults, f"{faults} for {params.clamped().to_dict()}"


@pytest.mark.parametrize("entry", corpus.load(CORPUS), ids=lambda e: e["reason"][:60])
def test_known_transfemoral_regressions_stay_fixed(entry):
    assert not tp.check(TFParams.from_dict(entry["params"]))


def test_defaults_hold():
    assert not tp.check(TFParams())


@pytest.mark.parametrize("key", [p.key for p in PRESETS])
def test_every_preset_holds(key):
    assert not tp.check(preset_params(key))


def test_the_sector_matches_the_reference_table():
    """40, 55 and 70 mm behind the axis, at 145 degrees split evenly."""
    knee = Knee(0.0, cfg.knee_axis_z, 145.0, 0.5, 0.0)
    for behind, (lo, hi) in ((40, (-57, 197)), (55, (-104, 244)), (70, (-152, 292))):
        got = knee.back_height_range(behind)
        assert round(got[0]) == lo and round(got[1]) == hi


def test_no_slider_setting_refuses_a_cover():
    """At the far ends of every attachment range a cover still comes out."""
    extremes = TFParams(
        magnet_diameter=12.0,
        magnet_height=6.0,
        magnet_count=8.0,
        lower_hole_diameter=45.0,
        upper_hole_width=90.0,
        upper_hole_depth=90.0,
        bolt_diameter=6.5,
        seam_offset=60.0,
        seam_solid_width=4.0,
    )
    cover = tp.build(extremes)
    assert not tp.closed(cover)
    assert cover.notes


def test_leaves_are_few_large_symmetric_and_on_the_back():
    """Leaves only on the back half, mirrored about its middle, and every panel
    between two veins still a hole the wall can carry."""
    import numpy as np

    from backend import measure
    from backend.transfemoral.leaves import BACK_MIDLINE_U

    cover = tp.build(TFParams(back_leaves=True, leaf_count=3.0))
    rings = cover.rings["back"]
    assert rings
    assert not tp.check(cover.params, cover)
    centres = np.array([r.mean(axis=0) for r in rings])
    # Every panel has a twin across the back midline, or sits on it.
    for c in centres:
        mirror = np.array([2 * BACK_MIDLINE_U - c[0], c[1]])
        assert np.min(np.linalg.norm(centres - mirror, axis=1)) < 0.004
    spans = measure.hole_spans(cover.layout.surface, rings)
    assert spans.max() <= cover.layout.surface.min_curvature_radius() * 0.9 / 0.95 + 1e-6

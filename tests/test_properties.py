"""Generative tests: the engine picks the parameters, we state the rules.

Every property must hold for every point in the declared ranges, in every
operation, under every mask. A failure is a generator bug, never a user
mistake, so the offending parameters are written to the regression corpus and
re-run from then on.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.params import ENUMS, RANGES, CoverParams
from backend.presets import PRESETS
from tests import corpus
from tests.properties import check, check_and_export

EXAMPLES = int(os.environ.get("COVER_EXAMPLES", "12"))


def _num(key: str):
    r = RANGES[key]
    return st.floats(min_value=r.lo, max_value=r.hi, allow_nan=False, allow_infinity=False)


def _enum(key: str):
    return st.sampled_from(list(ENUMS[key]))


cover_params = st.builds(
    CoverParams,
    # limb and section
    length=_num("length"),
    knee_diameter=_num("knee_diameter"),
    ankle_diameter=_num("ankle_diameter"),
    calf_bulge=_num("calf_bulge"),
    calf_position=_num("calf_position"),
    posterior_bias=_num("posterior_bias"),
    ovality=_num("ovality"),
    section_squareness=_num("section_squareness"),
    twist=_num("twist"),
    wall_thickness=_num("wall_thickness"),
    # cell field
    pattern_density=_num("pattern_density"),
    density_gradient=_num("density_gradient"),
    irregularity=_num("irregularity"),
    anisotropy=_num("anisotropy"),
    flow_angle=_num("flow_angle"),
    corner_radius=_num("corner_radius"),
    strut_width=_num("strut_width"),
    # operation
    operation=_enum("operation"),
    relief_depth=_num("relief_depth"),
    relief_profile=_enum("relief_profile"),
    # mask
    mask_mode=_enum("mask_mode"),
    mask_v_from=_num("mask_v_from"),
    mask_v_to=_num("mask_v_to"),
    mask_u_center=_num("mask_u_center"),
    mask_u_width=_num("mask_u_width"),
    mask_mirror=st.booleans(),
    mask_feather=_num("mask_feather"),
    # output
    split_halves=st.booleans(),
    seed=st.integers(min_value=0, max_value=2**16),
)


@settings(
    max_examples=EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(params=cover_params)
def test_every_cover_is_printable(params: CoverParams):
    faults = check(params)
    if faults:
        corpus.record(params.clamped().to_dict(), "; ".join(faults))
    assert not faults, f"{faults} for {params.clamped().to_dict()}"


@pytest.mark.parametrize("entry", corpus.load(), ids=lambda e: e["reason"][:60])
def test_known_regressions_stay_fixed(entry):
    params = CoverParams.from_dict(entry["params"])
    assert not check(params)


@pytest.mark.parametrize("preset", PRESETS, ids=lambda p: p.key)
def test_every_preset_builds_and_exports(preset):
    assert not check_and_export(preset.params())


@pytest.mark.parametrize("operation", list(ENUMS["operation"]))
def test_every_operation_is_printable(operation):
    assert not check(CoverParams(operation=operation))


@pytest.mark.parametrize("mode", list(ENUMS["mask_mode"]))
def test_every_mask_mode_is_printable(mode):
    assert not check(CoverParams(mask_mode=mode))


def test_defaults_are_printable():
    assert not check(CoverParams())

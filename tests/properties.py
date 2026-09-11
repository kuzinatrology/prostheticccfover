"""The printability properties, checked the same way for hypothesis and the
regression corpus.

Nothing here reads the generator's own arithmetic back to itself. Struts and
holes are measured on the 3D positions of the boundaries, the wall is probed
by firing rays at the finished mesh, and connectivity comes from the mesh's
own topology.
"""

from __future__ import annotations

import numpy as np

from backend import measure
from backend.export import write
from backend.fields import Fields
from backend.generator import DRAFT, Cover, audit, generate
from backend.params import CoverParams
from backend.generator import placement_for
from backend.pattern import SPAN_VS_CURVATURE, build_cells, build_pattern
from backend.printer_profile import DEFAULT_PROFILE as PROFILE
from backend.surface import Surface

PLANAR_TOLERANCE = 0.95
"""Flattening a curved hole ring shortens it by a couple of percent."""

ENGRAVE_FLOOR = 0.4
"""A groove may not leave the wall thinner than this fraction of itself."""

RAY_TOLERANCE = 0.93
"""Ray probes land between grid lines, where a facetted mesh sits slightly
inside the analytic surface."""


def check(params: CoverParams) -> list[str]:
    """Return every property this parameter set violates. Empty means good."""
    p = params.clamped()
    faults: list[str] = []
    cover: Cover = generate(p, quality=DRAFT)

    # 1. closed, and one piece (two when the user asked for two).
    faults += audit(cover)

    # 5. positive, and lighter than the same shape left plain unless the
    #    operation was adding material rather than taking it away.
    if not cover.volume_mm3 > 0:
        faults.append("volume is not positive")
    if p.cuts_through and cover.holes and cover.volume_mm3 >= cover.plain_volume_mm3:
        faults.append("perforated volume is not below the plain volume")

    surface = Surface.from_params(p)
    if p.operation == "cut":
        faults += _check_cut(p, cover, surface)
    else:
        faults += _check_solid(p, cover, surface)
    return faults


def _check_solid(p: CoverParams, cover: Cover, surface: Surface) -> list[str]:
    faults: list[str] = []
    # 6. nothing goes through the wall: the cover is still one tube with an
    #    opening at each end and no other hole in it.
    if cover.components == 1 and cover.mesh.euler_number != 0:
        faults.append(f"solid shell has euler number {cover.mesh.euler_number}, expected 0")

    # 7. a groove never eats more of the wall than it is allowed to.
    if p.operation == "engrave" and cover.components == 1:
        wall = min(p.wall_thickness, cover.max_wall)
        thickness = measure.wall_thickness_samples(cover.mesh, surface)
        if len(thickness):
            floor = ENGRAVE_FLOOR * wall * RAY_TOLERANCE
            if thickness.min() < floor:
                faults.append(
                    f"engraved wall down to {thickness.min():.2f} mm, floor {floor:.2f} mm"
                )
    return faults


def _check_cut(p: CoverParams, cover: Cover, surface: Surface) -> list[str]:
    faults: list[str] = []
    f = Fields.from_params(p)
    wall = min(p.wall_thickness, cover.max_wall)
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
    pattern = build_pattern(
        cells,
        f.mask,
        profile=PROFILE,
        corner_radius=p.corner_radius,
        quad_segs=DRAFT.quad_segs,
        chord_tolerance=0.05 * strut,
        placement=placement_for(p),
    )
    if not pattern.holes:
        return faults

    # 2. struts are at least as wide as the printer can lay down.
    gap = measure.min_strut(surface, pattern.holes)
    if gap < min(strut, PROFILE.MIN_STRUT) * PLANAR_TOLERANCE:
        faults.append(f"narrowest strut is {gap:.3f} mm, below {strut:.3f} mm")

    spans = measure.hole_spans(surface, pattern.holes)
    if len(spans):
        # 3. no hole spans more than the wall can carry.
        a_max = min(
            PROFILE.max_hole_span(wall),
            SPAN_VS_CURVATURE * surface.min_curvature_radius(),
        )
        if spans.max() > a_max / PLANAR_TOLERANCE:
            faults.append(f"widest hole is {spans.max():.2f} mm, above {a_max:.2f} mm")
        # 4. no hole too small to mean anything.
        if spans.min() < PROFILE.MIN_HOLE * PLANAR_TOLERANCE:
            faults.append(
                f"smallest hole is {spans.min():.2f} mm, below {PROFILE.MIN_HOLE} mm"
            )

    # 8. a masked panel keeps the pattern inside itself.
    if p.mask_mode == "panel":
        share = measure.hole_area(surface, pattern.holes) / measure.surface_area(surface)
        allowed = (p.mask_u_width + 2.0 * p.mask_feather) * (2.0 if p.mask_mirror else 1.0)
        if share > min(allowed, 1.0):
            faults.append(f"panel covers {share:.2f} of the cover, allowed {allowed:.2f}")
    return faults


def check_and_export(params: CoverParams) -> list[str]:
    """Everything above, plus proof that a print file actually comes out."""
    faults = check(params)
    cover = generate(params.clamped(), quality=DRAFT)
    for fmt in ("3mf", "stl"):
        if len(write(cover, fmt)) < 1024:
            faults.append(f"{fmt} export came back empty")
    return faults

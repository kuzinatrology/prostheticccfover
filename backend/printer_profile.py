"""Calibration constants for a physical printer + material combination.

Every number that depends on the machine lives here. Nothing in the geometry
code may hard-code a millimetre value that belongs in this file.

NOTE: all values below are PRELIMINARY. They are educated starting points for a
0.4 mm nozzle on a bedslinger FDM machine and MUST be replaced with measured
values after a calibration print (a plate of struts 0.4-1.6 mm, holes
1.0-4.0 mm, and a three-point bend coupon at each wall thickness).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrinterProfile:
    """One machine + material combination."""

    name: str

    MIN_STRUT: float
    """mm - thinnest strut the machine lays down reliably."""

    MIN_HOLE: float
    """mm - smallest hole that still reads as a hole rather than a blemish."""

    CLEARANCE: float
    """mm - gap left on mating surfaces (used when the cover is split)."""

    MAX_BRIDGE: float
    """mm - longest unsupported span the machine bridges cleanly."""

    STIFFNESS_C: float
    """Dimensionless. Largest hole span a_max = STIFFNESS_C * t**1.5."""

    # --- pattern sizing -------------------------------------------------
    SPACING_HEADROOM: float = 0.95
    """Coarsest seed spacing as a fraction of a_max. Below 1 so subdivision
    stays a rare local correction rather than the main sizing mechanism."""

    SPACING_SLACK: float = 5.0
    """mm added to (MIN_HOLE + strut) to get the finest usable seed spacing."""

    BRIDGE_ARCH_FACTOR: float = 3.0
    """A Voronoi hole is an arch, not a flat bridge: only about a third of its
    span runs near-horizontal at the crown, so the bridging limit applies to
    that fraction of the hole width rather than to the whole span."""

    CURVATURE_SAFETY: float = 0.8
    """Wall may use this fraction of the minimum surface radius of curvature."""

    def max_hole_span(self, wall_thickness: float) -> float:
        """Largest inscribed hole diameter allowed at this wall thickness.

        Two independent ceilings apply and the tighter one wins: plate
        stiffness (deflection grows with span^2 and falls with t^3, giving
        span ~ C * t**1.5) and the machine's bridging limit, relaxed by the
        arch factor because the crown of a hole is not a flat bridge.
        """
        return min(
            self.STIFFNESS_C * wall_thickness**1.5,
            self.BRIDGE_ARCH_FACTOR * self.MAX_BRIDGE,
        )


PLA_04_NOZZLE = PrinterProfile(
    name="0.4 mm nozzle, generic PLA/PETG",
    MIN_STRUT=0.8,
    MIN_HOLE=1.5,
    CLEARANCE=0.3,
    MAX_BRIDGE=12.0,
    STIFFNESS_C=6.0,
)

PROFILES = {PLA_04_NOZZLE.name: PLA_04_NOZZLE}

DEFAULT_PROFILE = PLA_04_NOZZLE

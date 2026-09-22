"""Run every stage in order.  Each stage is also runnable on its own; they
hand results to each other through anatomic/work.

    .venv/bin/python -m anatomic.run_all
"""

from __future__ import annotations

from . import (
    stage1_prepare,
    stage2_sections,
    stage3_profile,
    stage4_surface,
    stage5_flexion,
    stage6_shell,
)

STAGES = [
    ("1  prepare the scan", stage1_prepare.main),
    ("2  knee axis and sections", stage2_sections.main),
    ("3  proportion and style", stage3_profile.main),
    ("4  cover surface", stage4_surface.main),
    ("5  flexion and the notch", stage5_flexion.main),
    ("6  wall, closed mesh, STL", stage6_shell.main),
]


def main() -> None:
    for name, run in STAGES:
        print(f"\n=== stage {name} " + "=" * (50 - len(name)))
        run()


if __name__ == "__main__":
    main()

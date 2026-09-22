"""Stage 5 — does the knee still bend?

The socket turns about the knee axis relative to the shank, so in the shank's
own frame the cover is what swings, into a thigh that stands still.  Only 17 mm
of the knee module is above the axis; everything higher is socket, which is
under shorts on the scan, so the thigh is stood in for by a cylinder sized off
the scan's own girth just above the knee, as agreed.

The cover is swung from 0 to 130 degrees in 5 degree steps.  If it hits, the
back of the rim is taken down 2 mm at a time and the whole sweep is retried,
until it clears — so the notch ends up the smallest one that works, not a
guessed one.

    .venv/bin/python -m anatomic.stage5_flexion
"""

from __future__ import annotations

import json

import numpy as np
import trimesh
from scipy.ndimage import gaussian_filter1d, minimum_filter1d

from . import config, render, stage4_surface, stage6_shell


def thigh_body(prosthesis: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """The stand-in thigh: a body of revolution about the knee axis whose girth
    is the scan's own girth at that height.

    A single cylinder would be both too fat at the knee, where the socket is
    barely wider than the module, and mis-centred higher up, where the scanned
    thigh swings off sideways because the person was sitting.  Taking the
    radius about each section's own centre keeps the girth honest and stands
    the thigh up straight, which is the pose the flexion test needs.
    """
    v = np.asarray(prosthesis.vertices)
    heights = np.arange(0.0, config.THIGH_LENGTH_MM + 10.0, 10.0)
    radii = []
    for z in heights:
        band = v[np.abs(v[:, 2] - z) <= 7.5]
        if len(band) < 20:
            radii.append(np.nan)
            continue
        centre = (band[:, :2].min(axis=0) + band[:, :2].max(axis=0)) / 2
        radii.append(np.linalg.norm(band[:, :2] - centre, axis=1).max())
    radii = np.array(radii)
    if np.isnan(radii[0]):
        raise SystemExit("no scan surface above the knee to size the thigh from")
    known = np.flatnonzero(~np.isnan(radii))
    radii = np.interp(heights, heights[known], radii[known]) + config.THIGH_EXTRA_MM
    # Smoothed, not dilated. Forcing the profile never to narrow going up
    # carries the widest reading all the way to the top, and the scan's widest
    # readings are a seated thigh spread on a chair under loose shorts, which
    # is not what the cover has to miss.
    return heights, gaussian_filter1d(radii, 1.0, mode="nearest")


def flex(points: np.ndarray, degrees: float) -> np.ndarray:
    """Swing the shank back about the knee axis, which is x through the origin."""
    a = np.radians(-degrees)
    rotation = np.array([
        [1, 0, 0],
        [0, np.cos(a), -np.sin(a)],
        [0, np.sin(a), np.cos(a)],
    ])
    return points @ rotation.T


def hits(points: np.ndarray, heights: np.ndarray, radii: np.ndarray) -> int:
    """How many sampled points end up inside the thigh."""
    slack = config.FLEXION_TOLERANCE_MM
    inside = (points[:, 2] > slack) & (points[:, 2] < heights[-1])
    if not inside.any():
        return 0
    allowed = np.interp(points[inside, 2], heights, radii) - slack
    return int((np.linalg.norm(points[inside, :2], axis=1) < allowed).sum())


def maximal_rim(
    zs: np.ndarray, centre: np.ndarray, radius: np.ndarray,
    heights: np.ndarray, radii: np.ndarray, ceiling: float,
    wall: float = config.WALL_THICKNESS_MM,
    flexion_max: float = config.FLEXION_MAX,
) -> np.ndarray:
    """The highest rim the knee still clears, angle by angle.

    Searched rather than guessed, and searched the right way round: instead of
    cutting a notch and testing whether it is deep enough, every point of the
    untrimmed skin is tested, and the rim is put at the last height each column
    survives to. What comes out is the most cover the joint allows.

    It comes out looking like a leg because of how the arithmetic falls: swing
    a point at the front of the knee backwards about the axis and it drops
    *below* the thigh, so the front can be covered to the brim, while a point
    behind the axis rises straight into it. Which is why a foam cosmesis is cut
    away at the back and carries a patella at the front.
    """
    angles = np.radians(np.arange(0.0, flexion_max + config.FLEXION_STEP,
                                  config.FLEXION_STEP))
    theta = np.linspace(-np.pi, np.pi, radius.shape[1], endpoint=False) + np.pi / radius.shape[1]
    # The wall goes inward from this surface, so what the thigh meets is a
    # wall's thickness closer in than the skin.
    inner = radius - wall
    x = centre[:, 0:1] + inner * np.cos(theta)[None, :]
    y = centre[:, 1:2] + inner * np.sin(theta)[None, :]
    z = np.repeat(zs[:, None], radius.shape[1], axis=1)

    slack = config.FLEXION_TOLERANCE_MM
    safe = np.ones(z.shape, dtype=bool)
    for a in angles:
        # The shank swings back about the knee axis, so in its own frame the
        # cover turns and the thigh stands still.
        yy = y * np.cos(a) + z * np.sin(a)
        zz = -y * np.sin(a) + z * np.cos(a)
        into = (zz > slack) & (zz < heights[-1])
        allowed = np.interp(zz, heights, radii) - slack
        safe &= ~(into & (np.hypot(x, yy) < allowed))

    rim = np.empty(radius.shape[1])
    for j in range(radius.shape[1]):
        bad = np.flatnonzero(~safe[:, j])
        top = zs[bad[0] - 1] if len(bad) and bad[0] > 0 else (zs[0] if len(bad) else zs[-1])
        rim[j] = min(top, ceiling) - config.RIM_WALL_MARGIN_MM
    return rim


def smooth_rim(rim: np.ndarray, window: int = config.RIM_SMOOTH_WINDOW) -> np.ndarray:
    """Round the solved rim off without ever raising it.

    Eroded first, then blurred: blurring alone would lift the curve back over
    a dip and put material where the test had just taken it away.
    """
    padded = np.concatenate([rim[-window:], rim, rim[:window]])
    eroded = minimum_filter1d(padded, window, mode="nearest")
    blurred = gaussian_filter1d(eroded, window / 3.0, mode="nearest")
    return np.minimum(blurred[window:-window], rim)


def sweep(
    mesh: trimesh.Trimesh, heights: np.ndarray, radii: np.ndarray,
    flexion_max: float = config.FLEXION_MAX,
) -> list[dict]:
    v = np.asarray(mesh.vertices)
    samples = np.vstack([v, v[np.asarray(mesh.faces)].mean(axis=1)])
    rows = []
    for angle in np.arange(0.0, flexion_max + config.FLEXION_STEP, config.FLEXION_STEP):
        count = hits(flex(samples, angle), heights, radii)
        rows.append({"angle": float(angle), "collision": bool(count), "points_inside": count})
    return rows


def main() -> None:
    prosthesis = trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False)
    heights, radii = thigh_body(prosthesis)

    # Solve the rim on the untrimmed skin, then build the cover to it.
    base = stage4_surface.build(top_z=config.COVER_TOP_LIMIT)
    solved = maximal_rim(
        base["zs"], base["centre"], base["radius"], heights, radii, config.COVER_TOP_Z
    )
    rim = smooth_rim(solved)
    built = stage4_surface.build(top_z=config.COVER_TOP_Z, rim=rim)
    rows = sweep(stage6_shell.shell(built["grid"], config.WALL_THICKNESS_MM), heights, radii)

    angles = stage4_surface.ANGLES
    def at(deg: float) -> float:
        a = np.radians(deg)
        a = a if a <= np.pi else a - 2 * np.pi
        return round(float(np.interp(a, angles, rim)), 1)

    report = {
        "thigh_radius_at_knee_mm": round(float(radii[0]), 1),
        "thigh_radius_max_mm": round(float(radii.max()), 1),
        "rim": {"lateral": at(0), "front": at(90), "medial": at(180), "back": at(270),
                "back_lateral": at(315), "back_medial": at(225)},
        "rim_highest_mm": round(float(rim.max()), 1),
        "rim_lowest_mm": round(float(rim.min()), 1),
        "covers_knee": bool(rim.max() > 0.0),
        "knee_covered_over_deg": round(float(100.0 * (rim > 0).mean()), 1),
        "sweep": rows,
    }
    (config.WORK / "stage5.json").write_text(json.dumps(report, indent=2))
    np.save(config.WORK / "stage5_rim.npy", rim)
    stage4_surface.build(top_z=config.COVER_TOP_Z, rim=rim)["mesh"].export(
        config.WORK / "stage5_surface.stl"
    )

    draw(built, heights, radii)
    write_table(report)
    print(json.dumps({k: v for k, v in report.items() if k != "sweep"}, indent=2))
    print("collisions:", sum(r["collision"] for r in rows), "of", len(rows))


def draw(built: dict, heights: np.ndarray, radii: np.ndarray) -> None:
    cover = built["mesh"]
    angles = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    ring = np.stack([np.cos(angles), np.sin(angles)], -1)
    grid = np.stack([
        np.concatenate([ring * r, np.full((len(ring), 1), z)], axis=1)
        for z, r in zip(heights, radii)
    ])
    tv, tf = stage4_surface.loft(grid)

    angles = (0.0, 90.0, config.FLEXION_MAX)
    swung = [flex(np.asarray(cover.vertices), a) for a in angles]
    everything = np.vstack(swung + [tv])
    bounds = (everything.min(axis=0), everything.max(axis=0))

    paths = []
    for angle, v in zip(angles, swung):
        path = config.RENDERS / f"stage5_{angle:.0f}deg.png"
        render.render(
            [(tv, tf, config.PART_COLOURS["knee"]), (v, np.asarray(cover.faces), config.PART_COLOURS["socket"])],
            "side", path, bounds=bounds, height=900,
            labels=[((0, 0, 0), "knee axis", (185, 40, 30))],
            title=f"stage 5 — flexion {angle:.0f} deg",
        )
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage5_sheet.png", columns=3)


def write_table(report: dict) -> None:
    r = report["rim"]
    lines = [
        "# Этап 5 — сгибание и форма кромки",
        "",
        "Бедро заменено телом вращения вокруг оси колена: радиус на каждой высоте",
        "снят со скана вокруг собственного центра сечения плюс "
        f"{config.THIGH_EXTRA_MM:.0f} мм запаса. У колена "
        f"{report['thigh_radius_at_knee_mm']} мм, наверху "
        f"{report['thigh_radius_max_mm']} мм.",
        "",
        "Кромка не подбирается, а решается: каждая точка несрезанной поверхности",
        "прогоняется через все углы сгибания, и кромка ставится на последнюю",
        "высоту, которую столбец переживает. Получается максимум оболочки,",
        "который допускает сустав.",
        "",
        "| где | высота кромки, мм |",
        "|---|---|",
        f"| перёд | **{r['front']:+.0f}** |",
        f"| медиально | {r['medial']:+.0f} |",
        f"| латерально | {r['lateral']:+.0f} |",
        f"| зад-медиально | {r['back_medial']:+.0f} |",
        f"| **зад** | **{r['back']:+.0f}** |",
        f"| зад-латерально | {r['back_lateral']:+.0f} |",
        "",
        f"Колено закрыто на {report['knee_covered_over_deg']:.0f}% окружности "
        "(кромка выше оси колена).",
        "",
        "| угол | пересечение | точек внутри |",
        "|---|---|---|",
    ]
    for row in report["sweep"]:
        lines.append(
            f"| {row['angle']:.0f}° | {'ДА' if row['collision'] else 'нет'} | {row['points_inside']} |"
        )
    (config.RENDERS / "stage5_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

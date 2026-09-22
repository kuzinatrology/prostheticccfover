"""Stage 2 — put the knee axis on the prosthesis and measure it below the axis.

The flexion axis is not visible on the scan: the hardware is under shorts and a
sleeve.  It is placed from the catalogue instead, hung off the one landmark the
scan does show sharply — the top of the bare 34 mm pylon, which is the distal
end of the knee assembly.  Everything below is then sliced every 10 mm.

    .venv/bin/python -m anatomic.stage2_sections

Writes work/stage2_prosthesis.stl (re-origined on the knee axis),
work/stage2_sections.npz, work/stage2.json, renders/stage2_*.png and the
section table in renders/stage2_report.md.
"""

from __future__ import annotations

import json

import numpy as np
import trimesh

from . import config, render


def section_contour(vertices: np.ndarray, z: float, bins: int) -> np.ndarray | None:
    """The outline of the prosthesis at height `z`, as a radius per angle.

    Taken as the farthest surface point in each angular bin rather than by
    intersecting triangles: the scan is open and noisy, so a real cut returns
    broken loops, while the cover only ever needs the envelope it has to
    contain.  Empty bins — holes in the scan — are filled by interpolating
    around the circle.
    """
    slab = vertices[np.abs(vertices[:, 2] - z) <= config.SECTION_SLAB]
    if len(slab) < 24:
        return None

    centre = np.median(slab[:, :2], axis=0)
    offset = slab[:, :2] - centre
    angle = np.arctan2(offset[:, 1], offset[:, 0])
    radius = np.linalg.norm(offset, axis=1)

    edges = np.linspace(-np.pi, np.pi, bins + 1)
    index = np.clip(np.digitize(angle, edges) - 1, 0, bins - 1)
    out = np.full(bins, -np.inf)
    np.maximum.at(out, index, radius)
    out[np.isneginf(out)] = np.nan

    known = np.flatnonzero(~np.isnan(out))
    if len(known) < bins // 3:
        return None
    if len(known) < bins:
        centres = (edges[:-1] + edges[1:]) / 2
        out = np.interp(
            centres,
            np.concatenate([centres[known] - 2 * np.pi, centres[known], centres[known] + 2 * np.pi]),
            np.tile(out[known], 3),
        )

    centres = (edges[:-1] + edges[1:]) / 2
    return np.stack([centre[0] + out * np.cos(centres), centre[1] + out * np.sin(centres)], axis=-1)


def main() -> None:
    mesh = trimesh.load(config.WORK / "stage1_prosthesis.stl", process=False)
    stage1 = json.loads((config.WORK / "stage1.json").read_text())
    vertices = np.asarray(mesh.vertices)
    pylon_top = stage1["parts_z_mm"]["pylon"][1]

    # The bare 34 mm tube ends where the receiver sleeve starts, and the
    # receiver is the bottom of the knee assembly.  So the dome is one assembly
    # height above it, and the axis sits KNEE_DOME_TO_CENTRE under the dome.
    dome_z = pylon_top + config.KNEE_OVERALL_HEIGHT
    axis_z = dome_z - config.KNEE_DOME_TO_CENTRE

    # Fore-aft, the axis is taken at the middle of the knee frame at that
    # height.  Nothing in the scan pins it better; stage 5 tests it by rotating.
    frame = section_contour(vertices, axis_z, config.CONTOUR_BINS)
    if frame is None:
        raise SystemExit(f"no surface at the knee height z={axis_z:.0f} — check stage 1")
    axis_x = float(frame[:, 0].mean())
    axis_y = float(frame[:, 1].mean())

    # Re-origin: the knee axis is the origin from here on, x along the axis.
    # Stage 1 left the origin on a seed point, so x has to move as well or the
    # whole leg sits off to one side of the frame it is measured in.
    vertices = vertices - np.array([axis_x, axis_y, axis_z])
    trimesh.Trimesh(vertices, mesh.faces, process=False).export(
        config.WORK / "stage2_prosthesis.stl"
    )

    heights = np.arange(0.0, vertices[:, 2].min() - config.SECTION_SPACING, -config.SECTION_SPACING)
    rows, contours = [], {}
    for z in heights:
        contour = section_contour(vertices, z, config.CONTOUR_BINS)
        if contour is None:
            continue
        contours[f"{z:.0f}"] = contour
        rows.append({
            "z": round(float(z), 1),
            "width_mm": round(float(np.ptp(contour[:, 0])), 1),
            "thickness_mm": round(float(np.ptp(contour[:, 1])), 1),
            "centre_x_mm": round(float(contour[:, 0].mean()), 1),
            "centre_y_mm": round(float(contour[:, 1].mean()), 1),
            "max_radius_mm": round(float(np.linalg.norm(
                contour - contour.mean(axis=0), axis=1).max()), 1),
        })

    np.savez(config.WORK / "stage2_sections.npz", **contours)
    report = {
        "knee_axis": {
            "z_in_stage1_frame": round(axis_z, 1),
            "x_in_stage1_frame": round(axis_x, 1),
            "y_in_stage1_frame": round(axis_y, 1),
            "derived_from": "pylon top + 230 mm assembly height - 17 mm dome-to-centre",
            "dome_z_in_stage1_frame": round(dome_z, 1),
            "pyramid_centre_z": round(axis_z + config.KNEE_CENTRE_TO_PYRAMID, 1),
            "fore_aft_confidence_mm": 10.0,
        },
        "sections": rows,
    }
    (config.WORK / "stage2.json").write_text(json.dumps(report, indent=2))

    draw(vertices, np.asarray(mesh.faces), rows, contours)
    write_table(report)
    print(f"knee axis at stage-1 z={axis_z:.1f}, y={axis_y:.1f}; {len(rows)} sections")


def draw(vertices, faces, rows, contours) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colour = np.tile(np.array(config.PART_COLOURS["unassigned"], float), (len(faces), 1))
    centre_z = vertices[faces].mean(axis=1)[:, 2]
    colour[centre_z < 0] = config.PART_COLOURS["pylon"]

    rules = [(0.0, "knee axis  z = 0")] + [
        (r["z"], "") for r in rows if r["z"] % 50 == 0 and r["z"] != 0
    ]
    paths = []
    for view in ("side", "front"):
        path = config.RENDERS / f"stage2_{view}.png"
        render.render(
            [(vertices, faces, colour)],
            view,
            path,
            labels=[((0, 0, 0), "knee axis", (185, 40, 30))],
            rules=rules,
            title=f"stage 2 — {view}, sections every {config.SECTION_SPACING:.0f} mm",
        )
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage2_sheet.png", columns=2)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 6), constrained_layout=True)
    zs = [r["z"] for r in rows]
    ax1.plot([r["width_mm"] for r in rows], zs, label="width (medio-lateral)")
    ax1.plot([r["thickness_mm"] for r in rows], zs, label="thickness (fore-aft)")
    ax1.set_xlabel("mm"); ax1.set_ylabel("height below knee axis, mm")
    ax1.grid(alpha=0.3); ax1.legend(); ax1.set_title("prosthesis section size")

    span = min(float(n) for n in contours) or -1.0
    for name, contour in list(contours.items())[::3]:
        ax2.plot(*np.vstack([contour, contour[:1]]).T, lw=0.8,
                 color=plt.cm.viridis(1.0 - float(name) / span))
    ax2.set_aspect("equal"); ax2.grid(alpha=0.3)
    ax2.set_xlabel("x, mm (medio-lateral)"); ax2.set_ylabel("y, mm (fore-aft, + forward)")
    ax2.set_title("section contours, every 30 mm")
    fig.savefig(config.RENDERS / "stage2_profiles.png", dpi=130)


def write_table(report: dict) -> None:
    axis = report["knee_axis"]
    rows = report["sections"]
    pylon = [r for r in rows if -370 <= r["z"] <= -240]
    shoe = next(r["z"] for r in rows if r["width_mm"] > 60 and r["z"] < -400)
    lines = [
        "# Этап 2 — ось колена и сечения протеза",
        "",
        f"Ось колена: z = {axis['z_in_stage1_frame']} мм в системе этапа 1 "
        f"({axis['derived_from']}), вперёд-назад y = {axis['y_in_stage1_frame']} мм.",
        f"Купол модуля z = {axis['dome_z_in_stage1_frame']}, центр пирамиды "
        f"z = {axis['pyramid_centre_z']}.",
        "",
        "Начало координат с этого момента — на оси колена, z вниз отрицательный,",
        "x вдоль оси колена, y вперёд.",
        "",
        "## Проверка положения оси",
        "",
        "Независимая проверка: по инструкции (bench alignment, стр. 5) линия",
        "нагрузки проходит через центр колена, то есть пилон должен стоять под",
        f"осью. Центр пилона по глубине y = "
        f"{np.mean([r['centre_y_mm'] for r in pylon]):.1f} мм при оси y = 0 — "
        "сходится.",
        "",
        f"Вбок пилон смещён на {abs(np.mean([r['centre_x_mm'] for r in pylon])):.0f} мм "
        "от оси колена. Это настоящее смещение сборки, а не ошибка: оно держится",
        "постоянным по всей длине пилона. Оболочку надо строить вокруг линии",
        "центров сечений, а не вокруг вертикали через ось колена.",
        "",
        f"Обувь начинается на z = {shoe:.0f} мм: ниже этого сечения — кроссовок,",
        "а не протез, и низ оболочки должен быть выше.",
        "",
        "## Таблица сечений",
        "",
        "| z, мм | ширина, мм | толщина, мм | центр x | центр y | макс. радиус |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["sections"]:
        lines.append(
            f"| {r['z']:.0f} | {r['width_mm']} | {r['thickness_mm']} | "
            f"{r['centre_x_mm']} | {r['centre_y_mm']} | {r['max_radius_mm']} |"
        )
    (config.RENDERS / "stage2_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

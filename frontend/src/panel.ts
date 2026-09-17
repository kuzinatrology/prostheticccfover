/**
 * The order form.
 *
 * Every row is a label, a reading, and a control: either a hairline rule that
 * doubles as a slider, or a strip of choices. No string in this file — they
 * all come from strings.en.ts, and an empty one means the element is never
 * created.
 *
 * A preset moves the sliders and then gets out of the way. Nothing is locked
 * afterwards, because starting somewhere is the point.
 */

import type { MaterialSpec, Params, PresetSpec, Range, Schema, Silhouette, Stats } from "./api";
import { thumbnail } from "./presets";
import { has } from "./strings.en";
import { strings } from "./i18n";

const LOG_STEPS = 1000;

interface Group {
  key: keyof typeof strings.groups;
  params?: string[];
  choices?: string[];
  toggles?: string[];
  /** Named block of extra content, built by a dedicated method. */
  block?: "materials" | "motif";
  /** Shown only while this returns true. */
  when?: (p: Params) => boolean;
}

const RELIEF = (p: Params) => p.operation === "emboss" || p.operation === "engrave";
const CUTS = (p: Params) => p.operation === "cut";
const PATTERNED = (p: Params) => p.operation !== "none";
/** A picture only has anywhere to go when the pattern is cut through. */
const MOTIF = (p: Params) => p.operation === "cut" && p.hole_shape === "image";
const CELLS = (p: Params) => p.operation === "cut" && p.hole_shape !== "image";

const GROUPS: Group[] = [
  {
    key: "limb",
    params: ["length", "knee_diameter", "ankle_diameter", "calf_bulge", "calf_position", "posterior_bias"],
  },
  { key: "section", params: ["ovality", "section_squareness", "twist"] },
  { key: "shell", params: ["wall_thickness"] },
  {
    key: "pattern",
    choices: ["operation", "hole_shape"],
    block: "motif",
    params: ["threshold_bias", "motif_smoothing"],
    toggles: ["motif_invert"],
  },
  {
    key: "pattern",
    choices: [],
    params: [
      "pattern_density",
      "density_gradient",
      "irregularity",
      "anisotropy",
      "flow_angle",
      "corner_radius",
      "strut_width",
      "motif_fill",
      "motif_rotation",
      "motif_rotation_jitter",
      "motif_scale_jitter",
    ],
    toggles: ["motif_align_flow"],
    when: PATTERNED,
  },
  { key: "relief", choices: ["relief_profile"], params: ["relief_depth"], when: RELIEF },
  {
    key: "mask",
    choices: ["mask_mode"],
    params: ["mask_v_from", "mask_v_to", "mask_u_center", "mask_u_width", "mask_feather"],
    toggles: ["mask_mirror"],
    when: PATTERNED,
  },
  {
    key: "finish",
    choices: ["finish"],
    params: ["facet_scale"],
    toggles: ["split_halves"],
    block: "materials",
  },
];

/** Rows that only make sense under some other setting. */
const ROW_WHEN: Record<string, (p: Params) => boolean> = {
  corner_radius: CELLS,
  strut_width: CUTS,
  hole_shape: CUTS,
  threshold_bias: MOTIF,
  motif_smoothing: MOTIF,
  motif_invert: MOTIF,
  motif_fill: MOTIF,
  motif_rotation: MOTIF,
  motif_rotation_jitter: MOTIF,
  motif_scale_jitter: MOTIF,
  motif_align_flow: MOTIF,
  mask_v_from: (p) => p.mask_mode !== "full",
  mask_v_to: (p) => p.mask_mode !== "full",
  mask_u_center: (p) => p.mask_mode === "panel",
  mask_u_width: (p) => p.mask_mode === "panel" || p.mask_mode === "stripes",
  mask_feather: (p) => p.mask_mode !== "full",
  mask_mirror: (p) => p.mask_mode === "panel",
  facet_scale: (p) => p.finish === "faceted",
  relief_profile: RELIEF,
  operation: () => true,
};

function tag<K extends keyof HTMLElementTagNameMap>(
  name: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function decimals(step: number): number {
  if (step >= 1) return 0;
  if (step >= 0.1) return 1;
  return 2;
}

export interface PanelHandlers {
  onParam(key: string, value: number, live: boolean): void;
  onChoice(key: string, value: string): void;
  onToggle(key: string, value: boolean): void;
  onMaterial(key: string, second: boolean): void;
  onPreset(preset: PresetSpec): void;
  onDownload(fmt: string): void;
  onPicture(file: File): void;
}

export class Panel {
  private sliders = new Map<string, HTMLInputElement>();
  private values = new Map<string, HTMLElement>();
  private rows = new Map<string, HTMLElement>();
  private choices = new Map<string, Map<string, HTMLElement>>();
  private toggles = new Map<string, HTMLElement>();
  private swatches = new Map<string, HTMLElement>();
  private secondSwatches = new Map<string, HTMLElement>();
  private blocks: { node: HTMLElement; when: (p: Params) => boolean }[] = [];
  private presetTiles = new Map<string, HTMLElement>();
  private labels = new Map<string, HTMLElement>();
  private picture!: HTMLInputElement;
  private pictureButton!: HTMLButtonElement;
  private silhouette!: HTMLElement;
  private silhouetteNote!: HTMLElement;
  private loaded = false;
  private progress!: HTMLElement;
  private readouts = new Map<string, HTMLElement>();
  private summaryLabel!: HTMLElement;
  private summaryUnit!: HTMLElement;
  private notes!: HTMLElement;
  private notesHeading: HTMLElement | null = null;
  private materialLine!: HTMLElement;
  private materialDensity!: HTMLElement;
  private download!: HTMLButtonElement;
  private status!: HTMLElement;

  constructor(
    private root: HTMLElement,
    private schema: Schema,
    private handlers: PanelHandlers,
  ) {
    this.build();
  }

  /** Rebuild labels and controls after a locale change without changing parameters. */
  refreshStrings(): void {
    this.sliders.clear();
    this.values.clear();
    this.rows.clear();
    this.choices.clear();
    this.toggles.clear();
    this.swatches.clear();
    this.secondSwatches.clear();
    this.blocks = [];
    this.presetTiles.clear();
    this.labels.clear();
    this.readouts.clear();
    this.root.replaceChildren();
    this.build();
  }

  private build(): void {
    this.progress = tag("div", "progress");
    this.progress.append(tag("div", "progress-bar"));
    this.root.append(this.progress);
    this.root.append(this.presetStrip());

    const seen = new Set<string>();
    for (const group of GROUPS) {
      const block = tag("div", "block");
      // A group that only continues the one above it repeats no heading.
      const heading = seen.has(group.key) ? "" : strings.groups[group.key];
      seen.add(group.key);
      if (has(heading)) block.append(tag("p", "group", heading));
      for (const key of group.choices ?? []) block.append(this.choiceRow(key));
      if (group.block === "motif") block.append(this.pictureBlock());
      for (const key of group.params ?? []) block.append(this.row(key));
      for (const key of group.toggles ?? []) block.append(this.toggle(key));
      if (group.block === "materials") block.append(this.materials());
      this.root.append(block);
      if (group.when) this.blocks.push({ node: block, when: group.when });
    }

    this.root.append(this.readout());
    this.root.append(this.footer());
  }

  // --- presets ---------------------------------------------------------

  private presetStrip(): HTMLElement {
    const box = tag("div", "presets");
    if (has(strings.presets.heading)) {
      box.append(tag("p", "group group-first", strings.presets.heading));
    }
    const strip = tag("div", "preset-strip");
    for (const preset of this.schema.presets) {
      const tile = tag("button", "preset") as HTMLButtonElement;
      tile.type = "button";
      const art = tag("span", "preset-art");
      art.innerHTML = thumbnail(preset.key);
      tile.append(art, tag("span", "preset-name", preset.label));
      tile.title = preset.note;
      tile.addEventListener("click", () => this.handlers.onPreset(preset));
      this.presetTiles.set(preset.key, tile);
      strip.append(tile);
    }
    box.append(strip);
    return box;
  }

  // --- a parameter row -------------------------------------------------

  private row(key: string): HTMLElement {
    const range = this.schema.ranges[key];
    const row = tag("div", "row");
    const head = tag("div", "row-head");

    const label = strings.params[key];
    if (has(label)) {
      const node = tag("span", "row-label", label);
      head.append(node);
      this.labels.set(key, node);
    }

    const value = tag("span", "row-value");
    const unit = strings.units[range.unit] ?? "";
    value.append(tag("span", "row-number"));
    if (has(unit)) {
      // A degree sign hugs its number; a word-unit gets a space.
      value.append(tag("span", /^[a-z]/i.test(unit) ? "row-unit" : "row-unit row-unit-tight", unit));
    }
    head.append(value);
    this.values.set(key, value.firstElementChild as HTMLElement);

    const track = tag("div", "track");
    const slider = tag("input", "slider") as HTMLInputElement;
    slider.type = "range";
    if (range.scale === "log") {
      slider.min = "0";
      slider.max = String(LOG_STEPS);
      slider.step = "1";
    } else {
      slider.min = String(range.lo);
      slider.max = String(range.hi);
      slider.step = String(range.step);
    }
    if (has(label)) slider.setAttribute("aria-label", label);
    const read = () => this.read(key);
    slider.addEventListener("input", () => {
      this.paint(key, read());
      this.handlers.onParam(key, read(), true);
    });
    slider.addEventListener("change", () => this.handlers.onParam(key, read(), false));
    this.sliders.set(key, slider);

    track.append(slider);
    row.append(head, track);
    this.rows.set(key, row);
    return row;
  }

  /** A slider on a log scale carries a position, not the value itself. */
  private read(key: string): number {
    const range = this.schema.ranges[key];
    const slider = this.sliders.get(key)!;
    const raw = Number(slider.value);
    if (range.scale !== "log") return raw;
    const lo = Math.max(range.lo, 1e-6);
    return lo * Math.pow(Number(slider.max) > 0 ? range.hi / lo : 1, raw / LOG_STEPS);
  }

  private position(key: string, value: number): number {
    const range = this.schema.ranges[key];
    if (range.scale !== "log") return value;
    const lo = Math.max(range.lo, 1e-6);
    return (Math.log(Math.max(value, lo) / lo) / Math.log(range.hi / lo)) * LOG_STEPS;
  }

  private choiceRow(key: string): HTMLElement {
    const spec = strings.choices[key];
    const row = tag("div", "row");
    if (spec && has(spec.label)) {
      const head = tag("div", "row-head");
      head.append(tag("span", "row-label", spec.label));
      row.append(head);
    }
    const strip = tag("div", "choice");
    const buttons = new Map<string, HTMLElement>();
    for (const option of this.schema.enums[key] ?? []) {
      const text = spec?.options[option] ?? "";
      if (!has(text)) continue;
      const button = tag("button", "choice-option", text) as HTMLButtonElement;
      button.type = "button";
      button.addEventListener("click", () => this.handlers.onChoice(key, option));
      buttons.set(option, button);
      strip.append(button);
    }
    this.choices.set(key, buttons);
    row.append(strip);
    this.rows.set(key, row);
    return row;
  }

  private toggle(key: string): HTMLElement {
    const label = strings.toggles[key];
    const wrap = tag("label", "toggle");
    const input = tag("input") as HTMLInputElement;
    input.type = "checkbox";
    if (has(label)) {
      wrap.append(tag("span", "toggle-label", label));
      input.setAttribute("aria-label", label);
    }
    wrap.append(input, tag("span", "toggle-box"));
    input.addEventListener("change", () => {
      wrap.classList.toggle("toggle-on", input.checked);
      this.handlers.onToggle(key, input.checked);
    });
    this.toggles.set(key, wrap);
    this.rows.set(key, wrap);
    return wrap;
  }

  // --- the picture -----------------------------------------------------

  /** The drop zone and, beside it, the shape that was read out of the file.
   *
   *  The preview is not decoration. Without it the upload is a black box: a
   *  cover comes back carrying something that does not look like the picture
   *  and there is no way to tell whether the threshold missed or the picture
   *  was wrong. With it the answer is on screen before anything is cut, and
   *  the threshold slider is two seconds away.
   */
  private pictureBlock(): HTMLElement {
    const box = tag("div", "picture");

    this.picture = tag("input") as HTMLInputElement;
    this.picture.type = "file";
    this.picture.accept = "image/png,image/jpeg,image/webp,image/svg+xml";
    this.picture.hidden = true;
    this.picture.addEventListener("change", () => {
      const file = this.picture.files?.[0];
      if (file) this.handlers.onPicture(file);
      this.picture.value = "";
    });

    const drop = tag("div", "drop");
    this.pictureButton = tag("button", "drop-button", strings.motif.choose) as HTMLButtonElement;
    this.pictureButton.type = "button";
    this.pictureButton.addEventListener("click", () => this.picture.click());
    drop.append(this.pictureButton);
    if (has(strings.motif.hint)) drop.append(tag("p", "drop-hint", strings.motif.hint));

    // Dropping a file on the zone is the same act as choosing one.
    for (const name of ["dragenter", "dragover"]) {
      drop.addEventListener(name, (e) => {
        e.preventDefault();
        drop.classList.add("drop-over");
      });
    }
    for (const name of ["dragleave", "drop"]) {
      drop.addEventListener(name, () => drop.classList.remove("drop-over"));
    }
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      const file = (e as DragEvent).dataTransfer?.files?.[0];
      if (file) this.handlers.onPicture(file);
    });

    this.silhouette = tag("div", "silhouette");
    const pair = tag("div", "picture-pair");
    pair.append(drop, this.silhouette);
    this.silhouetteNote = tag("p", "picture-note", "");
    this.silhouetteNote.hidden = true;
    box.append(this.picture, pair, this.silhouetteNote);
    this.blocks.push({ node: box, when: MOTIF });
    return box;
  }

  /** Draw the outlines the server read, black on paper, in the unit square. */
  setSilhouette(shape: Silhouette | null, message: string): void {
    this.loaded = shape !== null;
    this.pictureButton.textContent = this.loaded
      ? strings.motif.replace
      : strings.motif.choose;
    this.silhouetteNote.textContent = message;
    this.silhouetteNote.hidden = !has(message);
    if (!shape) {
      this.silhouette.replaceChildren();
      return;
    }
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "-0.55 -0.55 1.1 1.1");
    if (has(strings.motif.previewLabel)) {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", strings.motif.previewLabel);
    }
    // The motif has y running up, the way the cover does; the screen does not.
    const group = document.createElementNS(ns, "g");
    group.setAttribute("transform", "scale(1,-1)");
    for (const d of shape.paths) {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", d);
      group.append(path);
    }
    svg.append(group);
    this.silhouette.replaceChildren(svg);
  }

  // --- material --------------------------------------------------------

  private materials(): HTMLElement {
    const section = tag("div", "materials");
    if (has(strings.material.heading)) {
      section.append(tag("p", "group", strings.material.heading));
    }
    section.append(this.swatchGrid(this.swatches, false));

    const line = tag("div", "material-line");
    this.materialLine = tag("span", "material-name");
    this.materialDensity = tag("span", "material-density");
    line.append(this.materialLine, this.materialDensity);
    section.append(line);

    const second = tag("div", "block");
    if (has(strings.material.secondHeading)) {
      second.append(tag("p", "group", strings.material.secondHeading));
    }
    second.append(this.swatchGrid(this.secondSwatches, true));
    section.append(second);
    this.blocks.push({ node: second, when: (p) => p.finish === "gradient" });
    return section;
  }

  private swatchGrid(into: Map<string, HTMLElement>, second: boolean): HTMLElement {
    const grid = tag("div", "swatches");
    for (const m of this.schema.materials) {
      const chip = tag("button", "swatch") as HTMLButtonElement;
      chip.type = "button";
      chip.style.setProperty("--chip", m.hex);
      chip.setAttribute("aria-label", m.label);
      chip.addEventListener("click", () => this.handlers.onMaterial(m.key, second));
      into.set(m.key, chip);
      grid.append(chip);
    }
    return grid;
  }

  // --- readings ---------------------------------------------------------

  private readout(): HTMLElement {
    const box = tag("div", "readout");
    for (const [key, label] of [
      ["holes", strings.readout.holes],
      ["triangles", strings.readout.triangles],
    ] as [string, string][]) {
      if (!has(label)) continue;
      const row = tag("div", "readout-row");
      row.append(tag("span", "readout-label", label));
      const value = tag("span", "readout-value");
      const number = tag("span", "readout-number");
      value.append(number);
      row.append(value);
      this.readouts.set(key, number);
      box.append(row);
    }
    this.blocks.push({ node: box, when: CUTS });
    return box;
  }

  /** The order form's total line, and the button that acts on it. */
  private footer(): HTMLElement {
    const box = tag("div", "footer");

    const notes = tag("div", "notes");
    if (has(strings.notes.heading)) {
      this.notesHeading = tag("p", "notes-heading", strings.notes.heading);
      notes.append(this.notesHeading);
    }
    this.notes = tag("div", "note-list");
    notes.append(this.notes);
    notes.hidden = true;
    box.append(notes);

    const summary = tag("div", "summary");
    if (has(strings.readout.mass)) {
      const cell = tag("div", "summary-cell summary-lead");
      cell.append(tag("span", "readout-label", strings.readout.mass));
      const value = tag("span", "readout-value");
      const number = tag("span", "readout-number");
      value.append(number);
      if (has(strings.readout.massUnit)) {
        value.append(tag("span", "readout-unit", strings.readout.massUnit));
      }
      cell.append(value);
      this.readouts.set("mass", number);
      summary.append(cell);
    }
    if (has(strings.readout.saving) || has(strings.readout.added)) {
      const cell = tag("div", "summary-cell");
      this.summaryLabel = tag("span", "readout-label");
      const value = tag("span", "readout-value");
      const number = tag("span", "readout-number");
      this.summaryUnit = tag("span", "readout-unit");
      value.append(number, this.summaryUnit);
      cell.append(this.summaryLabel, value);
      this.readouts.set("balance", number);
      summary.append(cell);
    }
    box.append(summary);

    // The empty-string rule holds for controls too: clear the label and the
    // button goes with it, rather than leaving a blank slab of accent colour.
    this.download = tag("button", "download", strings.actions.download) as HTMLButtonElement;
    this.download.type = "button";
    this.download.addEventListener("click", () =>
      this.handlers.onDownload(this.schema.formats[0]),
    );
    if (has(strings.actions.download)) box.append(this.download);

    const secondary = this.schema.formats[1];
    if (secondary && has(strings.actions.formatSecondary)) {
      const alt = tag("button", "alt-format", strings.actions.formatSecondary);
      alt.type = "button";
      alt.addEventListener("click", () => this.handlers.onDownload(secondary));
      box.append(alt);
    }
    if (has(strings.actions.formatHint)) {
      box.append(tag("p", "format-hint", strings.actions.formatHint));
    }
    this.status = tag("p", "status", "");
    this.status.hidden = true;
    box.append(this.status);
    return box;
  }

  // --- state in ---------------------------------------------------------

  setParams(params: Params, preset: string | null = null): void {
    for (const [key, slider] of this.sliders) {
      const value = Number(params[key]);
      slider.value = String(this.position(key, value));
      this.paint(key, value);
    }
    for (const [key, buttons] of this.choices) {
      for (const [option, node] of buttons) {
        node.classList.toggle("choice-on", params[key] === option);
      }
    }
    for (const [key, wrap] of this.toggles) {
      const on = Boolean(params[key]);
      (wrap.querySelector("input") as HTMLInputElement).checked = on;
      wrap.classList.toggle("toggle-on", on);
    }
    this.setMaterial(String(params.material), String(params.colour_b));
    this.applyLabels(params);
    this.applyVisibility(params, preset);
  }

  /** A slider that means something else under a picture says so. */
  private applyLabels(params: Params): void {
    const image = MOTIF(params);
    for (const [key, node] of this.labels) {
      const swapped = image ? strings.paramsImage[key] : undefined;
      node.textContent = has(swapped) ? swapped : strings.params[key];
    }
  }

  /** Hide what the current operation has nothing to say about. */
  private applyVisibility(params: Params, preset: string | null): void {
    for (const { node, when } of this.blocks) node.hidden = !when(params);
    for (const [key, row] of this.rows) {
      const rule = ROW_WHEN[key];
      if (rule) row.hidden = !rule(params);
    }
    // A tile stays lit only while the design still is that preset. Editing
    // anything moves the design on, and the strip says so.
    for (const [key, tile] of this.presetTiles) {
      tile.classList.toggle("preset-on", preset === key);
    }
  }

  private paint(key: string, value: number): void {
    const range = this.schema.ranges[key];
    const slider = this.sliders.get(key)!;
    const declared = range.hi - range.lo;
    if (range.scale === "log") {
      slider.style.setProperty("--fill", `${(this.position(key, value) / LOG_STEPS) * 100}%`);
      (slider.parentElement as HTMLElement).style.setProperty("--cap", "100%");
    } else {
      const reach = Number(slider.max);
      const usable = reach - range.lo;
      // The control only spans as far as the geometry allows. The rest of the
      // row keeps its dashes, so a shortened range is visible rather than felt.
      slider.style.setProperty(
        "--fill",
        usable > 0 ? `${((value - range.lo) / usable) * 100}%` : "0%",
      );
      (slider.parentElement as HTMLElement).style.setProperty(
        "--cap",
        declared > 0 ? `${(usable / declared) * 100}%` : "100%",
      );
    }
    this.values.get(key)!.textContent = value.toFixed(decimals(range.step));
  }

  /** A slider stops where the geometry says it must. */
  setCap(key: string, cap: number): void {
    const slider = this.sliders.get(key);
    if (!slider || this.schema.ranges[key].scale === "log") return;
    slider.max = String(cap);
    this.paint(key, Math.min(this.read(key), cap));
  }

  setMaterial(key: string, second: string): void {
    for (const [k, chip] of this.swatches) chip.classList.toggle("swatch-on", k === key);
    for (const [k, chip] of this.secondSwatches) {
      chip.classList.toggle("swatch-on", k === second);
    }
    const spec = this.schema.materials.find((m) => m.key === key);
    if (!spec) return;
    this.materialLine.textContent = has(strings.material.polymerSeparator)
      ? `${spec.label}${strings.material.polymerSeparator}${spec.polymer}`
      : spec.label;
    this.materialDensity.textContent = has(strings.material.densityUnit)
      ? `${spec.density.toFixed(2)} ${strings.material.densityUnit}`
      : spec.density.toFixed(2);
  }

  setStats(stats: Stats): void {
    this.readouts.get("mass")?.replaceChildren(stats.mass_g.toFixed(1));
    this.readouts.get("holes")?.replaceChildren(String(stats.holes));
    this.readouts.get("triangles")?.replaceChildren(String(stats.triangles));

    // Taking material away is a percentage off; putting it on is grams added.
    if (this.summaryLabel) {
      const lighter = stats.saving_pct >= 0;
      this.summaryLabel.textContent = lighter
        ? strings.readout.saving
        : strings.readout.added;
      this.summaryUnit.textContent = lighter
        ? strings.readout.savingUnit
        : strings.readout.addedUnit;
      this.readouts
        .get("balance")
        ?.replaceChildren(
          lighter ? String(stats.saving_pct) : `+${Math.round(stats.delta_g)}`,
        );
    }

    const host = this.notes.parentElement as HTMLElement;
    this.notes.replaceChildren(...stats.notes.map((note) => tag("p", "note", note)));
    host.hidden = stats.notes.length === 0;
    if (this.notesHeading) this.notesHeading.hidden = stats.notes.length === 0;
  }

  setBusy(busy: boolean, message: string): void {
    this.progress.classList.toggle("progress-live", busy);
    this.status.textContent = message;
    this.status.hidden = !has(message);
  }

  setDownloading(busy: boolean): void {
    this.download.disabled = busy;
    this.download.textContent = busy ? strings.actions.working : strings.actions.download;
  }

  materialsList(): MaterialSpec[] {
    return this.schema.materials;
  }

  rangeOf(key: string): Range {
    return this.schema.ranges[key];
  }
}

/**
 * Wiring.
 *
 * Dragging a slider asks for a draft mesh; letting go asks for the real one.
 * Requests are debounced and the newest always wins, so the model on screen is
 * the model the panel describes.
 */

import {
  downloadCover,
  fetchCover,
  fetchSchema,
  readMotif,
  uploadMotif,
  type Params,
  type PresetSpec,
  type Schema,
  type Silhouette,
} from "./api";
import { Panel } from "./panel";
import { has, strings } from "./strings.en";
import { Viewer } from "./viewer";

const DEBOUNCE_MS = 250;

const stage = document.getElementById("stage") as HTMLCanvasElement;
const masthead = document.getElementById("masthead") as HTMLElement;
const panelRoot = document.getElementById("panel") as HTMLElement;

let schema: Schema;
let params: Params;
let panel: Panel;
let viewer: Viewer;
let specLine: HTMLElement | null = null;

let timer: number | undefined;
let inflight: AbortController | null = null;
let pending = false;

/** The picture the session is holding, as the server read it. */
let silhouette: Silhouette | null = null;
let motifTimer: number | undefined;

/** The three controls that change how a held picture is read. */
const READING = new Set(["threshold_bias", "motif_smoothing", "motif_invert"]);

/** Ink or paper, whichever stays readable on the chosen colour. */
function readableOn(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance =
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255);
  return luminance > 0.35 ? "#1a1c1b" : "#e9eae6";
}

function applyAccent(hex: string): void {
  document.documentElement.style.setProperty("--accent", hex);
  document.documentElement.style.setProperty("--accent-ink", readableOn(hex));
}

/** Which preset, if any, the design still is. */
function activePreset(): string | null {
  for (const preset of schema.presets) {
    if (Object.entries(preset.values).every(([k, v]) => params[k] === v)) return preset.key;
  }
  return null;
}

function refreshPanel(): void {
  panel.setParams(params, activePreset());
  updateSpec();
}

function buildMasthead(): void {
  const { title, subtitle, specLabel } = strings.masthead;
  if (has(title)) {
    const node = document.createElement("h1");
    node.className = "masthead-title";
    node.textContent = title;
    masthead.append(node);
  }
  if (has(subtitle)) {
    const node = document.createElement("p");
    node.className = "masthead-subtitle";
    node.textContent = subtitle;
    masthead.append(node);
  }
  const keys = Object.keys(strings.masthead.specKeys).filter((k) =>
    has(strings.masthead.specKeys[k]),
  );
  if (keys.length === 0) return;
  const line = document.createElement("p");
  line.className = "masthead-spec";
  if (has(specLabel)) {
    const tagged = document.createElement("span");
    tagged.className = "masthead-spec-label";
    tagged.textContent = specLabel;
    line.append(tagged);
  }
  specLine = document.createElement("span");
  line.append(specLine);
  masthead.append(line);
}

function updateSpec(): void {
  if (!specLine) return;
  const { specKeys, specSeparator } = strings.masthead;
  const parts: string[] = [];
  for (const [key, letter] of Object.entries(specKeys)) {
    if (!has(letter)) continue;
    const range = schema.ranges[key];
    const value = Number(params[key]);
    const digits = range.step >= 1 ? 0 : range.step >= 0.1 ? 1 : 2;
    parts.push(`${letter}${value.toFixed(digits)}`);
  }
  const operation = strings.choices.operation.options[String(params.operation)];
  if (has(operation)) parts.push(operation.toUpperCase());
  // The picture is part of what the object is, so its digest goes on the
  // spec line: the same file and the same sliders rebuild the same cover.
  if (params.hole_shape === "image" && silhouette && has(strings.motif.specTag)) {
    parts.push(`${strings.motif.specTag} ${silhouette.short}`);
  }
  const material = schema.materials.find((m) => m.key === params.material);
  if (material) parts.push(material.label.toUpperCase());
  specLine.textContent = parts.join(specSeparator);
}

/** Read the held picture again after the threshold or smoothing moved. */
function reread(): void {
  clearTimeout(motifTimer);
  if (!silhouette) return;
  motifTimer = window.setTimeout(async () => {
    try {
      silhouette = await readMotif(params);
      panel.setSilhouette(silhouette, noteFor(silhouette));
      updateSpec();
    } catch {
      panel.setSilhouette(silhouette, strings.motif.unreadable);
    }
  }, DEBOUNCE_MS);
}

/** What the preview says about itself, if anything. */
function noteFor(shape: Silhouette): string {
  return shape.shapes === 0 ? strings.motif.empty : "";
}

async function takePicture(file: File): Promise<void> {
  panel.setSilhouette(silhouette, strings.motif.reading);
  try {
    silhouette = await uploadMotif(file);
  } catch {
    panel.setSilhouette(silhouette, strings.motif.unreadable);
    return;
  }
  // A new picture arrives at its own reading, so the two controls that would
  // otherwise still describe the last one go back to where they started.
  params.motif_id = silhouette.id;
  params.threshold_bias = schema.defaults.threshold_bias;
  params.motif_smoothing = schema.defaults.motif_smoothing;
  params.motif_invert = schema.defaults.motif_invert;
  panel.setSilhouette(silhouette, noteFor(silhouette));
  refreshPanel();
  request(false);
}

function request(draft: boolean): void {
  clearTimeout(timer);
  timer = window.setTimeout(() => void run(draft), draft ? DEBOUNCE_MS : 0);
}

async function run(draft: boolean): Promise<void> {
  inflight?.abort();
  const controller = new AbortController();
  inflight = controller;
  pending = true;
  panel.setBusy(true, draft ? strings.status.draft : strings.status.computing);
  try {
    const { glb, stats } = await fetchCover(params, draft, controller.signal);
    await viewer.setModel(glb);
    viewer.setFinish(stats.finish);
    panel.setStats(stats);
    panel.setCap("wall_thickness", stats.max_wall_thickness);
    panel.setCap("relief_depth", stats.max_relief_depth);
    applyAccent(stats.finish.colour_a);
    pending = false;
    panel.setBusy(false, "");
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    pending = false;
    panel.setBusy(false, strings.status.offline);
  }
}

async function start(): Promise<void> {
  schema = await fetchSchema();
  params = { ...schema.defaults };

  const first =
    schema.materials.find((m) => m.key === params.material) ?? schema.materials[0];
  viewer = new Viewer(stage, first.hex);
  applyAccent(first.hex);

  buildMasthead();
  panel = new Panel(panelRoot, schema, {
    onParam(key, value, live) {
      params[key] = value;
      refreshPanel();
      if (READING.has(key)) reread();
      request(live);
    },
    onChoice(key, value) {
      params[key] = value;
      refreshPanel();
      // Shading is drawn in the browser; only geometry needs the server.
      if (key === "finish") viewer.setFinish(finishOf());
      else request(false);
    },
    onToggle(key, value) {
      params[key] = value;
      refreshPanel();
      if (READING.has(key)) reread();
      request(false);
    },
    onMaterial(key, second) {
      params[second ? "colour_b" : "material"] = key;
      refreshPanel();
      if (!second) applyAccent(colourOf(key));
      viewer.setFinish(finishOf());
      // Density differs between polymers, so the weight has to come back.
      if (!second) request(false);
    },
    onPreset(preset: PresetSpec) {
      // A preset is a starting point: it moves the sliders and lets go.
      Object.assign(params, preset.values);
      refreshPanel();
      applyAccent(colourOf(String(params.material)));
      request(false);
    },
    onPicture(file: File) {
      void takePicture(file);
    },
    async onDownload(fmt) {
      panel.setDownloading(true);
      try {
        await downloadCover(params, fmt);
      } catch {
        panel.setBusy(pending, strings.status.offline);
      } finally {
        panel.setDownloading(false);
      }
    },
  });
  panel.setSilhouette(null, "");
  refreshPanel();
  void run(false);
}

function colourOf(key: string): string {
  return schema.materials.find((m) => m.key === key)?.hex ?? "#17514c";
}

function finishOf() {
  return {
    mode: String(params.finish),
    colour_a: colourOf(String(params.material)),
    colour_b: colourOf(String(params.colour_b)),
    facet_scale: Number(params.facet_scale),
  };
}

void start();

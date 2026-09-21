export interface Range {
  lo: number;
  hi: number;
  step: number;
  unit: string;
  scale: "linear" | "log";
}

export interface MaterialSpec {
  key: string;
  label: string;
  hex: string;
  polymer: string;
  density: number;
}

export interface PresetSpec {
  key: string;
  label: string;
  note: string;
  values: Record<string, number | boolean | string>;
}

export interface Schema {
  ranges: Record<string, Range>;
  enums: Record<string, string[]>;
  defaults: Record<string, number | boolean | string>;
  materials: MaterialSpec[];
  presets: PresetSpec[];
  profile: { name: string; min_strut: number; min_hole: number; clearance: number };
  formats: string[];
  bodies?: string[];
}

export interface Stats {
  mass_g: number;
  plain_mass_g: number;
  saving_pct: number;
  delta_g: number;
  holes: number;
  triangles: number;
  max_wall_thickness: number;
  max_relief_depth: number;
  operation: string;
  cuts_through: boolean;
  notes: string[];
  material: { key: string; label: string; hex: string; polymer: string };
  finish: { mode: string; colour_a: string; colour_b: string; facet_scale: number };
  draft: boolean;
  seconds: number;
  /** Transfemoral only: weight of each printed body, in grams. */
  bodies?: Record<string, number>;
  /** Transfemoral only: where each moving slider's track now ends. */
  limits?: Record<string, [number, number]>;
  explode_mm?: number;
}

export type Params = Record<string, number | boolean | string>;

/** The silhouette a picture was read as, in the unit square, y pointing up. */
export interface Silhouette {
  id: string;
  short: string;
  paths: string[];
  shapes: number;
  found: number;
  notes: string[];
}

/** Where a tab's service lives: "/api" for the transtibial cover. */
export type Base = string;

export async function fetchSchema(base: Base = "/api"): Promise<Schema> {
  const res = await fetch(`${base}/schema`);
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

export interface CoverResponse {
  glb: ArrayBuffer;
  stats: Stats;
}

export async function fetchCover(
  params: Params,
  draft: boolean,
  signal: AbortSignal,
  base: Base = "/api",
): Promise<CoverResponse> {
  const res = await fetch(`${base}/cover`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ params, draft }),
    signal,
  });
  if (!res.ok) throw new Error(String(res.status));
  const stats = JSON.parse(decodeURIComponent(res.headers.get("X-Cover") ?? "{}"));
  return { glb: await res.arrayBuffer(), stats };
}

/** Hand a picture over. The bytes stay on the server for the session. */
export async function uploadMotif(file: File): Promise<Silhouette> {
  const res = await fetch("/api/motif", { method: "POST", body: file });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

/** The same picture read again, at a different threshold or smoothing. */
export async function readMotif(params: Params): Promise<Silhouette> {
  const res = await fetch("/api/motif/preview", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      motif_id: params.motif_id,
      threshold_bias: params.threshold_bias,
      motif_invert: params.motif_invert,
      motif_smoothing: params.motif_smoothing,
    }),
  });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

export async function downloadCover(
  params: Params,
  fmt: string,
  base: Base = "/api",
  body = "",
): Promise<void> {
  const which = body ? `&body=${encodeURIComponent(body)}` : "";
  const res = await fetch(`${base}/download?fmt=${fmt}${which}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ params, draft: false }),
  });
  if (!res.ok) throw new Error(String(res.status));
  const blob = await res.blob();
  const name =
    res.headers.get("content-disposition")?.match(/filename="(.+)"/)?.[1] ??
    `cover.${fmt}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

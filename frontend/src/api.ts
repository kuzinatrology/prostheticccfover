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

export interface User { id: number; email: string; nickname: string; }
export interface Rating { average: number; count: number; mine: number | null; }
/** `mode` is the tab the design was drawn on; see `MODES` in main.ts. */
export interface SavedDesign { id: number; user_id?: number; name: string; mode?: string; params: Params; created_at: number; nickname?: string; rating?: Rating; }
export interface Participant { id: number; nickname: string; average: number; ratings: number; designs: number; }
export interface RankedDesigner { id: number; nickname: string; avatar_url: string; average: number; ratings: number; designs: number; rank?: number; }
export interface RankedDesign { id: number; user_id: number; name: string; mode?: string; nickname: string; avatar_url: string; average: number; ratings: number; }
export interface MyRank { rank: number | null; designer: RankedDesigner; }
export interface ProfileUser {
  id: number;
  nickname: string;
  avatar_url: string;
  first_name: string;
  last_name: string;
  city: string;
  bio: string;
  website: string;
  social_link: string;
}
export interface ProfileDesign { id: number; name: string; mode?: string; created_at: number; nickname: string; rating: Rating; }
export interface ActivityDay { date: string; count: number; }
export interface PublicProfile {
  user: ProfileUser;
  designs: ProfileDesign[];
  activity: ActivityDay[];
  stats: { designs: number; average: number; ratings: number };
  is_owner: boolean;
}

async function accountRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...options, headers: { "content-type": "application/json", ...(options?.headers ?? {}) } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? String(res.status));
  }
  return res.json();
}

export async function currentUser(): Promise<User | null> {
  const result = await accountRequest<{ user: User | null }>("/api/auth/me");
  return result.user;
}

export async function login(email: string, password: string): Promise<User> {
  const result = await accountRequest<{ user: User }>("/api/auth/login", {
    method: "POST", body: JSON.stringify({ email, password }),
  });
  return result.user;
}

export async function register(email: string, password: string, nickname: string): Promise<User> {
  const result = await accountRequest<{ user: User }>("/api/auth/register", {
    method: "POST", body: JSON.stringify({ email, password, nickname }),
  });
  return result.user;
}

export async function signOut(): Promise<void> { await accountRequest("/api/auth/logout", { method: "POST" }); }
export async function listDesigns(): Promise<SavedDesign[]> { return accountRequest<SavedDesign[]>("/api/designs"); }
export async function saveDesign(name: string, params: Params, mode: string): Promise<SavedDesign> {
  return accountRequest<SavedDesign>("/api/designs", { method: "POST", body: JSON.stringify({ name, mode, params }) });
}
export async function loadDesign(id: number): Promise<SavedDesign> { return accountRequest<SavedDesign>(`/api/designs/${id}`); }
export async function removeDesign(id: number): Promise<void> { await accountRequest(`/api/designs/${id}`, { method: "DELETE" }); }
export async function communityDesigns(search = ""): Promise<SavedDesign[]> { return accountRequest<SavedDesign[]>(`/api/community/designs?search=${encodeURIComponent(search)}`); }
export async function communityDesign(id: number): Promise<SavedDesign> { return accountRequest<SavedDesign>(`/api/community/designs/${id}`); }
export async function rateDesign(id: number, score: number): Promise<Rating> { return accountRequest<Rating>(`/api/community/designs/${id}/rating`, { method: "POST", body: JSON.stringify({ score }) }); }
export async function participants(): Promise<Participant[]> { return accountRequest<Participant[]>("/api/community/participants"); }
export async function topDesigners(limit = 5): Promise<RankedDesigner[]> { return accountRequest<RankedDesigner[]>(`/api/community/top-designers?limit=${limit}`); }
export async function topDesigns(limit = 5): Promise<RankedDesign[]> { return accountRequest<RankedDesign[]>(`/api/community/top-designs?limit=${limit}`); }
export async function myRank(): Promise<MyRank> { return accountRequest<MyRank>("/api/community/my-rank"); }
export async function fetchProfile(id: number): Promise<PublicProfile> { return accountRequest<PublicProfile>(`/api/profiles/${id}`); }
export async function updateProfile(values: Omit<ProfileUser, "id" | "nickname">): Promise<PublicProfile> {
  return accountRequest<PublicProfile>("/api/profile", { method: "PUT", body: JSON.stringify(values) });
}
export async function uploadAvatar(file: File): Promise<PublicProfile> {
  const res = await fetch("/api/profile/avatar", { method: "POST", headers: { "content-type": file.type }, body: file });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? String(res.status));
  }
  return res.json();
}

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

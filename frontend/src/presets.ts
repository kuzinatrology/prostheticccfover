/**
 * Thumbnails for the presets.
 *
 * The values themselves live on the server, so the tests can build and export
 * every preset. What belongs here is the picture: a small drawing of what each
 * one does to the cover, in the shape of a cover.
 *
 * Every drawing is deterministic, so a preset always looks like itself.
 */

const W = 44;
const H = 58;

/** A small repeatable generator, so a tile never changes between renders. */
function noise(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

/** The cover's silhouette: narrow at the ankle, fuller at the calf. */
function outline(y: number): number {
  const t = y / H;
  return 5.5 + 8.5 * Math.sin(Math.PI * (0.18 + 0.72 * t)) ** 0.6;
}

function wrap(body: string): string {
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="100%" aria-hidden="true">
    <defs><clipPath id="c"><path d="${silhouette()}"/></clipPath></defs>
    <path d="${silhouette()}" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.45"/>
    <g clip-path="url(#c)">${body}</g>
  </svg>`;
}

function silhouette(): string {
  const left: string[] = [];
  const right: string[] = [];
  for (let y = 3; y <= H - 3; y += 2) {
    const r = outline(y);
    left.push(`${W / 2 - r},${y}`);
    right.push(`${W / 2 + r},${y}`);
  }
  return `M${left.join(" L")} L${right.reverse().join(" L")} Z`;
}

function cellCentres(seed: number, rows: number, cols: number, jitter: number) {
  const rnd = noise(seed);
  const out: { x: number; y: number }[] = [];
  for (let j = 0; j < rows; j++) {
    const y = 4 + ((H - 8) * (j + 0.5)) / rows;
    for (let i = 0; i < cols; i++) {
      const x = ((W * (i + (j % 2 ? 0.5 : 0))) / cols) % W;
      out.push({ x: x + (rnd() - 0.5) * jitter, y: y + (rnd() - 0.5) * jitter });
    }
  }
  return out;
}

function lattice(): string {
  const rnd = noise(11);
  return wrap(
    cellCentres(7, 9, 5, 3.4)
      .map(({ x, y }) => {
        const pts: string[] = [];
        for (let k = 0; k < 6; k++) {
          const a = (k / 6) * Math.PI * 2 + rnd() * 0.4;
          const r = 2.0 + rnd() * 0.7;
          pts.push(`${(x + Math.cos(a) * r).toFixed(1)},${(y + Math.sin(a) * r * 1.15).toFixed(1)}`);
        }
        return `<polygon points="${pts.join(" ")}" fill="currentColor"/>`;
      })
      .join(""),
  );
}

function chevron(): string {
  const out: string[] = [];
  for (let j = 0; j < 13; j++) {
    const y = 3 + j * 4.2;
    for (let i = -1; i < 5; i++) {
      const x = i * 9 + (j % 2) * 4.5;
      out.push(
        `<path d="M${x} ${y + 3.4} L${x + 5.4} ${y}" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" fill="none"/>`,
      );
    }
  }
  return wrap(out.join(""));
}

function scales(): string {
  const out: string[] = [];
  for (let j = 0; j < 12; j++) {
    const y = 3 + j * 4.6;
    for (let i = -1; i < 6; i++) {
      const x = i * 8 + (j % 2) * 4;
      out.push(
        `<path d="M${x} ${y + 3.2} a 4 3.6 0 0 1 8 0" fill="none" stroke="currentColor" stroke-width="1.3"/>`,
      );
    }
  }
  return wrap(out.join(""));
}

function vent(): string {
  const dots: string[] = [];
  for (let j = 0; j < 11; j++) {
    for (let i = 0; i < 4; i++) {
      const x = W / 2 - 5.4 + i * 3.6 + (j % 2) * 1.8;
      const y = 12 + j * 3.2;
      dots.push(`<circle cx="${x}" cy="${y}" r="1.25" fill="currentColor"/>`);
    }
  }
  return wrap(dots.join(""));
}

function facet(): string {
  const out: string[] = [];
  const rnd = noise(23);
  for (let j = 0; j < 9; j++) {
    const y = 2 + j * 6.4;
    for (let i = -1; i < 5; i++) {
      const x = i * 10 + (j % 2) * 5;
      const shade = 0.16 + rnd() * 0.5;
      out.push(
        `<polygon points="${x},${y} ${x + 10},${y + 1} ${x + 5},${y + 6.4}" fill="currentColor" opacity="${shade.toFixed(2)}"/>`,
        `<polygon points="${x + 10},${y + 1} ${x + 15},${y + 6.4} ${x + 5},${y + 6.4}" fill="currentColor" opacity="${(0.7 - shade).toFixed(2)}"/>`,
      );
    }
  }
  return wrap(out.join(""));
}

function ridge(): string {
  const out: string[] = [];
  for (let j = 0; j < 10; j++) {
    const y = 2 + j * 6;
    out.push(
      `<path d="M-2 ${y + 4} Q ${W / 4} ${y}, ${W / 2} ${y + 3} T ${W + 2} ${y + 2}"
        fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.75"/>`,
    );
  }
  return wrap(out.join(""));
}

const DRAWINGS: Record<string, () => string> = {
  lattice,
  chevron,
  scales,
  vent,
  facet,
  ridge,
};

export function thumbnail(key: string): string {
  return (DRAWINGS[key] ?? lattice)();
}

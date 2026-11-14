import type {HistoryProps, TimelineEvent} from './types';

export const clamp = (value: number, low = 0, high = 1) => Math.max(low, Math.min(high, value));
export const ease = (value: number) => {const p = clamp(value); return p * p * (3 - 2 * p);};
export function yearLabel(year: number): string {
  if (!Number.isFinite(year) || year === 0) throw new Error('History uses civil BCE/CE dates; year zero is not supported.');
  return year < 0 ? `公元前 ${Math.abs(year)}` : `公元 ${year}`;
}
export function yearOrdinal(year: number): number {return year < 0 ? year + 1 : year;}
export function sortedEvents(events: TimelineEvent[]): TimelineEvent[] {return [...events].sort((a, b) => a.year - b.year);}

/** Preserve audience facts while removing clauses about internal renderer fields. */
export function audienceNote(value: string | undefined, fallback: string): string {
  const text = value?.trim() ?? '';
  if (!text) return fallback;
  const internal = /\b(date_label|source_ids|viewport|portrait_asset)\b/i;
  if (!internal.test(text)) return text;
  const clauses = text.split(/[；;。\n]+/).map((s) => s.trim()).filter((s) => s && !internal.test(s));
  return clauses.length ? clauses.join('；') + '。' : fallback;
}

export function mapLabel(name: string): string {
  const concise = name.replace(/（[^（）]*）|\([^()]*\)/g, '').trim();
  return concise || name.trim();
}

export type MapLabelAnchor = {id: string; name: string; x: number; y: number};
export type MapLabelBox = {id: string; text: string; x: number; y: number; width: number; height: number; anchorX: number; anchorY: number};
const overlapArea = (a: {x: number; y: number; width: number; height: number}, b: {x: number; y: number; width: number; height: number}, gap = 0): number =>
  Math.max(0, Math.min(a.x + a.width + gap, b.x + b.width + gap) - Math.max(a.x - gap, b.x - gap)) *
  Math.max(0, Math.min(a.y + a.height + gap, b.y + b.height + gap) - Math.max(a.y - gap, b.y - gap));
const pointSegmentDistance = (px: number, py: number, ax: number, ay: number, bx: number, by: number): number => {
  const lengthSquared = (bx - ax) ** 2 + (by - ay) ** 2;
  const t = lengthSquared ? clamp(((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / lengthSquared) : 0;
  return Math.hypot(px - ax - t * (bx - ax), py - ay - t * (by - ay));
};

/** Frame-independent label layout. Only labels move; the geographic anchors never do. */
export function layoutMapLabels(anchors: MapLabelAnchor[], width: number, height: number, fontSize = 19): MapLabelBox[] {
  const placed: MapLabelBox[] = [];
  const ranked = anchors.map((anchor, index) => ({anchor, index, density: anchors.filter((a) => Math.hypot(a.x - anchor.x, a.y - anchor.y) < 105).length}))
    .sort((a, b) => b.density - a.density || a.index - b.index);
  for (const {anchor, index} of ranked) {
    const text = mapLabel(anchor.name);
    const units = [...text].reduce((total, char) => total + (char.charCodeAt(0) < 128 ? .57 : 1), 0);
    const boxWidth = Math.min(width - 32, units * fontSize + 18);
    const boxHeight = fontSize + 11;
    const directions = index % 2 === 0 ? [[0,-1],[0,1],[1,0],[-1,0],[1,-1],[-1,-1],[1,1],[-1,1]] : [[0,1],[0,-1],[-1,0],[1,0],[-1,1],[1,1],[-1,-1],[1,-1]];
    let winner: MapLabelBox | undefined;
    let best = Infinity;
    for (let ring = 0; ring < 7; ring++) for (let d = 0; d < directions.length; d++) {
      const [dx, dy] = directions[d];
      const distance = 14 + ring * 22;
      const cx = anchor.x + dx * (boxWidth / 2 + distance);
      const cy = anchor.y + dy * (boxHeight / 2 + distance);
      const candidate: MapLabelBox = {id: anchor.id, text, x: clamp(cx - boxWidth / 2, 14, width - boxWidth - 14),
        y: clamp(cy - boxHeight / 2, 14, height - boxHeight - 43), width: boxWidth, height: boxHeight, anchorX: anchor.x, anchorY: anchor.y};
      const collisions = placed.reduce((sum, p) => sum + overlapArea(candidate, p, 4), 0);
      const coveredAnchors = anchors.reduce((sum, a) => sum + overlapArea(candidate, {x: a.x - 9, y: a.y - 9, width: 18, height: 18}, 2), 0);
      const lineX = clamp(anchor.x, candidate.x + 4, candidate.x + candidate.width - 4);
      const lineY = clamp(anchor.y, candidate.y + 4, candidate.y + candidate.height - 4);
      const crossedAnchors = anchors.reduce((sum, a) => a.id === anchor.id ? sum : sum + Math.max(0, 10 - pointSegmentDistance(a.x, a.y, anchor.x, anchor.y, lineX, lineY)), 0);
      const offset = Math.hypot(candidate.x + boxWidth / 2 - anchor.x, candidate.y + boxHeight / 2 - anchor.y);
      const score = collisions * 10000 + coveredAnchors * 10000 + crossedAnchors * 100000 + offset * offset + d * 3;
      if (score < best) {best = score; winner = candidate;}
    }
    placed.push(winner!);
  }
  return anchors.map((a) => placed.find((p) => p.id === a.id)!);
}

export function captionPages(text: string, size = 28): string[] {
  const chunks = [...text.replace(/\s+/g, ' ').trim()];
  const pages: string[] = [];
  while (chunks.length) {
    let count = Math.min(size, chunks.length);
    if (chunks.length > size) {
      for (let i = count - 1; i >= Math.floor(size * .55); i--) {
        if (/[，。！？；,.!?;]/.test(chunks[i])) {count = i + 1; break;}
      }
    }
    pages.push(chunks.splice(0, count).join(''));
  }
  if (pages.length > 1 && pages.at(-1)!.length < 5) {
    const last = pages.pop()!;
    const previous = pages.pop()!;
    const move = Math.min(5 - last.length, Math.floor(previous.length / 2));
    pages.push(previous.slice(0, previous.length - move), previous.slice(previous.length - move) + last);
  }
  return pages;
}

export function captionAt(text: string, seconds: number, offset: number, duration: number, size = 28): string {
  if (seconds < offset || seconds >= offset + duration || duration <= 0) return '';
  const pages = captionPages(text, size);
  const position = clamp((seconds - offset) / duration) * pages.reduce((n, p) => n + p.length, 0);
  let accumulated = 0;
  return pages.find((page) => {accumulated += page.length; return position < accumulated;}) ?? pages.at(-1) ?? '';
}

export function validateProps(props: HistoryProps): void {
  const scene = props.scene;
  if (!scene || !Number.isFinite(scene.duration) || scene.duration <= 0) throw new Error('Scene requires positive duration in seconds.');
  if (scene.components?.length !== 1) throw new Error('History Remotion scene requires exactly one main component.');
  const c = scene.components[0];
  if (!['history.map', 'history.timeline', 'history.person'].includes(c.id)) throw new Error(`Unsupported history component: ${c.id}`);
  if (c.id === 'history.map') {
    const p = c.parameters;
    if (!Array.isArray(p.locations) || p.locations.length < 1 || p.locations.length > 12) throw new Error('Map needs 1–12 locations.');
    const ids = new Set(p.locations.map((l) => l.id));
    if (ids.size !== p.locations.length) throw new Error('Map location ids must be unique.');
    for (const l of p.locations) {
      if (!l.id || !l.name || !Number.isFinite(l.lon) || !Number.isFinite(l.lat) || Math.abs(l.lon) > 180 || Math.abs(l.lat) > 85) throw new Error('Map locations require names and valid longitude/latitude.');
    }
    for (const r of p.routes ?? []) if (!ids.has(r.from) || !ids.has(r.to)) throw new Error('Route references an unknown location.');
    if (p.viewport) {
      const v = p.viewport;
      if (![v.west, v.east, v.south, v.north].every(Number.isFinite) || !(v.west < v.east && v.south < v.north)) throw new Error('Map viewport bounds must increase.');
    }
  } else if (c.id === 'history.timeline') {
    if (!Array.isArray(c.parameters.events) || !c.parameters.events.length || c.parameters.events.length > 8) throw new Error('Timeline needs 1–8 events.');
    for (const e of c.parameters.events) if (!Number.isFinite(e.year) || e.year === 0 || !e.label) throw new Error('Timeline events need a nonzero civil year and label.');
  } else {
    const p = c.parameters;
    if (!p.name || !p.role || !Array.isArray(p.facts) || p.facts.length < 1 || p.facts.length > 5) throw new Error('Person needs name, role and 1–5 facts.');
    if (p.portrait_asset && (!p.portrait_asset.startsWith('portraits/') || p.portrait_asset.includes('..') || /[\\:]/.test(p.portrait_asset))) throw new Error('Portraits must be approved local public/portraits assets.');
  }
}

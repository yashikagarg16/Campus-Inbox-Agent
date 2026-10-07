import type { RuleStatus } from "../api";

export interface Mark {
  key: number; // index of the rule this evidence belongs to
  start: number;
  end: number;
  status: RuleStatus;
}

export interface Segment {
  text: string;
  start: number;
  marks: Mark[];
}

const SEVERITY: Record<RuleStatus, number> = { pass: 0, unknown: 1, fail: 2 };

/** Split `text` into segments so overlapping evidence spans can each be highlighted. */
export function segmentText(text: string, marks: Mark[]): Segment[] {
  const valid = marks.filter((m) => m.start >= 0 && m.end <= text.length && m.start < m.end);
  const cuts = new Set<number>([0, text.length]);
  for (const m of valid) {
    cuts.add(m.start);
    cuts.add(m.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [start, end] = [points[i], points[i + 1]];
    if (start === end) continue;
    segments.push({
      text: text.slice(start, end),
      start,
      marks: valid.filter((m) => m.start <= start && m.end >= end),
    });
  }
  return segments;
}

/** The most serious status among a segment's marks decides its colour. */
export function worstStatus(marks: Mark[]): RuleStatus | null {
  if (!marks.length) return null;
  return marks.reduce((a, b) => (SEVERITY[b.status] > SEVERITY[a.status] ? b : a)).status;
}

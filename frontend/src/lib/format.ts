// The backend stores naive datetimes in IST. Parse and display them in IST regardless of the
// browser's time zone, so "5 PM" in the email shows as 5 PM here.

const IST = "Asia/Kolkata";

export function parseServerDate(value: string): Date {
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  return new Date(hasZone ? value : `${value}+05:30`);
}

export function formatDeadline(value: string | null): string {
  if (!value) return "No deadline found";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(parseServerDate(value));
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, dateStyle: "medium", timeStyle: "short" }).format(
    parseServerDate(value),
  );
}

/** "in 3 days", "in 5 hours", "2 days ago" */
export function relativeDeadline(value: string | null, now: Date = new Date()): string {
  if (!value) return "";
  const ms = parseServerDate(value).getTime() - now.getTime();
  const abs = Math.abs(ms);
  const hours = Math.round(abs / 3_600_000);
  const days = Math.round(abs / 86_400_000);
  const amount = hours < 36 ? (hours < 1 ? "under an hour" : `${hours} hour${hours === 1 ? "" : "s"}`) : `${days} days`;
  return ms >= 0 ? `in ${amount}` : `${amount} ago`;
}

export type Urgency = "passed" | "urgent" | "soon" | "later" | "none";

export function deadlineUrgency(value: string | null, now: Date = new Date()): Urgency {
  if (!value) return "none";
  const hours = (parseServerDate(value).getTime() - now.getTime()) / 3_600_000;
  if (hours < 0) return "passed";
  if (hours <= 48) return "urgent";
  if (hours <= 24 * 7) return "soon";
  return "later";
}

export const RULE_LABELS: Record<string, string> = {
  batches: "Batch",
  min_cgpa: "CGPA",
  branches: "Branch",
  min_10th_percent: "10th %",
  min_12th_percent: "12th %",
  max_active_backlogs: "Backlogs",
  required_skills: "Skills",
  other_criteria: "Other condition",
};

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export function splitList(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

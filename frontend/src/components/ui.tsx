import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { RuleStatus, Verdict } from "../api";

const VERDICT_STYLE: Record<Verdict, { label: string; className: string }> = {
  eligible: {
    label: "Eligible",
    className: "bg-emerald-100 text-emerald-800 ring-emerald-600/20 dark:bg-emerald-950 dark:text-emerald-300",
  },
  not_eligible: {
    label: "Not eligible",
    className: "bg-rose-100 text-rose-800 ring-rose-600/20 dark:bg-rose-950 dark:text-rose-300",
  },
  needs_review: {
    label: "Needs review",
    className: "bg-amber-100 text-amber-900 ring-amber-600/20 dark:bg-amber-950 dark:text-amber-300",
  },
};

export function VerdictBadge({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return <span className="text-sm text-slate-500">No decision</span>;
  const s = VERDICT_STYLE[verdict];
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${s.className}`}>
      {s.label}
    </span>
  );
}

const STATUS_STYLE: Record<RuleStatus, { symbol: string; label: string; className: string }> = {
  pass: { symbol: "✓", label: "Pass", className: "bg-emerald-600 text-white" },
  fail: { symbol: "✕", label: "Fail", className: "bg-rose-600 text-white" },
  unknown: { symbol: "?", label: "Unclear", className: "bg-amber-500 text-white" },
};

export function StatusIcon({ status }: { status: RuleStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <span
      role="img"
      aria-label={s.label}
      title={s.label}
      className={`inline-flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${s.className}`}
    >
      {s.symbol}
    </span>
  );
}

export const HIGHLIGHT_CLASS: Record<RuleStatus, string> = {
  pass: "bg-emerald-200/70 dark:bg-emerald-800/60",
  fail: "bg-rose-200/80 dark:bg-rose-800/60",
  unknown: "bg-amber-200/80 dark:bg-amber-700/60",
};

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANT: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-500 disabled:bg-indigo-400",
  secondary:
    "bg-white text-slate-900 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700",
  danger: "bg-rose-600 text-white hover:bg-rose-500",
  ghost: "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
};

export function buttonClass(variant: Variant = "primary", className = ""): string {
  return `inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium shadow-sm transition disabled:cursor-not-allowed disabled:opacity-70 ${VARIANT[variant]} ${className}`;
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button className={buttonClass(variant, className)} {...props} />;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={`rounded-lg bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800 ${className}`}
    >
      {children}
    </section>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="rounded-md bg-rose-50 p-3 text-sm text-rose-800 ring-1 ring-rose-200 dark:bg-rose-950 dark:text-rose-200 dark:ring-rose-900">
      {message}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "ok" }) {
  const style = {
    info: "bg-sky-50 text-sky-900 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-900",
    warn: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-900",
    ok: "bg-emerald-50 text-emerald-900 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-900",
  }[tone];
  return <div className={`rounded-md p-3 text-sm ring-1 ${style}`}>{children}</div>;
}

export const inputClass =
  "block w-full rounded-md border-0 bg-white px-3 py-1.5 text-sm shadow-sm ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-600 dark:bg-slate-800 dark:ring-slate-700";

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

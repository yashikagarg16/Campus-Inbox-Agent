import type { RuleResult } from "../api";
import { formatValue, RULE_LABELS } from "../lib/format";
import { StatusIcon } from "./ui";

interface Props {
  rules: RuleResult[];
  activeKey: number | null;
  onSelect: (key: number) => void;
}

export function RuleList({ rules, activeKey, onSelect }: Props) {
  if (!rules.length) {
    return <p className="text-sm text-slate-500">No eligibility rules were found in this email.</p>;
  }
  return (
    <ul className="space-y-2">
      {rules.map((r, i) => (
        <li key={i}>
          <button
            type="button"
            onClick={() => onSelect(i)}
            aria-pressed={activeKey === i}
            className={`w-full rounded-md p-3 text-left ring-1 transition ${
              activeKey === i
                ? "bg-indigo-50 ring-indigo-400 dark:bg-indigo-950"
                : "ring-slate-200 hover:bg-slate-50 dark:ring-slate-800 dark:hover:bg-slate-800/60"
            }`}
          >
            <div className="flex items-start gap-2">
              <StatusIcon status={r.status} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium">{RULE_LABELS[r.rule] ?? r.rule}</span>
                  <span className="text-xs text-slate-500">
                    needs {formatValue(r.required)}
                    {r.actual !== null && r.actual !== undefined && <> · you {formatValue(r.actual)}</>}
                  </span>
                </div>
                <p className="mt-0.5 text-sm text-slate-700 dark:text-slate-300">{r.reason}</p>
                {r.evidence && (
                  <blockquote className="mt-1.5 border-l-2 border-slate-300 pl-2 text-xs italic text-slate-600 dark:border-slate-600 dark:text-slate-400">
                    “{r.evidence}”
                    {!r.span && <span className="not-italic"> (not located in the email)</span>}
                  </blockquote>
                )}
              </div>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

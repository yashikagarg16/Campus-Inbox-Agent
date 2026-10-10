import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type OpportunitySummary, type Verdict } from "../api";
import { useServerConfig } from "../App";
import { Button, buttonClass, Card, ErrorBox, Notice, VerdictBadge } from "../components/ui";
import { deadlineUrgency, formatDeadline, relativeDeadline, type Urgency } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useIsVisitor } from "../session";

type Filter = "all" | Verdict;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "eligible", label: "Eligible" },
  { value: "needs_review", label: "Needs review" },
  { value: "not_eligible", label: "Not eligible" },
];

const URGENCY_CLASS: Record<Urgency, string> = {
  passed: "text-slate-400 line-through",
  urgent: "font-semibold text-rose-700 dark:text-rose-400",
  soon: "text-amber-800 dark:text-amber-300",
  later: "",
  none: "text-slate-500",
};

export function filterOpportunities(items: OpportunitySummary[], filter: Filter, showPast: boolean) {
  return items.filter(
    (o) => (filter === "all" || o.verdict === filter) && (showPast || o.deadline_passed !== true),
  );
}

export function DashboardPage() {
  const { data, error, loading, reload } = useAsync(() => api.listOpportunities(), []);
  const { config, error: configError } = useServerConfig();
  const [filter, setFilter] = useState<Filter>("all");
  const [showPast, setShowPast] = useState(false);
  // The demo's synthetic emails have fixed October 2026 deadlines, so show them all to visitors.
  const visitor = useIsVisitor();
  useEffect(() => {
    if (visitor) setShowPast(true);
  }, [visitor]);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<unknown>(null);

  const items = useMemo(() => filterOpportunities(data ?? [], filter, showPast), [data, filter, showPast]);
  const counts = useMemo(() => {
    const live = (data ?? []).filter((o) => showPast || o.deadline_passed !== true);
    return Object.fromEntries(FILTERS.map((f) => [f.value, filterOpportunities(live, f.value, true).length]));
  }, [data, showPast]);

  async function sync() {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const r = await api.syncImap(7);
      setSyncMessage(`Checked ${r.fetched} emails: ${r.new} new, ${r.duplicates} already here, ${r.failed} failed.`);
      await reload();
    } catch (e) {
      setSyncError(e);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Opportunities</h1>
          <p className="mt-1 text-sm text-slate-500">Sorted by deadline. Open one to see the sentence behind each rule.</p>
        </div>
        <div className="flex gap-2">
          {config?.imap_configured && !config.demo_mode && (
            <Button variant="secondary" onClick={sync} disabled={syncing}>
              {syncing ? "Checking inbox…" : "Check inbox (last 7 days)"}
            </Button>
          )}
          <Link to="/app/add" className={buttonClass()}>
            Check an email
          </Link>
        </div>
      </div>

      {configError ? (
        <ErrorBox error={configError} />
      ) : (
        config && !config.llm_configured && !config.demo_mode && (
          <Notice tone="warn">The server has no GEMINI_API_KEY, so new emails can't be processed yet.</Notice>
        )
      )}
      {data && data.length > 0 && <StatTiles items={data} />}
      {syncMessage && <Notice tone="ok">{syncMessage}</Notice>}
      <ErrorBox error={syncError} />

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            aria-pressed={filter === f.value}
            className={`rounded-full px-3 py-1 text-sm ring-1 ${
              filter === f.value
                ? "bg-slate-900 text-white ring-slate-900 dark:bg-slate-100 dark:text-slate-900"
                : "ring-slate-300 hover:bg-slate-100 dark:ring-slate-700 dark:hover:bg-slate-800"
            }`}
          >
            {f.label} <span className="opacity-70">{counts[f.value] ?? 0}</span>
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm">
          <input type="checkbox" checked={showPast} onChange={(e) => setShowPast(e.target.checked)} />
          Show past deadlines
        </label>
      </div>

      {!configError && <ErrorBox error={error} />}
      {loading && !data && <p className="text-sm text-slate-500">Loading…</p>}
      {data && items.length === 0 && (
        <Card>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {data.length === 0 ? (
              <>
                Nothing here yet. <Link className="text-indigo-600 underline" to="/app/add">Paste a placement email</Link>{" "}
                to get started, and fill in your <Link className="text-indigo-600 underline" to="/app/profile">profile</Link>{" "}
                so eligibility can be checked.
              </>
            ) : (
              "No opportunities match this filter."
            )}
          </p>
        </Card>
      )}

      {items.length > 0 && (
        <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-slate-200 dark:divide-slate-800 dark:bg-slate-900 dark:ring-slate-800">
          {items.map((o) => {
            const urgency = deadlineUrgency(o.deadline);
            return (
              <li key={o.id}>
                <Link
                  to={`/app/opportunities/${o.id}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/60"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">
                      {o.company ?? "Unknown company"}
                      {o.role && <span className="font-normal text-slate-500"> · {o.role}</span>}
                    </p>
                    {(o.subject || !o.is_opportunity) && (
                      <p className="truncate text-xs text-slate-500">
                        {[!o.is_opportunity && "Notice, not an application", o.subject].filter(Boolean).join(" · ")}
                      </p>
                    )}
                  </div>
                  <div className={`text-right text-sm ${URGENCY_CLASS[urgency]}`}>
                    <div>{formatDeadline(o.deadline)}</div>
                    {o.deadline && <div className="text-xs">{relativeDeadline(o.deadline)}</div>}
                  </div>
                  <div className="w-28 text-right">
                    <VerdictBadge verdict={o.verdict} />
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function StatTiles({ items }: { items: OpportunitySummary[] }) {
  const count = (v: Verdict) => items.filter((o) => o.verdict === v).length;
  const dueSoon = items.filter((o) => ["urgent", "soon"].includes(deadlineUrgency(o.deadline))).length;
  const tiles = [
    { label: "Eligible", value: count("eligible"), accent: "bg-emerald-500" },
    { label: "Needs review", value: count("needs_review"), accent: "bg-amber-500" },
    { label: "Not eligible", value: count("not_eligible"), accent: "bg-rose-500" },
    { label: "Due in 7 days", value: dueSoon, accent: "bg-indigo-500" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <span className={`size-2 rounded-full ${t.accent}`} />
            {t.label}
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">{t.value}</p>
        </div>
      ))}
    </div>
  );
}

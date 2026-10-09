import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useServerConfig } from "../App";
import { AuditLog } from "../components/AuditLog";
import { Drafts } from "../components/Drafts";
import { EvidenceText } from "../components/EvidenceText";
import { RuleList } from "../components/RuleList";
import { Button, buttonClass, Card, ErrorBox, Notice, VerdictBadge } from "../components/ui";
import { deadlineUrgency, formatDateTime, formatDeadline, formatValue, relativeDeadline, RULE_LABELS } from "../lib/format";
import type { Mark } from "../lib/highlight";
import { useAsync } from "../lib/useAsync";

const FIELD_LABELS: Record<string, string> = {
  ...RULE_LABELS,
  company: "Company",
  role: "Role",
  deadline: "Deadline",
  form_link: "Form link",
};

export function OpportunityPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { config } = useServerConfig();
  const { data: opp, setData, error, loading } = useAsync(() => api.getOpportunity(id), [id]);
  const [activeKey, setActiveKey] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<unknown>(null);

  const rules = opp?.decision?.rules ?? [];
  const marks = useMemo<Mark[]>(
    () =>
      rules.flatMap((r, key) => (r.span ? [{ key, start: r.span[0], end: r.span[1], status: r.status }] : [])),
    [rules],
  );

  async function remove() {
    if (!opp) return;
    const others = opp.siblings.length ? ` and the ${opp.siblings.length} other opportunities from it` : "";
    if (!window.confirm(`Delete this email${others}? This removes it and its audit log from the database.`)) return;
    try {
      await api.deleteEmail(opp.email_id);
      navigate("/");
    } catch (e) {
      setDeleteError(e);
    }
  }

  if (loading && !opp) return <p className="text-sm text-slate-500">Loading…</p>;
  if (error) return <ErrorBox error={error} />;
  if (!opp) return null;

  const decision = opp.decision;
  const urgency = deadlineUrgency(opp.deadline);

  return (
    <div className="space-y-4">
      <Link to="/" className="text-sm text-indigo-600 hover:underline">
        ← All opportunities
      </Link>

      <Card className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">{opp.company ?? "Unknown company"}</h1>
            <p className="text-slate-600 dark:text-slate-400">{opp.role ?? "Role not stated"}</p>
          </div>
          <div className="text-lg">
            <VerdictBadge verdict={opp.verdict} />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <span className={urgency === "urgent" ? "font-semibold text-rose-700 dark:text-rose-400" : ""}>
            Deadline: {formatDeadline(opp.deadline)}
            {opp.deadline && <span className="text-slate-500"> ({relativeDeadline(opp.deadline)})</span>}
          </span>
          {opp.received_at && <span className="text-slate-500">Received {formatDateTime(opp.received_at)}</span>}
          {opp.form_link && (
            <a
              href={opp.form_link}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className={buttonClass("secondary")}
            >
              Open form ↗
            </a>
          )}
        </div>
        {decision && (
          <ul className="list-inside list-disc space-y-0.5 text-sm text-slate-700 dark:text-slate-300">
            {decision.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        {decision?.notes.map((n) => (
          <Notice key={n} tone="warn">
            {n}
          </Notice>
        ))}
        {opp.siblings.length > 0 && (
          <p className="text-sm text-slate-500">
            Same email also lists:{" "}
            {opp.siblings.map((s, i) => (
              <span key={s}>
                {i > 0 && ", "}
                <Link className="text-indigo-600 underline" to={`/opportunities/${s}`}>
                  opportunity #{s}
                </Link>
              </span>
            ))}
          </p>
        )}
      </Card>

      {opp.issues.length > 0 && (
        <Card className="space-y-2">
          <h2 className="font-semibold">Couldn't verify</h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            The LLM reported these, but its quote or value didn't check out against the email, so they were
            ignored. Read the email yourself for these points.
          </p>
          <ul className="space-y-1 text-sm">
            {opp.issues.map((i, n) => (
              <li key={n}>
                <span className="font-medium">{FIELD_LABELS[i.field] ?? i.field}</span>: {formatValue(i.value)} —{" "}
                {i.reason}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3">
          <h2 className="font-semibold">Rules checked</h2>
          <RuleList rules={rules} activeKey={activeKey} onSelect={setActiveKey} />
        </Card>
        <Card className="space-y-3">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="font-semibold">Email</h2>
            <span className="truncate text-xs text-slate-500">{opp.sender ?? opp.subject ?? ""}</span>
          </div>
          <EvidenceText text={opp.email_text} marks={marks} activeKey={activeKey} onSelect={setActiveKey} />
        </Card>
      </div>

      <Card className="space-y-3">
        <h2 className="font-semibold">Draft answers</h2>
        <Drafts
          opportunityId={opp.id}
          drafts={opp.drafts}
          onChange={(drafts) => setData({ ...opp, drafts })}
          llmConfigured={config?.llm_configured ?? false}
        />
      </Card>

      <Card className="space-y-3">
        <AuditLog opportunityId={opp.id} />
        <div className="border-t border-slate-200 pt-3 dark:border-slate-800">
          {!config?.demo_mode && (
            <Button variant="danger" onClick={remove}>
              Delete email
            </Button>
          )}
          <ErrorBox error={deleteError} />
        </div>
      </Card>
    </div>
  );
}

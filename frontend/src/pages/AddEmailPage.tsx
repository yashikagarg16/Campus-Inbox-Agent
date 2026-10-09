import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type IngestResult, type PreviewOpportunity, type PreviewResult } from "../api";
import { useServerConfig } from "../App";
import { EvidenceText } from "../components/EvidenceText";
import { RuleList } from "../components/RuleList";
import { Button, Card, ErrorBox, Field, inputClass, Notice, VerdictBadge } from "../components/ui";
import { formatDeadline } from "../lib/format";
import type { Mark } from "../lib/highlight";
import { useSession } from "../session";

type Mode = "paste" | "upload";

export function AddEmailPage() {
  const navigate = useNavigate();
  const { config } = useServerConfig();
  const { email } = useSession();
  const demo = config?.demo_mode ?? false;
  // On the public demo, a signed-in owner gets a live check that stores nothing.
  const previewOnly = demo && Boolean(email);
  const locked = demo && !email;

  const [mode, setMode] = useState<Mode>("paste");
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);

  const received = receivedAt ? `${receivedAt}:00+05:30` : undefined;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(null);
    try {
      if (previewOnly) {
        setPreview(await api.preview({ text, received_at: received }));
        return;
      }
      const r =
        mode === "paste"
          ? await api.submitEmail({ text, subject: subject || undefined, received_at: received })
          : await api.uploadEml(file!);
      if (r.opportunities.length === 1 && !r.duplicate) {
        navigate(`/app/opportunities/${r.opportunities[0].id}`);
        return;
      }
      setResult(r);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = !locked && (mode === "paste" || previewOnly ? text.trim().length >= 20 : file !== null);

  if (locked) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card className="space-y-4 p-8 text-center">
          <div className="mx-auto inline-flex size-12 items-center justify-center rounded-full bg-indigo-50 text-xl dark:bg-indigo-950">
            🔒
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Live checks are for signed-in users</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Checking a new email calls Gemini, so it's limited to the owner on this public demo. You can still open any
            of the demo opportunities to see the extracted facts, each rule's verdict and the sentence that proves it.
          </p>
          <div className="flex justify-center gap-3">
            <Link to="/app" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500">
              Browse the demo
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Check an email</h1>
        <p className="mt-1 text-sm text-slate-500">
          {previewOnly
            ? "Paste a placement email to run the full pipeline live. Nothing is saved, and it isn't added to the demo."
            : "Paste a placement email or upload a .eml file. It's extracted, verified and checked against your profile."}
        </p>
      </div>
      <Notice>
        Remove anything you don't want sent to the LLM (phone numbers, other students' names) before pasting.
        {previewOnly && " Verdicts use the demo profile."}
      </Notice>

      {!previewOnly && (
        <div className="flex gap-2" role="tablist">
          {(["paste", "upload"] as Mode[]).map((m) => (
            <button
              key={m}
              role="tab"
              type="button"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                mode === m ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "ring-1 ring-slate-300 dark:ring-slate-700"
              }`}
            >
              {m === "paste" ? "Paste text" : "Upload .eml"}
            </button>
          ))}
        </div>
      )}

      <Card>
        <form onSubmit={submit} className="space-y-4">
          {mode === "paste" || previewOnly ? (
            <>
              <Field label="Email text">
                <textarea
                  className={`${inputClass} min-h-64 font-mono`}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Paste the whole email, including the eligibility and deadline lines."
                />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                {!previewOnly && (
                  <Field label="Subject (optional)">
                    <input className={inputClass} value={subject} onChange={(e) => setSubject(e.target.value)} />
                  </Field>
                )}
                <Field label="Received at (optional)" hint="Used to work out the year and words like “tomorrow”. Defaults to now.">
                  <input type="datetime-local" className={inputClass} value={receivedAt} onChange={(e) => setReceivedAt(e.target.value)} />
                </Field>
              </div>
            </>
          ) : (
            <Field label=".eml file" hint="In Outlook on the web: open the email › ⋯ › Download.">
              <input
                type="file"
                accept=".eml,message/rfc822"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block text-sm"
              />
            </Field>
          )}
          <Button type="submit" disabled={!canSubmit || busy}>
            {busy ? "Reading the email… (up to a minute)" : previewOnly ? "Run live check" : "Check eligibility"}
          </Button>
        </form>
      </Card>

      <ErrorBox error={error} />

      {preview && <PreviewResults result={preview} />}

      {result && (
        <Card className="space-y-3">
          {result.duplicate ? (
            <Notice tone="info">You've already added this email, so it wasn't processed again.</Notice>
          ) : (
            <p className="text-sm">This email contains {result.opportunities.length} opportunities:</p>
          )}
          <ul className="space-y-2">
            {result.opportunities.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-2">
                <Link className="text-indigo-600 underline" to={`/app/opportunities/${o.id}`}>
                  {o.company ?? "Unknown company"}
                  {o.role ? ` · ${o.role}` : ""}
                </Link>
                <VerdictBadge verdict={o.verdict} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function PreviewResults({ result }: { result: PreviewResult }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500">
        Found {result.opportunities.length} opportunit{result.opportunities.length === 1 ? "y" : "ies"}. Not saved.
      </p>
      {result.opportunities.map((o, i) => (
        <PreviewCard key={i} opp={o} text={result.email_text} />
      ))}
    </div>
  );
}

function PreviewCard({ opp, text }: { opp: PreviewOpportunity; text: string }) {
  const [activeKey, setActiveKey] = useState<number | null>(null);
  const rules = opp.decision.rules;
  const marks = useMemo<Mark[]>(
    () => rules.flatMap((r, key) => (r.span ? [{ key, start: r.span[0], end: r.span[1], status: r.status }] : [])),
    [rules],
  );
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{opp.company ?? "Unknown company"}</h2>
          <p className="text-sm text-slate-500">
            {opp.role ?? "Role not stated"} · Deadline: {formatDeadline(opp.deadline)}
          </p>
        </div>
        <VerdictBadge verdict={opp.verdict} />
      </div>
      <ul className="list-inside list-disc text-sm text-slate-700 dark:text-slate-300">
        {opp.decision.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {opp.decision.notes.map((n) => (
        <Notice key={n} tone="warn">
          {n}
        </Notice>
      ))}
      {opp.issues.length > 0 && (
        <p className="text-sm text-amber-800 dark:text-amber-300">
          Couldn't verify: {opp.issues.map((i) => i.field).join(", ")}. Check those in the email yourself.
        </p>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <RuleList rules={rules} activeKey={activeKey} onSelect={setActiveKey} />
        <EvidenceText text={text} marks={marks} activeKey={activeKey} onSelect={setActiveKey} />
      </div>
    </Card>
  );
}

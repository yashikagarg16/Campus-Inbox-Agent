import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type IngestResult } from "../api";
import { Button, Card, ErrorBox, Field, inputClass, Notice, VerdictBadge } from "../components/ui";
import { useIsVisitor, useSession } from "../session";

type Mode = "paste" | "upload";

export function AddEmailPage() {
  const navigate = useNavigate();
  const { me, refresh, signOut } = useSession();
  const visitor = useIsVisitor();

  const [mode, setMode] = useState<Mode>("paste");
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<IngestResult | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r =
        mode === "paste"
          ? await api.submitEmail({
              text,
              subject: subject || undefined,
              received_at: receivedAt ? `${receivedAt}:00+05:30` : undefined,
            })
          : await api.uploadEml(file!);
      void refresh(); // usage count changed
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

  if (visitor) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card className="space-y-4 p-8 text-center">
          <div className="mx-auto inline-flex size-12 items-center justify-center rounded-full bg-indigo-50 text-xl dark:bg-indigo-950">
            ✉️
          </div>
          <h1 className="text-xl font-semibold tracking-tight">Check your own placement emails</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Create a free account to paste your emails and get eligibility verdicts against your own profile. Your
            emails stay private to your account. The demo you're browsing is read-only.
          </p>
          <div className="flex justify-center gap-3">
            <button
              type="button"
              onClick={() => {
                signOut();
                navigate("/");
              }}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-500"
            >
              Create a free account
            </button>
            <Link to="/app" className="rounded-lg px-4 py-2 text-sm font-semibold ring-1 ring-slate-300 dark:ring-slate-700">
              Keep browsing the demo
            </Link>
          </div>
        </Card>
      </div>
    );
  }

  const outOfChecks = me?.daily_limit != null && me.usage_today >= me.daily_limit;
  const canSubmit = !outOfChecks && (mode === "paste" ? text.trim().length >= 20 : file !== null);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Check an email</h1>
        <p className="mt-1 text-sm text-slate-500">
          Paste a placement email or upload a .eml file. It's extracted, verified and checked against your profile.
        </p>
      </div>
      {me?.daily_limit != null && (
        <Notice tone={outOfChecks ? "warn" : "info"}>
          {outOfChecks
            ? `You've used all ${me.daily_limit} free checks for today. They reset at midnight IST.`
            : `${me.daily_limit - me.usage_today} of ${me.daily_limit} free checks left today. Re-adding an email you've already checked is free.`}
        </Notice>
      )}
      <Notice>
        Remove anything you don't want sent to the LLM (phone numbers, other students' names) before pasting.
      </Notice>

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

      <Card>
        <form onSubmit={submit} className="space-y-4">
          {mode === "paste" ? (
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
                <Field label="Subject (optional)">
                  <input className={inputClass} value={subject} onChange={(e) => setSubject(e.target.value)} />
                </Field>
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
            {busy ? "Reading the email… (up to a minute)" : "Check eligibility"}
          </Button>
        </form>
      </Card>

      <ErrorBox error={error} />

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

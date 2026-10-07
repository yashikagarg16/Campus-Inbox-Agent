import { useState } from "react";
import { api, type Draft } from "../api";
import { Button, ErrorBox, inputClass, Notice } from "./ui";

interface Props {
  opportunityId: number;
  drafts: Draft[];
  onChange: (drafts: Draft[]) => void;
  llmConfigured: boolean;
}

/** Draft answers to form questions. You edit and approve them; nothing is ever submitted. */
export function Drafts({ opportunityId, drafts, onChange, llmConfigured }: Props) {
  const [questions, setQuestions] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function generate() {
    const list = questions.split("\n").map((q) => q.trim()).filter(Boolean);
    if (!list.length) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.createDrafts(opportunityId, list);
      onChange([...drafts, ...created]);
      setQuestions("");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Notice>
        Paste the questions from the application form, one per line. Drafts use only your profile and
        this email. Edit them, approve them, then copy them into the form yourself.
      </Notice>
      <textarea
        className={`${inputClass} min-h-24`}
        placeholder={"Why do you want to join?\nDescribe a project you are proud of."}
        value={questions}
        onChange={(e) => setQuestions(e.target.value)}
        aria-label="Form questions, one per line"
      />
      <div className="flex items-center gap-3">
        <Button onClick={generate} disabled={busy || !questions.trim() || !llmConfigured}>
          {busy ? "Drafting…" : "Draft answers"}
        </Button>
        {!llmConfigured && <span className="text-xs text-slate-500">The server has no LLM key set.</span>}
      </div>
      <ErrorBox error={error} />
      {drafts.map((d) => (
        <DraftItem
          key={d.id}
          draft={d}
          onSaved={(saved) => onChange(drafts.map((x) => (x.id === saved.id ? saved : x)))}
          onDeleted={() => onChange(drafts.filter((x) => x.id !== d.id))}
        />
      ))}
    </div>
  );
}

function DraftItem({
  draft,
  onSaved,
  onDeleted,
}: {
  draft: Draft;
  onSaved: (d: Draft) => void;
  onDeleted: () => void;
}) {
  const [answer, setAnswer] = useState(draft.answer);
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
  const dirty = answer !== draft.answer;

  async function save(status?: "draft" | "approved") {
    setError(null);
    try {
      onSaved(await api.updateDraft(draft.id, { ...(dirty ? { answer } : {}), ...(status ? { status } : {}) }));
    } catch (e) {
      setError(e);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setError(new Error("Couldn't copy; select the text and copy it manually."));
    }
  }

  async function remove() {
    try {
      await api.deleteDraft(draft.id);
      onDeleted();
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="space-y-2 rounded-md p-3 ring-1 ring-slate-200 dark:ring-slate-800">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">{draft.question}</p>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
            draft.status === "approved"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
              : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
          }`}
        >
          {draft.status === "approved" ? "Approved" : "Draft"}
        </span>
      </div>
      <textarea
        className={`${inputClass} min-h-24`}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        aria-label={`Answer to: ${draft.question}`}
      />
      {draft.warnings.length > 0 && (
        <ul className="list-inside list-disc text-xs text-amber-800 dark:text-amber-300">
          {draft.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        {dirty && (
          <Button variant="secondary" onClick={() => save()}>
            Save edit
          </Button>
        )}
        {(draft.status !== "approved" || dirty) && <Button onClick={() => save("approved")}>Approve</Button>}
        <Button variant="secondary" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button variant="ghost" onClick={remove}>
          Delete
        </Button>
      </div>
      <ErrorBox error={error} />
    </div>
  );
}

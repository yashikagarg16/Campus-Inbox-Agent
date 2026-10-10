import { useEffect, useState, type FormEvent } from "react";
import { api, type Profile } from "../api";
import { useNavigate } from "react-router-dom";
import { useIsVisitor, useSession } from "../session";
import { Button, Card, ErrorBox, Field, inputClass, Notice } from "../components/ui";
import { splitList } from "../lib/format";
import { useAsync } from "../lib/useAsync";

interface FormState {
  name: string;
  batch: string;
  cgpa: string;
  cgpa_scale: string;
  branch: string;
  branch_aliases: string;
  tenth_percent: string;
  twelfth_percent: string;
  active_backlogs: string;
  skills: string;
  resume_summary: string;
}

const str = (v: number | string | null) => (v === null || v === undefined ? "" : String(v));
const num = (v: string) => (v.trim() === "" ? null : Number(v));

export function toForm(p: Profile): FormState {
  return {
    name: str(p.name),
    batch: str(p.batch),
    cgpa: str(p.cgpa),
    cgpa_scale: str(p.cgpa_scale),
    branch: str(p.branch),
    branch_aliases: p.branch_aliases.join(", "),
    tenth_percent: str(p.tenth_percent),
    twelfth_percent: str(p.twelfth_percent),
    active_backlogs: str(p.active_backlogs),
    skills: p.skills.join(", "),
    resume_summary: str(p.resume_summary),
  };
}

export function fromForm(f: FormState): Profile {
  return {
    name: f.name.trim() || null,
    batch: num(f.batch),
    cgpa: num(f.cgpa),
    cgpa_scale: num(f.cgpa_scale) ?? 10,
    branch: f.branch.trim() || null,
    branch_aliases: splitList(f.branch_aliases),
    tenth_percent: num(f.tenth_percent),
    twelfth_percent: num(f.twelfth_percent),
    active_backlogs: num(f.active_backlogs),
    skills: splitList(f.skills),
    resume_summary: f.resume_summary.trim() || null,
  };
}

export function ProfilePage() {
  const { data, error } = useAsync(() => api.getProfile(), []);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const demo = useIsVisitor();
  const { me, signOut } = useSession();
  const navigate = useNavigate();
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (data) setForm(toForm(data));
  }, [data]);

  if (error) return <ErrorBox error={error} />;
  if (!form) return <p className="text-sm text-slate-500">Loading…</p>;

  const set = (key: keyof FormState) => (e: { target: { value: string } }) => {
    setForm({ ...form, [key]: e.target.value });
    setSaved(null);
  };

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    try {
      const r = await api.saveProfile(fromForm(form!));
      setForm(toForm(r.profile));
      setSaved(`Saved. Re-checked ${r.reevaluated} opportunit${r.reevaluated === 1 ? "y" : "ies"} with the new profile.`);
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Your profile</h1>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Eligibility is checked against these values in plain code. Leave a field empty if you don't want it
        checked; rules that need it will show as “needs review”.
      </p>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" hint="Only used in drafted answers.">
              <input className={inputClass} value={form.name} onChange={set("name")} />
            </Field>
            <Field label="Batch (graduation year)">
              <input className={inputClass} type="number" min={2000} max={2100} value={form.batch} onChange={set("batch")} />
            </Field>
            <Field label="CGPA">
              <input className={inputClass} type="number" step="0.01" min={0} value={form.cgpa} onChange={set("cgpa")} />
            </Field>
            <Field label="CGPA scale" hint="10 for most Indian colleges.">
              <input className={inputClass} type="number" step="0.1" min={1} value={form.cgpa_scale} onChange={set("cgpa_scale")} />
            </Field>
            <Field label="Branch" hint="e.g. CSE, ECE, Mechanical">
              <input className={inputClass} value={form.branch} onChange={set("branch")} />
            </Field>
            <Field label="Other names for your branch" hint="Comma-separated, e.g. “CSE (AI&ML), CSE” if emails for CSE include you.">
              <input className={inputClass} value={form.branch_aliases} onChange={set("branch_aliases")} />
            </Field>
            <Field label="10th %">
              <input className={inputClass} type="number" step="0.01" min={0} max={100} value={form.tenth_percent} onChange={set("tenth_percent")} />
            </Field>
            <Field label="12th %">
              <input className={inputClass} type="number" step="0.01" min={0} max={100} value={form.twelfth_percent} onChange={set("twelfth_percent")} />
            </Field>
            <Field label="Active backlogs">
              <input className={inputClass} type="number" min={0} value={form.active_backlogs} onChange={set("active_backlogs")} />
            </Field>
            <Field label="Skills" hint="Comma-separated">
              <input className={inputClass} value={form.skills} onChange={set("skills")} />
            </Field>
          </div>
          <Field label="About you" hint="Projects, internships, interests. Drafted answers use only what's written here.">
            <textarea className={`${inputClass} min-h-32`} value={form.resume_summary} onChange={set("resume_summary")} />
          </Field>
          {demo && <p className="text-sm text-slate-500">This is the demo profile; saving is turned off in the public demo.</p>}
          <Button type="submit" disabled={saving || demo}>
            {saving ? "Saving…" : "Save profile"}
          </Button>
        </form>
      </Card>
      <ErrorBox error={saveError} />
      {saved && <Notice tone="ok">{saved}</Notice>}
      {me?.role === "user" && <DeleteAccount onDeleted={() => { signOut(); navigate("/"); }} />}
    </div>
  );
}

function DeleteAccount({ onDeleted }: { onDeleted: () => void }) {
  const [error, setError] = useState<unknown>(null);
  async function remove() {
    if (!window.confirm("Delete your account? This permanently removes your profile, emails and drafts.")) return;
    try {
      await api.deleteAccount();
      onDeleted();
    } catch (e) {
      setError(e);
    }
  }
  return (
    <Card className="space-y-2">
      <h2 className="font-semibold">Delete account</h2>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Permanently removes your account and everything stored in it. This can't be undone.
      </p>
      <Button variant="danger" onClick={remove}>
        Delete my account
      </Button>
      <ErrorBox error={error} />
    </Card>
  );
}

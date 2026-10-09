import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useServerConfig } from "../App";
import { Logo } from "../components/Logo";
import { ErrorBox, inputClass } from "../components/ui";
import { useSession } from "../session";

const FEATURES = [
  { title: "Evidence for every verdict", body: "Each rule links to the exact sentence in the email that proves it." },
  { title: "The LLM reads, code decides", body: "Gemini extracts the facts; plain Python compares them with your profile." },
  { title: "Says “needs review” instead of guessing", body: "Vague criteria and unverifiable quotes are never turned into a yes or no." },
];

export function LandingPage() {
  const { email, demo, signIn, enterDemo } = useSession();
  const { config } = useServerConfig();
  const navigate = useNavigate();
  const [address, setAddress] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (email || demo) return <Navigate to="/app" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(address, password);
      navigate("/app");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  function openDemo() {
    enterDemo();
    navigate("/app");
  }

  const loginAvailable = config?.owner_login ?? false;

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-slate-950 px-12 py-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -left-32 -top-32 size-[28rem] rounded-full bg-indigo-600/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 right-0 size-[30rem] rounded-full bg-violet-600/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <Logo className="size-9" />
          <span className="text-lg font-semibold tracking-tight">Campus Inbox Agent</span>
        </div>

        <div className="relative mt-auto max-w-xl">
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">
            Know which placement emails you're eligible for, <span className="text-indigo-300">with proof.</span>
          </h1>
          <ul className="mt-8 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-3">
                <span className="mt-1 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-indigo-500/20 text-xs text-indigo-200 ring-1 ring-indigo-400/40">
                  ✓
                </span>
                <div>
                  <p className="font-medium">{f.title}</p>
                  <p className="text-sm text-slate-400">{f.body}</p>
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-10 rounded-xl bg-white/5 p-4 ring-1 ring-white/10 backdrop-blur">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>Quantly · Quant Research Internship</span>
              <span className="rounded-full bg-rose-500/15 px-2 py-0.5 font-semibold text-rose-300 ring-1 ring-rose-400/30">
                Not eligible
              </span>
            </div>
            <p className="mt-3 font-mono text-[13px] leading-relaxed text-slate-300">
              Please{" "}
              <mark className="rounded bg-rose-400/25 px-0.5 text-rose-100">register only if you're 8.5+ out of 10</mark>.
            </p>
            <p className="mt-2 text-xs text-slate-400">Your CGPA 8.2 is below the minimum 8.5.</p>
          </div>
        </div>

        <p className="relative mt-12 text-xs text-slate-500">
          Read-only by design · never submits forms or sends email · FastAPI · Gemini · React
        </p>
      </section>

      <section className="flex items-center justify-center bg-slate-50 px-6 py-12 dark:bg-slate-950">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logo className="size-8" />
            <span className="font-semibold tracking-tight">Campus Inbox Agent</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-slate-500">Welcome back. Sign in to run live checks on your emails.</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">Email</span>
              <input
                type="email"
                autoComplete="username"
                className={inputClass}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                disabled={!loginAvailable}
                required
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium">Password</span>
              <input
                type="password"
                autoComplete="current-password"
                className={inputClass}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={!loginAvailable}
                required
              />
            </label>
            <ErrorBox error={error} />
            <button
              type="submit"
              disabled={busy || !loginAvailable}
              className="w-full rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
            {config && !loginAvailable && (
              <p className="text-xs text-slate-500">Sign-in isn't set up on this server.</p>
            )}
          </form>

          {config?.demo_mode && (
            <>
              <div className="my-8 flex items-center gap-3 text-xs uppercase tracking-wider text-slate-400">
                <span className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
                or
                <span className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
              </div>
              <button
                type="button"
                onClick={openDemo}
                className="w-full rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 transition hover:bg-slate-50 dark:bg-slate-900 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-800"
              >
                Explore the live demo →
              </button>
              <p className="mt-3 text-center text-xs text-slate-500">
                No account needed. 36 synthetic placement emails with real Gemini extractions.
              </p>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

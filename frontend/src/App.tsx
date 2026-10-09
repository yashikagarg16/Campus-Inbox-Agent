import { createContext, useContext, type ReactNode } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useNavigate } from "react-router-dom";
import { api, type ServerConfig } from "./api";
import { Logo } from "./components/Logo";
import { useAsync } from "./lib/useAsync";
import { AddEmailPage } from "./pages/AddEmailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LandingPage } from "./pages/LandingPage";
import { OpportunityPage } from "./pages/OpportunityPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SettingsPage } from "./pages/SettingsPage";
import { SessionProvider, useSession } from "./session";

interface ConfigState {
  config: ServerConfig | null;
  error: unknown;
  reload: () => Promise<void>;
}

const ConfigContext = createContext<ConfigState>({ config: null, error: null, reload: async () => {} });
export const useServerConfig = () => useContext(ConfigContext);

export default function App() {
  const { data, error, reload } = useAsync(() => api.config(), []);
  return (
    <ConfigContext.Provider value={{ config: data, error, reload }}>
      <SessionProvider>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/app" element={<RequireSession><Shell /></RequireSession>}>
            <Route index element={<DashboardPage />} />
            <Route path="add" element={<AddEmailPage />} />
            <Route path="opportunities/:id" element={<OpportunityPage />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </SessionProvider>
    </ConfigContext.Provider>
  );
}

function RequireSession({ children }: { children: ReactNode }) {
  const { email, demo, checking } = useSession();
  const { config, error } = useServerConfig();
  if (checking) return <FullPageMessage>Loading…</FullPageMessage>;
  // A local server with no sign-in configured needs no session.
  const open = config && !config.auth_required && !config.demo_mode;
  if (email || demo || open || error) return <>{children}</>;
  if (!config) return <FullPageMessage>Loading…</FullPageMessage>;
  return <Navigate to="/" replace />;
}

function FullPageMessage({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">{children}</div>;
}

const NAV = [
  { to: "/app", label: "Opportunities", end: true, icon: "M4 6h16M4 12h16M4 18h10" },
  { to: "/app/add", label: "Check an email", end: false, icon: "M12 5v14M5 12h14" },
  { to: "/app/profile", label: "Profile", end: false, icon: "M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0" },
];

function NavIcon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function Shell() {
  const { email, demo, signOut } = useSession();
  const { config } = useServerConfig();
  const navigate = useNavigate();
  const isDemo = config?.demo_mode ?? false;

  const links = isDemo
    ? NAV
    : [...NAV, { to: "/app/settings", label: "Settings", end: false, icon: "M12 15a3 3 0 100-6 3 3 0 000 6z" }];

  function leave() {
    signOut();
    navigate("/");
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <aside className="border-b border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col lg:border-b-0 lg:border-r dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-2.5 px-5 py-4">
          <Logo className="size-7" />
          <span className="font-semibold tracking-tight">Campus Inbox Agent</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:pb-0">
          {links.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              <NavIcon d={n.icon} />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-slate-200 p-4 lg:block dark:border-slate-800">
          {email ? (
            <div className="flex items-center gap-3">
              <span className="inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 text-xs font-semibold uppercase text-white">
                {email.slice(0, 2)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{email}</p>
                <button onClick={leave} className="text-xs text-slate-500 hover:text-slate-900 dark:hover:text-slate-100">
                  Sign out
                </button>
              </div>
            </div>
          ) : (
            <div>
              <p className="text-sm font-medium">{demo ? "Demo visitor" : "Local mode"}</p>
              {demo && (
                <button onClick={leave} className="text-xs text-indigo-600 hover:underline dark:text-indigo-400">
                  Sign in instead
                </button>
              )}
            </div>
          )}
        </div>
      </aside>

      <div className="min-w-0">
        {isDemo && (
          <div className="border-b border-amber-200/70 bg-amber-50/80 dark:border-amber-900 dark:bg-amber-950/60">
            <p className="mx-auto max-w-6xl px-6 py-2 text-xs text-amber-900 dark:text-amber-200">
              <strong>Read-only demo.</strong> Synthetic placement emails with real Gemini extractions, checked against a
              demo profile.{" "}
              <a className="underline" href="https://github.com/yashikagarg16/Campus-Inbox-Agent" target="_blank" rel="noreferrer">
                Source on GitHub
              </a>
            </p>
          </div>
        )}
        <main className="mx-auto max-w-6xl px-6 py-8">
          <Outlet />
        </main>
        <footer className="mx-auto max-w-6xl px-6 pb-8 text-xs text-slate-500">
          Read-only by design. This app never submits forms or sends email for you. Always check the original email.
          {(email || demo) && (
            <button onClick={leave} className="ml-3 underline lg:hidden">
              {email ? "Sign out" : "Leave demo"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

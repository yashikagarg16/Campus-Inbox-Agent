import { createContext, useContext } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, type ServerConfig } from "./api";
import { useAsync } from "./lib/useAsync";
import { AddEmailPage } from "./pages/AddEmailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { OpportunityPage } from "./pages/OpportunityPage";
import { ProfilePage } from "./pages/ProfilePage";
import { SettingsPage } from "./pages/SettingsPage";

interface ConfigState {
  config: ServerConfig | null;
  error: unknown;
  reload: () => Promise<void>;
}

const ConfigContext = createContext<ConfigState>({ config: null, error: null, reload: async () => {} });
export const useServerConfig = () => useContext(ConfigContext);

const NAV = [
  { to: "/", label: "Opportunities", end: true },
  { to: "/add", label: "Add email" },
  { to: "/profile", label: "Profile" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  const { data, error, reload } = useAsync(() => api.config(), []);

  return (
    <ConfigContext.Provider value={{ config: data, error, reload }}>
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <NavLink to="/" className="text-base font-semibold tracking-tight">
            Campus Inbox Agent
          </NavLink>
          <nav className="flex flex-wrap gap-1">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium ${
                    isActive
                      ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/add" element={<AddEmailPage />} />
          <Route path="/opportunities/:id" element={<OpportunityPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-slate-500">
        Read-only. This app never submits forms or sends email for you. Always check the original email.
      </footer>
    </ConfigContext.Provider>
  );
}

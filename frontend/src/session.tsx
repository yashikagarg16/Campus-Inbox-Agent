import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, getToken, setToken } from "./api";

const DEMO_KEY = "cia.demo";

interface SessionState {
  /** Signed-in owner's email, or null. */
  email: string | null;
  /** Browsing the public demo without signing in. */
  demo: boolean;
  checking: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  enterDemo: () => void;
}

const SessionContext = createContext<SessionState | null>(null);

function readDemo(): boolean {
  try {
    return sessionStorage.getItem(DEMO_KEY) === "1";
  } catch {
    return false;
  }
}

function writeDemo(on: boolean): void {
  try {
    if (on) sessionStorage.setItem(DEMO_KEY, "1");
    else sessionStorage.removeItem(DEMO_KEY);
  } catch {
    // storage blocked; demo flag lasts for this page only
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [demo, setDemo] = useState(readDemo);
  const [checking, setChecking] = useState(() => Boolean(getToken()));

  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then((me) => setEmail(me.email))
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) setToken(""); // expired or revoked
      })
      .finally(() => setChecking(false));
  }, []);

  const signIn = useCallback(async (address: string, password: string) => {
    const r = await api.login(address, password);
    setToken(r.token);
    setEmail(r.email);
    writeDemo(false);
    setDemo(false);
  }, []);

  const signOut = useCallback(() => {
    setToken("");
    setEmail(null);
    writeDemo(false);
    setDemo(false);
  }, []);

  const enterDemo = useCallback(() => {
    writeDemo(true);
    setDemo(true);
  }, []);

  return (
    <SessionContext.Provider value={{ email, demo, checking, signIn, signOut, enterDemo }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}

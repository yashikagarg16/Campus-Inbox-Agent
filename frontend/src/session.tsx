import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, getToken, setToken, type Me } from "./api";

const DEMO_KEY = "cia.demo";

interface SessionState {
  /** Signed-in account's email, or null. */
  email: string | null;
  /** Role, today's usage and limit for the signed-in account. */
  me: Me | null;
  /** Browsing the public demo without signing in. */
  demo: boolean;
  checking: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => void;
  enterDemo: () => void;
  /** Re-read usage after an action that calls the LLM. */
  refresh: () => Promise<void>;
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
  const [me, setMe] = useState<Me | null>(null);
  const [demo, setDemo] = useState(readDemo);
  const [checking, setChecking] = useState(() => Boolean(getToken()));

  const refresh = useCallback(async () => {
    if (!getToken()) return;
    try {
      setMe(await api.me());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setToken(""); // expired, revoked or deleted
        setMe(null);
      }
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    refresh().finally(() => setChecking(false));
  }, [refresh]);

  const start = useCallback(
    async (token: string) => {
      setToken(token);
      writeDemo(false);
      setDemo(false);
      await refresh();
    },
    [refresh],
  );

  const signIn = useCallback(async (email: string, password: string) => {
    await start((await api.login(email, password)).token);
  }, [start]);

  const signUp = useCallback(async (email: string, password: string) => {
    await start((await api.signup(email, password)).token);
  }, [start]);

  const signOut = useCallback(() => {
    setToken("");
    setMe(null);
    writeDemo(false);
    setDemo(false);
  }, []);

  const enterDemo = useCallback(() => {
    writeDemo(true);
    setDemo(true);
  }, []);

  return (
    <SessionContext.Provider
      value={{ email: me?.email ?? null, me, demo, checking, signIn, signUp, signOut, enterDemo, refresh }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionState {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}

/** A demo visitor who isn't signed in: can look, can't change anything. */
export function useIsVisitor(): boolean {
  const { email, demo } = useSession();
  return !email && demo;
}

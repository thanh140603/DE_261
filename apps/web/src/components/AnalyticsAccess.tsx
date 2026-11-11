import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { analyticsApi, type LakehouseSession } from "../analytics";
import { useFetch } from "../hooks";
import { Btn, Callout, Status } from "./ui";

export type Role = "instructor" | "advisor" | "admin";
const ROLE_LABEL: Record<Role, string> = { instructor: "Instructor", advisor: "Advisor", admin: "Organisation admin" };
const DEMO_TOKEN: Record<Role, string> = { instructor: "instructor-demo", advisor: "advisor-demo", admin: "admin-demo" };
const storageKey = (role: Role) => `br45-${role}-token`;

function read(role: Role) {
  try { return sessionStorage.getItem(storageKey(role)) ?? ""; } catch { return ""; }
}

interface Auth {
  token: (role: Role) => string;
  identity: (role: Role) => string | null;
  signIn: (role: Role, token: string) => void;
  signOut: (role: Role) => void;
  setIdentity: (role: Role, id: string | null) => void;
}
const AuthContext = createContext<Auth | null>(null);

/** One token per role, kept for the browser tab (sessionStorage) and shared by every page of that workspace. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [tokens, setTokens] = useState<Record<Role, string>>(() => ({ instructor: read("instructor"), advisor: read("advisor"), admin: read("admin") }));
  const [ids, setIds] = useState<Record<Role, string | null>>({ instructor: null, advisor: null, admin: null });
  const signIn = useCallback((role: Role, value: string) => {
    try { sessionStorage.setItem(storageKey(role), value); } catch { /* private mode: keep in memory */ }
    setTokens((t) => ({ ...t, [role]: value }));
  }, []);
  const signOut = useCallback((role: Role) => {
    try { sessionStorage.removeItem(storageKey(role)); } catch { /* ignore */ }
    setTokens((t) => ({ ...t, [role]: "" }));
    setIds((i) => ({ ...i, [role]: null }));
  }, []);
  const setIdentity = useCallback((role: Role, id: string | null) => setIds((i) => (i[role] === id ? i : { ...i, [role]: id })), []);
  const value = useMemo<Auth>(() => ({
    token: (r) => tokens[r], identity: (r) => ids[r], signIn, signOut, setIdentity,
  }), [tokens, ids, signIn, signOut, setIdentity]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Sign-in gate. `source` picks the session endpoint: BR4/BR5 PostgreSQL or the BR6-BR8 lakehouse. */
export function AnalyticsAccess({ role, source = "br45", children }: {
  role: Role;
  source?: "br45" | "lakehouse";
  children: (token: string, session: LakehouseSession) => ReactNode;
}) {
  const auth = useAuth();
  const token = auth.token(role);
  const session = useFetch<LakehouseSession>(token ? async () => {
    const client = analyticsApi(token);
    return source === "lakehouse" ? client.lakehouseSession() : { organisations: [], ...(await client.session()) };
  } : null, [token, source]);
  const authorized = !!token && session.data?.role === role && !session.error;
  useEffect(() => { auth.setIdentity(role, authorized ? session.data!.id : null); }, [authorized, session.data, role]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!token) return <SignIn role={role} />;
  return (
    <Status loading={session.loading && !session.data} error={session.error}>
      {session.data && session.data.role !== role
        ? <Callout tone="bad">This token does not grant {role} access. <Btn variant="link" onClick={() => auth.signOut(role)}>Use a different token</Btn></Callout>
        : authorized && children(token, session.data!)}
      {session.error && <div className="actions"><Btn onClick={() => auth.signOut(role)}>Use a different token</Btn></div>}
    </Status>
  );
}

function SignIn({ role }: { role: Role }) {
  const auth = useAuth();
  const [input, setInput] = useState("");
  return (
    <section className="card signin" aria-label={`${ROLE_LABEL[role]} sign in`}>
      <h2>Sign in as {ROLE_LABEL[role].toLowerCase()}</h2>
      <p className="muted small" style={{ marginTop: 6 }}>
        {role === "admin"
          ? "Reports are scoped to the organisations your token allows."
          : "Records are scoped to the courses your token allows."}
      </p>
      <form onSubmit={(e) => { e.preventDefault(); if (input.trim()) auth.signIn(role, input.trim()); }}>
        <label className="field">Access token
          <input className="input full" type="password" autoComplete="off" value={input} onChange={(e) => setInput(e.target.value)} aria-label={`${role} access token`} />
        </label>
        <Btn type="submit" variant="primary" disabled={!input.trim()}>Connect</Btn>
      </form>
      <p className="xs muted" style={{ marginTop: 12 }}>Local demo token: <code>{DEMO_TOKEN[role]}</code></p>
    </section>
  );
}

export function useAnalyticsPolling(reload: () => Promise<void>, ms = 5000) {
  useEffect(() => { const id = window.setInterval(() => void reload(), ms); return () => window.clearInterval(id); }, [reload, ms]);
}

export const localDateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "No observation";
export const utcDay = (value: string, end = false) =>
  value ? new Date(new Date(`${value}T00:00:00Z`).getTime() + (end ? 86400000 : 0)).toISOString() : undefined;

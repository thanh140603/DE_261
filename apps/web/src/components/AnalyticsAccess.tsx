import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { analyticsApi, type AnalyticsClient, type LakehouseSession, type StaffIdentity, type StaffRole } from "../analytics";
import { api, ApiError } from "../api";
import { useAction, useFetch } from "../hooks";
import { useStore } from "../store";
import { Btn, Callout, Status } from "./ui";

export type Role = StaffRole;
const ROLES = ["instructor", "advisor", "admin"] as const;
const ROLE_LABEL: Record<Role, string> = { instructor: "Instructor", advisor: "Advisor", admin: "Organisation admin" };
type Identities = Partial<Record<Role, StaffIdentity | null>>;

interface Auth {
  identities: Identities;
  errors: Partial<Record<Role, string>>;
  clients: Record<Role, AnalyticsClient>;
  signIn: (role: Role, username: string, password: string) => Promise<void>;
  signOut: (role: Role) => Promise<void>;
}
const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [identities, setIdentities] = useState<Identities>({});
  const [errors, setErrors] = useState<Partial<Record<Role, string>>>({});
  useEffect(() => {
    const pending = new AbortController();
    for (const role of ROLES) {
      void api.staff.current(role, pending.signal).then((identity) => {
        if (!pending.signal.aborted) setIdentities((current) => ({ ...current, [role]: identity }));
      }, (error: unknown) => {
        if (pending.signal.aborted) return;
        setIdentities((current) => ({ ...current, [role]: null }));
        if (!(error instanceof ApiError && error.status === 401)) {
          setErrors((current) => ({ ...current, [role]: (error as Error).message }));
        }
      });
    }
    return () => pending.abort();
  }, []);
  const signIn = useCallback(async (role: Role, username: string, password: string) => {
    const identity = await api.staff.login(role, username, password);
    setIdentities((current) => ({ ...current, [role]: identity }));
    setErrors((current) => ({ ...current, [role]: undefined }));
  }, []);
  const signOut = useCallback(async (role: Role) => {
    await api.staff.logout(role);
    setIdentities((current) => ({ ...current, [role]: null }));
  }, []);
  const clients = useMemo(() => {
    const client = (role: Role) => analyticsApi(role, () => {
      setIdentities((current) => current[role] === identities[role] ? { ...current, [role]: null } : current);
    });
    return { instructor: client("instructor"), advisor: client("advisor"), admin: client("admin") };
  }, [identities]);
  return <AuthContext.Provider value={{ identities, errors, clients, signIn, signOut }}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function AnalyticsAccess({ role, source = "br45", children }: {
  role: Role;
  source?: "br45" | "lakehouse" | "identity";
  children: (client: AnalyticsClient, session: LakehouseSession) => ReactNode;
}) {
  const { identities, clients } = useAuth();
  const { overview } = useStore();
  const identity = identities[role];
  const client = clients[role];
  const session = useFetch<LakehouseSession>(identity && source !== "identity" ? async () => {
    return source === "lakehouse" ? client.lakehouseSession() : { organisations: [], ...(await client.session()) };
  } : null, [identity, client, source]);
  // Even an idle dashboard must return to sign-in after expiry or API restart.
  const checkSession = useCallback(async () => {
    await client.currentStaffSession().catch(() => undefined);
  }, [client]);
  useAnalyticsPolling(checkSession, identity ? 30000 : null);

  if (identity === undefined) return <p role="status">Checking staff session…</p>;
  if (!identity) return <SignIn role={role} />;
  if (source === "identity") {
    return children(client, {
      ...identity,
      courses: identity.courses.map((id) => ({ id, title: id })),
      organisations: identity.organisations.map((id) => ({
        id, name: overview?.organisations.find((org) => org.id === id)?.name ?? id,
      })),
    });
  }
  return <Status loading={session.loading} error={session.error}>
    {session.data && session.data.role === role && session.data.id === identity.id && children(client, session.data)}
  </Status>;
}

function SignIn({ role }: { role: Role }) {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useAction(async () => {
    await auth.signIn(role, username.trim(), password);
    setPassword("");
  });
  const error = login.error ?? auth.errors[role];
  return (
    <section className="card signin" aria-label={`${ROLE_LABEL[role]} sign in`}>
      <h2>Sign in as {ROLE_LABEL[role].toLowerCase()}</h2>
      {error && <Callout tone="bad">{error}</Callout>}
      <form onSubmit={(event) => { event.preventDefault(); void login.run(); }}>
        <label className="field">Username
          <input className="input full" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={64} />
        </label>
        <label className="field">Password
          <input className="input full" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={128} />
        </label>
        <Btn type="submit" variant="primary" disabled={login.pending}>Sign in</Btn>
      </form>
    </section>
  );
}

export function useAnalyticsPolling(reload: () => Promise<void>, ms: number | null = 5000) {
  useEffect(() => { if (ms === null) return; const id = window.setInterval(() => void reload(), ms); return () => window.clearInterval(id); }, [reload, ms]);
}

export function AnalyticsFreshness({ client }: { client: AnalyticsClient }) {
  const diagnostics = useFetch(() => client.diagnostics(), [client]);
  useAnalyticsPolling(diagnostics.reload);
  const heartbeat = diagnostics.data?.state.find((s) => s.key === "cdc_heartbeat");
  const stream = diagnostics.data?.state.find((s) => s.key === "spark_progress");
  const risk = diagnostics.data?.state.find((s) => s.key === "risk_refresh");
  const features = diagnostics.data?.state.find((s) => s.key === "feature_freshness")?.value;
  const pending = features?.caught_up === false || (diagnostics.data?.outbox_pending ?? 0) > 0;
  const stale = !heartbeat || !stream || [heartbeat, stream].some((s) => Date.now() - Date.parse(s.updated_at) > 120000);
  const label = diagnostics.error ? "Pipeline unavailable" : stale ? "Pipeline status is stale"
    : pending ? "Waiting for committed activity windows" : risk ? "Risk results published" : "Waiting for the first risk evaluation";
  return <div className={stale || diagnostics.error ? "freshness stale" : "freshness"} role="status">
    <strong>{label}</strong>
    <span>Last risk publication · {localDateTime(risk?.updated_at)}</span>
    <span>CDC heartbeat · {localDateTime(heartbeat?.updated_at)}</span>
    <span>Pending activity events · {diagnostics.data?.outbox_pending ?? "—"}</span>
  </div>;
}

export function Pager({ offset, total, limit = 20, onChange }: { offset: number; total: number; limit?: number; onChange: (offset: number) => void }) {
  return <div className="toolbar" aria-label="Pagination">
    <Btn onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>Previous</Btn>
    <span className="small num">{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : "0 results"}</span>
    <Btn onClick={() => onChange(offset + limit)} disabled={offset + limit >= total}>Next</Btn>
  </div>;
}

export const localDateTime = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "No observation";
export const utcDay = (value: string, end = false) =>
  value ? new Date(new Date(`${value}T00:00:00Z`).getTime() + (end ? 86400000 : 0)).toISOString() : undefined;

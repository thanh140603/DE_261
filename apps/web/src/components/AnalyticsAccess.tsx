import { useEffect, useState, type ReactNode } from "react";
import { analyticsApi, type AnalyticsSession } from "../analytics";
import { useFetch } from "../hooks";
import { Btn, Status } from "./ui";

export function AnalyticsAccess({ role, children }: {
  role: "instructor" | "advisor";
  children: (token: string, session: AnalyticsSession) => ReactNode;
}) {
  const storageKey = `br45-${role}-token`;
  const [token, setToken] = useState(() => sessionStorage.getItem(storageKey) ?? "");
  const [input, setInput] = useState(token);
  const session = useFetch(token ? () => analyticsApi(token).session() : null, [token]);
  const authorized = !!token && session.data?.role === role && !session.error && !session.loading;
  function connect() { sessionStorage.setItem(storageKey, input.trim()); setToken(input.trim()); void session.reload(); }
  function disconnect() { sessionStorage.removeItem(storageKey); setToken(""); setInput(""); }
  return <>
    <form className="toolbar analytics-access" onSubmit={(event) => { event.preventDefault(); connect(); }}>
      <label className="field"><span>{role === "instructor" ? "Instructor" : "Advisor"} access token</span>
        <input type="password" autoComplete="off" value={input} onChange={(event) => setInput(event.target.value)} aria-label={`${role} access token`} />
      </label>
      <button className="btn" type="submit" disabled={!input.trim()}>Connect</button>
      {authorized && <><span className="muted small">Signed in as {session.data!.id}</span><Btn onClick={disconnect}>Disconnect</Btn></>}
    </form>
    {!token && <p className="empty">Enter your course-scoped access token to load assessment and learner records.</p>}
    {token && <Status loading={session.loading} error={session.error}>
      {session.data && session.data.role !== role && <p className="error">This token does not grant {role} access. Connect with a {role} token.</p>}
      {authorized && children(token, session.data!)}
    </Status>}
  </>;
}

export function useAnalyticsPolling(reload: () => Promise<void>) {
  useEffect(() => { const id = window.setInterval(() => void reload(), 5000); return () => window.clearInterval(id); }, [reload]);
}

export function Pager({ offset, total, limit = 20, onChange }: { offset: number; total: number; limit?: number; onChange: (offset: number) => void }) {
  return <div className="toolbar" aria-label="Pagination">
    <Btn onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>Previous</Btn>
    <span className="small num">{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : "0 results"}</span>
    <Btn onClick={() => onChange(offset + limit)} disabled={offset + limit >= total}>Next</Btn>
  </div>;
}

export const localDateTime = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : "No observation";
export const utcDay = (value: string, end = false) => value ? new Date(new Date(`${value}T00:00:00Z`).getTime() + (end ? 86400000 : 0)).toISOString() : undefined;

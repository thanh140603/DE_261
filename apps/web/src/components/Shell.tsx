import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { formatTime, initials, relTime } from "../hooks";
import { notificationIcon, useNotifications } from "../notifications";
import { useStore } from "../store";
import type { SseMessage } from "../types";
import { locate, WORKSPACES, type WorkspaceDef } from "../workspaces";
import { useAuth } from "./AnalyticsAccess";
import { Icon } from "./Icon";
import { Callout } from "./ui";

function stored(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function store(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* private mode */ }
}
const systemDark = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

export function Shell({ children }: { children: ReactNode }) {
  const { overviewError } = useStore();
  const { pathname } = useLocation();
  const { ws, page } = locate(pathname);
  useEffect(() => { document.title = `${page.label} · EduPlatform`; }, [page.label]);
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return (
    <div className="app">
      <Sidebar current={ws} />
      <div className="main-col">
        <TopBar ws={ws} pageLabel={page.label} />
        <main>
          {overviewError && (
            <div className="server-error">
              <Callout tone="bad">The server is not reachable ({overviewError}). Start it with <code>uvicorn edu_platform.entrypoints.api.main:app</code> and reload.</Callout>
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}

function Sidebar({ current }: { current: WorkspaceDef }) {
  const { overview, learnerId } = useStore();
  const auth = useAuth();
  const learnerName = overview?.learners.find((l) => l.id === learnerId)?.name;
  const [showBr, setShowBr] = useState(() => stored("ui-br") !== "0");
  const [theme, setTheme] = useState<string | null>(() => stored("ui-theme"));
  const [dark, setDark] = useState(() => (theme ? theme === "dark" : systemDark()));
  useLayoutEffect(() => { document.body.classList.toggle("hide-br", !showBr); }, [showBr]);
  useLayoutEffect(() => {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
    setDark(theme ? theme === "dark" : systemDark());
  }, [theme]);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => { if (!stored("ui-theme")) setDark(mq.matches); };
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  const who = (w: WorkspaceDef) =>
    w.id === "learner" ? learnerName ?? "Choose a learner"
      : w.role ? (auth.identity(w.role) ?? (auth.token(w.role) ? "Signed in" : "Not signed in"))
        : "Demo runtime";
  return (
    <aside className="sidebar" aria-label="Workspaces and pages">
      <div className="brand">
        <div className="brand-mark"><Icon name="cap" /></div>
        <div>EduPlatform<small>Learning analytics</small></div>
      </div>
      <div className="nav-label" id="ws-label">Workspace</div>
      <nav className="nav-list" aria-labelledby="ws-label">
        {WORKSPACES.map((w) => (
          <Link key={w.id} to={w.pages[0].path} className={`nav-btn${w.id === current.id ? " current" : ""}`} aria-current={w.id === current.id ? "true" : undefined}>
            <span className="ws-ico"><Icon name={w.icon} /></span>
            <span className="grow">{w.label}<span className="who">{who(w)}</span></span>
          </Link>
        ))}
      </nav>
      <div className="nav-label" id="pg-label">Pages</div>
      <nav className="nav-list" aria-labelledby="pg-label">
        {current.pages.map((p) => (
          <NavLink key={p.path} to={p.path} end className="nav-btn">
            <Icon name={p.icon} /><span className="grow">{p.label}</span><span className="br">{p.br}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        <label className="switch">Requirement tags
          <input type="checkbox" checked={showBr} onChange={(e) => { setShowBr(e.target.checked); store("ui-br", e.target.checked ? "1" : "0"); }} />
        </label>
        <label className="switch">Dark theme
          <input type="checkbox" checked={dark} onChange={(e) => { const v = e.target.checked ? "dark" : "light"; store("ui-theme", v); setTheme(v); }} />
        </label>
        <p className="xs muted foot-note">Each page is tagged with the business requirement it serves.</p>
      </div>
    </aside>
  );
}

function TopBar({ ws, pageLabel }: { ws: WorkspaceDef; pageLabel: string }) {
  const { overview, learnerId, setLearnerId } = useStore();
  const auth = useAuth();
  const identity = ws.role ? auth.identity(ws.role) : null;
  const learners = overview?.learners ?? [];
  const learnerName = learners.find((l) => l.id === learnerId)?.name ?? "";
  return (
    <header className="topbar">
      <div className="crumbs">{ws.label} <Icon name="arrow-right" /> <b>{pageLabel}</b></div>
      <div className="top-tools">
        <LiveEvents />
        {ws.id === "learner" && (
          <>
            <select className="top-select" aria-label="Learner" value={learnerId} onChange={(e) => setLearnerId(e.target.value)}>
              {learners.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <Bell learnerId={learnerId} />
            <span className="avatar" title={learnerName}>{learnerName ? initials(learnerName) : "?"}</span>
          </>
        )}
        {ws.role && identity && (
          <>
            <span className="session-chip" title={`Signed in as ${identity}`}><Icon name="shield" />{identity}</span>
            <button className="icon-btn" onClick={() => auth.signOut(ws.role!)} aria-label="Sign out" title="Sign out"><Icon name="logout" /></button>
            <span className="avatar">{initials(identity)}</span>
          </>
        )}
      </div>
    </header>
  );
}

function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return { open, setOpen, ref };
}

function Bell({ learnerId }: { learnerId: string }) {
  const { q, unread, isUnread, markSeen } = useNotifications(learnerId);
  const pop = usePopover();
  const navigate = useNavigate();
  return (
    <div className="pop-anchor" ref={pop.ref}>
      <button className="icon-btn" aria-label={`Notifications, ${unread} unread`} aria-expanded={pop.open} onClick={() => pop.setOpen(!pop.open)}>
        <Icon name="bell" />{unread > 0 && <span className="count">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {pop.open && (
        <div className="popover" role="dialog" aria-label="Notifications">
          <h3>Notifications {unread > 0 && <button className="btn sm ghost" onClick={markSeen}>Mark all read</button>}</h3>
          {(q.data ?? []).slice(0, 6).map((n) => (
            <div key={n.id} className={`notif${isUnread(n) ? " unread" : ""}${n.priority === "high" ? " high" : ""}`}>
              <div className="notif-ico"><Icon name={notificationIcon(n)} /></div>
              <div>
                <div className="notif-title" style={{ fontSize: 13 }}>{n.title}</div>
                <div className="notif-meta" style={{ marginTop: 2 }}>{relTime(n.created_at)}</div>
              </div>
            </div>
          ))}
          {q.data?.length === 0 && <p className="empty">No notifications yet.</p>}
          <button className="btn sm" style={{ marginTop: 8 }} onClick={() => { pop.setOpen(false); navigate("/learner"); }}>Open all notifications</button>
        </div>
      )}
    </div>
  );
}

function summarise(type: string, p: Record<string, unknown>): string {
  const s = (k: string) => (p[k] === undefined || p[k] === null ? "" : String(p[k]));
  switch (type) {
    case "telemetry.raw":
    case "telemetry.silver": return `${s("verb") || "event"} ${s("learner_pseudonym").slice(0, 10) || s("learner_id")} ${s("course_id")}`.trim();
    case "telemetry.dlq": return `rejected: ${s("reason")}`;
    case "notification": return `${s("title")} (${s("learner_id")})`;
    case "risk.alert": return `${s("learner_id")} ${s("course_id")} score ${s("score")}`;
    case "submission.graded": return `${s("submission_id") || s("id")} pass rate ${s("pass_rate")}`;
    case "content.sync": return `${s("content_id")} v${s("version")} ${s("step")}`.trim();
    default: return JSON.stringify(p).slice(0, 80);
  }
}

function LiveEvents() {
  const { events, connected } = useStore();
  const pop = usePopover();
  return (
    <div className="pop-anchor" ref={pop.ref}>
      <button className={`live${connected ? " on" : ""}`} onClick={() => pop.setOpen(!pop.open)} aria-expanded={pop.open} title={connected ? "Receiving live events" : "Reconnecting"}>
        <i /><span>{connected ? "Live" : "Reconnecting"}</span>
      </button>
      {pop.open && (
        <div className="popover" role="dialog" aria-label="Live events">
          <h3>Live events <span className="xs muted">{events.length} recent</span></h3>
          {events.length === 0 && <p className="empty">Nothing yet. Start the simulator on the Data platform page or use any demo control.</p>}
          <div className="events">
            {events.slice(0, 40).map((e: SseMessage, i) => (
              <div className="event-row" key={`${e.at}-${i}`}>
                <span className="muted num">{formatTime(e.at)}</span>
                <span className="event-type" title={e.type}>{e.type}</span>
                <span className="wrap-any">{summarise(e.type, e.payload)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

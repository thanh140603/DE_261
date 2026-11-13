import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { formatTime, initials, relTime, useAction } from "../hooks";
import { notificationIcon, useNotifications } from "../notifications";
import { useStore } from "../store";
import type { SseMessage } from "../types";
import { locate, WORKSPACES, type PageDef, type WorkspaceDef } from "../workspaces";
import { useAuth } from "./AnalyticsAccess";
import { Icon } from "./Icon";
import { Callout } from "./ui";

function stored(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function store(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* private mode */ }
}

/**
 * LMS-style shell: a global navigation rail on the left (Dashboard, Assignments, Teaching, ...),
 * a course-style side menu for areas with several pages, and a breadcrumb bar on top.
 */
export function Shell({ children }: { children: ReactNode }) {
  const { overviewError } = useStore();
  const { pathname } = useLocation();
  const { ws, page } = locate(pathname);
  const [menuOpen, setMenuOpen] = useState(() => stored("ui-menu") !== "0");
  useEffect(() => { document.title = `${page.label} · EduPlatform`; }, [page.label]);
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  const hasMenu = !ws.flat && ws.pages.length > 1;
  const toggleMenu = () => { store("ui-menu", menuOpen ? "0" : "1"); setMenuOpen(!menuOpen); };
  return (
    <div className="app">
      <GlobalNav ws={ws} page={page} />
      <div className="main-col">
        <TopBar ws={ws} page={page} onMenu={hasMenu ? toggleMenu : undefined} menuOpen={menuOpen} />
        <div className={`layout${hasMenu && menuOpen ? " with-menu" : ""}`}>
          {hasMenu && menuOpen && <AreaMenu ws={ws} />}
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
    </div>
  );
}

interface RailItem { key: string; label: string; icon: string; to: string; current: boolean; hint: string }

function railItems(ws: WorkspaceDef, page: PageDef): RailItem[] {
  return WORKSPACES.flatMap((w) => w.flat
    ? w.pages.map((p) => ({ key: p.path, label: p.label, icon: p.icon, to: p.path, current: w.id === ws.id && p.path === page.path, hint: `${w.label}: ${p.label}` }))
    : [{ key: w.id, label: w.nav, icon: w.icon, to: w.pages[0].path, current: w.id === ws.id, hint: `${w.label} workspace` }]);
}

function GlobalNav({ ws, page }: { ws: WorkspaceDef; page: PageDef }) {
  return (
    <nav className="rail" aria-label="Global navigation">
      <Link to="/learner" className="rail-logo" aria-label="EduPlatform dashboard" title="EduPlatform">
        <Icon name="cap" /><span>EduPlatform</span>
      </Link>
      <AccountMenu />
      {railItems(ws, page).map((r) => (
        <Link key={r.key} to={r.to} className="rail-item" aria-current={r.current ? "page" : undefined} title={r.hint}>
          <Icon name={r.icon} /><span>{r.label}</span>
        </Link>
      ))}
    </nav>
  );
}

/** Account tray: who is signed in where, plus display preferences. */
function AccountMenu() {
  const { overview, learnerId } = useStore();
  const auth = useAuth();
  const pop = usePopover();
  const learnerName = overview?.learners.find((l) => l.id === learnerId)?.name ?? "Learner";
  // Requirement tags help trace pages to BR1-BR8 during a demo; a real LMS hides them, so they start off.
  const [showBr, setShowBr] = useState(() => stored("ui-br") === "1");
  // Light is the default for everyone (an LMS is read in daylight, often for long sessions); dark is opt-in.
  const [dark, setDark] = useState(() => stored("ui-theme") === "dark");
  useLayoutEffect(() => { document.body.classList.toggle("hide-br", !showBr); }, [showBr]);
  useLayoutEffect(() => { document.documentElement.setAttribute("data-theme", dark ? "dark" : "light"); }, [dark]);
  const roles = WORKSPACES.filter((w) => w.role).map((w) => ({ w, id: auth.identities[w.role!]?.name }));
  return (
    <div className="pop-anchor rail-account" ref={pop.ref}>
      <button className="rail-item" onClick={() => pop.setOpen(!pop.open)} aria-expanded={pop.open} aria-haspopup="dialog">
        <span className="avatar sm">{initials(learnerName)}</span><span>Account</span>
      </button>
      {pop.open && (
        <div className="popover tray" role="dialog" aria-label="Account">
          <div className="tray-head">
            <span className="avatar">{initials(learnerName)}</span>
            <div><b>{learnerName}</b><span className="small muted">Student · demo account</span></div>
          </div>
          <h3>Staff sessions</h3>
          <ul className="tray-list">
            {roles.map(({ w, id }) => (
              <li key={w.id}><span>{w.label}</span><span className={id ? "small" : "small muted"}>{id ?? "not signed in"}</span></li>
            ))}
          </ul>
          <h3>Preferences</h3>
          <label className="switch">Dark theme
            <input type="checkbox" checked={dark} onChange={(e) => { setDark(e.target.checked); store("ui-theme", e.target.checked ? "dark" : "light"); }} />
          </label>
          <label className="switch">Show requirement tags (BR1–BR8)
            <input type="checkbox" checked={showBr} onChange={(e) => { setShowBr(e.target.checked); store("ui-br", e.target.checked ? "1" : "0"); }} />
          </label>
        </div>
      )}
    </div>
  );
}

/** Course-style side menu for an area with several pages (Canvas-like course navigation). */
function AreaMenu({ ws }: { ws: WorkspaceDef }) {
  return (
    <nav className="area-menu" aria-label={`${ws.nav} pages`}>
      <div className="area-title">{ws.nav}</div>
      {ws.pages.map((p) => (
        <NavLink key={p.path} to={p.path} end className="area-link">
          <span>{p.label}</span><span className="br">{p.br}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function TopBar({ ws, page, onMenu, menuOpen }: { ws: WorkspaceDef; page: PageDef; onMenu?: () => void; menuOpen: boolean }) {
  const { overview, learnerId, setLearnerId, student, setStudent } = useStore();
  const logout = useAction(async () => {
    await api.classroom.logout();
    setStudent(null);
  });
  const auth = useAuth();
  const identity = ws.role ? auth.identities[ws.role] : null;
  const staffLogout = useAction(auth.signOut);
  const learners = overview?.learners ?? [];
  const learnerName = learners.find((l) => l.id === learnerId)?.name ?? "";
  return (
    <header className="topbar">
      {onMenu && (
        <button className="menu-btn" onClick={onMenu} aria-expanded={menuOpen} aria-label={menuOpen ? `Hide ${ws.nav} menu` : `Show ${ws.nav} menu`} title="Toggle menu">
          <Icon name="menu" />
        </button>
      )}
      <nav className="crumbs" aria-label="Breadcrumb">
        {ws.flat
          ? <span aria-current="page">{page.label}</span>
          : <><Link to={ws.pages[0].path}>{ws.nav}</Link><Icon name="chevron-right" /><span aria-current="page">{page.label}</span></>}
      </nav>
      <div className="top-tools">
        <LiveEvents />
        {ws.id === "learner" && overview && !overview.classroom && (
          <>
            <label className="act-as"><span>Student</span>
              <select className="top-select" aria-label="Learner" value={learnerId} onChange={(e) => setLearnerId(e.target.value)}>
                {learners.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
            <Bell learnerId={learnerId} />
            <span className="avatar" title={learnerName}>{learnerName ? initials(learnerName) : "?"}</span>
          </>
        )}
        {ws.id === "learner" && overview?.classroom && student && (
          <>
            <span className="session-chip"><Icon name="shield" />{student.name}</span>
            <Bell learnerId={student.id} />
            <button className="icon-btn" aria-label="Sign out" title="Sign out"
              disabled={logout.pending} onClick={() => void logout.run()}><Icon name="logout" /></button>
            {logout.error && <span role="alert">{logout.error}</span>}
          </>
        )}
        {ws.role && identity && (
          <>
            <span className="session-chip" title={`Signed in as ${identity.name}`}><Icon name="user" />{identity.name}</span>
            <button className="icon-btn" disabled={staffLogout.pending} onClick={() => void staffLogout.run(identity.role)}
              aria-label="Sign out" title="Sign out"><Icon name="logout" /></button>
            {staffLogout.error && <span role="alert">{staffLogout.error}</span>}
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

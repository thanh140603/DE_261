import type { Role } from "./components/AnalyticsAccess";

export interface PageDef { path: string; label: string; icon: string; br: string }
/**
 * `nav` is the label in the global navigation rail (LMS vocabulary: Dashboard, Teaching, ...).
 * A `flat` workspace puts each of its pages straight into the rail instead of a course-style side menu.
 */
export interface WorkspaceDef { id: string; label: string; nav: string; icon: string; role?: Role; flat?: boolean; pages: PageDef[] }

/** Workspaces (one per stakeholder) and their pages, in navigation order. */
export const WORKSPACES: WorkspaceDef[] = [
  { id: "learner", label: "Learner", nav: "Dashboard", icon: "home", flat: true, pages: [
    { path: "/learner", label: "Dashboard", icon: "home", br: "BR1 · BR2" },
    { path: "/learner/code-lab", label: "Assignments", icon: "code", br: "BR3" },
  ] },
  { id: "instructor", label: "Instructor", nav: "Teaching", icon: "board", role: "instructor", pages: [
    { path: "/instructor/assessments", label: "Assessment health", icon: "flag", br: "BR4" },
    { path: "/instructor/videos", label: "Video insights", icon: "video", br: "BR7" },
    { path: "/instructor/engagement", label: "Engagement", icon: "trend-down", br: "BR8" },
    { path: "/instructor/content", label: "Content & search", icon: "file", br: "BR8" },
  ] },
  { id: "advisor", label: "Advisor", nav: "Advising", icon: "buoy", role: "advisor", pages: [
    { path: "/advisor", label: "Learners to support", icon: "users", br: "BR5" },
  ] },
  { id: "admin", label: "Org admin", nav: "Reports", icon: "building", role: "admin", pages: [
    { path: "/admin", label: "Organisation progress", icon: "chart", br: "BR6" },
  ] },
  { id: "pipeline", label: "Data platform", nav: "Platform", icon: "database", pages: [
    { path: "/pipeline", label: "Pipeline health", icon: "activity", br: "Ops" },
  ] },
];

export function locate(pathname: string): { ws: WorkspaceDef; page: PageDef } {
  const ws = WORKSPACES.find((w) => pathname === `/${w.id}` || pathname.startsWith(`/${w.id}/`)) ?? WORKSPACES[0];
  const page = [...ws.pages].sort((a, b) => b.path.length - a.path.length).find((p) => pathname === p.path || pathname.startsWith(`${p.path}/`)) ?? ws.pages[0];
  return { ws, page };
}

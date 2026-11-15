import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { useFetch } from "./hooks";
import { useStore } from "./store";
import type { Notification } from "./types";

const EVENT = "notifications-seen";
const keyFor = (learnerId: string) => `notif-seen-${learnerId}`;
function read(key: string): number {
  try { return Number(localStorage.getItem(key) ?? 0); } catch { return 0; }
}

/**
 * BR1 notifications for one learner, refreshed on every live event.
 *
 * The list is paged: the API returns only the newest `limit` items, so a learner with a long
 * history does not pay for it on every SSE event. `loadMore` grows the window, and the unread
 * badge comes from the server-side count since the browser's last-seen mark (localStorage),
 * so it stays correct even when older unread items are outside the loaded page.
 */
export function useNotifications(learnerId: string, pageSize = 20) {
  const { lastEventAt } = useStore();
  const [limit, setLimit] = useState(pageSize);
  const q = useFetch(learnerId ? () => api.learner.notifications(learnerId, limit) : null, [learnerId, limit]);
  const key = keyFor(learnerId);
  const [seen, setSeen] = useState(() => read(key));
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    setSeen(read(key));
    const sync = () => setSeen(read(key));
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, [key]);

  useEffect(() => {
    if (!learnerId) { setUnread(0); return; }
    let cancelled = false;
    api.learner.unreadNotifications(learnerId, seen)
      .then((r) => { if (!cancelled) setUnread(r.unread); })
      .catch(() => { if (!cancelled) setUnread(0); });
    return () => { cancelled = true; };
  }, [learnerId, seen, lastEventAt]);

  useEffect(() => { if (learnerId) void q.reload(); }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps

  const markSeen = useCallback(() => {
    const now = Date.now();
    try { localStorage.setItem(key, String(now)); } catch { /* private mode */ }
    setSeen(now);
    setUnread(0);
    window.dispatchEvent(new Event(EVENT));
  }, [key]);

  const isUnread = useCallback((n: Notification) => new Date(n.created_at).getTime() > seen, [seen]);
  const loadMore = useCallback(() => setLimit((current) => current + pageSize), [pageSize]);
  const hasMore = (q.data?.length ?? 0) >= limit;
  return { q, unread, isUnread, markSeen, loadMore, hasMore };
}

export const notificationIcon = (n: Notification) =>
  n.source_event_type.includes("deadline") ? "clock"
    : n.source_event_type.includes("assignment") ? "file"
      : n.source_event_type.includes("course") || n.source_event_type.includes("content") ? "refresh"
        : n.source_event_type.includes("grad") || n.source_event_type.includes("submission") ? "check" : "bell";

export type NotificationKind = "deadline" | "course" | "feedback";
export const notificationKind = (n: Notification): NotificationKind =>
  n.source_event_type.includes("deadline") ? "deadline"
    : n.source_event_type.includes("grad") || n.source_event_type.includes("submission") ? "feedback" : "course";

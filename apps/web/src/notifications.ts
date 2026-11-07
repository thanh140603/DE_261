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

/** BR1 notifications for one learner, refreshed on every live event, with a per-browser "seen" mark. */
export function useNotifications(learnerId: string) {
  const { lastEventAt } = useStore();
  const q = useFetch(learnerId ? () => api.learner.notifications(learnerId) : null, [learnerId]);
  useEffect(() => { if (learnerId) void q.reload(); }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const key = keyFor(learnerId);
  const [seen, setSeen] = useState(() => read(key));
  useEffect(() => {
    setSeen(read(key));
    const sync = () => setSeen(read(key));
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, [key]);
  const markSeen = useCallback(() => {
    const now = Date.now();
    try { localStorage.setItem(key, String(now)); } catch { /* private mode */ }
    setSeen(now);
    window.dispatchEvent(new Event(EVENT));
  }, [key]);
  const isUnread = useCallback((n: Notification) => new Date(n.created_at).getTime() > seen, [seen]);
  const unread = q.data?.filter(isUnread).length ?? 0;
  return { q, unread, isUnread, markSeen };
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

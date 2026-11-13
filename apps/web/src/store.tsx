import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { ClassroomStudent, Overview, SseMessage, Stats } from "./types";

interface Store {
  stats: Stats | null;
  refreshStats: () => Promise<void>;
  connected: boolean;
  events: SseMessage[];
  overview: Overview | null;
  overviewError: string | null;
  lastEventAt: number; // monotonic tick used by views to refetch after live changes
  learnerId: string;
  setLearnerId: (id: string) => void;
  student: ClassroomStudent | null;
  setStudent: (student: ClassroomStudent | null) => void;
  studentLoading: boolean;
  studentError: string | null;
}

const StoreContext = createContext<Store | null>(null);

const MAX_EVENTS = 100;

export function StoreProvider({ children }: { children: ReactNode }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<SseMessage[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [lastEventAt, setLastEventAt] = useState(0);
  const [student, setStudent] = useState<ClassroomStudent | null>(null);
  const [studentLoading, setStudentLoading] = useState(true);
  const [studentError, setStudentError] = useState<string | null>(null);
  const retryRef = useRef(1000);
  const [learnerId, setLearnerIdState] = useState(() => {
    try { return sessionStorage.getItem("learner-id") ?? ""; } catch { return ""; }
  });
  const setLearnerId = useCallback((id: string) => {
    setLearnerIdState(id);
    try { sessionStorage.setItem("learner-id", id); } catch { /* private mode */ }
  }, []);
  useEffect(() => {
    const learners = overview?.learners ?? [];
    if (learners.length && !learners.some((l) => l.id === learnerId)) setLearnerId(learners[0].id);
  }, [overview, learnerId, setLearnerId]);

  const classroom = overview?.classroom;
  useEffect(() => {
    if (!classroom) return;
    let mounted = true;
    api.classroom.current().then((account) => {
      if (mounted) setStudent(account);
    }).catch((error: unknown) => {
      if (mounted && !(error instanceof ApiError && error.status === 401)) {
        setStudentError(error instanceof Error ? error.message : "Could not check the classroom session");
      }
    }).finally(() => {
      if (mounted) setStudentLoading(false);
    });
    return () => { mounted = false; };
  }, [classroom]);

  const refreshStats = useCallback(async () => {
    try {
      setStats(await api.pipeline.stats());
    } catch {
      /* stats are best-effort; the flow strip shows dashes */
    }
  }, []);

  useEffect(() => {
    api.overview().then(setOverview).catch((e: Error) => setOverviewError(e.message));
    void refreshStats();
  }, [refreshStats]);

  // useSse: EventSource with reconnect and exponential backoff.
  useEffect(() => {
    let source: EventSource | null = null;
    let timer: number | undefined;
    let stopped = false;

    const connect = () => {
      source = new EventSource("/api/events");
      source.onopen = () => {
        setConnected(true);
        retryRef.current = 1000;
      };
      source.onmessage = (ev: MessageEvent<string>) => {
        let msg: SseMessage;
        try {
          msg = JSON.parse(ev.data) as SseMessage;
        } catch {
          return;
        }
        if (msg.type === "stats") {
          setStats(msg.payload as unknown as Stats);
          return;
        }
        setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
        setLastEventAt(Date.now());
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (stopped) return;
        timer = window.setTimeout(connect, retryRef.current);
        retryRef.current = Math.min(retryRef.current * 2, 15000);
      };
    };
    connect();
    return () => {
      stopped = true;
      source?.close();
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  const value = useMemo<Store>(
    () => ({
      stats, refreshStats, connected, events, overview, overviewError, lastEventAt,
      learnerId: classroom ? student?.id ?? "" : learnerId, setLearnerId,
      student, setStudent, studentLoading, studentError,
    }),
    [stats, refreshStats, connected, events, overview, overviewError, lastEventAt, classroom,
      learnerId, setLearnerId, student, studentLoading, studentError],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used inside StoreProvider");
  return ctx;
}

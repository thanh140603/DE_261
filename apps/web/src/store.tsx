import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Overview, SseMessage, Stats } from "./types";

interface Store {
  stats: Stats | null;
  refreshStats: () => Promise<void>;
  connected: boolean;
  events: SseMessage[];
  overview: Overview | null;
  overviewError: string | null;
  lastEventAt: number; // monotonic tick used by views to refetch after live changes
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
  const retryRef = useRef(1000);

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
    () => ({ stats, refreshStats, connected, events, overview, overviewError, lastEventAt }),
    [stats, refreshStats, connected, events, overview, overviewError, lastEventAt],
  );
  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used inside StoreProvider");
  return ctx;
}

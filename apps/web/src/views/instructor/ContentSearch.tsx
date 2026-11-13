import { useEffect, useState } from "react";
import { type AnalyticsClient, type ContentStatus } from "../../analytics";
import { AnalyticsAccess, localDateTime, useAnalyticsPolling } from "../../components/AnalyticsAccess";
import { Icon } from "../../components/Icon";
import { Badge, Btn, Callout, Card, Chip, PageHead, Seg, Status } from "../../components/ui";
import { useAction, useFetch } from "../../hooks";
import { CourseSelect, useInstructorCourse } from "./common";

export function ContentSearch() {
  return (
    <>
      <PageHead br="BR8" title="Content & search">
        Publish a new version and follow it until the cache, the transcript passages and the search index all serve it.
      </PageHead>
      <AnalyticsAccess role="instructor" source="lakehouse">{(client, session) => <Content client={client} courses={session.courses} />}</AnalyticsAccess>
    </>
  );
}

interface Tracking { version: number; at: number; invalidated?: number; indexed?: number; synced?: number }

function Content({ client, courses }: { client: AnalyticsClient; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useInstructorCourse(courses);
  const list = useFetch(course ? () => client.courseContent(course) : null, [client, course]);
  useAnalyticsPolling(list.reload);
  const [picked, setPicked] = useState("");
  useEffect(() => setPicked(""), [course]);
  const contentId = picked || list.data?.items[0]?.content_id || "";
  const current = list.data?.items.find((i) => i.content_id === contentId);
  const doc = useFetch(contentId ? () => client.contentDocument(contentId) : null, [client, contentId]);
  const loaded = doc.data?.content_id === contentId ? doc.data : null; // never edit a stale document
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  useEffect(() => { if (loaded) { setTitle(loaded.title); setBody(loaded.body); } }, [loaded?.content_id, loaded?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const [track, setTrack] = useState<Tracking | null>(null);
  useEffect(() => setTrack(null), [contentId]);
  const publish = useAction(async () => {
    const r = await client.publishVersion(contentId, body, title);
    if (r.changed) setTrack({ version: r.version, at: Date.now() });
    await list.reload();
    return r;
  });
  const pending = !!track && track.synced === undefined;
  // poll fast while a published version travels LMS -> CDC -> content sync, and timestamp each stage we observe
  useEffect(() => {
    if (!pending) return;
    const id = window.setInterval(() => void list.reload(), 1000);
    return () => window.clearInterval(id);
  }, [pending, list.reload]);
  useEffect(() => {
    if (!track || !current || track.synced !== undefined) return;
    const now = Date.now();
    const next = { ...track };
    if (next.invalidated === undefined && (current.cache_state === "invalidated" || current.indexed_version === track.version)) next.invalidated = now;
    if (next.indexed === undefined && current.indexed_version === track.version) next.indexed = now;
    if (current.in_sync && current.indexed_version === track.version) { next.synced = now; void doc.reload(); }
    if (JSON.stringify(next) !== JSON.stringify(track)) setTrack(next);
  }, [current, track]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="filters"><CourseSelect courses={courses} value={course} onChange={setCourse} /></div>
      <Card title={`${courses.find((c) => c.id === course)?.title ?? "Course"} · content`} sub="Select an item to edit it.">
        <Status loading={list.loading && !list.data} error={list.error} empty={list.data && list.data.items.length === 0 ? "No content in this course." : false}>
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th style={{ minWidth: 180 }}>Content</th><th className="r">Published</th><th className="r">Searchable</th><th className="r">Passages</th><th>Cache</th><th>Search</th></tr></thead>
              <tbody>
                {list.data?.items.map((i) => (
                  <tr key={i.content_id} className="selectable" aria-selected={i.content_id === contentId} onClick={() => setPicked(i.content_id)} style={{ cursor: "pointer" }}>
                    <td><button className="btn link" aria-pressed={i.content_id === contentId} onClick={(e) => { e.stopPropagation(); setPicked(i.content_id); }}>{i.title}</button><span className="sub">{i.content_type}</span></td>
                    <td className="r num">v{i.version}</td>
                    <td className="r num">{i.indexed_version === null ? "–" : `v${i.indexed_version}`}</td>
                    <td className="r num">{i.chunk_count}</td>
                    <td>{i.cache_state === "warm" ? <Badge tone="good">Warm</Badge> : <Badge tone="warn" icon="refresh">Invalidated</Badge>}</td>
                    <td>{i.in_sync ? <Badge tone="good">In sync</Badge> : <Badge tone="info" icon="clock">Syncing</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Status>
      </Card>
      {contentId && (
        <div className="grid-1-1 mt">
          <Card title={`Edit · ${current?.title ?? ""}`} sub={loaded ? `Editing ${loaded.title} from v${loaded.version} (served from cache: ${loaded.cache})` : undefined}>
            <Status loading={!loaded && !doc.error} error={doc.error}>
              <label className="field">Title<input className="input full" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
              <label className="field" style={{ marginTop: 12 }}>Transcript
                <textarea className="textarea" rows={10} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Transcript body" />
              </label>
              <div className="actions">
                <Btn variant="primary" icon="upload" onClick={() => void publish.run()} pending={publish.pending} disabled={!body.trim() || pending}>Publish new version</Btn>
                <span className="small muted">Every version is kept; learners are notified of the change.</span>
              </div>
              {publish.error && <div className="mt"><Callout tone="bad">{publish.error}</Callout></div>}
              {publish.result && !publish.result.changed && <p className="small muted" style={{ marginTop: 10 }}>No change: the title and body match the current version.</p>}
            </Status>
          </Card>
          <div className="stack">
            {current && <SyncStatus item={current} track={track} />}
            <SearchPreview client={client} course={course} />
          </div>
        </div>
      )}
    </>
  );
}

function SyncStatus({ item, track }: { item: ContentStatus; track: Tracking | null }) {
  const version = track?.version ?? item.version;
  const since = (t?: number) => (track && t !== undefined ? `+${((t - track.at) / 1000).toFixed(1)} s` : "");
  const indexed = item.indexed_version === version;
  const steps: { title: string; sub: string; done: boolean; at?: number }[] = [
    { title: "Version saved", sub: "Immutable copy in object storage and the LMS", done: true, at: track?.at },
    { title: "Change captured, cache invalidated", sub: "Read from the LMS database log; old cache entries dropped", done: track ? track.invalidated !== undefined : indexed || item.cache_state === "invalidated", at: track?.invalidated },
    { title: "Re-chunked and embedded", sub: indexed ? `${item.chunk_count} passages from v${version}` : "Splitting the transcript into searchable passages", done: track ? track.indexed !== undefined : indexed, at: track?.indexed },
    { title: "Search index refreshed", sub: "Learners' searches return the new text", done: track ? track.synced !== undefined : item.in_sync && indexed, at: track?.synced },
  ];
  const active = steps.findIndex((s) => !s.done);
  const synced = active === -1;
  return (
    <Card title="Sync status" br="BR8" sub={`Version ${version} · published ${localDateTime(item.updated_at)}`}
      actions={synced ? <Badge tone="good">Searchable</Badge> : <Badge tone="info" icon="clock">Syncing</Badge>}>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.title} className={`step ${s.done ? "done" : i === active ? "active" : "pending"}`}>
            <span className="step-dot">{s.done && <Icon name="check" />}</span>
            <div><div className="step-title">{s.title}</div><div className="step-sub">{s.sub}</div></div>
            <span className="step-time">{s.done && i > 0 ? since(s.at) : ""}</span>
          </li>
        ))}
      </ol>
      {track?.synced !== undefined && <div className="mt" aria-live="polite"><Callout tone="good">Version {track.version} is searchable {((track.synced - track.at) / 1000).toFixed(1)} s after publishing.</Callout></div>}
      {track && track.synced === undefined && <p className="small muted" style={{ marginTop: 12 }} aria-live="polite">Version {track.version} saved. Waiting for change capture and the sync service…</p>}
    </Card>
  );
}

function SearchPreview({ client, course }: { client: AnalyticsClient; course: string }) {
  const [query, setQuery] = useState("left join");
  const [mode, setMode] = useState<"hybrid" | "keyword">("hybrid");
  const search = useAction(() => client.search(course, query, mode));
  return (
    <Card title="Search preview" sub="What learners get when they search this course.">
      <form className="filters" style={{ marginBottom: 6 }} onSubmit={(e) => { e.preventDefault(); if (query.trim()) void search.run(); }}>
        <label className="field grow">Search this course<input className="input full" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
        <Seg label="Ranking" value={mode} onChange={setMode} options={[{ value: "hybrid", label: "Hybrid" }, { value: "keyword", label: "Keyword" }]} />
        <Btn type="submit" icon="search" pending={search.pending} disabled={!query.trim()}>Search</Btn>
      </form>
      {search.error && <Callout tone="bad">{search.error}</Callout>}
      {search.result && (search.result.hits.length === 0
        ? <p className="empty">No matching passages in the current versions.</p>
        : (
          <ul className="hits" aria-label="Search results">
            {search.result.hits.map((h) => (
              <li className="hit" key={`${h.content_id}-${h.ordinal}`}>
                <div className="hit-title">{h.title} <Chip>v{h.version}</Chip>{h.section_path.length > 0 && <span className="xs muted">{h.section_path.join(" › ")}</span>}</div>
                <p className="small" style={{ marginTop: 4 }}>{h.snippet}</p>
              </li>
            ))}
          </ul>
        ))}
    </Card>
  );
}

import { type AnalyticsClient } from "../analytics";
import { useAction, useFetch } from "../hooks";
import { localDateTime, useAnalyticsPolling } from "./AnalyticsAccess";
import { Badge, Btn, Callout, Card, Status } from "./ui";

export function ReplayControl({ client, refresh }: { client: AnalyticsClient; refresh: () => Promise<unknown> }) {
  const stage = useFetch(() => client.replayStatus(), [client]);
  useAnalyticsPolling(stage.reload);
  const advance = useAction(async (revision: number) => {
    await client.advanceReplay(revision);
    await Promise.all([stage.reload(), refresh()]);
  });

  return <div className="toolbar" aria-label="Replay controls">
    <Badge tone="warn">Simulated data</Badge>
    {stage.data && <>
      <span role="status">Stage {stage.data.stage} of {stage.data.stage_count} · {stage.data.label}</span>
      <Btn disabled={advance.pending} onClick={() => { if (stage.data) void advance.run(stage.data.revision); }}>Advance demo</Btn>
    </>}
    {(stage.error || advance.error) && <span role="alert">{advance.error ?? stage.error}</span>}
  </div>;
}

export function MeasuredBenchmarks({ client, requirement }: { client: AnalyticsClient; requirement: "BR4" | "BR5" }) {
  const results = useFetch(() => client.replayBenchmarks(), [client]);
  const comparison = requirement === "BR4"
    ? results.data?.engine_comparison?.br4 : results.data?.engine_comparison?.br5;
  return <Card title="Measured benchmarks" sub="Historical local runs on synthetic inputs">
    <Status loading={results.loading} error={results.error}>
      {comparison ? <>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Engine</th><th>Phase</th><th>Records</th><th>Median (ms)</th><th>Trials</th></tr></thead>
            <tbody>{[...comparison.processing, ...comparison.end_to_end].map((row) => <tr key={`${row.engine}-${row.phase}-${row.records}`}>
              <td>{row.engine}</td><td>{row.phase.replaceAll("_", " ")}</td><td>{row.records.toLocaleString()}</td>
              <td>{row.median_ms?.toFixed(1) ?? "—"}</td>
              <td>{Object.entries(row.statuses).map(([status, count]) => `${count} ${status}`).join(", ")}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </> : results.data && <Callout tone="info">CDC to alert in the historical run took {results.data.cdc_to_alert_ms.toLocaleString()} ms. Measured {localDateTime(results.data.cdc_measured_at)}.</Callout>}
    </Status>
  </Card>;
}

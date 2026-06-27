import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

type ReplayBatch = { id: number | null; name: string; status: string; mode: string; as_of_start: string; as_of_end: string; config_json: string; summary_json: string };
type ReplaySlice = { id: number | null; replay_batch_id: number; as_of: string; status: string; run_id: number | null; input_summary_json: string; output_summary_json: string };
type BatchDetail = { batch: ReplayBatch; slices: ReplaySlice[]; summary: Record<string, unknown>; resolved_tickers: string[] };
type CoverageResponse = { slice_id: number; source: string; coverage: Record<string, unknown> };

type TickerCoverage = { ticker?: string; tier?: string; blockers?: string[]; warnings?: string[]; generation?: Record<string, unknown>; resolution?: Record<string, unknown> };

function parseObject(value: string | null | undefined): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function tierCounts(payload: Record<string, unknown> | null | undefined): Record<string, unknown> {
  const counts = payload?.tier_counts;
  return counts && typeof counts === "object" && !Array.isArray(counts) ? counts as Record<string, unknown> : {};
}

export function HistoricalReplayPage() {
  const [params, setParams] = useSearchParams();
  const [batches, setBatches] = useState<ReplayBatch[] | null>(null);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(params.get("batch") ? Number(params.get("batch")) : null);
  const [selectedSliceId, setSelectedSliceId] = useState<number | null>(params.get("slice") ? Number(params.get("slice")) : null);
  const [error, setError] = useState<string | null>(null);

  async function loadBatches() {
    const loaded = await getJson<ReplayBatch[]>("/api/historical-replay/batches");
    setBatches(loaded);
    setSelectedBatchId((current) => current ?? loaded[0]?.id ?? null);
  }

  async function loadDetail(batchId: number) {
    const loaded = await getJson<BatchDetail>(`/api/historical-replay/batches/${batchId}`);
    setDetail(loaded);
    setSelectedSliceId((current) => current && loaded.slices.some((slice) => slice.id === current) ? current : loaded.slices[0]?.id ?? null);
  }

  async function loadCoverage(sliceId: number) {
    setCoverage(await getJson<CoverageResponse>(`/api/historical-replay/slices/${sliceId}/coverage`));
  }

  useEffect(() => {
    loadBatches().catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Failed to load replay batches"));
  }, []);

  useEffect(() => {
    if (!selectedBatchId) return;
    setParams((current) => {
      current.set("batch", String(selectedBatchId));
      return current;
    });
    loadDetail(selectedBatchId).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Failed to load replay batch detail"));
  }, [selectedBatchId]);

  useEffect(() => {
    if (!selectedSliceId) return;
    setParams((current) => {
      current.set("slice", String(selectedSliceId));
      return current;
    });
    loadCoverage(selectedSliceId).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : "Failed to load replay coverage"));
  }, [selectedSliceId]);

  const selectedSlice = useMemo(() => detail?.slices.find((slice) => slice.id === selectedSliceId) ?? detail?.slices[0] ?? null, [detail, selectedSliceId]);
  const outputSummary = parseObject(selectedSlice?.output_summary_json);
  const replayResolution = outputSummary.replay_resolution && typeof outputSummary.replay_resolution === "object" ? outputSummary.replay_resolution as Record<string, unknown> : {};
  const coveragePayload = coverage?.coverage ?? null;
  const coverageTickers = Array.isArray(coveragePayload?.tickers) ? coveragePayload.tickers as TickerCoverage[] : [];

  if (error) return <ErrorState message={error} />;
  if (!batches) return <LoadingState message="Loading historical replay…" />;

  return (
    <>
      <PageHeader kicker="Research" title="Historical replay" subtitle="Audit point-in-time replay slices, coverage tiers, and replay-generated outcome resolution." />
      <section className="card-grid">
        <Card>
          <SectionTitle kicker="Batches" title="Replay batches" subtitle="Select a batch to inspect slices and coverage." />
          <div className="data-stack top-gap-small">
            {batches.length === 0 ? <EmptyState message="No replay batches yet." /> : batches.map((batch) => (
              <button key={batch.id ?? batch.name} type="button" className={`data-card data-card-button ${selectedBatchId === batch.id ? "data-card-selected" : ""}`} onClick={() => setSelectedBatchId(batch.id)}>
                <div className="data-card-header"><strong>{batch.name}</strong><Badge>{batch.status}</Badge></div>
                <div className="helper-text">{batch.mode} · {formatDate(batch.as_of_start)} → {formatDate(batch.as_of_end)}</div>
              </button>
            ))}
          </div>
        </Card>
        <Card>
          <SectionTitle kicker="Selected batch" title={detail?.batch.name ?? "No batch selected"} subtitle="Slice status and replay outcome split." />
          {detail ? <div className="metrics-grid top-gap-small">
            <StatCard label="Slices" value={detail.slices.length} helper={JSON.stringify(detail.summary.status_counts ?? {})} />
            <StatCard label="Tickers" value={detail.resolved_tickers.length} helper={detail.resolved_tickers.slice(0, 6).join(", ") || "—"} />
            <StatCard label="Tier A" value={String(tierCounts(coveragePayload).tier_a ?? "—")} helper="Selected slice coverage" />
            <StatCard label="Resolution" value={String(replayResolution.stored_outcome_count ?? "—")} helper={`sources ${JSON.stringify(replayResolution.source_counts ?? {})}`} />
          </div> : <EmptyState message="Select a batch." />}
        </Card>
      </section>

      <DisclosureCard kicker="Slices" title="Replay slice detail" subtitle="Coverage report separates generation inputs from post-as-of outcome resolution bars.">
        {detail ? <div className="data-stack top-gap-small">
          <select className="input" value={selectedSlice?.id ?? ""} onChange={(event) => setSelectedSliceId(Number(event.target.value))}>
            {detail.slices.map((slice) => <option key={slice.id ?? slice.as_of} value={slice.id ?? ""}>Slice #{slice.id} · {formatDate(slice.as_of)} · {slice.status}</option>)}
          </select>
          {coveragePayload ? <>
            <section className="metrics-grid top-gap-small">
              <StatCard label="Tier A/B/C" value={`${tierCounts(coveragePayload).tier_a ?? 0}/${tierCounts(coveragePayload).tier_b ?? 0}/${tierCounts(coveragePayload).tier_c ?? 0}`} helper={`ineligible ${tierCounts(coveragePayload).ineligible ?? 0}`} />
              <StatCard label="Tier A ratio" value={String(coveragePayload.tier_a_ratio ?? "—")} helper="Readiness for replay tuning" />
              <StatCard label="News" value={String((coveragePayload.news_coverage as Record<string, unknown> | undefined)?.covered_ticker_count ?? "—")} helper="point-in-time availability" />
              <StatCard label="Resolution split" value={JSON.stringify(replayResolution.source_counts ?? {})} helper="intraday vs daily fallback" />
            </section>
            <div className="table-wrapper top-gap-small"><table className="data-table"><thead><tr><th>Ticker</th><th>Tier</th><th>Generation bars</th><th>Resolution bars</th><th>Warnings/blockers</th></tr></thead><tbody>
              {coverageTickers.map((ticker) => <tr key={ticker.ticker}><td>{ticker.ticker}</td><td><Badge>{ticker.tier ?? "—"}</Badge></td><td>{String(ticker.generation?.daily_bar_count ?? "—")} daily · {String(ticker.generation?.intraday_1m_bar_count ?? "—")} 1m</td><td>{String(ticker.resolution?.daily_bar_count ?? "—")} daily · {String(ticker.resolution?.intraday_1m_bar_count ?? "—")} 1m</td><td>{[...(ticker.warnings ?? []), ...(ticker.blockers ?? [])].join(", ") || "—"}</td></tr>)}
            </tbody></table></div>
          </> : <LoadingState message="Loading coverage…" />}
          <details><summary className="helper-text">Raw slice summaries</summary><pre className="code-block top-gap-small">{JSON.stringify({ input: parseObject(selectedSlice?.input_summary_json), output: outputSummary, coverage }, null, 2)}</pre></details>
        </div> : <EmptyState message="Select a batch first." />}
      </DisclosureCard>
    </>
  );
}

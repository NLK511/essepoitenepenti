import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getJson } from "../api";
import { Badge, Card, ErrorState, LoadingState, PageHeader, SectionTitle, SegmentedTabs } from "../components/ui";
import type { ActiveWorkersResponse, WorkerHeartbeat, WorkerLogsResponse } from "../types";
import { formatDate } from "../utils";

type LogLevelFilter = "all" | "debug" | "info" | "warning" | "error";

function formatWorkerLabel(worker: WorkerHeartbeat | null): string {
  if (!worker) {
    return "Unknown worker";
  }
  return `${worker.worker_id} · ${worker.hostname} · pid ${worker.pid}`;
}

function statusTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "running") {
    return "ok";
  }
  if (status === "idle") {
    return "info";
  }
  if (status === "stale") {
    return "warning";
  }
  return "neutral";
}

function matchesLogLevel(line: string, filter: LogLevelFilter): boolean {
  if (filter === "all") {
    return true;
  }
  const haystack = line.toLowerCase();
  if (filter === "debug") {
    return haystack.includes("debug");
  }
  if (filter === "info") {
    return haystack.includes("info");
  }
  if (filter === "warning") {
    return haystack.includes("warn");
  }
  return haystack.includes("error") || haystack.includes("exception") || haystack.includes("traceback");
}

export function WorkerLogsPage() {
  const { workerId } = useParams();
  const [workers, setWorkers] = useState<WorkerHeartbeat[] | null>(null);
  const [logs, setLogs] = useState<WorkerLogsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [followTail, setFollowTail] = useState(true);
  const [logLevel, setLogLevel] = useState<LogLevelFilter>("all");
  const logViewRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    if (!workerId) {
      setError("Missing worker id.");
      return;
    }

    let mounted = true;
    const load = async () => {
      try {
        setError(null);
        const [activeWorkers, workerLogs] = await Promise.all([
          getJson<ActiveWorkersResponse>("/api/workers/active"),
          getJson<WorkerLogsResponse>(`/api/workers/${workerId}/logs?tail=250`),
        ]);
        if (mounted) {
          setWorkers(activeWorkers.workers);
          setLogs(workerLogs);
        }
      } catch (loadError) {
        if (mounted) {
          setError(loadError instanceof Error ? loadError.message : "Failed to load worker logs");
        }
      }
    };

    void load();
    const interval = window.setInterval(() => {
      void load();
    }, 2500);

    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, [workerId]);

  useEffect(() => {
    if (!followTail || !logViewRef.current) {
      return;
    }
    const el = logViewRef.current;
    el.scrollTop = el.scrollHeight;
  }, [followTail, logs, logLevel]);

  const selectedWorker = useMemo(() => {
    if (!workerId || !workers) {
      return null;
    }
    return workers.find((worker) => worker.worker_id === workerId) ?? null;
  }, [workerId, workers]);

  const visibleLines = useMemo(() => {
    if (!logs) {
      return [] as string[];
    }
    return logs.lines.filter((line) => matchesLogLevel(line, logLevel));
  }, [logs, logLevel]);

  const workerBadgeTone = selectedWorker ? statusTone(selectedWorker.status) : logs ? "info" : "neutral";
  const workerBadgeLabel = selectedWorker
    ? selectedWorker.active_run_id !== null && selectedWorker.active_run_id !== undefined
      ? `run ${selectedWorker.active_run_id}`
      : selectedWorker.status
    : logs
      ? "streaming"
      : "—";

  return (
    <>
      <PageHeader
        kicker="Worker diagnostics"
        title={workerId ? `Worker logs · ${workerId}` : "Worker logs"}
        actions={<Link to="/" className="button-secondary">Back to dashboard</Link>}
      />

      {error ? <ErrorState message={error} /> : null}

      <section className="metrics-grid top-gap">
        <Card>
          <div className="metric-label">Selected worker</div>
          <div className="metric-value worker-metric-value">{workerId ?? "—"}</div>
          <div className="helper-text">{formatWorkerLabel(selectedWorker)}</div>
        </Card>
        <Card>
          <div className="metric-label">Worker status</div>
          <div className="metric-value worker-metric-value">{selectedWorker ? selectedWorker.status : logs ? "active" : "—"}</div>
          <div className="helper-text">Heartbeat refreshed from the active worker registry.</div>
        </Card>
        <Card>
          <div className="metric-label">Status badge</div>
          <div className="cluster" style={{ marginTop: 10 }}>
            <Badge tone={workerBadgeTone}>{workerBadgeLabel}</Badge>
          </div>
          <div className="helper-text">Running, idle, or active run state for the selected worker.</div>
        </Card>
        <Card>
          <div className="metric-label">Last heartbeat</div>
          <div className="metric-value worker-metric-value">{selectedWorker ? formatDate(selectedWorker.last_heartbeat_at) : "—"}</div>
          <div className="helper-text">Current worker health is polled live while this page is open.</div>
        </Card>
        <Card>
          <div className="metric-label">Visible log lines</div>
          <div className="metric-value worker-metric-value">{visibleLines.length}</div>
          <div className="helper-text">{logs ? `Showing ${visibleLines.length} of ${logs.line_count} total line(s).` : "Waiting for logs…"}</div>
        </Card>
        <Card>
          <div className="metric-label">Log tail</div>
          <div className="metric-value worker-metric-value">{logs?.line_count ?? 0}</div>
          <div className="helper-text">{logs ? `${logs.truncated ? "Latest" : "All"} ${logs.tail} line(s) from ${logs.log_path}` : "Waiting for logs…"}</div>
        </Card>
      </section>

      <Card className="top-gap">
        <SectionTitle
          kicker="Live stream"
          title="Worker log output"
          actions={
            <div className="worker-log-toolbar">
              <label className="worker-log-toggle">
                <input
                  type="checkbox"
                  checked={followTail}
                  onChange={(event) => setFollowTail(event.target.checked)}
                />
                Follow tail
              </label>
              <SegmentedTabs
                value={logLevel}
                onChange={setLogLevel}
                options={[
                  { value: "all", label: "All" },
                  { value: "debug", label: "Debug" },
                  { value: "info", label: "Info" },
                  { value: "warning", label: "Warn" },
                  { value: "error", label: "Error" },
                ]}
              />
              {logs ? <Badge tone={logs.truncated ? "warning" : "neutral"}>{logs.truncated ? "truncated" : "complete"}</Badge> : null}
            </div>
          }
        />
        <div className="worker-log-summary">
          {followTail ? "Auto-scrolling to the newest line." : "Auto-scroll is paused while you inspect earlier output."}
        </div>
        {!logs && !error ? <LoadingState message="Loading worker logs…" /> : null}
        {logs ? (
          <pre ref={logViewRef} className="worker-log-view">
            {visibleLines.join("\n") || "No log lines match the current filter."}
          </pre>
        ) : null}
      </Card>
    </>
  );
}

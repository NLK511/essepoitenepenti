import { FormEvent, useEffect, useState } from "react";

import { getJson, postForm } from "../api";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { BrokerRiskAssessment } from "../types";

function metricNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2).replace(/\.00$/, "") : "—";
}

function reasonLabel(reason: string): string {
  return reason.split("_").join(" ");
}

export function RiskPage() {
  const [assessment, setAssessment] = useState<BrokerRiskAssessment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  async function loadRisk() {
    try {
      setError(null);
      setAssessment(await getJson<BrokerRiskAssessment>("/api/risk"));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load risk state");
    }
  }

  useEffect(() => {
    void loadRisk();
  }, []);

  async function haltTrading(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    try {
      setSaving("halt");
      setError(null);
      setNotice(null);
      setAssessment(await postForm<BrokerRiskAssessment>("/api/risk/halt", { reason: String(formData.get("reason") ?? "manual halt") }));
      setNotice("Trading halted");
    } catch (haltError) {
      setError(haltError instanceof Error ? haltError.message : "Failed to halt trading");
    } finally {
      setSaving(null);
    }
  }

  async function resumeTrading() {
    try {
      setSaving("resume");
      setError(null);
      setNotice(null);
      setAssessment(await postForm<BrokerRiskAssessment>("/api/risk/resume", {}));
      setNotice("Trading resumed");
    } catch (resumeError) {
      setError(resumeError instanceof Error ? resumeError.message : "Failed to resume trading");
    } finally {
      setSaving(null);
    }
  }

  const metrics = assessment?.metrics ?? {};

  return (
    <>
      <PageHeader
        kicker="Execution safety"
        title="Risk manager"
        actions={<HelpHint tooltip="The risk manager blocks new broker submissions when kill-switch or exposure limits are breached." to="/docs?doc=broker-risk-management-spec" />}
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <Card><div className="helper-text">{notice}</div></Card> : null}
      {!assessment && !error ? <LoadingState message="Loading risk state…" /> : null}
      {assessment ? (
        <div className="stack-page">
          <section className="metrics-grid">
            <StatCard label="Trading allowed" value={assessment.allowed ? "yes" : "no"} helper={assessment.enabled ? "Risk manager enabled" : "Risk manager disabled"} />
            <StatCard label="Kill switch" value={assessment.halt_enabled ? "halted" : "clear"} helper={assessment.halt_reason || "Manual halt is not active"} />
            <StatCard label="Today's realized P&L" value={`$${metricNumber(metrics.today_realized_pnl_usd)}`} helper={`${metrics.today_win_count ?? 0} wins · ${metrics.today_loss_count ?? 0} losses`} />
            <StatCard label="Open exposure" value={`$${metricNumber(metrics.open_notional_usd)}`} helper={`${metrics.open_position_count ?? 0} open/submitted positions`} />
            <StatCard label="Consecutive losses" value={String(metrics.today_consecutive_losses ?? 0)} helper={`Limit ${assessment.config.max_consecutive_losses}`} />
          </section>

          <section className="card-grid">
            <Card>
              <SectionTitle kicker="State" title="Current risk decision" subtitle="This is the gate used before Alpaca paper order submission and manual resubmit." />
              <div className="cluster top-gap-small">
                <Badge tone={assessment.allowed ? "ok" : "danger"}>{assessment.allowed ? "allowed" : "blocked"}</Badge>
                <Badge tone={assessment.enabled ? "info" : "warning"}>{assessment.enabled ? "enabled" : "disabled"}</Badge>
                {assessment.halt_enabled ? <Badge tone="danger">halted</Badge> : <Badge tone="ok">not halted</Badge>}
              </div>
              {assessment.reasons.length ? (
                <ul className="top-gap-small">
                  {assessment.reasons.map((reason) => <li key={reason}>{reasonLabel(reason)}</li>)}
                </ul>
              ) : <EmptyState message="No active risk blocks." />}
            </Card>

            <Card>
              <SectionTitle kicker="Controls" title="Manual kill switch" subtitle="Use this before changing execution settings or investigating broker/account mismatches." />
              <form className="form-grid top-gap-small" onSubmit={(event) => void haltTrading(event)}>
                <label className="form-field">
                  <span>Halt reason</span>
                  <input name="reason" defaultValue="manual operator halt" />
                </label>
                <button type="submit" className="button button-danger" disabled={saving === "halt"}>Halt trading</button>
              </form>
              <div className="cluster top-gap-small">
                <button type="button" className="button-secondary" onClick={() => void resumeTrading()} disabled={saving === "resume"}>Resume trading</button>
                <button type="button" className="button-secondary" onClick={() => void loadRisk()}>Refresh</button>
              </div>
            </Card>

            <Card>
              <SectionTitle kicker="Limits" title="Configured guardrails" subtitle="Edit these in Settings → Risk management." />
              <div className="data-points top-gap-small">
                <div className="data-point"><span className="data-point-label">daily loss</span><span className="data-point-value">${assessment.config.max_daily_realized_loss_usd}</span></div>
                <div className="data-point"><span className="data-point-label">open positions</span><span className="data-point-value">{assessment.config.max_open_positions}</span></div>
                <div className="data-point"><span className="data-point-label">open notional</span><span className="data-point-value">${assessment.config.max_open_notional_usd}</span></div>
                <div className="data-point"><span className="data-point-label">position notional</span><span className="data-point-value">${assessment.config.max_position_notional_usd}</span></div>
                <div className="data-point"><span className="data-point-label">same ticker</span><span className="data-point-value">{assessment.config.max_same_ticker_open_positions}</span></div>
                <div className="data-point"><span className="data-point-label">loss streak</span><span className="data-point-value">{assessment.config.max_consecutive_losses}</span></div>
              </div>
            </Card>
          </section>
        </div>
      ) : null}
    </>
  );
}

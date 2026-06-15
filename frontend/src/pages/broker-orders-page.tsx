import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm, postJson } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, DisclosureCard, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { AccountRiskState, BrokerAccountSummary, BrokerOrderExecution, BrokerPosition, BrokerSyncState, BrokerWorkbench, GlobalLiveSummary, RiskHaltEvent } from "../types";
import { brokerExecutionStatusTone, formatDate, humanizeKey, isBrokerExecutionCancelable, isBrokerExecutionFailed, isBrokerExecutionResubmittable, isBrokerExecutionSkipped, isBrokerExecutionSubmittedLike } from "../utils";

function metricNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2).replace(/\.00$/, "") : "—";
}


function prettyPayload(payload: Record<string, unknown>): string {
  try {
    return JSON.stringify(payload, null, 2);
  } catch (_error) {
    return String(payload);
  }
}

function isEtoroLiveOrder(order: BrokerOrderExecution): boolean {
  return order.broker === "etoro" && order.account_mode === "live";
}

function modeBadgeTone(mode: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (mode.toLowerCase() === "live") {
    return "danger";
  }
  if (mode.toLowerCase() === "demo") {
    return "warning";
  }
  return "info";
}

export function BrokerOrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams({ limit: "50" });
  const [orders, setOrders] = useState<BrokerOrderExecution[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeActionId, setActiveActionId] = useState<number | null>(null);
  const [positions, setPositions] = useState<BrokerPosition[] | null>(null);
  const [risk, setRisk] = useState<AccountRiskState | null>(null);
  const [haltEvents, setHaltEvents] = useState<RiskHaltEvent[]>([]);
  const [syncState, setSyncState] = useState<BrokerSyncState | null>(null);
  const [brokerAccounts, setBrokerAccounts] = useState<BrokerAccountSummary[]>([]);
  const [globalLiveSummary, setGlobalLiveSummary] = useState<GlobalLiveSummary | null>(null);
  const [globalBrokerRiskCaps, setGlobalBrokerRiskCaps] = useState<Record<string, number | null>>({});
  const { showToast } = useToast();
  const limit = Math.max(1, Number(searchParams.get("limit") ?? "50") || 50);
  const runId = searchParams.get("run_id");
  const brokerAccountFilter = searchParams.get("broker_account_id") ?? "";
  const brokerFilter = searchParams.get("broker") ?? "";
  const accountModeFilter = searchParams.get("account_mode") ?? "";
  const statusFilter = searchParams.get("status") ?? "";
  const selectedOrderId = searchParams.get("order_id");

  useEffect(() => {
    async function load() {
      try {
        setError(null);
        setActionError(null);
        const params = new URLSearchParams({ limit: String(limit) });
        if (runId) {
          params.set("run_id", runId);
        }
        if (brokerAccountFilter) {
          params.set("broker_account_id", brokerAccountFilter);
        }
        if (brokerFilter) {
          params.set("broker", brokerFilter);
        }
        if (accountModeFilter) {
          params.set("account_mode", accountModeFilter);
        }
        if (statusFilter) {
          params.set("status", statusFilter);
        }
        const workbench = await getJson<BrokerWorkbench>(`/api/broker-workbench?${params.toString()}`);
        const loadedOrders = workbench.broker_orders;
        setOrders(loadedOrders);
        setPositions(workbench.broker_positions);
        setRisk(workbench.risk);
        setHaltEvents(workbench.risk_halt_events ?? []);
        setSyncState(workbench.broker_sync_state ?? null);
        setBrokerAccounts(workbench.broker_accounts ?? []);
        setGlobalLiveSummary(workbench.global_live_summary ?? null);
        setGlobalBrokerRiskCaps(workbench.global_broker_risk_caps ?? {});
        if (!selectedOrderId && loadedOrders[0]?.id) {
          const next = new URLSearchParams(searchParams);
          next.set("order_id", String(loadedOrders[0].id));
          setSearchParams(next, { replace: true });
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load broker orders");
      }
    }
    void load();
  }, [limit, runId, brokerAccountFilter, brokerFilter, accountModeFilter, statusFilter, setSearchParams]);

  const stats = useMemo(() => {
    const items = orders ?? [];
    return {
      total: items.length,
      submitted: items.filter((order) => isBrokerExecutionSubmittedLike(order.status)).length,
      failed: items.filter((order) => isBrokerExecutionFailed(order.status)).length,
      skipped: items.filter((order) => isBrokerExecutionSkipped(order.status)).length,
    };
  }, [orders]);

  const positionByOrderId = useMemo(() => {
    const map = new Map<number, BrokerPosition>();
    for (const position of positions ?? []) {
      map.set(position.broker_order_execution_id, position);
    }
    return map;
  }, [positions]);

  const selectedOrder = useMemo(
    () => orders?.find((order) => String(order.id) === selectedOrderId) ?? null,
    [orders, selectedOrderId],
  );
  const selectedPosition = selectedOrder?.id ? positionByOrderId.get(selectedOrder.id) ?? null : null;
  const actionRequiredOrders = useMemo(
    () => (orders ?? []).filter((order) => isBrokerExecutionFailed(order.status) || isBrokerExecutionResubmittable(order.status) || isBrokerExecutionCancelable(order.status)).slice(0, 5),
    [orders],
  );

  async function reloadOrders(nextSelectedOrderId?: number) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (runId) {
      params.set("run_id", runId);
    }
    if (brokerAccountFilter) {
      params.set("broker_account_id", brokerAccountFilter);
    }
    if (brokerFilter) {
      params.set("broker", brokerFilter);
    }
    if (accountModeFilter) {
      params.set("account_mode", accountModeFilter);
    }
    if (statusFilter) {
      params.set("status", statusFilter);
    }
    const workbench = await getJson<BrokerWorkbench>(`/api/broker-workbench?${params.toString()}`);
    const loadedOrders = workbench.broker_orders;
    setOrders(loadedOrders);
    setPositions(workbench.broker_positions);
    setRisk(workbench.risk);
    setHaltEvents(workbench.risk_halt_events ?? []);
    setSyncState(workbench.broker_sync_state ?? null);
    setBrokerAccounts(workbench.broker_accounts ?? []);
    setGlobalLiveSummary(workbench.global_live_summary ?? null);
    setGlobalBrokerRiskCaps(workbench.global_broker_risk_caps ?? {});
    const nextOrderId = nextSelectedOrderId ?? loadedOrders[0]?.id ?? null;
    if (nextOrderId) {
      const next = new URLSearchParams(searchParams);
      next.set("order_id", String(nextOrderId));
      setSearchParams(next, { replace: true });
    }
  }

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.delete("order_id");
    setSearchParams(next);
  }

  function clearFilters() {
    const next = new URLSearchParams(searchParams);
    for (const key of ["broker_account_id", "broker", "account_mode", "status"]) {
      next.delete(key);
    }
    next.delete("order_id");
    setSearchParams(next);
  }

  async function refreshVisibleOrders() {
    setActionError(null);
    setActiveActionId(-1);
    try {
      await postForm("/api/broker-orders/sync", {});
      showToast({ message: "Broker orders refreshed", tone: "success" });
      await reloadOrders(selectedOrder?.id ?? undefined);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : "Failed to refresh broker orders");
    } finally {
      setActiveActionId(null);
    }
  }

  async function haltTrading() {
    const reason = window.prompt("Reason for halting broker execution", "manual operator halt") ?? "manual operator halt";
    setActionError(null);
    try {
      const updated = await postForm<AccountRiskState>("/api/risk/halt", { reason });
      setRisk(updated);
      showToast({ message: "Broker execution halted", tone: "success" });
      await reloadOrders(selectedOrder?.id ?? undefined);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : "Failed to halt broker execution");
    }
  }

  async function resumeTrading() {
    setActionError(null);
    try {
      const updated = await postForm<AccountRiskState>("/api/risk/resume", {});
      setRisk(updated);
      showToast({ message: "Broker execution resumed", tone: "success" });
      await reloadOrders(selectedOrder?.id ?? undefined);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : "Failed to resume broker execution");
    }
  }

  async function recordDemoValidationArtifact(account: BrokerAccountSummary) {
    const artifactId = window.prompt("Demo validation artifact id", String(account.risk_settings.demo_validation_artifact_id ?? "")) ?? "";
    if (!artifactId.trim()) {
      return;
    }
    const notes = window.prompt("Demo validation notes", String(account.risk_settings.demo_validation_notes ?? "")) ?? "";
    setActionError(null);
    try {
      await postJson<BrokerAccountSummary>(`/api/broker-accounts/${account.broker_account_id}/demo-validation-artifact`, {
        artifact_id: artifactId.trim(),
        notes,
      });
      showToast({ message: "Demo validation artifact recorded", tone: "success" });
      await reloadOrders(selectedOrder?.id ?? undefined);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : "Failed to record demo validation artifact");
    }
  }

  async function clearAccountCircuitBreaker(account: BrokerAccountSummary) {
    const reason = window.prompt("Reason for clearing this broker-account circuit breaker", "operator reviewed latest broker evidence") ?? "";
    if (!reason.trim()) {
      return;
    }
    setActionError(null);
    try {
      await postJson(`/api/broker-accounts/${account.broker_account_id}/circuit-breaker/clear`, { reason: reason.trim() });
      showToast({ message: "Circuit breaker cleared", tone: "success" });
      await reloadOrders(selectedOrder?.id ?? undefined);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : "Failed to clear circuit breaker");
    }
  }

  async function handleAction(orderId: number, action: "resubmit" | "cancel" | "refresh") {
    setActionError(null);
    setActiveActionId(orderId);
    try {
      const order = orders?.find((item) => item.id === orderId) ?? null;
      if (order && isEtoroLiveOrder(order) && action !== "refresh") {
        const expected = `CONFIRM LIVE ETORO ${order.broker_account_id} ${action}`;
        const confirmationText = window.prompt(`Live eToro ${action} requires exact confirmation`, expected) ?? "";
        await postJson(`/api/broker-orders/${orderId}/${action}`, { confirmation_text: confirmationText });
      } else {
        await postForm(`/api/broker-orders/${orderId}/${action}`, {});
      }
      showToast({ message: `Order #${orderId} ${action === "refresh" ? "refreshed" : `${action}ed`}`, tone: "success" });
      await reloadOrders(orderId);
    } catch (actionErr) {
      setActionError(actionErr instanceof Error ? actionErr.message : `Failed to ${action} order`);
    } finally {
      setActiveActionId(null);
    }
  }

  return (
    <>
      <PageHeader
        kicker="Execution authority"
        title="Execution & Risk"
        actions={
          <div className="cluster">
            <button type="button" className="button-secondary" onClick={() => void refreshVisibleOrders()}>⟳ Statuses</button>
            <HelpHint tooltip="This page shows the latest broker submissions, their status, and the exact bracket order payloads sent to Alpaca paper trading." to="/docs?doc=alpaca-paper-order-execution-spec" />
          </div>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {actionError ? <ErrorState message={actionError} /> : null}

      <section className="metrics-grid top-gap">
        <StatCard label="Risk state" value={risk ? (risk.allowed ? "allowed" : "blocked") : "—"} helper={risk?.reasons.length ? risk.reasons.map(humanizeKey).join(", ") : "No active risk blocks"} />
        <StatCard label="Kill switch" value={risk?.halt_enabled ? "halted" : "clear"} helper={risk?.halt_reason || "Manual halt is not active"} />
        <StatCard label="Open exposure" value={risk ? `$${metricNumber(risk.metrics.open_notional_usd)}` : "—"} helper={risk ? `${risk.metrics.open_position_count ?? 0} open/submitted/closing positions` : "Broker lifecycle ledger"} />
        <StatCard
          label="Last broker sync"
          value={syncState?.last_at ? formatDate(syncState.last_at) : "Never"}
          helper={
            syncState?.last_error
              ? `Last count ${syncState.last_count ?? "—"} · Error ${syncState.last_error}`
              : `Last count ${syncState?.last_count ?? "—"} · Auto-refresh runs about every 2 hours during market hours`
          }
        />
      </section>

      <Card className="top-gap">
        <SectionTitle kicker="Filters" title="Separate live, demo, paper, and account-specific records" subtitle="Filters apply to the workbench order and position lists while keeping global account risk visible." />
        <div className="data-points top-gap-small">
          <label className="data-point">
            <span className="data-point-label">broker account</span>
            <select className="input" value={brokerAccountFilter} onChange={(event) => updateFilter("broker_account_id", event.target.value)}>
              <option value="">All accounts</option>
              {brokerAccounts.map((account) => (
                <option key={account.broker_account_id} value={account.broker_account_id}>{account.account_label || account.broker_account_id}</option>
              ))}
            </select>
          </label>
          <label className="data-point">
            <span className="data-point-label">broker</span>
            <select className="input" value={brokerFilter} onChange={(event) => updateFilter("broker", event.target.value)}>
              <option value="">All brokers</option>
              <option value="etoro">eToro</option>
              <option value="alpaca">Alpaca</option>
            </select>
          </label>
          <label className="data-point">
            <span className="data-point-label">mode</span>
            <select className="input" value={accountModeFilter} onChange={(event) => updateFilter("account_mode", event.target.value)}>
              <option value="">All modes</option>
              <option value="live">Live</option>
              <option value="demo">Demo</option>
              <option value="paper">Paper</option>
            </select>
          </label>
          <label className="data-point">
            <span className="data-point-label">status</span>
            <input className="input" value={statusFilter} placeholder="accepted, skipped…" onChange={(event) => updateFilter("status", event.target.value)} />
          </label>
        </div>
        <div className="cluster top-gap-small">
          <button type="button" className="button-secondary" onClick={clearFilters}>Clear filters</button>
          <span className="helper-text">Showing {orders?.length ?? "—"} orders and {positions?.length ?? "—"} positions.</span>
        </div>
      </Card>

      {brokerAccounts.length > 0 ? (
        <DisclosureCard
          className="top-gap"
          kicker="Broker accounts"
          title="Live/demo/paper account safety"
          subtitle="Account-scoped risk, drawdown, circuit breakers, and live caps are shown before manual actions."
          defaultOpen
        >
          <section className="metrics-grid top-gap-small">
            <StatCard label="Enabled live accounts" value={globalLiveSummary?.enabled_live_account_count ?? 0} helper={(globalLiveSummary?.enabled_live_broker_accounts ?? []).join(", ") || "No live accounts enabled"} />
            <StatCard label="Live open notional" value={`$${metricNumber(globalLiveSummary?.active_live_open_notional_usd)}`} helper={`Cap $${metricNumber(globalBrokerRiskCaps.global_max_live_open_notional_usd)}`} />
            <StatCard label="Live orders today" value={globalLiveSummary?.live_order_count_today ?? 0} helper={`Cap ${globalBrokerRiskCaps.global_max_live_order_count_per_day ?? "—"}`} />
          </section>
          <div className="data-stack top-gap-small">
            {brokerAccounts.map((account) => (
              <div key={account.broker_account_id} className="data-card compact">
                <div className="data-card-header">
                  <div>
                    <div className="data-card-title">{account.account_label || account.broker_account_id}</div>
                    <div className="helper-text">{account.broker_account_id} · {account.broker}</div>
                  </div>
                  <div className="cluster">
                    <Badge tone={modeBadgeTone(account.account_mode)}>{account.mode_badge}</Badge>
                    {account.circuit_breaker.active ? <Badge tone="danger">breaker</Badge> : <Badge tone="ok">clear</Badge>}
                    {account.enabled ? <Badge tone="ok">enabled</Badge> : <Badge tone="neutral">disabled</Badge>}
                  </div>
                </div>
                <div className="helper-text top-gap-small">
                  Credentials {account.has_credentials ? "configured" : "missing"} · validation {account.validation_status} · manual actions {account.manual_actions_enabled ? "enabled" : "disabled"}
                </div>
                <div className="helper-text">
                  Drawdown {account.drawdown?.trusted ? "trusted" : "untrusted"} · equity {account.drawdown?.current_equity ?? "—"} · breaker reason {account.circuit_breaker.reason || "—"}
                </div>
                <div className="helper-text">
                  Demo artifact {String(account.risk_settings.demo_validation_artifact_id ?? "—")}
                </div>
                <div className="cluster top-gap-small">
                  {account.broker === "etoro" ? (
                    <button type="button" className="button-secondary" onClick={() => void recordDemoValidationArtifact(account)}>Record demo artifact</button>
                  ) : null}
                  {account.circuit_breaker.active ? (
                    <button type="button" className="button button-danger" onClick={() => void clearAccountCircuitBreaker(account)}>Clear breaker</button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </DisclosureCard>
      ) : null}

      <Card className="top-gap">
        <SectionTitle kicker="Action required" title="Orders and positions needing operator attention" subtitle="Failures, resubmittable orders, and cancelable live orders are shown before the raw order history." />
        {!orders && !error ? <LoadingState message="Loading broker order actions…" /> : null}
        {orders && actionRequiredOrders.length === 0 ? <EmptyState message="No broker orders currently require action." /> : null}
        {actionRequiredOrders.length > 0 ? (
          <div className="data-stack top-gap-small">
            {actionRequiredOrders.map((order) => (
              <button
                key={order.id ?? order.client_order_id}
                type="button"
                className={`data-card link-button${String(order.id) === selectedOrderId ? " is-selected" : ""}`}
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  if (order.id) {
                    next.set("order_id", String(order.id));
                  }
                  setSearchParams(next);
                }}
              >
                <div className="data-card-header">
                  <div>
                    <div className="data-card-title">{order.ticker} · {order.action}</div>
                    <div className="helper-text">plan #{order.recommendation_plan_id} · run {order.run_id ?? "—"} · qty {order.quantity}</div>
                  </div>
                  <Badge tone={brokerExecutionStatusTone(order.status)}>{order.status}</Badge>
                </div>
                {order.error_message ? <div className="helper-text top-gap-small">{order.error_message}</div> : null}
              </button>
            ))}
          </div>
        ) : null}
      </Card>

      {risk ? (
        <DisclosureCard
          kicker="Execution safety"
          title="Broker risk manager"
          subtitle="Pre-trade guardrails used before Alpaca paper submissions and manual resubmits. Limits are edited in Settings."
          className="top-gap"
          defaultOpen
          actions={
            <div className="cluster">
              <button type="button" className="button-secondary" onClick={() => void reloadOrders(selectedOrder?.id ?? undefined)}>⟳ Risk</button>
              {risk.halt_enabled ? (
                <button type="button" className="button-secondary" onClick={() => void resumeTrading()}>▶ Resume</button>
              ) : (
                <button type="button" className="button button-danger" onClick={() => void haltTrading()}>⛔ Halt</button>
              )}
              <HelpHint tooltip="The risk manager blocks new broker submissions when halt, loss, exposure, or concentration limits are breached." to="/docs?doc=broker-risk-management-spec" />
            </div>
          }
        >
          <div className="data-points top-gap-small">
            <div className="data-point"><span className="data-point-label">decision</span><span className="data-point-value"><Badge tone={risk.allowed ? "ok" : "danger"}>{risk.allowed ? "allowed" : "blocked"}</Badge></span></div>
            <div className="data-point"><span className="data-point-label">loss streak</span><span className="data-point-value">{String(risk.metrics.today_consecutive_losses ?? 0)} / {risk.config.max_consecutive_losses}</span></div>
            <div className="data-point"><span className="data-point-label">daily loss limit</span><span className="data-point-value">${risk.config.max_daily_realized_loss_usd}</span></div>
            <div className="data-point"><span className="data-point-label">open positions limit</span><span className="data-point-value">{String(risk.metrics.open_position_count ?? 0)} / {risk.config.max_open_positions}</span></div>
            <div className="data-point"><span className="data-point-label">open notional limit</span><span className="data-point-value">${metricNumber(risk.metrics.open_notional_usd)} / ${risk.config.max_open_notional_usd}</span></div>
            <div className="data-point"><span className="data-point-label">single position limit</span><span className="data-point-value">${risk.config.max_position_notional_usd}</span></div>
          </div>
          {risk.reasons.length ? (
            <div className="alert alert-warning top-gap-small">Blocked by: {risk.reasons.map(humanizeKey).join(", ")}</div>
          ) : <div className="helper-text top-gap-small">No active risk blocks.</div>}
          {haltEvents.length ? (
            <div className="top-gap-small">
              <div className="helper-text">Recent halt/resume audit</div>
              <div className="data-stack top-gap-small">
                {haltEvents.slice(0, 3).map((event) => (
                  <div key={event.id ?? `${event.action}-${event.created_at}`} className="data-card compact">
                    <div className="data-card-header">
                      <span>{event.action}</span>
                      <Badge tone={event.new_halt_enabled ? "danger" : "ok"}>{event.new_halt_enabled ? "halted" : "clear"}</Badge>
                    </div>
                    <div className="helper-text">{formatDate(event.created_at)} · {event.reason || "no reason"}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </DisclosureCard>
      ) : null}

      <DisclosureCard
        className="top-gap"
        kicker="Supporting counts"
        title="Order volume summary"
        subtitle="Useful for audit context, but not the primary safety decision."
      >
        <section className="metrics-grid top-gap-small">
          <StatCard label="Today's broker P&L" value={risk ? `$${metricNumber(risk.metrics.today_realized_pnl_usd)}` : "—"} helper={risk ? `${risk.metrics.today_win_count ?? 0} wins · ${risk.metrics.today_loss_count ?? 0} losses` : "Broker-backed realized P&L"} />
          <StatCard label="Orders loaded" value={stats.total} helper="Visible broker-order records" />
          <StatCard label="Submitted" value={stats.submitted} helper="Accepted or filled orders" />
          <StatCard label="Failed" value={stats.failed} helper="Broker or client errors" />
          <StatCard label="Skipped" value={stats.skipped} helper="Missing levels or disabled execution" />
        </section>
      </DisclosureCard>

      <section className="two-column top-gap">
        <DisclosureCard className="sticky-toolbar" kicker="Order list" title="Recent submissions" subtitle="If execution is enabled, actionable plans produce a row here after proposal generation finishes." defaultOpen actions={<HelpHint tooltip="If execution is enabled, actionable plans produce a row here after proposal generation finishes." to="/docs?doc=alpaca-paper-order-execution-spec" />}>
          {!orders && !error ? <LoadingState message="Loading broker orders…" /> : null}
          {orders && orders.length === 0 ? <EmptyState message="No broker orders recorded yet." /> : null}
          {orders ? (
            <div className="data-stack top-gap-small">
              {orders.map((order) => (
                <button
                  key={order.id ?? order.client_order_id}
                  type="button"
                  className={`data-card link-button${String(order.id) === selectedOrderId ? " is-selected" : ""}`}
                  onClick={() => {
                    const next = new URLSearchParams(searchParams);
                    if (order.id) {
                      next.set("order_id", String(order.id));
                    }
                    setSearchParams(next);
                  }}
                >
                  <div className="data-card-header">
                    <div>
                      <div className="data-card-title">{order.ticker} · {order.action}</div>
                      <div className="helper-text">
                        plan #{order.recommendation_plan_id} · run {order.run_id ?? "—"} · qty {order.quantity}
                      </div>
                    </div>
                    <Badge tone={brokerExecutionStatusTone(order.status)}>{order.status}</Badge>
                  </div>
                  <div className="helper-text top-gap-small">
                    {order.side.toUpperCase()} · {order.order_type} · {order.broker_account_id} · <Badge tone={modeBadgeTone(order.account_mode)}>{order.account_mode}</Badge>
                  </div>
                </button>
              ))}
            </div>
          ) : null}
        </DisclosureCard>

        <DisclosureCard title={selectedOrder ? `Order #${selectedOrder.id}` : "Select an order"} subtitle="Inspect the payload and broker response only when you need the full audit trail." defaultOpen={Boolean(selectedOrder)} actions={selectedOrder?.run_id ? <Link className="button-secondary" to={`/runs/${selectedOrder.run_id}`}>↗ Run</Link> : undefined}>
          {!selectedOrder && !error ? <EmptyState message="Choose an order from the left panel to inspect its payload and broker response." /> : null}
          {selectedOrder ? (
            <div className="stack-page top-gap-small">
              <div className="data-points">
                <div className="data-point"><span className="data-point-label">broker account</span><span className="data-point-value">{selectedOrder.broker_account_id}</span></div>
                <div className="data-point"><span className="data-point-label">broker</span><span className="data-point-value">{selectedOrder.broker}</span></div>
                <div className="data-point"><span className="data-point-label">mode</span><span className="data-point-value"><Badge tone={modeBadgeTone(selectedOrder.account_mode)}>{selectedOrder.account_mode}</Badge></span></div>
                <div className="data-point"><span className="data-point-label">side</span><span className="data-point-value"><Badge tone={brokerExecutionStatusTone(selectedOrder.status)}>{selectedOrder.side}</Badge></span></div>
                <div className="data-point"><span className="data-point-label">qty</span><span className="data-point-value">{selectedOrder.quantity}</span></div>
                <div className="data-point"><span className="data-point-label">entry</span><span className="data-point-value">{selectedOrder.entry_price ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">stop</span><span className="data-point-value">{selectedOrder.stop_loss ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">take profit</span><span className="data-point-value">{selectedOrder.take_profit ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">client id</span><span className="data-point-value">{selectedOrder.client_order_id}</span></div>
              </div>
              <div className="helper-text">Created {formatDate(selectedOrder.created_at)} · Updated {formatDate(selectedOrder.updated_at)} · Submitted {formatDate(selectedOrder.submitted_at)}</div>
              {selectedOrder.broker_order_id ? <div className="helper-text">Broker order id: {selectedOrder.broker_order_id}</div> : null}
              {selectedOrder.error_message ? <div className="alert alert-warning">{selectedOrder.error_message}</div> : null}
              {selectedPosition ? (
                <Card>
                  <SectionTitle kicker="Position lifecycle" title="Broker-backed position" subtitle="Derived from the latest Alpaca bracket snapshot." />
                  <div className="data-points top-gap-small">
                    <div className="data-point"><span className="data-point-label">position status</span><span className="data-point-value"><Badge tone={brokerExecutionStatusTone(selectedPosition.status)}>{selectedPosition.status}</Badge></span></div>
                    <div className="data-point"><span className="data-point-label">current qty</span><span className="data-point-value">{selectedPosition.current_quantity}</span></div>
                    <div className="data-point"><span className="data-point-label">entry avg</span><span className="data-point-value">{selectedPosition.entry_avg_price ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">exit avg</span><span className="data-point-value">{selectedPosition.exit_avg_price ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">exit reason</span><span className="data-point-value">{selectedPosition.exit_reason ?? "—"}</span></div>
                    <div className="data-point"><span className="data-point-label">realized P&L</span><span className="data-point-value">{selectedPosition.realized_pnl === null ? "—" : selectedPosition.realized_pnl.toFixed(2)}</span></div>
                    <div className="data-point"><span className="data-point-label">return</span><span className="data-point-value">{selectedPosition.realized_return_pct === null ? "—" : `${selectedPosition.realized_return_pct.toFixed(2)}%`}</span></div>
                    <div className="data-point"><span className="data-point-label">R multiple</span><span className="data-point-value">{selectedPosition.realized_r_multiple === null ? "—" : selectedPosition.realized_r_multiple.toFixed(2)}</span></div>
                  </div>
                  <div className="helper-text top-gap-small">Entry {formatDate(selectedPosition.entry_filled_at)} · Exit {formatDate(selectedPosition.exit_filled_at)}</div>
                  {selectedPosition.error_message ? <div className="alert alert-warning top-gap-small">{selectedPosition.error_message}</div> : null}
                </Card>
              ) : null}
              <div className="cluster top-gap-small">
                {selectedOrder.id ? <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => void handleAction(selectedOrder.id as number, "refresh")}>⟳ Status</button> : null}
                {isBrokerExecutionResubmittable(selectedOrder.status) ? (
                  <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => selectedOrder.id && void handleAction(selectedOrder.id, "resubmit")}>↻ Resubmit</button>
                ) : null}
                {isBrokerExecutionCancelable(selectedOrder.status) && selectedOrder.broker_order_id ? (
                  <button type="button" className="button button-danger" disabled={activeActionId === selectedOrder.id} onClick={() => selectedOrder.id && void handleAction(selectedOrder.id, "cancel")}>✕ Cancel</button>
                ) : null}
              </div>

              <DisclosureCard kicker="Request" title="Bracket order payload" subtitle="Exact JSON submitted to Alpaca paper trading.">
                <pre className="code-block top-gap-small">{prettyPayload(selectedOrder.request_payload)}</pre>
              </DisclosureCard>
              <DisclosureCard kicker="Response" title="Broker response" subtitle="Exact JSON returned by the broker client.">
                <pre className="code-block top-gap-small">{prettyPayload(selectedOrder.response_payload)}</pre>
              </DisclosureCard>
            </div>
          ) : null}
        </DisclosureCard>
      </section>
    </>
  );
}

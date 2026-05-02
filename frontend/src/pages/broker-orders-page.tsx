import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { AccountRiskState, BrokerOrderExecution, BrokerPosition, BrokerSyncState, BrokerWorkbench, RiskHaltEvent } from "../types";
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
  const { showToast } = useToast();
  const limit = Math.max(1, Number(searchParams.get("limit") ?? "50") || 50);
  const runId = searchParams.get("run_id");
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
        const workbench = await getJson<BrokerWorkbench>(`/api/broker-workbench?${params.toString()}`);
        const loadedOrders = workbench.broker_orders;
        setOrders(loadedOrders);
        setPositions(workbench.broker_positions);
        setRisk(workbench.risk);
        setHaltEvents(workbench.risk_halt_events ?? []);
        setSyncState(workbench.broker_sync_state ?? null);
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
  }, [limit, runId, searchParams, selectedOrderId, setSearchParams]);

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

  async function reloadOrders(nextSelectedOrderId?: number) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (runId) {
      params.set("run_id", runId);
    }
    const workbench = await getJson<BrokerWorkbench>(`/api/broker-workbench?${params.toString()}`);
    const loadedOrders = workbench.broker_orders;
    setOrders(loadedOrders);
    setPositions(workbench.broker_positions);
    setRisk(workbench.risk);
    setHaltEvents(workbench.risk_halt_events ?? []);
    setSyncState(workbench.broker_sync_state ?? null);
    const nextOrderId = nextSelectedOrderId ?? loadedOrders[0]?.id ?? null;
    if (nextOrderId) {
      const next = new URLSearchParams(searchParams);
      next.set("order_id", String(nextOrderId));
      setSearchParams(next, { replace: true });
    }
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

  async function handleAction(orderId: number, action: "resubmit" | "cancel" | "refresh") {
    setActionError(null);
    setActiveActionId(orderId);
    try {
      await postForm(`/api/broker-orders/${orderId}/${action}`, {});
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
        kicker="Execution audit"
        title="Broker orders" 
        actions={
          <div className="cluster">
            <button type="button" className="button-secondary" onClick={() => void refreshVisibleOrders()}>Refresh statuses</button>
            <HelpHint tooltip="This page shows the latest broker submissions, their status, and the exact bracket order payloads sent to Alpaca paper trading." to="/docs?doc=alpaca-paper-order-execution-spec" />
          </div>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {actionError ? <ErrorState message={actionError} /> : null}

      <section className="metrics-grid top-gap">
        <StatCard label="Risk state" value={risk ? (risk.allowed ? "allowed" : "blocked") : "—"} helper={risk?.reasons.length ? risk.reasons.map(humanizeKey).join(", ") : "No active risk blocks"} />
        <StatCard label="Kill switch" value={risk?.halt_enabled ? "halted" : "clear"} helper={risk?.halt_reason || "Manual halt is not active"} />
        <StatCard label="Today's broker P&L" value={risk ? `$${metricNumber(risk.metrics.today_realized_pnl_usd)}` : "—"} helper={risk ? `${risk.metrics.today_win_count ?? 0} wins · ${risk.metrics.today_loss_count ?? 0} losses` : "Broker-backed realized P&L"} />
        <StatCard label="Open exposure" value={risk ? `$${metricNumber(risk.metrics.open_notional_usd)}` : "—"} helper={risk ? `${risk.metrics.open_position_count ?? 0} open/submitted positions` : "Broker lifecycle ledger"} />
        <StatCard label="Orders loaded" value={stats.total} helper="Visible broker-order records" />
        <StatCard label="Submitted" value={stats.submitted} helper="Accepted or filled orders" />
        <StatCard label="Failed" value={stats.failed} helper="Broker or client errors" />
        <StatCard label="Skipped" value={stats.skipped} helper="Missing levels or disabled execution" />
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

      {risk ? (
        <Card className="top-gap">
          <SectionTitle
            kicker="Execution safety"
            title="Broker risk manager"
            subtitle="Pre-trade guardrails used before Alpaca paper submissions and manual resubmits. Limits are edited in Settings."
            actions={
              <div className="cluster">
                <button type="button" className="button-secondary" onClick={() => void reloadOrders(selectedOrder?.id ?? undefined)}>Refresh risk</button>
                {risk.halt_enabled ? (
                  <button type="button" className="button-secondary" onClick={() => void resumeTrading()}>Resume trading</button>
                ) : (
                  <button type="button" className="button button-danger" onClick={() => void haltTrading()}>Halt trading</button>
                )}
                <HelpHint tooltip="The risk manager blocks new broker submissions when halt, loss, exposure, or concentration limits are breached." to="/docs?doc=broker-risk-management-spec" />
              </div>
            }
          />
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
        </Card>
      ) : null}

      <section className="two-column top-gap">
        <Card className="sticky-toolbar">
          <SectionTitle
            kicker="Order list"
            title="Recent submissions"
            actions={<HelpHint tooltip="If execution is enabled, actionable plans produce a row here after proposal generation finishes." to="/docs?doc=alpaca-paper-order-execution-spec" />}
          />
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
                    {order.side.toUpperCase()} · {order.order_type} · {order.account_mode}
                  </div>
                </button>
              ))}
            </div>
          ) : null}
        </Card>

        <Card>
          <SectionTitle
            kicker="Order detail"
            title={selectedOrder ? `Order #${selectedOrder.id}` : "Select an order"}
            actions={selectedOrder?.run_id ? <Link className="button-secondary" to={`/runs/${selectedOrder.run_id}`}>Open run</Link> : undefined}
          />
          {!selectedOrder && !error ? <EmptyState message="Choose an order from the left panel to inspect its payload and broker response." /> : null}
          {selectedOrder ? (
            <div className="stack-page top-gap-small">
              <div className="data-points">
                <div className="data-point"><span className="data-point-label">broker</span><span className="data-point-value">{selectedOrder.broker}</span></div>
                <div className="data-point"><span className="data-point-label">mode</span><span className="data-point-value">{selectedOrder.account_mode}</span></div>
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
                {selectedOrder.id ? <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => void handleAction(selectedOrder.id as number, "refresh")}>Refresh status</button> : null}
                {isBrokerExecutionResubmittable(selectedOrder.status) ? (
                  <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => selectedOrder.id && void handleAction(selectedOrder.id, "resubmit")}>Resubmit</button>
                ) : null}
                {isBrokerExecutionCancelable(selectedOrder.status) && selectedOrder.broker_order_id ? (
                  <button type="button" className="button button-danger" disabled={activeActionId === selectedOrder.id} onClick={() => selectedOrder.id && void handleAction(selectedOrder.id, "cancel")}>Cancel</button>
                ) : null}
              </div>

              <Card>
                <SectionTitle kicker="Request" title="Bracket order payload" subtitle="Exact JSON submitted to Alpaca paper trading." />
                <pre className="code-block top-gap-small">{prettyPayload(selectedOrder.request_payload)}</pre>
              </Card>
              <Card>
                <SectionTitle kicker="Response" title="Broker response" subtitle="Exact JSON returned by the broker client." />
                <pre className="code-block top-gap-small">{prettyPayload(selectedOrder.response_payload)}</pre>
              </Card>
            </div>
          ) : null}
        </Card>
      </section>
    </>
  );
}

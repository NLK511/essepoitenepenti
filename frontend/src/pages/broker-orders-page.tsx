import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { getJson, postForm } from "../api";
import { useToast } from "../components/toast";
import { Badge, Card, EmptyState, ErrorState, HelpHint, LoadingState, PageHeader, SectionTitle, StatCard } from "../components/ui";
import type { AppSetting, BrokerOrderExecution, SettingsResponse } from "../types";
import { formatDate } from "../utils";

function orderTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "submitted" || status === "accepted" || status === "filled" || status === "partially_filled") {
    return "ok";
  }
  if (status === "canceled" || status === "expired") {
    return "warning";
  }
  if (status === "failed" || status === "rejected") {
    return "danger";
  }
  if (status === "skipped") {
    return "warning";
  }
  return "neutral";
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
  const [settings, setSettings] = useState<AppSetting[] | null>(null);
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
        const [loadedOrders, loadedSettings] = await Promise.all([
          getJson<BrokerOrderExecution[]>(`/api/broker-orders?${params.toString()}`),
          getJson<SettingsResponse>("/api/settings"),
        ]);
        setOrders(loadedOrders);
        setSettings(loadedSettings.settings);
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
      submitted: items.filter((order) => order.status === "submitted" || order.status === "accepted" || order.status === "filled").length,
      failed: items.filter((order) => order.status === "failed").length,
      skipped: items.filter((order) => order.status === "skipped").length,
    };
  }, [orders]);

  const syncSettings = useMemo(() => {
    const map = new Map((settings ?? []).map((setting) => [setting.key, setting.value]));
    return {
      lastAt: map.get("broker_order_sync_last_at") ?? null,
      lastCount: map.get("broker_order_sync_last_count") ?? null,
      lastError: map.get("broker_order_sync_last_error") ?? null,
    };
  }, [settings]);

  const selectedOrder = useMemo(
    () => orders?.find((order) => String(order.id) === selectedOrderId) ?? null,
    [orders, selectedOrderId],
  );

  async function reloadOrders(nextSelectedOrderId?: number) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (runId) {
      params.set("run_id", runId);
    }
    const [loadedOrders, loadedSettings] = await Promise.all([
      getJson<BrokerOrderExecution[]>(`/api/broker-orders?${params.toString()}`),
      getJson<SettingsResponse>("/api/settings"),
    ]);
    setOrders(loadedOrders);
    setSettings(loadedSettings.settings);
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
        <StatCard label="Orders loaded" value={stats.total} helper="Visible broker-order records" />
        <StatCard label="Submitted" value={stats.submitted} helper="Accepted or filled orders" />
        <StatCard label="Failed" value={stats.failed} helper="Broker or client errors" />
        <StatCard label="Skipped" value={stats.skipped} helper="Missing levels or disabled execution" />
        <StatCard
          label="Last broker sync"
          value={syncSettings.lastAt ? formatDate(syncSettings.lastAt) : "Never"}
          helper={
            syncSettings.lastError
              ? `Last count ${syncSettings.lastCount ?? "—"} · Error ${syncSettings.lastError}`
              : `Last count ${syncSettings.lastCount ?? "—"} · Auto-refresh runs about every 2 hours during market hours`
          }
        />
      </section>

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
                    <Badge tone={orderTone(order.status)}>{order.status}</Badge>
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
                <div className="data-point"><span className="data-point-label">side</span><span className="data-point-value"><Badge tone={orderTone(selectedOrder.status)}>{selectedOrder.side}</Badge></span></div>
                <div className="data-point"><span className="data-point-label">qty</span><span className="data-point-value">{selectedOrder.quantity}</span></div>
                <div className="data-point"><span className="data-point-label">entry</span><span className="data-point-value">{selectedOrder.entry_price ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">stop</span><span className="data-point-value">{selectedOrder.stop_loss ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">take profit</span><span className="data-point-value">{selectedOrder.take_profit ?? "—"}</span></div>
                <div className="data-point"><span className="data-point-label">client id</span><span className="data-point-value">{selectedOrder.client_order_id}</span></div>
              </div>
              <div className="helper-text">Created {formatDate(selectedOrder.created_at)} · Updated {formatDate(selectedOrder.updated_at)} · Submitted {formatDate(selectedOrder.submitted_at)}</div>
              {selectedOrder.broker_order_id ? <div className="helper-text">Broker order id: {selectedOrder.broker_order_id}</div> : null}
              {selectedOrder.error_message ? <div className="alert alert-warning">{selectedOrder.error_message}</div> : null}
              <div className="cluster top-gap-small">
                {selectedOrder.id ? <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => void handleAction(selectedOrder.id as number, "refresh")}>Refresh status</button> : null}
                {selectedOrder.status === "failed" || selectedOrder.status === "canceled" ? (
                  <button type="button" className="button-secondary" disabled={activeActionId === selectedOrder.id} onClick={() => selectedOrder.id && void handleAction(selectedOrder.id, "resubmit")}>Resubmit</button>
                ) : null}
                {selectedOrder.status !== "canceled" && selectedOrder.status !== "filled" && selectedOrder.broker_order_id ? (
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

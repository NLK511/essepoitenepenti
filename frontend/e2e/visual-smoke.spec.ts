import { expect, test, type Page } from "@playwright/test";

const FIXED_NOW = "2026-05-10T09:00:00.000Z";

async function mockApi(page: Page) {
  await page.clock.setFixedTime(new Date(FIXED_NOW));
  await page.addInitScript(() => {
    window.localStorage.setItem("trade-proposer-auth-token", "visual-test-token");
    window.localStorage.setItem("trade-proposer-theme", "dark");
  });

  await page.route("**/api/health", async (route) => {
    await route.fulfill({ json: { status: "ok", app: "trade-proposer-app", env: "test", preflight: { status: "ok", engine: "mock", checked_at: FIXED_NOW }, workers: { status: "ok", count: 1, details: [] } } });
  });
  await page.route("**/api/workers/active", async (route) => {
    await route.fulfill({ json: { workers: [{ worker_id: "visual-worker", hostname: "localhost", pid: 1001, status: "idle", last_heartbeat_at: FIXED_NOW, started_at: FIXED_NOW, version: "test", active_run_id: null }] } });
  });
  await page.route("**/api/dashboard?**", async (route) => {
    await route.fulfill({ json: {
      dashboard_window: "1d",
      watchlists: [], jobs: [], latest_runs: [], recent_runs: [], recommendation_plans: [],
      recommendation_quality: { summary: { status: "watch", status_reason: "Visual fixture: enough layout data to exercise the board.", generated_at: FIXED_NOW, resolved_outcomes: 42 } },
      dashboard_summary: { overall_win_rate_percent: 52.4, broker_win_rate_percent: 50.0, total_profit: 123.45, broker_realized_pnl: 88.12, shortlist_rate_percent: 18.2, actionable_rate_percent: 9.4, actionability_gap_percent: -1.2, plan_amount: 11, signals_amount: 60, actionable_plans: 4, phantom_win_outcomes: 2, phantom_resolved_outcomes: 8, actionable_win_outcomes: 3, actionable_resolved_outcomes: 7 },
      technical_summary: { broker_closed_positions: 6, news_processed: 24, tweets_processed: 8, bars_stored: 1200, orders_placed: 3, broker_wins: 3, broker_losses: 3, broker_realized_pnl: 88.12 },
      major_failures: [], distinct_warnings: []
    } });
  });
  await page.route("**/api/research/performance-workbench**", async (route) => {
    await route.fulfill({ json: {
      job: null, history_count: 0, latest_run: null, latest_assessment: {}, calibration_summary: null,
      policy_health: { label: "watch", reasons: ["mostly_simulated_evidence"], resolved_selected_outcomes: 42, win_rate_percent: 52.4, realized_pnl: 123.45, calibration_gap_percent: 3.1, broker_outcome_share_percent: 24.0 },
      edge_validation_gate: { label: "research_only", reasons: ["thin_broker_sample"], resolved_selected_outcomes: 42, broker_selected_outcomes: 10, broker_outcome_share_percent: 24.0, win_rate_percent: 52.4, realized_pnl: 123.45, average_return_percent: 0.8, average_r_multiple: 0.2, profit_factor: 1.3, calibration_gap_percent: 3.1, walk_forward_qualified_slices: 1, walk_forward_promotion_recommended: false }
    } });
  });
  await page.route("**/api/risk", async (route) => {
    await route.fulfill({ json: { allowed: true, enabled: true, halt_enabled: false, halt_reason: "", reasons: [], metrics: {}, config: { risk_management_enabled: true, risk_halt_enabled: true, max_daily_loss_usd: 100, max_open_notional_usd: 1000, max_position_notional_usd: 250, max_same_ticker_open_positions: 1, max_consecutive_losses: 3 } } });
  });
  await page.route("**/api/data-quality/audit?**", async (route) => {
    await route.fulfill({ json: { generated_at: FIXED_NOW, ticker_count: 25, issue_ticker_count: 1, issue_counts: { stale_bars: 1 }, items: [] } });
  });
  await page.route("**/api/dashboard/trends", async (route) => {
    await route.fulfill({ json: { dashboard_trends: { windows: [], series: [] } } });
  });
}

test.describe("visual layout smoke", () => {
  test("dashboard operator board stays inside cards", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByText("Operator status")).toBeVisible();
    await expect(page).toHaveScreenshot("dashboard-operator-board.png", { fullPage: true, animations: "disabled" });
  });
});

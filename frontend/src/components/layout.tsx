import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth";
import { getJson } from "../api";
import { Badge } from "../components/ui";
import { AurelioMark } from "../theme/aurelio";
import { ActiveWorkersResponse, AppHealthResponse, WorkerHeartbeat } from "../types";

const THEME_KEY = "trade-proposer-theme";

type Theme = "dark" | "light";

type NavItem = {
  to: string;
  label: string;
  shortLabel: string;
  icon: string;
  end?: boolean;
  match?: (pathname: string) => boolean;
};

type NavSubsection = {
  label: string;
  items: NavItem[];
};

type NavSection = {
  label: string;
  items: NavItem[];
  subsections?: NavSubsection[];
};

const navSections: NavSection[] = [
  {
    label: "Overview",
    items: [
      { to: "/", label: "Dashboard", shortLabel: "Dash", icon: "◌", end: true },
      { to: "/jobs", label: "Jobs", shortLabel: "Jobs", icon: "▣", end: true },
      { to: "/jobs/watchlists", label: "Watchlists", shortLabel: "WL", icon: "◎" },
    ],
  },
  {
    label: "Review",
    items: [
      { to: "/jobs/ticker-signals", label: "Ticker signals", shortLabel: "Signals", icon: "≈" },
      { to: "/jobs/recommendation-plans", label: "Recommendation plans", shortLabel: "Plans", icon: "↗" },
      { to: "/jobs/debugger", label: "Run debugger", shortLabel: "Debug", icon: "⌘" },
      { to: "/context", label: "Context review", shortLabel: "Context", icon: "◔" },
    ],
  },
  {
    label: "Research",
    items: [
      { to: "/research", label: "Research home", shortLabel: "Hub", icon: "⌂", end: true },
    ],
    subsections: [
      {
        label: "Advanced review",
        items: [
          { to: "/research/decision-samples", label: "Decision samples", shortLabel: "Samples", icon: "◉" },
          { to: "/recommendation-quality", label: "Quality summary", shortLabel: "Quality", icon: "◈" },
        ],
      },
      {
        label: "Tuning",
        items: [
          { to: "/research/signal-gating/gating-job", label: "Signal gating tuning", shortLabel: "Gate", icon: "↯" },
          { to: "/research/plan-generation-tuning", label: "Plan generation tuning", shortLabel: "Plan tune", icon: "↗" },
        ],
      },
    ],
  },
  {
    label: "Reference",
    items: [
      { to: "/settings", label: "Settings", shortLabel: "Set", icon: "⚙" },
      { to: "/docs", label: "Docs", shortLabel: "Docs", icon: "✦" },
    ],
  },
];

const jobsSectionLinks = [
  { to: "/jobs", label: "Overview", end: true },
  { to: "/jobs/watchlists", label: "Watchlists" },
  { to: "/jobs/ticker-signals", label: "Signals" },
  { to: "/jobs/recommendation-plans", label: "Plans" },
  { to: "/jobs/debugger", label: "Debugger" },
];

function readInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function isItemActive(item: NavItem, pathname: string): boolean {
  if (item.match) {
    return item.match(pathname);
  }
  if (item.end) {
    return pathname === item.to;
  }
  return pathname === item.to || pathname.startsWith(`${item.to}/`);
}

function routeMeta(pathname: string): { eyebrow: string; title: string; description: string } {
  if (pathname === "/") {
    return {
      eyebrow: "Workspace overview",
      title: "Decision-support cockpit",
      description: "Track runs, context, watchlists, and recommendation plans from one place.",
    };
  }
  if (pathname === "/jobs") {
    return {
      eyebrow: "Automation",
      title: "Jobs and execution",
      description: "Create repeatable workflows, queue runs, and monitor operational health.",
    };
  }
  if (pathname.startsWith("/jobs/watchlists")) {
    return {
      eyebrow: "Automation",
      title: "Watchlists",
      description: "Define the universes, default horizons, and scheduling assumptions that shape plan generation.",
    };
  }
  if (pathname.startsWith("/jobs/ticker-signals")) {
    return {
      eyebrow: "Review",
      title: "Ticker signals",
      description: "Review candidates before they become action plans.",
    };
  }
  if (pathname.startsWith("/jobs/recommendation-plans")) {
    return {
      eyebrow: "Review",
      title: "Recommendation plans",
      description: "Review action plans first, with advanced analytics available when needed.",
    };
  }
  if (pathname.startsWith("/recommendation-quality")) {
    return {
      eyebrow: "Advanced review",
      title: "Recommendation quality summary",
      description: "Review calibration, evidence concentration, and walk-forward readiness in one consolidated place.",
    };
  }
  if (pathname.startsWith("/research/signal-gating/gating-job") || pathname.startsWith("/research/signal-gating")) {
    return {
      eyebrow: "Research",
      title: "Signal gating tuning",
      description: "Adjust upstream selection controls, launch tuning runs, and inspect candidate results without a separate hub page.",
    };
  }
  if (pathname.startsWith("/research/plan-generation-tuning")) {
    return {
      eyebrow: "Research",
      title: "Plan generation tuning",
      description: "Inspect active plan-generation configs, ranked backtest candidates, and guarded promotions.",
    };
  }
  if (pathname.startsWith("/research")) {
    return {
      eyebrow: "Research",
      title: "Research hub",
      description: "Review tuning, calibration, and backtesting work without mixing it into the operational workflow.",
    };
  }
  if (pathname.startsWith("/jobs/debugger")) {
    return {
      eyebrow: "Review",
      title: "Run debugger",
      description: "Trace what each run scanned, shortlisted, persisted, and warned about.",
    };
  }
  if (pathname.startsWith("/runs/")) {
    return {
      eyebrow: "Execution detail",
      title: "Run review",
      description: "Follow the full execution path from cheap scan to context objects, signals, and plans.",
    };
  }
  if (pathname.startsWith("/workers/")) {
    return {
      eyebrow: "Worker diagnostics",
      title: "Worker logs",
      description: "Inspect live worker output and follow a running worker’s progress in real time.",
    };
  }
  if (pathname.startsWith("/tickers/")) {
    return {
      eyebrow: "Ticker review",
      title: "Ticker drill-down",
      description: "Inspect a ticker’s recent plans, outcomes, and supporting context.",
    };
  }
  if (pathname.startsWith("/context") || pathname.startsWith("/sentiment")) {
    return {
      eyebrow: "Context",
      title: "Context review",
      description: "Review the shared macro and industry backdrop behind current plans and signals.",
    };
  }
  if (pathname.startsWith("/settings")) {
    return {
      eyebrow: "Reference",
      title: "Settings",
      description: "Configure providers, credentials, and operational defaults.",
    };
  }
  if (pathname.startsWith("/docs")) {
    return {
      eyebrow: "Reference",
      title: "Docs",
      description: "Read product, redesign, and operator guidance without leaving the app.",
    };
  }
  return {
    eyebrow: "Trade proposer app",
    title: "Workspace",
    description: "Navigate the recommendation workflow, supporting context, and system settings.",
  };
}

function workerStatusTone(status: string): "ok" | "warning" | "danger" | "neutral" | "info" {
  if (status === "running") {
    return "ok";
  }
  if (status === "idle") {
    return "danger";
  }
  if (status === "stale") {
    return "danger";
  }
  return "neutral";
}

function workerStatusLabel(worker: WorkerHeartbeat): string {
  if (worker.active_run_id !== null && worker.active_run_id !== undefined) {
    return `run ${worker.active_run_id}`;
  }
  return worker.status;
}

function summarizeWorkers(workers: WorkerHeartbeat[]): { label: string; tone: "ok" | "warning" | "danger" | "neutral" | "info" } {
  const running = workers.filter((worker) => worker.status === "running").length;
  const idle = workers.filter((worker) => worker.status === "idle").length;
  const stale = workers.filter((worker) => worker.status === "stale").length;

  if (running > 0) {
    return { label: `${running} running`, tone: "ok" };
  }
  if (idle > 0) {
    return { label: `${idle} idle`, tone: "danger" };
  }
  if (stale > 0) {
    return { label: `${stale} stale`, tone: "danger" };
  }
  return { label: "No active workers", tone: "neutral" };
}

export function AppLayout() {
  const [theme, setTheme] = useState<Theme>(() => readInitialTheme());
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();
  const { logout } = useAuth();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMobileNavOpen(false);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const meta = useMemo(() => routeMeta(location.pathname), [location.pathname]);
  const [health, setHealth] = useState<AppHealthResponse | null>(null);
  const [activeWorkers, setActiveWorkers] = useState<WorkerHeartbeat[]>([]);
  const [workerPopoverHovered, setWorkerPopoverHovered] = useState(false);
  const [workerPopoverPinned, setWorkerPopoverPinned] = useState(false);

  useEffect(() => {
    let mounted = true;
    const fetchHealth = () => {
      getJson<AppHealthResponse>("/api/health")
        .then((data) => {
          if (mounted) setHealth(data);
        })
        .catch((err) => console.error("Health fetch failed", err));
    };

    const fetchWorkers = () => {
      getJson<ActiveWorkersResponse>("/api/workers/active")
        .then((data) => {
          if (mounted) setActiveWorkers(data.workers);
        })
        .catch((err) => console.error("Worker list fetch failed", err));
    };

    fetchHealth();
    fetchWorkers();
    const interval = setInterval(() => {
      fetchHealth();
      fetchWorkers();
    }, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const workerStatus = health?.workers?.status || "unknown";
  const workerCount = activeWorkers.length || health?.workers?.count || 0;
  const workerPopoverOpen = workerPopoverPinned || workerPopoverHovered;
  const workerSummary = summarizeWorkers(activeWorkers);

  const jobsSectionActive = location.pathname === "/jobs" || location.pathname.startsWith("/jobs/");

  return (
    <div className="workspace-shell">
      <aside className="sidebar-shell">
        <div className="sidebar-shell-content">
          <div className="sidebar-brand">
            <NavLink to="/" className="brand-mark brand-mark-large" aria-label="Aurelio home">
              <AurelioMark className="brand-mark-icon" />
            </NavLink>
            <div className="brand-copy">
              <div className="brand-title">Aurelio</div>
              <div className="brand-subtitle">Stoic clarity for modern markets</div>
            </div>
          </div>

          <div
            className="sidebar-status-wrap"
            onMouseEnter={() => setWorkerPopoverHovered(true)}
            onMouseLeave={() => setWorkerPopoverHovered(false)}
          >
            <div className="sidebar-status-card">
              <div className="kicker">Current mode</div>
              <h2>Disciplined conviction</h2>
              <p>
                Review watchlists, shortlist candidates, and inspect recommendation plans with outcome-aware evidence.
              </p>

              <div className="sidebar-status-indicator-group">
                <div className={`status-dot ${workerSummary.tone === "ok" ? "is-ok" : workerSummary.tone === "danger" ? "is-failed" : "is-warning"}`} />
                <div className="status-indicator-label">
                  {workerSummary.label === "No active workers"
                    ? workerStatus === "ok"
                      ? `${workerCount} worker${workerCount !== 1 ? "s" : ""} active`
                      : "No workers active"
                    : workerSummary.label}
                </div>
              </div>

              <div className="sidebar-status-actions">
                <button
                  type="button"
                  className="button-subtle sidebar-status-link worker-popover-toggle"
                  aria-expanded={workerPopoverOpen}
                  onClick={() => setWorkerPopoverPinned((current) => !current)}
                >
                  {workerPopoverPinned ? "Unpin workers" : "Show workers"}
                </button>
                <a href="/api/health" className="button-subtle sidebar-status-link" target="_blank" rel="noreferrer">
                  Open API health
                </a>
              </div>
            </div>

            {workerPopoverOpen ? (
              <div className="worker-status-popover" role="dialog" aria-label="Running workers">
                <div className="worker-status-popover-header">
                  <div>
                    <div className="kicker">Active workers</div>
                    <div className="worker-status-popover-title">{workerSummary.label}</div>
                  </div>
                  <div className="worker-status-popover-actions">
                    <div className={`status-dot ${workerSummary.tone === "ok" ? "is-ok" : workerSummary.tone === "danger" ? "is-failed" : "is-warning"}`} />
                    {workerPopoverPinned ? (
                      <button
                        type="button"
                        className="button-subtle worker-status-popover-close"
                        onClick={() => setWorkerPopoverPinned(false)}
                        aria-label="Close worker popover"
                      >
                        ✕
                      </button>
                    ) : null}
                  </div>
                </div>
                {activeWorkers.length === 0 ? (
                  <div className="empty-state worker-status-empty">No active workers detected.</div>
                ) : (
                  <div className="worker-status-list">
                    {activeWorkers.map((worker) => (
                      <Link key={worker.worker_id} to={`/workers/${worker.worker_id}`} className="worker-status-item" onClick={() => setWorkerPopoverPinned(false)}>
                        <div className="worker-status-item-topline">
                          <div className="worker-status-item-title">{worker.worker_id}</div>
                          <Badge tone={workerStatusTone(worker.status)}>{workerStatusLabel(worker)}</Badge>
                        </div>
                        <div className="worker-status-item-meta">{worker.hostname} · pid {worker.pid}</div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            ) : null}
          </div>

          <div className="sidebar-nav-scroll">
            <nav className="sidebar-nav" aria-label="Primary navigation">
              {navSections.map((section) => (
                <div key={section.label} className="sidebar-nav-section">
                  <div className="sidebar-section-label">{section.label}</div>
                  <div className="sidebar-link-list">
                    {section.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.end}
                        className={() => `sidebar-link${isItemActive(item, location.pathname) ? " is-active" : ""}`}
                      >
                        <span className="sidebar-link-icon" aria-hidden="true">{item.icon}</span>
                        <span className="sidebar-link-copy">
                          <span className="sidebar-link-label">{item.label}</span>
                          <span className="sidebar-link-short">{item.shortLabel}</span>
                        </span>
                      </NavLink>
                    ))}
                  </div>
                  {section.subsections ? section.subsections.map((subsection) => (
                    <div key={subsection.label} className="sidebar-subsection">
                      <div className="sidebar-subsection-label">{subsection.label}</div>
                      <div className="sidebar-link-list sidebar-subsection-links">
                        {subsection.items.map((item) => (
                          <NavLink
                            key={item.to}
                            to={item.to}
                            end={item.end}
                            className={() => `sidebar-link${isItemActive(item, location.pathname) ? " is-active" : ""}`}
                          >
                            <span className="sidebar-link-icon" aria-hidden="true">{item.icon}</span>
                            <span className="sidebar-link-copy">
                              <span className="sidebar-link-label">{item.label}</span>
                              <span className="sidebar-link-short">{item.shortLabel}</span>
                            </span>
                          </NavLink>
                        ))}
                      </div>
                    </div>
                  )) : null}
                </div>
              ))}
            </nav>
          </div>
        </div>
      </aside>

      <div className="content-shell">
        <header className="content-topbar">
          <div className="content-topbar-meta">
            <div className="kicker">{meta.eyebrow}</div>
            <div className="content-topbar-title">{meta.title}</div>
            <div className="content-topbar-subtitle">{meta.description}</div>
          </div>
          <div className="content-topbar-actions">
            <button
              type="button"
              className="mobile-nav-toggle"
              aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={mobileNavOpen}
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              ☰
            </button>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              <span aria-hidden="true">◐</span>
              <span>{theme === "dark" ? "Dark" : "Light"}</span>
            </button>
            <button type="button" className="button-subtle" onClick={logout}>
              Log out
            </button>
          </div>
        </header>

        {jobsSectionActive ? (
          <div className="section-tabs" aria-label="Jobs section navigation">
            {jobsSectionLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) => `section-tab${isActive ? " is-active" : ""}`}
              >
                {link.label}
              </NavLink>
            ))}
          </div>
        ) : null}

        <div className={`mobile-nav-panel${mobileNavOpen ? " is-open" : ""}`} aria-hidden={!mobileNavOpen}>
          <nav aria-label="Mobile navigation">
            {navSections.map((section) => (
              <div key={section.label} className="mobile-nav-group">
                <div className="mobile-nav-group-title">{section.label}</div>
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={() => `nav-link mobile-nav-link${isItemActive(item, location.pathname) ? " is-active" : ""}`}
                    onClick={() => setMobileNavOpen(false)}
                  >
                    <span aria-hidden="true">{item.icon}</span>
                    <span>{item.label}</span>
                  </NavLink>
                ))}
                {section.subsections ? section.subsections.map((subsection) => (
                  <div key={subsection.label} className="mobile-nav-subgroup">
                    <div className="mobile-nav-subgroup-title">{subsection.label}</div>
                    {subsection.items.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.end}
                        className={() => `nav-link mobile-nav-link mobile-nav-link-sub${isItemActive(item, location.pathname) ? " is-active" : ""}`}
                        onClick={() => setMobileNavOpen(false)}
                      >
                        <span aria-hidden="true">{item.icon}</span>
                        <span>{item.label}</span>
                      </NavLink>
                    ))}
                  </div>
                )) : null}
              </div>
            ))}
          </nav>
        </div>
        {mobileNavOpen && (
          <button
            type="button"
            className="mobile-nav-backdrop"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
        )}

        <main className="page-shell">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

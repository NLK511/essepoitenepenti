import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth";
import { getJson } from "../api";
import { BrandLogo, BrandMark } from "../components/brand";
import { Badge } from "../components/ui";
import { ActiveWorkersResponse, AppHealthResponse, WorkerHeartbeat } from "../types";
import { workerStatusTone } from "../utils";

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
    label: "Operate",
    items: [
      { to: "/", label: "Dashboard", shortLabel: "Dash", icon: "◌", end: true },
      { to: "/jobs/recommendation-plans", label: "Trade review", shortLabel: "Trades", icon: "↗" },
      { to: "/recommendation-quality", label: "Quality & Edge", shortLabel: "Edge", icon: "◈" },
      { to: "/broker-orders", label: "Execution & Risk", shortLabel: "Risk", icon: "⟐" },
    ],
  },
  {
    label: "Evidence & diagnostics",
    items: [
      { to: "/context", label: "Context review", shortLabel: "Context", icon: "◔" },
      { to: "/data-quality", label: "Data quality", shortLabel: "Data", icon: "◇" },
      { to: "/jobs/debugger", label: "Run debugger", shortLabel: "Debug", icon: "⌘" },
    ],
  },
  {
    label: "Configure",
    items: [
      { to: "/jobs/watchlists", label: "Watchlists", shortLabel: "WL", icon: "◎" },
      { to: "/jobs", label: "Jobs", shortLabel: "Jobs", icon: "▣", end: true },
      { to: "/settings", label: "Settings", shortLabel: "Set", icon: "⚙" },
    ],
  },
  {
    label: "Research Lab",
    items: [
      { to: "/research", label: "Lab launcher", shortLabel: "Lab", icon: "⌂", end: true },
      { to: "/research/signal-gating/gating-job", label: "Signal gating tuning", shortLabel: "Gate", icon: "↯" },
      { to: "/research/plan-generation-tuning", label: "Plan generation tuning", shortLabel: "Plan tune", icon: "↗" },
      { to: "/research/decision-samples", label: "Decision samples", shortLabel: "Samples", icon: "◉" },
      { to: "/jobs/ticker-signals", label: "Candidate signals", shortLabel: "Signals", icon: "≈" },
    ],
  },
  {
    label: "Help",
    items: [
      { to: "/docs", label: "Docs", shortLabel: "Docs", icon: "✦" },
    ],
  },
];

const jobsSectionLinks = [
  { to: "/jobs", label: "Overview", end: true },
  { to: "/jobs/watchlists", label: "Watchlists" },
  { to: "/jobs/recommendation-plans", label: "Trade review" },
  { to: "/jobs/debugger", label: "Debugger" },
  { to: "/jobs/ticker-signals", label: "Candidate signals" },
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

function isSectionActive(section: NavSection, pathname: string): boolean {
  return section.items.some((item) => isItemActive(item, pathname))
    || section.subsections?.some((subsection) => subsection.items.some((item) => isItemActive(item, pathname)))
    || false;
}

function routeMeta(pathname: string): { eyebrow: string; title: string; description: string } {
  if (pathname === "/") {
    return {
      eyebrow: "Operate",
      title: "Dashboard",
      description: "Check safety, performance, inputs, and the current work queue from one place.",
    };
  }
  if (pathname === "/jobs") {
    return {
      eyebrow: "Configure",
      title: "Jobs",
      description: "Create, schedule, and manually queue repeatable workflows.",
    };
  }
  if (pathname.startsWith("/jobs/watchlists")) {
    return {
      eyebrow: "Configure",
      title: "Watchlists",
      description: "Define monitored ticker universes and the assumptions inherited by proposal jobs.",
    };
  }
  if (pathname.startsWith("/jobs/ticker-signals")) {
    return {
      eyebrow: "Research Lab",
      title: "Candidate Signals",
      description: "Inspect shortlisted, blocked, and deep-analysis candidate signals as an advanced diagnostic surface.",
    };
  }
  if (pathname.startsWith("/jobs/recommendation-plans")) {
    return {
      eyebrow: "Operate",
      title: "Trade Review",
      description: "Review current plans and trade objects; use Quality & Edge for the system-performance verdict.",
    };
  }
  if (pathname.startsWith("/recommendation-quality")) {
    return {
      eyebrow: "Operate",
      title: "Quality & Edge",
      description: "Use the authoritative edge gate, effective outcomes, calibration, reliability, and evidence-backed next actions.",
    };
  }
  if (pathname.startsWith("/research/signal-gating/gating-job") || pathname.startsWith("/research/signal-gating")) {
    return {
      eyebrow: "Research Lab",
      title: "Signal Gating Tuning",
      description: "Adjust upstream shortlist thresholds only when evidence supports a gating change.",
    };
  }
  if (pathname.startsWith("/research/plan-generation-tuning")) {
    return {
      eyebrow: "Research Lab",
      title: "Plan Generation Tuning",
      description: "Inspect downstream plan-framing candidates, validation, and guarded promotions.",
    };
  }
  if (pathname.startsWith("/research")) {
    return {
      eyebrow: "Research Lab",
      title: "Advanced Tools",
      description: "Open tuning and sample-review workflows after Quality & Edge justifies a research action.",
    };
  }
  if (pathname.startsWith("/jobs/debugger")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Run Debugger",
      description: "Triage failed, warning-heavy, or active runs before opening full run detail.",
    };
  }
  if (pathname.startsWith("/broker-orders")) {
    return {
      eyebrow: "Operate",
      title: "Execution & Risk",
      description: "Review broker risk state, kill switch, exposure, reconciliation, and broker-order audit details.",
    };
  }
  if (pathname.startsWith("/data-quality")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Data Quality",
      description: "Audit no-bars, no-news, stale coverage, and broker-reject ticker issues.",
    };
  }
  if (pathname.startsWith("/runs/")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Run Detail",
      description: "Follow the full execution path from cheap scan to context objects, signals, plans, and broker orders.",
    };
  }
  if (pathname.startsWith("/workers/")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Worker Logs",
      description: "Inspect live worker output and follow a running worker’s progress in real time.",
    };
  }
  if (pathname.startsWith("/tickers/")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Ticker Detail",
      description: "Inspect a ticker’s recent plans, outcomes, and supporting context.",
    };
  }
  if (pathname.startsWith("/context") || pathname.startsWith("/sentiment")) {
    return {
      eyebrow: "Evidence & diagnostics",
      title: "Context Review",
      description: "Review the shared macro and industry backdrop behind current plans and signals.",
    };
  }
  if (pathname.startsWith("/settings")) {
    return {
      eyebrow: "Configure",
      title: "Settings",
      description: "Configure providers, credentials, execution toggles, safety limits, and operational defaults.",
    };
  }
  if (pathname.startsWith("/docs")) {
    return {
      eyebrow: "Help",
      title: "Docs",
      description: "Read product, methodology, operator, and reference guidance without leaving the app.",
    };
  }
  return {
    eyebrow: "Trade proposer app",
    title: "Not found",
    description: "Navigate the recommendation workflow, supporting context, and system settings.",
  };
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
          <NavLink to="/" className="sidebar-brand" aria-label="Aurelio home">
            <BrandLogo markSize="lg" subtitle="Stoic clarity for modern markets" decorativeMark className="sidebar-brand-lockup" />
          </NavLink>

          <div
            className="sidebar-status-wrap"
            onMouseEnter={() => setWorkerPopoverHovered(true)}
            onMouseLeave={() => setWorkerPopoverHovered(false)}
          >
            <div className="sidebar-status-card">
              <div className="kicker">Current mode</div>
              <h2>Operating status</h2>
              <p>
                Watch workers and review plans before expanding risk.
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
            <Link to="/" className="mobile-header-brand" aria-label="Aurelio home">
              <BrandMark size="sm" decorative />
              <span className="mobile-header-brand-copy">Aurelio</span>
            </Link>
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
            {navSections.map((section) => {
              const sectionActive = isSectionActive(section, location.pathname);
              return (
                <details key={section.label} className="mobile-nav-group" open={sectionActive}>
                  <summary className="mobile-nav-group-title">{section.label}</summary>
                  <div className="mobile-nav-group-body">
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
                    {section.subsections ? section.subsections.map((subsection) => {
                      const subsectionActive = subsection.items.some((item) => isItemActive(item, location.pathname));
                      return (
                        <details key={subsection.label} className="mobile-nav-subgroup" open={subsectionActive}>
                          <summary className="mobile-nav-subgroup-title">{subsection.label}</summary>
                          <div className="mobile-nav-subgroup-body">
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
                        </details>
                      );
                    }) : null}
                  </div>
                </details>
              );
            })}
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

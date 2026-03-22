import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth";

const jobsSectionLinks = [
  { to: "/jobs", label: "Jobs overview", shortLabel: "Jobs", end: true },
  { to: "/jobs/watchlists", label: "Watchlists", shortLabel: "WL" },
  { to: "/jobs/history", label: "Recommendations", shortLabel: "Recs" },
  { to: "/jobs/debugger", label: "Debugger", shortLabel: "Debug" },
];

const THEME_KEY = "trade-proposer-theme";

type Theme = "dark" | "light";

type ResponsiveLabelProps = {
  full: string;
  short: string;
};

function ResponsiveLabel({ full, short }: ResponsiveLabelProps) {
  return (
    <>
      <span className="nav-link-label">{full}</span>
      <span className="nav-link-label-short">{short}</span>
    </>
  );
}

function readInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
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

  const jobsSectionActive = location.pathname === "/jobs" || location.pathname.startsWith("/jobs/");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <NavLink to="/" className="brand-mark">
            TP
          </NavLink>
          <div className="brand-text">
            <div className="brand-title">Trade Proposer App</div>
            <div className="brand-title-short">TP App</div>
            <div className="brand-subtitle">React frontend over the existing FastAPI API</div>
            <div className="brand-subtitle-short">React UI over FastAPI</div>
          </div>
        </div>
        <div className="topbar-actions">
          <button
            type="button"
            className="mobile-nav-toggle"
            aria-label={mobileNavOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((current) => !current)}
          >
            ☰
          </button>
          <nav className="main-nav" aria-label="Primary navigation">
            <NavLink to="/" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`} end>
              <ResponsiveLabel full="Dashboard" short="Dash" />
            </NavLink>
            <div className="nav-dropdown">
              <NavLink to="/jobs" className={`nav-link${jobsSectionActive ? " is-active" : ""}`}>
                <ResponsiveLabel full="Jobs" short="Jobs" />
                <span aria-hidden="true">▾</span>
              </NavLink>
              <div className="nav-dropdown-menu" aria-label="Jobs navigation">
                {jobsSectionLinks.map((link) => (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    className={({ isActive }) => `nav-dropdown-link${isActive ? " is-active" : ""}`}
                    end={link.end}
                  >
                    <ResponsiveLabel full={link.label} short={link.shortLabel} />
                  </NavLink>
                ))}
              </div>
            </div>
            <NavLink to="/sentiment" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
              <ResponsiveLabel full="Sentiment" short="Sent" />
            </NavLink>
            <NavLink to="/settings" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
              <ResponsiveLabel full="Settings" short="Set" />
            </NavLink>
            <NavLink to="/docs" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
              <ResponsiveLabel full="Docs" short="Docs" />
            </NavLink>
            <a href="/api/health" className="nav-link" target="_blank" rel="noreferrer">
              <ResponsiveLabel full="Health" short="Health" />
            </a>
          </nav>
          <button type="button" className="button-subtle" onClick={logout}>
            Log out
          </button>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            <span aria-hidden="true">◐</span>
            <span>{theme === "dark" ? "Dark" : "Light"}</span>
          </button>
        </div>
      </header>

      <div className={`mobile-nav-panel${mobileNavOpen ? " is-open" : ""}`} aria-hidden={!mobileNavOpen}>
        <nav aria-label="Mobile navigation">
          <NavLink
            to="/"
            className={({ isActive }) => `nav-link mobile-nav-link${isActive ? " is-active" : ""}`}
            end
            onClick={() => setMobileNavOpen(false)}
          >
            <ResponsiveLabel full="Dashboard" short="Dash" />
          </NavLink>
          <div className="mobile-nav-group">
            <div className="mobile-nav-group-title">Jobs</div>
            {jobsSectionLinks.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) => `nav-link mobile-nav-link${isActive ? " is-active" : ""}`}
                end={link.end}
                onClick={() => setMobileNavOpen(false)}
              >
                <ResponsiveLabel full={link.label} short={link.shortLabel} />
              </NavLink>
            ))}
          </div>
          <NavLink
            to="/sentiment"
            className={({ isActive }) => `nav-link mobile-nav-link${isActive ? " is-active" : ""}`}
            onClick={() => setMobileNavOpen(false)}
          >
            <ResponsiveLabel full="Sentiment" short="Sent" />
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-link mobile-nav-link${isActive ? " is-active" : ""}`}
            onClick={() => setMobileNavOpen(false)}
          >
            <ResponsiveLabel full="Settings" short="Set" />
          </NavLink>
          <NavLink
            to="/docs"
            className={({ isActive }) => `nav-link mobile-nav-link${isActive ? " is-active" : ""}`}
            onClick={() => setMobileNavOpen(false)}
          >
            <ResponsiveLabel full="Docs" short="Docs" />
          </NavLink>
          <a
            href="/api/health"
            className="nav-link mobile-nav-link"
            target="_blank"
            rel="noreferrer"
            onClick={() => setMobileNavOpen(false)}
          >
            <ResponsiveLabel full="Health" short="Health" />
          </a>
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
  );
}

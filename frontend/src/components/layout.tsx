import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

const THEME_KEY = "trade-proposer-theme";

type Theme = "dark" | "light";

function readInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_KEY);
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function AppLayout() {
  const [theme, setTheme] = useState<Theme>(() => readInitialTheme());
  const location = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const jobsSectionActive = location.pathname === "/jobs" || location.pathname.startsWith("/jobs/");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <NavLink to="/" className="brand-mark">
            TP
          </NavLink>
          <div>
            <div className="brand-title">Trade Proposer App</div>
            <div className="brand-subtitle">React frontend over the existing FastAPI API</div>
          </div>
        </div>
        <div className="topbar-actions">
          <nav className="main-nav" aria-label="Primary navigation">
            <NavLink to="/" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`} end>
              Dashboard
            </NavLink>
            <div className="nav-dropdown">
              <NavLink to="/jobs" className={`nav-link${jobsSectionActive ? " is-active" : ""}`}>
                <span>Jobs</span>
                <span aria-hidden="true">▾</span>
              </NavLink>
              <div className="nav-dropdown-menu" aria-label="Jobs navigation">
                <NavLink to="/jobs" className={({ isActive }) => `nav-dropdown-link${isActive ? " is-active" : ""}`} end>
                  Jobs overview
                </NavLink>
                <NavLink to="/jobs/watchlists" className={({ isActive }) => `nav-dropdown-link${isActive ? " is-active" : ""}`}>
                  Watchlists
                </NavLink>
                <NavLink to="/jobs/history" className={({ isActive }) => `nav-dropdown-link${isActive ? " is-active" : ""}`}>
                  Recommendations
                </NavLink>
                <NavLink to="/jobs/debugger" className={({ isActive }) => `nav-dropdown-link${isActive ? " is-active" : ""}`}>
                  Debugger
                </NavLink>
              </div>
            </div>
            <NavLink to="/settings" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
              Settings
            </NavLink>
            <NavLink to="/docs" className={({ isActive }) => `nav-link${isActive ? " is-active" : ""}`}>
              Docs
            </NavLink>
            <a href="/api/health" className="nav-link" target="_blank" rel="noreferrer">
              Health
            </a>
          </nav>
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
      <main className="page-shell">
        <Outlet />
      </main>
    </div>
  );
}

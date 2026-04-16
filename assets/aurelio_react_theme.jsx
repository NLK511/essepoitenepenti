import React from "react";
import { motion } from "framer-motion";
import {
  Bell,
  BookOpen,
  Brain,
  Briefcase,
  CandlestickChart,
  ChartColumnBig,
  Compass,
  Globe,
  LayoutGrid,
  LineChart,
  Newspaper,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Wallet,
} from "lucide-react";

/**
 * AURELIO REACT THEME KIT
 *
 * Single-file starter kit containing:
 * - brand tokens
 * - CSS variables
 * - logo components
 * - icon wrappers
 * - app shell primitives
 * - example dashboard screen
 *
 * Next step can be splitting this into:
 * /theme/tokens.ts
 * /theme/global.css
 * /components/brand/*
 * /components/icons/*
 * /app/dashboard/page.tsx
 */

export const aurelioTheme = {
  name: "Aurelio",
  philosophy: "Stoic clarity for modern markets",
  colors: {
    ink: "#071311",
    inkSoft: "#0B1A17",
    panel: "#10211D",
    panel2: "#132923",
    edge: "rgba(201, 168, 97, 0.16)",
    edgeStrong: "rgba(201, 168, 97, 0.36)",
    gold: "#C9A861",
    goldSoft: "#E7D2A0",
    sage: "#78927D",
    mist: "#A9BBB1",
    text: "#F4EFE2",
    textDim: "#B5BAAF",
    success: "#7FB089",
    warning: "#D1A85C",
    danger: "#C97B63",
    info: "#7D9FA6",
  },
  gradients: {
    hero: "linear-gradient(135deg, rgba(201,168,97,0.18), rgba(7,19,17,0) 50%)",
    border: "linear-gradient(135deg, rgba(231,210,160,0.45), rgba(201,168,97,0.08))",
    glow: "radial-gradient(circle at top, rgba(201,168,97,0.18), transparent 60%)",
  },
  radius: {
    sm: "12px",
    md: "18px",
    lg: "24px",
    xl: "32px",
    pill: "999px",
  },
  shadow: {
    soft: "0 10px 30px rgba(0,0,0,0.28)",
    gold: "0 0 0 1px rgba(201,168,97,0.14), 0 16px 40px rgba(0,0,0,0.32)",
  },
  fonts: {
    display: "ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif",
    body: "Inter, ui-sans-serif, system-ui, sans-serif",
    mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
  },
};

export function AurelioGlobalStyles() {
  return (
    <style>{`
      :root {
        --aur-ink: ${aurelioTheme.colors.ink};
        --aur-ink-soft: ${aurelioTheme.colors.inkSoft};
        --aur-panel: ${aurelioTheme.colors.panel};
        --aur-panel-2: ${aurelioTheme.colors.panel2};
        --aur-edge: ${aurelioTheme.colors.edge};
        --aur-edge-strong: ${aurelioTheme.colors.edgeStrong};
        --aur-gold: ${aurelioTheme.colors.gold};
        --aur-gold-soft: ${aurelioTheme.colors.goldSoft};
        --aur-sage: ${aurelioTheme.colors.sage};
        --aur-mist: ${aurelioTheme.colors.mist};
        --aur-text: ${aurelioTheme.colors.text};
        --aur-text-dim: ${aurelioTheme.colors.textDim};
        --aur-success: ${aurelioTheme.colors.success};
        --aur-warning: ${aurelioTheme.colors.warning};
        --aur-danger: ${aurelioTheme.colors.danger};
        --aur-info: ${aurelioTheme.colors.info};

        --aur-radius-sm: ${aurelioTheme.radius.sm};
        --aur-radius-md: ${aurelioTheme.radius.md};
        --aur-radius-lg: ${aurelioTheme.radius.lg};
        --aur-radius-xl: ${aurelioTheme.radius.xl};
        --aur-radius-pill: ${aurelioTheme.radius.pill};

        --aur-shadow-soft: ${aurelioTheme.shadow.soft};
        --aur-shadow-gold: ${aurelioTheme.shadow.gold};

        --aur-hero: ${aurelioTheme.gradients.hero};
        --aur-border: ${aurelioTheme.gradients.border};
        --aur-glow: ${aurelioTheme.gradients.glow};
      }

      html, body, #root {
        background:
          radial-gradient(circle at top, rgba(201,168,97,0.10), transparent 32%),
          linear-gradient(180deg, #0A1715 0%, #071311 100%);
        color: var(--aur-text);
        font-family: ${aurelioTheme.fonts.body};
      }

      * { box-sizing: border-box; }

      .aur-card {
        background: linear-gradient(180deg, rgba(19,41,35,0.95), rgba(11,26,23,0.96));
        border: 1px solid var(--aur-edge);
        box-shadow: var(--aur-shadow-gold);
        border-radius: var(--aur-radius-lg);
      }

      .aur-hairline {
        border: 1px solid var(--aur-edge);
      }

      .aur-title {
        font-family: ${aurelioTheme.fonts.display};
        letter-spacing: 0.04em;
      }

      .aur-gold-text {
        color: var(--aur-gold-soft);
      }

      .aur-muted {
        color: var(--aur-text-dim);
      }

      .aur-button-primary {
        background: linear-gradient(180deg, rgba(201,168,97,0.18), rgba(201,168,97,0.10));
        border: 1px solid rgba(201,168,97,0.38);
        color: var(--aur-gold-soft);
        border-radius: var(--aur-radius-pill);
        transition: all .2s ease;
      }

      .aur-button-primary:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 24px rgba(0,0,0,0.24);
      }

      .aur-button-secondary {
        background: rgba(255,255,255,0.02);
        border: 1px solid var(--aur-edge);
        color: var(--aur-text);
        border-radius: var(--aur-radius-pill);
      }

      .aur-input {
        background: rgba(255,255,255,0.02);
        border: 1px solid var(--aur-edge);
        border-radius: var(--aur-radius-pill);
        color: var(--aur-text);
      }

      .aur-badge {
        border-radius: var(--aur-radius-pill);
        border: 1px solid var(--aur-edge);
        background: rgba(201,168,97,0.08);
        color: var(--aur-gold-soft);
      }

      .aur-grid-overlay {
        background-image:
          linear-gradient(rgba(169,187,177,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(169,187,177,0.03) 1px, transparent 1px);
        background-size: 28px 28px;
      }
    `}</style>
  );
}

export function AurelioMark({ className = "h-10 w-10" }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      fill="none"
      aria-label="Aurelio mark"
    >
      <path
        d="M12 52L31 10L52 52"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M20 52H43"
        stroke="currentColor"
        strokeWidth="5"
        strokeLinecap="round"
      />
      <path d="M32 35V48" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <path d="M40 29V44" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <path d="M24 39V47" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <circle cx="24" cy="39" r="1.5" fill="currentColor" />
      <circle cx="32" cy="35" r="1.5" fill="currentColor" />
      <circle cx="40" cy="29" r="1.5" fill="currentColor" />
    </svg>
  );
}

export function AurelioWordmark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`flex items-center ${compact ? "gap-2" : "gap-3"}`}>
      <div className="text-[var(--aur-gold)]">
        <AurelioMark className={compact ? "h-7 w-7" : "h-9 w-9"} />
      </div>
      <div>
        <div
          className={`aur-title aur-gold-text ${compact ? "text-lg" : "text-2xl"} leading-none tracking-[0.22em]`}
        >
          AURELIO
        </div>
        {!compact && (
          <div className="mt-1 text-[10px] uppercase tracking-[0.34em] text-[var(--aur-text-dim)]">
            Wisdom for swing trading
          </div>
        )}
      </div>
    </div>
  );
}

function AurelioIconFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-[var(--aur-edge)] bg-[rgba(201,168,97,0.06)] text-[var(--aur-gold-soft)] shadow-[var(--aur-shadow-soft)]">
      {children}
    </div>
  );
}

export const AurelioIcons = {
  dashboard: () => <AurelioIconFrame><LayoutGrid className="h-5 w-5" /></AurelioIconFrame>,
  market: () => <AurelioIconFrame><LineChart className="h-5 w-5" /></AurelioIconFrame>,
  candlestick: () => <AurelioIconFrame><CandlestickChart className="h-5 w-5" /></AurelioIconFrame>,
  signals: () => <AurelioIconFrame><TrendingUp className="h-5 w-5" /></AurelioIconFrame>,
  news: () => <AurelioIconFrame><Newspaper className="h-5 w-5" /></AurelioIconFrame>,
  fundamentals: () => <AurelioIconFrame><BookOpen className="h-5 w-5" /></AurelioIconFrame>,
  llm: () => <AurelioIconFrame><Brain className="h-5 w-5" /></AurelioIconFrame>,
  wisdom: () => <AurelioIconFrame><Compass className="h-5 w-5" /></AurelioIconFrame>,
  portfolio: () => <AurelioIconFrame><Wallet className="h-5 w-5" /></AurelioIconFrame>,
  positions: () => <AurelioIconFrame><Briefcase className="h-5 w-5" /></AurelioIconFrame>,
  watchlist: () => <AurelioIconFrame><ChartColumnBig className="h-5 w-5" /></AurelioIconFrame>,
  search: () => <AurelioIconFrame><Search className="h-5 w-5" /></AurelioIconFrame>,
  globe: () => <AurelioIconFrame><Globe className="h-5 w-5" /></AurelioIconFrame>,
  alerts: () => <AurelioIconFrame><Bell className="h-5 w-5" /></AurelioIconFrame>,
  trust: () => <AurelioIconFrame><ShieldCheck className="h-5 w-5" /></AurelioIconFrame>,
  settings: () => <AurelioIconFrame><Settings className="h-5 w-5" /></AurelioIconFrame>,
  spark: () => <AurelioIconFrame><Sparkles className="h-5 w-5" /></AurelioIconFrame>,
};

export function AurelioSidebar() {
  const items = [
    ["Dashboard", AurelioIcons.dashboard],
    ["Markets", AurelioIcons.market],
    ["Signals", AurelioIcons.signals],
    ["News", AurelioIcons.news],
    ["Fundamentals", AurelioIcons.fundamentals],
    ["Wisdom Engine", AurelioIcons.llm],
    ["Portfolio", AurelioIcons.portfolio],
    ["Settings", AurelioIcons.settings],
  ] as const;

  return (
    <aside className="aur-card aur-grid-overlay flex h-full w-full flex-col gap-6 p-4">
      <AurelioWordmark compact />
      <nav className="flex flex-col gap-2">
        {items.map(([label, Icon], idx) => (
          <button
            key={label}
            className={`flex items-center gap-3 rounded-2xl px-3 py-2 text-left transition ${
              idx === 0
                ? "bg-[rgba(201,168,97,0.10)] text-[var(--aur-gold-soft)]"
                : "text-[var(--aur-text-dim)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--aur-text)]"
            }`}
          >
            <Icon />
            <span className="text-sm font-medium">{label}</span>
          </button>
        ))}
      </nav>
      <div className="mt-auto rounded-3xl border border-[var(--aur-edge)] bg-[rgba(201,168,97,0.06)] p-4">
        <div className="text-xs uppercase tracking-[0.25em] text-[var(--aur-sage)]">Core principle</div>
        <div className="aur-title mt-2 text-lg text-[var(--aur-gold-soft)]">Disciplined conviction</div>
        <p className="mt-2 text-sm text-[var(--aur-text-dim)]">
          Blend price action, news context, fundamentals, and reasoning into one calm decision surface.
        </p>
      </div>
    </aside>
  );
}

export function AurelioTopbar() {
  return (
    <div className="aur-card flex items-center justify-between gap-4 p-3">
      <div className="flex items-center gap-3">
        <div className="aur-badge px-3 py-1 text-xs uppercase tracking-[0.25em]">Swing mode</div>
        <div className="text-sm text-[var(--aur-text-dim)]">Daily timeframe · US equities</div>
      </div>
      <div className="flex items-center gap-2">
        <input className="aur-input px-4 py-2 text-sm outline-none" placeholder="Search ticker, sector, theme" />
        <button className="aur-button-secondary px-4 py-2 text-sm">Watchlist</button>
        <button className="aur-button-primary px-4 py-2 text-sm">New analysis</button>
      </div>
    </div>
  );
}

export function AurelioStatCard({
  label,
  value,
  delta,
  positive = true,
}: {
  label: string;
  value: string;
  delta: string;
  positive?: boolean;
}) {
  return (
    <div className="aur-card p-5">
      <div className="text-xs uppercase tracking-[0.24em] text-[var(--aur-sage)]">{label}</div>
      <div className="mt-3 aur-title text-3xl text-[var(--aur-gold-soft)]">{value}</div>
      <div className={`mt-2 text-sm ${positive ? "text-[var(--aur-success)]" : "text-[var(--aur-danger)]"}`}>
        {delta}
      </div>
    </div>
  );
}

export function AurelioInsightCard() {
  return (
    <div className="aur-card p-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.24em] text-[var(--aur-sage)]">Wisdom engine</div>
          <div className="aur-title mt-2 text-2xl text-[var(--aur-gold-soft)]">AAPL swing thesis</div>
        </div>
        <div className="aur-badge px-3 py-1 text-xs uppercase tracking-[0.2em]">High quality</div>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-4">
        {[
          ["Technical", "Trend intact"],
          ["News", "Neutral to positive"],
          ["Fundamentals", "Resilient margins"],
          ["LLM synthesis", "Wait for pullback"],
        ].map(([k, v]) => (
          <div key={k} className="rounded-2xl border border-[var(--aur-edge)] bg-[rgba(255,255,255,0.02)] p-4">
            <div className="text-xs uppercase tracking-[0.2em] text-[var(--aur-sage)]">{k}</div>
            <div className="mt-2 text-sm text-[var(--aur-text)]">{v}</div>
          </div>
        ))}
      </div>

      <p className="mt-5 max-w-3xl text-sm leading-7 text-[var(--aur-text-dim)]">
        Aurelio favors patient entries where structure, context, and business quality align. The interface should always feel ceremonial,
        restrained, and precise—not noisy, not gamer-like, not crypto-neon.
      </p>
    </div>
  );
}

export function AurelioDesignRules() {
  const rules = [
    "Prefer deep green-black surfaces over pure black.",
    "Use gold only as emphasis, never as a full flood color.",
    "Every interactive element should feel calm, exact, and premium.",
    "Charts and data should stay visually secondary to decision quality.",
    "Icons should be outlined, balanced, and readable at 16px.",
    "Spacing should feel editorial, not cramped.",
  ];

  return (
    <div className="aur-card p-6">
      <div className="text-xs uppercase tracking-[0.24em] text-[var(--aur-sage)]">Visual rules</div>
      <div className="aur-title mt-2 text-2xl text-[var(--aur-gold-soft)]">Brand system</div>
      <div className="mt-4 space-y-3">
        {rules.map((rule) => (
          <div key={rule} className="flex items-start gap-3 rounded-2xl border border-[var(--aur-edge)] bg-[rgba(255,255,255,0.02)] p-4">
            <div className="mt-1 h-2 w-2 rounded-full bg-[var(--aur-gold)]" />
            <div className="text-sm text-[var(--aur-text-dim)]">{rule}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AurelioThemePreview() {
  return (
    <div className="min-h-screen bg-[var(--aur-ink)] text-[var(--aur-text)]">
      <AurelioGlobalStyles />

      <div className="grid min-h-screen grid-cols-1 gap-4 p-4 lg:grid-cols-[280px_1fr]">
        <motion.div initial={{ opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.35 }}>
          <AurelioSidebar />
        </motion.div>

        <main className="flex flex-col gap-4">
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
            <AurelioTopbar />
          </motion.div>

          <div className="grid gap-4 md:grid-cols-3">
            <AurelioStatCard label="Hit rate" value="63%" delta="+4.2% this quarter" positive />
            <AurelioStatCard label="Avg reward/risk" value="2.4" delta="Disciplined entries preserved" positive />
            <AurelioStatCard label="Risk state" value="Moderate" delta="Macro event density elevated" positive={false} />
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.4fr_0.9fr]">
            <AurelioInsightCard />
            <AurelioDesignRules />
          </div>

          <div className="aur-card p-6">
            <div className="text-xs uppercase tracking-[0.24em] text-[var(--aur-sage)]">Icon set</div>
            <div className="aur-title mt-2 text-2xl text-[var(--aur-gold-soft)]">Core app icons</div>
            <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              {Object.entries(AurelioIcons).map(([key, Icon]) => (
                <div key={key} className="rounded-3xl border border-[var(--aur-edge)] bg-[rgba(255,255,255,0.02)] p-4">
                  <Icon />
                  <div className="mt-3 text-xs uppercase tracking-[0.18em] text-[var(--aur-text-dim)]">{key}</div>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

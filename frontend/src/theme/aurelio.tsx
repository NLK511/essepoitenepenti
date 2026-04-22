import type { CSSProperties } from "react";

export const aurelioTheme = {
  name: "Aurelio",
  philosophy: "Stoic clarity for modern markets",
  colors: {
    ink: "#0A1210",
    inkSoft: "#101A17",
    panel: "#14201C",
    panel2: "#182722",
    edge: "rgba(214, 186, 120, 0.18)",
    edgeStrong: "rgba(214, 186, 120, 0.34)",
    gold: "#D6BA78",
    goldSoft: "#F3E7C3",
    sage: "#93A596",
    mist: "#C9D3CC",
    text: "#F7F4EA",
    textDim: "#D2D8D1",
    textSoft: "#B4BDB5",
    success: "#9BC89B",
    warning: "#E2BB6B",
    danger: "#D68F7C",
    info: "#97B8C0",
  },
  gradients: {
    hero: "linear-gradient(135deg, rgba(214,186,120,0.12), rgba(10,18,16,0) 52%)",
    border: "linear-gradient(135deg, rgba(243,231,195,0.34), rgba(214,186,120,0.08))",
    glow: "radial-gradient(circle at top, rgba(214,186,120,0.10), transparent 58%)",
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
    gold: "0 0 0 1px rgba(214,186,120,0.14), 0 16px 40px rgba(0,0,0,0.32)",
  },
  fonts: {
    display: "ui-serif, Georgia, Cambria, 'Times New Roman', Times, serif",
    body: "Inter, ui-sans-serif, system-ui, sans-serif",
    mono: "ui-monospace, SFMono-Regular, Menlo, monospace",
  },
} as const;

export function AurelioMark(props: { className?: string; style?: CSSProperties }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={props.className}
      style={props.style}
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
      <path d="M20 52H43" stroke="currentColor" strokeWidth="5" strokeLinecap="round" />
      <path d="M32 35V48" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <path d="M40 29V44" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <path d="M24 39V47" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      <circle cx="24" cy="39" r="1.5" fill="currentColor" />
      <circle cx="32" cy="35" r="1.5" fill="currentColor" />
      <circle cx="40" cy="29" r="1.5" fill="currentColor" />
    </svg>
  );
}

export function AurelioWordmark(props: { compact?: boolean; subtitle?: string }) {
  return (
    <div className={`aurelio-wordmark${props.compact ? " is-compact" : ""}`}>
      <div className="aurelio-wordmark-mark" aria-hidden="true">
        <AurelioMark className={props.compact ? "aurelio-mark aurelio-mark-compact" : "aurelio-mark"} />
      </div>
      <div className="aurelio-wordmark-copy">
        <div className="aurelio-wordmark-title">AURELIO</div>
        {!props.compact ? <div className="aurelio-wordmark-subtitle">{props.subtitle ?? "Wisdom for swing trading"}</div> : null}
      </div>
    </div>
  );
}

import type { PropsWithChildren, ReactNode } from "react";
import { Link } from "react-router-dom";

export function PageHeader(props: {
  kicker: string;
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <section className="page-header">
      <div>
        <div className="kicker">{props.kicker}</div>
        <h1 className="page-title">{props.title}</h1>
        <p className="page-subtitle">{props.subtitle}</p>
      </div>
      {props.actions ? <div className="cluster">{props.actions}</div> : null}
    </section>
  );
}

export function Card(props: PropsWithChildren<{ className?: string }>) {
  return <section className={`panel ${props.className ?? ""}`.trim()}>{props.children}</section>;
}

export function Badge(props: PropsWithChildren<{ tone?: "ok" | "warning" | "danger" | "neutral" | "info"; title?: string }>) {
  return <span className={`badge badge-${props.tone ?? "neutral"}`} title={props.title}>{props.children}</span>;
}

export function EmptyState(props: { message: string }) {
  return <div className="empty-state">{props.message}</div>;
}

export function LoadingState(props: { message?: string }) {
  return (
    <div className="empty-state loading-state">
      <div className="loading-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div>{props.message ?? "Loading…"}</div>
    </div>
  );
}

export function ErrorState(props: { message: string }) {
  return <div className="alert alert-danger">{props.message}</div>;
}

export function SectionTitle(props: { kicker?: string; title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="section-header">
      <div>
        {props.kicker ? <div className="kicker">{props.kicker}</div> : null}
        <h2 className="section-title">{props.title}</h2>
        {props.subtitle ? <p className="helper-text">{props.subtitle}</p> : null}
      </div>
      {props.actions ? <div className="cluster">{props.actions}</div> : null}
    </div>
  );
}

export function StatCard(props: { label: string; value: ReactNode; helper?: string; className?: string }) {
  return (
    <Card className={props.className}>
      <div className="metric-label">{props.label}</div>
      <div className="metric-value">{props.value}</div>
      {props.helper ? <div className="helper-text">{props.helper}</div> : null}
    </Card>
  );
}

export function SegmentedTabs<T extends string>(props: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <>
      <div className="desktop-only">
        <div className="segmented-tabs" role="tablist" aria-label="Section tabs">
          {props.options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`segmented-tab${props.value === option.value ? " is-active" : ""}`}
              onClick={() => props.onChange(option.value)}
              role="tab"
              aria-selected={props.value === option.value}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <div className="mobile-only segmented-tabs-mobile">
        <label className="form-field">
          <span>Section</span>
          <select value={props.value} onChange={(event) => props.onChange(event.target.value as T)}>
            {props.options.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>
    </>
  );
}

export function HelpHint(props: { tooltip: string; to: string; ariaLabel?: string }) {
  return (
    <Link
      to={props.to}
      className="help-hint"
      aria-label={props.ariaLabel ?? `${props.tooltip}. Open related documentation.`}
    >
      <span className="help-hint-icon" aria-hidden="true">?</span>
      <span className="help-hint-tooltip" role="tooltip">{props.tooltip}</span>
    </Link>
  );
}

import type { PropsWithChildren, ReactNode } from "react";

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

export function Badge(props: PropsWithChildren<{ tone?: "ok" | "warning" | "danger" | "neutral" | "info" }>) {
  return <span className={`badge badge-${props.tone ?? "neutral"}`}>{props.children}</span>;
}

export function EmptyState(props: { message: string }) {
  return <div className="empty-state">{props.message}</div>;
}

export function LoadingState(props: { message?: string }) {
  return <div className="empty-state">{props.message ?? "Loading…"}</div>;
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

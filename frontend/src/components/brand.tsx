import AurelioLogoAnimation from "./aurelio-logo-animation";

type BrandSize = "xs" | "sm" | "md" | "lg" | "xl";

export function BrandMark(props: {
  size?: BrandSize;
  className?: string;
  decorative?: boolean;
  animate?: boolean;
}) {
  return (
    <AurelioLogoAnimation
      showWordmark={false}
      size={props.size ?? "md"}
      decorative={props.decorative ?? true}
      animate={props.animate ?? false}
      className={["brand-mark-animation", props.className ?? ""].filter(Boolean).join(" ")}
    />
  );
}

export function BrandLogo(props: {
  markSize?: BrandSize;
  className?: string;
  compact?: boolean;
  decorativeMark?: boolean;
  subtitle?: string;
  wordmark?: boolean;
  animate?: boolean;
}) {
  if (props.wordmark) {
    return (
      <div className={["brand-logo-stack", props.className ?? ""].filter(Boolean).join(" ")}>
        <AurelioLogoAnimation
          showWordmark
          size={props.markSize ?? "xl"}
          decorative={props.decorativeMark ?? true}
          animate={props.animate ?? true}
          className="brand-logo-wordmark"
        />
        {props.subtitle ? <div className="brand-logo-stack-subtitle">{props.subtitle}</div> : null}
      </div>
    );
  }

  return (
    <div className={["brand-lockup", props.compact ? "is-compact" : "", props.className ?? ""].filter(Boolean).join(" ")}>
      <div className="brand-lockup-mark" aria-hidden={props.decorativeMark ? true : undefined}>
        <BrandMark size={props.markSize ?? (props.compact ? "sm" : "lg")} decorative={props.decorativeMark ?? true} animate={props.animate ?? false} />
      </div>
      <div className="brand-lockup-copy">
        <div className="brand-lockup-title">Aurelio</div>
        {!props.compact ? <div className="brand-lockup-subtitle">{props.subtitle ?? "Stoic clarity for modern markets"}</div> : null}
      </div>
    </div>
  );
}

export function BrandLoader(props: {
  className?: string;
  compact?: boolean;
  message?: string;
  prominence?: "inline" | "hero";
}) {
  const prominence = props.prominence ?? "inline";

  return (
    <div
      className={[
        "brand-loader",
        props.compact ? "is-compact" : "",
        prominence === "hero" ? "is-hero" : "is-inline",
        props.className ?? "",
      ].filter(Boolean).join(" ")}
      role="status"
      aria-live="polite"
    >
      <AurelioLogoAnimation
        showWordmark={false}
        size={prominence === "hero" ? "lg" : props.compact ? "sm" : "md"}
        decorative
        animate
        className="brand-loader-animation"
      />
      {props.message ? <div className="brand-loader-message">{props.message}</div> : <span className="sr-only">Loading</span>}
    </div>
  );
}

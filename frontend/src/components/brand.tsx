import AurelioLogoAnimation from "./aurelio-logo-animation";

type BrandSize = "xs" | "sm" | "md" | "lg" | "xl";

const pixelSize: Record<BrandSize, number> = {
  xs: 18,
  sm: 24,
  md: 32,
  lg: 48,
  xl: 72,
};

function StaticBrandMark(props: { size: number; className?: string; decorative?: boolean }) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={props.size}
      height={props.size}
      className={["brand-mark-image", props.className ?? ""].filter(Boolean).join(" ")}
      fill="none"
      aria-hidden={props.decorative ? true : undefined}
      aria-label={props.decorative ? undefined : "Aurelio mark"}
      role={props.decorative ? undefined : "img"}
    >
      <path d="M12 52L31 10L52 52" stroke="#D6BA78" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M20 52H43" stroke="#D6BA78" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M24 39V48" stroke="#F3E7C3" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M32 35V48" stroke="#F3E7C3" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M40 29V44" stroke="#F3E7C3" strokeWidth="3.5" strokeLinecap="round" />
    </svg>
  );
}

export function BrandMark(props: {
  size?: BrandSize;
  className?: string;
  decorative?: boolean;
  animate?: boolean;
}) {
  const size = props.size ?? "md";

  if (!(props.animate ?? false)) {
    return <StaticBrandMark size={pixelSize[size]} className={props.className} decorative={props.decorative ?? true} />;
  }

  return (
    <AurelioLogoAnimation
      showWordmark={false}
      size={size}
      decorative={props.decorative ?? true}
      animate
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

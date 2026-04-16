import { useId } from "react";

type AurelioLogoAnimationProps = {
  className?: string;
  compact?: boolean;
  message?: string;
};

export function AurelioLogoAnimation(props: AurelioLogoAnimationProps) {
  const glowId = useId();
  return (
    <div className={["aurelio-loader", props.compact ? "is-compact" : "", props.className ?? ""].filter(Boolean).join(" ")}>
      <svg
        viewBox="0 0 320 320"
        className="aurelio-loader-svg"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="Aurelio animated logo"
        role="img"
      >
        <defs>
          <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path
          className="aurelio-loader-stroke aurelio-loader-draw-a"
          d="M74 235 L142 78 L208 206 M91 234 H132"
          strokeWidth="10"
        />

        <g className="aurelio-loader-candle aurelio-loader-candle-1 aurelio-loader-fill">
          <rect x="150" y="170" width="12" height="34" rx="2" />
          <rect x="155" y="160" width="2" height="10" rx="1" />
          <rect x="155" y="204" width="2" height="10" rx="1" />
        </g>

        <g className="aurelio-loader-candle aurelio-loader-candle-2 aurelio-loader-fill">
          <rect x="176" y="150" width="12" height="42" rx="2" />
          <rect x="181" y="138" width="2" height="12" rx="1" />
          <rect x="181" y="192" width="2" height="12" rx="1" />
        </g>

        <g className="aurelio-loader-candle aurelio-loader-candle-3 aurelio-loader-fill">
          <rect x="202" y="130" width="12" height="52" rx="2" />
          <rect x="207" y="116" width="2" height="14" rx="1" />
          <rect x="207" y="182" width="2" height="12" rx="1" />
        </g>

        <path
          className="aurelio-loader-stroke aurelio-loader-laurel-path"
          d="M178 232 C198 230, 220 221, 240 198"
          strokeWidth="5"
        />

        <g className="aurelio-loader-fill">
          <ellipse className="aurelio-loader-leaf aurelio-loader-leaf-1" cx="191" cy="225" rx="7" ry="3.4" transform="rotate(-25 191 225)" />
          <ellipse className="aurelio-loader-leaf aurelio-loader-leaf-2" cx="205" cy="219" rx="7.5" ry="3.6" transform="rotate(-28 205 219)" />
          <ellipse className="aurelio-loader-leaf aurelio-loader-leaf-3" cx="218" cy="210" rx="8" ry="3.8" transform="rotate(-32 218 210)" />
          <ellipse className="aurelio-loader-leaf aurelio-loader-leaf-4" cx="229" cy="198" rx="7.5" ry="3.5" transform="rotate(-40 229 198)" />
          <ellipse className="aurelio-loader-leaf aurelio-loader-leaf-5" cx="239" cy="185" rx="7" ry="3.3" transform="rotate(-48 239 185)" />
        </g>

        <circle
          className="aurelio-loader-fill aurelio-loader-tip-pulse"
          cx="208"
          cy="206"
          r="4"
          filter={`url(#${glowId})`}
        />
      </svg>
      {props.message ? <div className="aurelio-loader-message">{props.message}</div> : null}
    </div>
  );
}

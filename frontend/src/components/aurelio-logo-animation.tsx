import { useId } from "react";

type AurelioLogoAnimationProps = {
  showWordmark?: boolean;
  className?: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  decorative?: boolean;
  animate?: boolean;
};

export default function AurelioLogoAnimation({
  showWordmark = true,
  className,
  size = "md",
  decorative = true,
  animate = true,
}: AurelioLogoAnimationProps) {
  const id = useId().replace(/:/g, "");
  const goldGradientId = `goldGradient-${id}`;
  const greenFadeId = `greenFade-${id}`;
  const softShadowId = `softShadow-${id}`;
  const goldGlowId = `goldGlow-${id}`;
  const viewBox = showWordmark ? "0 0 900 620" : "250 40 420 360";

  return (
    <div className={["aurelio-logo-animation", `size-${size}`, showWordmark ? "has-wordmark" : "icon-only", !animate ? "is-static" : "", className ?? ""].filter(Boolean).join(" ")}>
      <svg
        viewBox={viewBox}
        className="aurelio-logo-animation-svg"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label={decorative ? undefined : "Aurelio animated logo"}
        aria-hidden={decorative ? true : undefined}
        role={decorative ? undefined : "img"}
      >
        <defs>
          <linearGradient id={goldGradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#f7df9c" />
            <stop offset="45%" stopColor="#d8b56a" />
            <stop offset="100%" stopColor="#9f7727" />
          </linearGradient>

          <linearGradient id={greenFadeId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#0d1f1a" />
            <stop offset="100%" stopColor="#071411" />
          </linearGradient>

          <filter id={softShadowId} x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="8" stdDeviation="10" floodColor="#000000" floodOpacity="0.32" />
          </filter>

          <filter id={goldGlowId} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <style>{`
          .gold-stroke {
            stroke: url(#${goldGradientId});
            stroke-linecap: round;
            stroke-linejoin: round;
          }

          .gold-fill {
            fill: url(#${goldGradientId});
          }

          .panel {
            opacity: 0;
            animation: fadePanel 0.6s ease-out forwards;
          }

          .icon-wrap {
            opacity: 0;
            transform-origin: center;
            animation: riseIn 0.8s cubic-bezier(0.22, 1, 0.36, 1) forwards;
            animation-delay: 0.1s;
          }

          .draw-a {
            stroke-dasharray: 760;
            stroke-dashoffset: 760;
            animation: drawA 1s cubic-bezier(0.22, 1, 0.36, 1) forwards;
            animation-delay: 0.15s;
          }

          .candle {
            opacity: 0;
            transform-box: fill-box;
            transform-origin: center bottom;
            animation: candleIn 0.42s ease-out forwards;
          }

          .candle-1 { animation-delay: 0.9s; }
          .candle-2 { animation-delay: 1.08s; }
          .candle-3 { animation-delay: 1.26s; }

          .laurel-stem {
            stroke-dasharray: 220;
            stroke-dashoffset: 220;
            animation: laurelDraw 0.72s ease-in-out forwards;
            animation-delay: 1.28s;
          }

          .leaf {
            opacity: 0;
            transform-box: fill-box;
            transform-origin: center;
            animation: leafIn 0.28s ease-out forwards;
          }

          .leaf-1 { animation-delay: 1.42s; }
          .leaf-2 { animation-delay: 1.50s; }
          .leaf-3 { animation-delay: 1.58s; }
          .leaf-4 { animation-delay: 1.66s; }
          .leaf-5 { animation-delay: 1.74s; }

          .spark {
            opacity: 0;
            animation: sparkIn 0.6s ease-out forwards, pulse 2.2s ease-in-out infinite;
            animation-delay: 1.9s, 2.4s;
          }

          .ring {
            opacity: 0;
            stroke-dasharray: 740;
            stroke-dashoffset: 740;
            animation: ringIn 0.9s ease-out forwards;
            animation-delay: 0.35s;
          }

          .wordmark,
          .submark {
            opacity: 0;
            animation: fadeUp 0.7s ease-out forwards;
          }

          .wordmark { animation-delay: 1.05s; }
          .submark { animation-delay: 1.28s; }

          @keyframes fadePanel {
            from { opacity: 0; }
            to { opacity: 1; }
          }

          @keyframes riseIn {
            from {
              opacity: 0;
              transform: translateY(8px) scale(0.985);
            }
            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }

          @keyframes drawA {
            to { stroke-dashoffset: 0; }
          }

          @keyframes candleIn {
            from {
              opacity: 0;
              transform: translateY(10px) scale(0.92);
            }
            to {
              opacity: 1;
              transform: translateY(0) scale(1);
            }
          }

          @keyframes laurelDraw {
            to { stroke-dashoffset: 0; }
          }

          @keyframes leafIn {
            from {
              opacity: 0;
              transform: scale(0.76) rotate(-8deg);
            }
            to {
              opacity: 1;
              transform: scale(1) rotate(0deg);
            }
          }

          @keyframes sparkIn {
            from {
              opacity: 0;
              transform: scale(0.6);
            }
            to {
              opacity: 0.95;
              transform: scale(1);
            }
          }

          @keyframes pulse {
            0%, 100% { opacity: 0.45; }
            50% { opacity: 0.95; }
          }

          @keyframes ringIn {
            from {
              opacity: 0;
              stroke-dashoffset: 740;
            }
            to {
              opacity: 0.6;
              stroke-dashoffset: 0;
            }
          }

          @keyframes fadeUp {
            from {
              opacity: 0;
              transform: translateY(10px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }

          @media (prefers-reduced-motion: reduce) {
            .panel,
            .icon-wrap,
            .draw-a,
            .candle,
            .laurel-stem,
            .leaf,
            .spark,
            .ring,
            .wordmark,
            .submark {
              animation: none !important;
              opacity: 1 !important;
              stroke-dashoffset: 0 !important;
              transform: none !important;
            }
          }
        `}</style>

        {showWordmark ? <rect className="panel" x="0" y="0" width="900" height="620" rx="36" fill={`url(#${greenFadeId})`} /> : null}

        <g filter={`url(#${softShadowId})`}>
          <g className="icon-wrap">
            <circle className="gold-stroke ring" cx="450" cy="225" r="153" strokeWidth="3.5" opacity="0.55" />

            <path className="gold-stroke draw-a" d="M313 356 L430 100 L552 286 M344 356 H414" strokeWidth="14" />

            <g className="candle candle-1 gold-fill">
              <rect x="440" y="242" width="19" height="55" rx="3" />
              <rect x="448.5" y="225" width="2.5" height="17" rx="1.25" />
              <rect x="448.5" y="297" width="2.5" height="17" rx="1.25" />
            </g>

            <g className="candle candle-2 gold-fill">
              <rect x="480" y="208" width="19" height="68" rx="3" />
              <rect x="488.5" y="190" width="2.5" height="18" rx="1.25" />
              <rect x="488.5" y="276" width="2.5" height="18" rx="1.25" />
            </g>

            <g className="candle candle-3 gold-fill">
              <rect x="520" y="174" width="19" height="82" rx="3" />
              <rect x="528.5" y="152" width="2.5" height="22" rx="1.25" />
              <rect x="528.5" y="256" width="2.5" height="18" rx="1.25" />
            </g>

            <path className="gold-stroke laurel-stem" d="M486 352 C519 349, 560 334, 607 283" strokeWidth="7" />

            <g className="gold-fill">
              <ellipse className="leaf leaf-1" cx="515" cy="341" rx="14" ry="6.3" transform="rotate(-18 515 341)" />
              <ellipse className="leaf leaf-2" cx="539" cy="332" rx="14.5" ry="6.5" transform="rotate(-22 539 332)" />
              <ellipse className="leaf leaf-3" cx="562" cy="316" rx="15.5" ry="6.9" transform="rotate(-29 562 316)" />
              <ellipse className="leaf leaf-4" cx="584" cy="296" rx="14.5" ry="6.3" transform="rotate(-38 584 296)" />
              <ellipse className="leaf leaf-5" cx="603" cy="272" rx="13.5" ry="5.9" transform="rotate(-46 603 272)" />
            </g>

            <circle className="spark gold-fill" cx="550" cy="286" r="6" filter={`url(#${goldGlowId})`} />
          </g>
        </g>

        {showWordmark ? (
          <>
            <text
              x="450"
              y="495"
              textAnchor="middle"
              className="wordmark"
              fill={`url(#${goldGradientId})`}
              fontSize="102"
              letterSpacing="10"
              fontFamily="'Cormorant Garamond', 'Trajan Pro', 'Times New Roman', serif"
            >
              AURELIO
            </text>
            <text
              x="450"
              y="552"
              textAnchor="middle"
              className="submark"
              fill="#5d8d7c"
              fontSize="28"
              letterSpacing="8"
              fontFamily="Inter, ui-sans-serif, system-ui, sans-serif"
            >
              WISE • INFORMED • DISCIPLINED
            </text>
          </>
        ) : null}
      </svg>
    </div>
  );
}

export { AurelioLogoAnimation };

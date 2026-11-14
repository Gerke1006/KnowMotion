import { useId } from "react";

export function BrandMark({ className = "", animated = false }: { className?: string; animated?: boolean }) {
  const gradient = useId();
  const clip = useId();
  return (
    <svg
      className={`brand-mark ${animated ? "is-animated" : ""} ${className}`}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <clipPath id={clip}>
          <rect x="2" y="2" width="44" height="44" rx="13" />
        </clipPath>
        <linearGradient
          id={gradient}
          x1="17"
          y1="8"
          x2="39"
          y2="37"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#a7d4cc" />
          <stop offset=".5" stopColor="#60a89f" />
          <stop offset="1" stopColor="#bcd8df" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="46" height="46" rx="14" fill="#142d43" />
      <rect
        x="1.5"
        y="1.5"
        width="45"
        height="45"
        rx="13.5"
        stroke="white"
        strokeOpacity=".12"
      />
      <path
        d="M12.5 12.5V35.5"
        stroke="white"
        strokeWidth="3.3"
        strokeLinecap="round"
      />
      <g clipPath={`url(#${clip})`}><path
        className="brand-triangle"
        d="M19 12L36.5 23.1C37.2 23.55 37.2 24.45 36.5 24.9L19 36V12Z"
        fill={`url(#${gradient})`}
      /></g>
      <path
        d="M12.5 24L24 14.5M12.5 24L24 33.5"
        stroke="white"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
export function Brand() {
  return (
    <span className="brand-lockup">
      <BrandMark />
      <span className="brand-wordmark">
        Know<span>Motion</span>
        <i />
      </span>
    </span>
  );
}

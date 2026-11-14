import { useId } from "react";

export function BrandMark({ className = "" }: { className?: string }) {
  const gradient = useId();
  return (
    <svg
      className={`brand-mark ${className}`}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient
          id={gradient}
          x1="17"
          y1="8"
          x2="39"
          y2="37"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#b6b3ff" />
          <stop offset=".5" stopColor="#8b86ee" />
          <stop offset="1" stopColor="#b8d8f2" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="46" height="46" rx="14" fill="#20212b" />
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
      <path
        d="M19 12L36.5 23.1C37.2 23.55 37.2 24.45 36.5 24.9L19 36V12Z"
        fill={`url(#${gradient})`}
      />
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

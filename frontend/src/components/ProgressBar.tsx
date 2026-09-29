// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import "./ProgressBar.css";

export type ProgressVariant = "accent" | "neutral" | "good" | "warning" | "serious" | "critical";

export interface ProgressBarProps {
  value: number;
  max?: number;
  /** "accent" is the Nocturne gradient (accent-700 → accent), for VRAM-like fills. */
  variant?: ProgressVariant;
  /** Accessible name; the bar is a role="progressbar"/meter for screen readers. */
  label: string;
  /** Spoken value, e.g. "18.2 of 24 GB". Defaults to the percentage. */
  valueText?: string;
  height?: number;
  className?: string;
}

export function ProgressBar({
  value,
  max = 100,
  variant = "accent",
  label,
  valueText,
  height = 5,
  className,
}: ProgressBarProps) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (100 * value) / max)) : 0;
  return (
    <div
      className={`progress${className ? " " + className : ""}`}
      style={{ height }}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={valueText}
    >
      {/* A non-zero value keeps a 2px sliver: "a little" and "none" are different answers. */}
      <div className={`progress-fill progress-${variant}`} style={{ width: `${pct}%`, minWidth: value > 0 ? 2 : 0 }} />
    </div>
  );
}

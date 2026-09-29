// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useId, type ReactNode } from "react";
import "./SegmentedControl.css";

export interface SegmentOption<V extends string | number> {
  value: V;
  label: ReactNode;
  title?: string;
  disabled?: boolean;
}

export interface SegmentedControlProps<V extends string | number> {
  options: readonly SegmentOption<V>[];
  value: V;
  onChange: (value: V) => void;
  /** Accessible name of the group. */
  label: string;
  size?: "sm" | "md";
  disabled?: boolean;
  className?: string;
}

/* Nocturne's .seg on native radio inputs: arrow keys, focus ring and the
   checked state come from the platform, not from script. */
export function SegmentedControl<V extends string | number>({
  options,
  value,
  onChange,
  label,
  size = "md",
  disabled,
  className,
}: SegmentedControlProps<V>) {
  const name = useId();
  return (
    <div
      className={`seg giq-seg giq-seg-${size}${className ? " " + className : ""}`}
      role="radiogroup"
      aria-label={label}
    >
      {options.map((o) => (
        <label key={String(o.value)} className="seg-opt" title={o.title}>
          <input
            type="radio"
            name={name}
            value={String(o.value)}
            checked={o.value === value}
            disabled={disabled || o.disabled}
            onChange={() => onChange(o.value)}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

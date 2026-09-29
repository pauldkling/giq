// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import "./charts.css";

export interface LegendItem {
  id: string;
  label: ReactNode;
  /** CSS colour, normally a var(--s-…)/var(--series-n) reference. */
  color: string;
  /** Replaces the swatch, e.g. a WorkerIcon already tinted in the series colour. */
  icon?: ReactNode;
}

/** A chart legend: always present for two or more series, so identity is never colour alone. */
export function Legend({ items, label }: { items: LegendItem[]; label?: string }) {
  if (!items.length) return null;
  return (
    <ul className="chart-legend" aria-label={label}>
      {items.map((it) => (
        <li key={it.id} className="chart-legend-item">
          {it.icon ?? <span className="chart-legend-swatch" style={{ background: it.color }} />}
          {it.label}
        </li>
      ))}
    </ul>
  );
}

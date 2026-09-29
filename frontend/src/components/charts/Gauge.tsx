// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTooltip } from "../TooltipProvider";
import "./Gauge.css";

export interface GaugeSegment {
  id: string;
  value: number;
  color: string;
  /** Tooltip / accessible text for this share ("giq: 18.2 GB"). */
  label: string;
}

export interface GaugeProps {
  segments: GaugeSegment[];
  total: number;
  /** Accessible summary of the whole bar. */
  ariaLabel: string;
  height?: number;
}

/* A capacity bar split into shares over a free remainder (VRAM: giq's share,
   everyone else's, free). A non-zero share keeps a 2px floor: 0.3 GB of a
   16 GB card is 2% of a thin bar and rounds to nothing, but "a little" and
   "none" are different answers. The exact figures go in the tooltip. */
export function Gauge({ segments, total, ariaLabel, height = 6 }: GaugeProps) {
  const tip = useTooltip();
  const pct = (v: number) => `${((100 * Math.max(v, 0)) / (total || 1)).toFixed(2)}%`;
  return (
    <div className="gauge" style={{ height }} role="img" aria-label={ariaLabel}>
      {segments.map((s) => (
        <div
          key={s.id}
          className="gauge-seg"
          style={{ width: pct(s.value), minWidth: s.value > 0.05 ? 2 : 0, background: s.color }}
          onPointerMove={(e) => tip.show(e, s.label)}
          onPointerLeave={tip.hide}
        />
      ))}
    </div>
  );
}

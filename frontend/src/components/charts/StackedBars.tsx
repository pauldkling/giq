// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useElementWidth } from "../../lib/useElementWidth";
import { useTooltip } from "../TooltipProvider";
import { axisPad } from "./axisWidth";
import { ChartEmpty } from "./ChartEmpty";
import "./charts.css";

export interface BarSegment {
  id: string;
  value: number;
  /** CSS colour (a var(--…) reference, so it follows the theme). */
  color: string;
}

export interface BarBucket {
  key: string | number;
  /** Bottom to top. Keep one fixed order (e.g. WORKER_ORDER) across buckets. */
  segments: BarSegment[];
}

export interface StackedBarsProps {
  /** Every bucket of the x-domain, in order — empty ones included, so quiet periods show as gaps. */
  buckets: BarBucket[];
  ariaLabel: string;
  height?: number;
  /** Tooltip for a whole column (the hit target spans the column's full height). */
  tooltip?: (bucket: BarBucket, index: number) => ReactNode;
  /** Labels under the first and last column. */
  xLabels?: { start?: string; end?: string };
  formatY?: (v: number) => string;
  emptyText?: string;
  /** Left gutter in px; by default measured from the y-tick labels. */
  padLeft?: number;
}

const PAD_B = 16;
const PAD_T = 6;
const GAP = 2; // surface gap between columns and between stacked segments

export function StackedBars({
  buckets,
  ariaLabel,
  height = 180,
  tooltip,
  xLabels,
  formatY = (v) => String(Math.round(v)),
  emptyText,
  padLeft,
}: StackedBarsProps) {
  const { t } = useTranslation();
  const [ref, W] = useElementWidth();
  const tip = useTooltip();
  const sums = buckets.map((b) => b.segments.reduce((a, s) => a + Math.max(0, s.value), 0));
  const maxY = Math.max(1, ...sums);
  const empty = sums.every((s) => s === 0);
  const ticks = [0.5, 1].map((f) => ({ f, label: formatY(maxY * f) }));
  const padL = padLeft ?? axisPad(ticks.map((k) => k.label));
  const n = Math.max(1, buckets.length);
  const slot = (W - padL) / n;
  const bw = Math.max(2, slot - GAP);
  const plotH = height - PAD_T - PAD_B;
  const scale = plotH / maxY;

  return (
    <div className="chart" ref={ref}>
      {W > 0 && empty ? (
        <ChartEmpty text={emptyText ?? t("empty.noData")} height={height} />
      ) : W > 0 ? (
        <svg width={W} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map(({ f, label }) => {
            const y = PAD_T + plotH * (1 - f);
            return (
              <g key={f}>
                <line className="grid-line" x1={padL} x2={W} y1={y} y2={y} />
                <text x={padL - 4} y={y + 3} textAnchor="end">
                  {label}
                </text>
              </g>
            );
          })}
          {buckets.map((b, i) => {
            const x = padL + i * slot + GAP / 2;
            const segs = b.segments.filter((s) => s.value > 0);
            let cursor = height - PAD_B;
            return (
              <g
                key={b.key}
                className="col"
                onPointerMove={tooltip ? (e) => tip.show(e, tooltip(b, i)) : undefined}
                onPointerLeave={tooltip ? tip.hide : undefined}
              >
                <rect className="hit" x={x - GAP / 2} y={PAD_T} width={slot} height={plotH} />
                {segs.map((s, si) => {
                  const h = s.value * scale;
                  const top = si === segs.length - 1;
                  cursor -= h;
                  return (
                    <rect
                      key={s.id}
                      className="bar"
                      x={x}
                      y={cursor}
                      width={bw}
                      height={Math.max(1, h - (top ? 0 : GAP))}
                      rx={top ? 2 : 1}
                      fill={s.color}
                      pointerEvents="none"
                    />
                  );
                })}
              </g>
            );
          })}
          {xLabels?.start && (
            <text x={padL} y={height - 3}>
              {xLabels.start}
            </text>
          )}
          {xLabels?.end && (
            <text x={W - 2} y={height - 3} textAnchor="end">
              {xLabels.end}
            </text>
          )}
        </svg>
      ) : (
        <div style={{ height }} />
      )}
    </div>
  );
}

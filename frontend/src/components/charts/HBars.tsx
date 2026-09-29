// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ellipsize } from "../../lib/format";
import { useElementWidth } from "../../lib/useElementWidth";
import { useTooltip } from "../TooltipProvider";
import { ChartEmpty } from "./ChartEmpty";
import "./charts.css";

export interface HBarRow {
  id: string;
  /** Full label; truncated on the chart, whole in its <title> and the tooltip. */
  label: string;
  value: number;
  color: string;
  /** Text after the bar ("1.2 s · 14 jobs"). */
  valueLabel?: string;
}

export interface HBarsProps {
  rows: HBarRow[];
  ariaLabel: string;
  tooltip?: (row: HBarRow) => ReactNode;
  /** Width reserved for labels, px. */
  labelWidth?: number;
  maxLabelChars?: number;
  /** Width reserved right of the longest bar for its value label, px. */
  valueWidth?: number;
  rowHeight?: number;
  emptyText?: string;
}

/** Ranked horizontal bars with direct value labels (caller sorts and caps the rows). */
export function HBars({
  rows,
  ariaLabel,
  tooltip,
  labelWidth = 130,
  maxLabelChars = 18,
  valueWidth = 110,
  rowHeight = 28,
  emptyText,
}: HBarsProps) {
  const { t } = useTranslation();
  const [ref, W] = useElementWidth();
  const tip = useTooltip();
  const height = Math.max(rowHeight, rows.length * rowHeight) + 4;
  const maxV = Math.max(1e-9, ...rows.map((r) => r.value));
  const room = Math.max(10, W - labelWidth - valueWidth);

  return (
    <div className="chart" ref={ref}>
      {W > 0 && !rows.length ? (
        <ChartEmpty text={emptyText ?? t("empty.noJobs")} height={120} />
      ) : W > 0 ? (
        <svg width={W} height={height} role="img" aria-label={ariaLabel}>
          {rows.map((r, i) => {
            const mid = 2 + i * rowHeight + rowHeight / 2;
            const bw = Math.max(3, (room * r.value) / maxV);
            return (
              <g
                key={r.id}
                onPointerMove={tooltip ? (e) => tip.show(e, tooltip(r)) : undefined}
                onPointerLeave={tooltip ? tip.hide : undefined}
              >
                <title>{r.label}</title>
                <rect className="hit" x={0} y={mid - rowHeight / 2} width={W} height={rowHeight} />
                <text className="hbar-label" x={0} y={mid + 3.5}>
                  {ellipsize(r.label, maxLabelChars)}
                </text>
                <rect x={labelWidth} y={mid - 5} width={bw} height={10} rx={3} fill={r.color} pointerEvents="none" />
                {r.valueLabel && (
                  <text x={labelWidth + bw + 5} y={mid + 3.5}>
                    {r.valueLabel}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      ) : (
        <div style={{ height }} />
      )}
    </div>
  );
}

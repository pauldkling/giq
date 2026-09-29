// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, type PointerEvent } from "react";
import { useElementWidth } from "../../lib/useElementWidth";
import { useTooltip } from "../TooltipProvider";
import type { TimePoint } from "./AreaLine";
import { nearest } from "./nearest";
import "./charts.css";

export interface SparklineProps {
  points: TimePoint[];
  ariaLabel: string;
  /** x-domain [start, end], epoch seconds (e.g. the last 6 h, so gaps read as gaps). */
  domain: [number, number];
  height?: number;
  /** A dashed reference, e.g. the card's power limit; the y-range stretches to include it. */
  refLine?: number | null;
  color?: string;
  /** Tooltip value text ("65 °C"). */
  formatValue: (v: number) => string;
  /** Tooltip time text. */
  formatTime: (t: number) => string;
}

const PAD = 2;

/** A small trend with no axes: area + line, hover dot and tooltip. Renders nothing under two samples. */
export function Sparkline({
  points,
  ariaLabel,
  domain: [t0, t1],
  height = 44,
  refLine,
  color = "var(--chart-seq)",
  formatValue,
  formatTime,
}: SparklineProps) {
  const [ref, W] = useElementWidth();
  const tip = useTooltip();
  const [hover, setHover] = useState<TimePoint | null>(null);
  const vals = points.map((p) => p.v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals, refLine ?? -Infinity);
  const span = Math.max(hi - lo, 1);
  const xs = (t: number) => PAD + ((W - 2 * PAD) * (t - t0)) / Math.max(1, t1 - t0);
  const ys = (v: number) => PAD + (height - 2 * PAD) * (1 - (v - lo) / span);

  let line = "";
  points.forEach((p, i) => (line += `${i ? "L" : "M"}${xs(p.t).toFixed(1)} ${ys(p.v).toFixed(1)}`));
  const first = points[0];
  const last = points[points.length - 1];
  const area =
    first && last ? `${line}L${xs(last.t).toFixed(1)} ${height - PAD}L${xs(first.t).toFixed(1)} ${height - PAD}Z` : "";

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const p = nearest(points, t0 + ((e.clientX - box.left) / box.width) * (t1 - t0));
    if (!p) return;
    setHover(p);
    tip.show(e, (
      <>
        <b>{formatTime(p.t)}</b>
        <br />
        {formatValue(p.v)}
      </>
    ));
  };

  return (
    <div className="chart" ref={ref}>
      {W > 0 && points.length >= 2 ? (
        <svg width={W} height={height} role="img" aria-label={ariaLabel}>
          {refLine != null && refLine >= lo && (
            <line className="ref-line" x1={PAD} x2={W - PAD} y1={ys(refLine)} y2={ys(refLine)} />
          )}
          <path d={area} fill={color} opacity={0.12} />
          <path d={line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
          {hover && (
            <circle cx={xs(hover.t)} cy={ys(hover.v)} r={3} fill={color} stroke="var(--chart-ring)" strokeWidth={1.5} />
          )}
          <rect
            className="hit"
            x={0}
            y={0}
            width={W}
            height={height}
            onPointerMove={onMove}
            onPointerLeave={() => {
              setHover(null);
              tip.hide();
            }}
          />
        </svg>
      ) : (
        <div style={{ height }} />
      )}
    </div>
  );
}

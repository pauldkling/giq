// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, type PointerEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useElementWidth } from "../../lib/useElementWidth";
import { useTooltip } from "../TooltipProvider";
import { axisPad } from "./axisWidth";
import { ChartEmpty } from "./ChartEmpty";
import { nearest } from "./nearest";
import "./charts.css";

export interface TimePoint {
  /** Epoch seconds. */
  t: number;
  v: number;
}

export interface AreaLineProps<P extends TimePoint> {
  points: P[];
  ariaLabel: string;
  /** x-domain [start, end] in epoch seconds; defaults to the points' extent. */
  domain?: [number, number];
  /** Top of the y-axis (e.g. the card's total VRAM); defaults to the data maximum. */
  yMax?: number;
  height?: number;
  /** CSS colour of line and fill; defaults to the sequential accent. */
  color?: string;
  /** Tooltip for the point under the crosshair. */
  tooltip?: (p: P) => ReactNode;
  formatY?: (v: number) => string;
  xLabels?: { start?: string; end?: string };
  emptyText?: string;
  /** Left gutter in px; by default measured from the y-tick labels. */
  padLeft?: number;
}

const PAD_B = 16;
const PAD_T = 6;

/** A single series over time: area + 2px line, with a crosshair and a dot on the nearest sample. */
export function AreaLine<P extends TimePoint>({
  points,
  ariaLabel,
  domain,
  yMax,
  height = 180,
  color = "var(--chart-seq)",
  tooltip,
  formatY = (v) => String(Math.round(v)),
  xLabels,
  emptyText,
  padLeft,
}: AreaLineProps<P>) {
  const { t } = useTranslation();
  const [ref, W] = useElementWidth();
  const tip = useTooltip();
  const [hover, setHover] = useState<P | null>(null);

  const t0 = domain?.[0] ?? Math.min(...points.map((p) => p.t));
  const t1 = domain?.[1] ?? Math.max(...points.map((p) => p.t));
  const top = yMax ?? Math.max(1, ...points.map((p) => p.v));
  const ticks = [0.5, 1].map((f) => ({ f, label: formatY(top * f) }));
  const padL = padLeft ?? axisPad(ticks.map((k) => k.label));
  const pts = points.filter((p) => p.t >= t0 && p.t <= t1);
  const plotH = height - PAD_T - PAD_B;
  const xs = (x: number) => padL + ((W - padL) * (x - t0)) / Math.max(1, t1 - t0);
  const ys = (v: number) => PAD_T + plotH * (1 - v / top);

  const onMove = (e: PointerEvent<SVGRectElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const at = t0 + ((e.clientX - box.left) / box.width) * (t1 - t0);
    const p = nearest(pts, at);
    if (!p) return;
    setHover(p);
    if (tooltip) tip.show(e, tooltip(p));
  };

  let line = "";
  pts.forEach((p, i) => (line += `${i ? "L" : "M"}${xs(p.t).toFixed(1)} ${ys(p.v).toFixed(1)}`));
  const first = pts[0];
  const last = pts[pts.length - 1];
  const area =
    first && last ? `${line}L${xs(last.t).toFixed(1)} ${ys(0)}L${xs(first.t).toFixed(1)} ${ys(0)}Z` : "";

  return (
    <div className="chart" ref={ref}>
      {W > 0 && pts.length < 2 ? (
        <ChartEmpty text={emptyText ?? t("empty.collecting")} height={height} />
      ) : W > 0 ? (
        <svg width={W} height={height} role="img" aria-label={ariaLabel}>
          {ticks.map(({ f, label }) => (
            <g key={f}>
              <line className="grid-line" x1={padL} x2={W} y1={ys(top * f)} y2={ys(top * f)} />
              <text x={padL - 4} y={ys(top * f) + 3} textAnchor="end">
                {label}
              </text>
            </g>
          ))}
          <path d={area} fill={color} opacity={0.15} />
          <path d={line} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
          {hover && (
            <>
              <line className="crosshair" x1={xs(hover.t)} x2={xs(hover.t)} y1={PAD_T} y2={height - PAD_B} />
              <circle cx={xs(hover.t)} cy={ys(hover.v)} r={4} fill={color} stroke="var(--chart-ring)" strokeWidth={2} />
            </>
          )}
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
          <rect
            className="hit"
            x={padL}
            y={0}
            width={Math.max(0, W - padL)}
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

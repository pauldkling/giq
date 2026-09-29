// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/* The left gutter a y-axis needs for its tick labels. A fixed gutter clipped
   German figures ("92.459" is two characters wider than "92k" and a thousands
   separator English doesn't print), so the gutter is measured from the labels
   the chart is about to draw, in the font charts.css gives them. */

const FONT = "10.5px Inter Variable, Inter, system-ui, sans-serif";
const TICK_GAP = 4; // the label's x offset from the plot edge
const MIN_PAD = 22;

let ctx: CanvasRenderingContext2D | null | undefined;

function textWidth(s: string): number {
  if (ctx === undefined) {
    ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
    if (ctx) ctx.font = FONT;
  }
  // Without a canvas (tests), tabular digits at this size are about 6.2px each.
  return ctx ? ctx.measureText(s).width : s.length * 6.2;
}

/** Left padding that fits every label, plus the gap to the plot. */
export function axisPad(labels: string[]): number {
  const widest = labels.reduce((m, l) => Math.max(m, textWidth(l)), 0);
  return Math.max(MIN_PAD, Math.ceil(widest) + TICK_GAP + 2);
}

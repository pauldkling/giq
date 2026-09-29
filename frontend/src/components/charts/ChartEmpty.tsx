// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/** The text a chart shows in place of marks when there is nothing to plot. */
export function ChartEmpty({ text, height }: { text: string; height: number }) {
  return (
    <div className="chart-empty" style={{ height }}>
      {text}
    </div>
  );
}

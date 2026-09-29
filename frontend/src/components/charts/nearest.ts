// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/** The sample closest in time to `t` (points need not be sorted). */
export function nearest<P extends { t: number }>(points: readonly P[], t: number): P | undefined {
  let best: P | undefined;
  for (const p of points) if (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
  return best;
}

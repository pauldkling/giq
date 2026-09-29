// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import "./LiveDot.css";

export type LiveState = "live" | "paused" | "down" | "connecting";

/** The status dot: pulsing accent while live, still neutral when paused, critical when giq cannot be reached. */
export function LiveDot({ state, label }: { state: LiveState; label: string }) {
  return (
    <span className={`live live-${state}`} role="status">
      <span className="live-dot" aria-hidden />
      {label}
    </span>
  );
}

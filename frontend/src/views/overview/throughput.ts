// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { JobRecord } from "../../api/types";

/** How far back the throughput tile looks. */
export const THROUGHPUT_WINDOW_S = 300;

export interface Throughput {
  /** Output tokens per second of run time; null when no job qualifies. */
  rate: number | null;
  jobs: number;
  tokens: number;
}

/* Generation rate as giq actually recorded it: output tokens over run time,
   summed across the LLM jobs that finished inside the window. It is a
   per-job rate (prompt processing included, so it reads a little under the
   engine's decode speed), not a node total — concurrent jobs are not added
   up, because the job log cannot say which ones overlapped. With no such
   job there is no rate, and the tile says so instead of showing 0. */
export function throughput(
  jobs: readonly JobRecord[],
  nowS: number,
  windowS = THROUGHPUT_WINDOW_S,
): Throughput {
  let tokens = 0;
  let runMs = 0;
  let n = 0;
  for (const j of jobs) {
    if (j.t < nowS - windowS) continue;
    if (j.status !== "completed" || j.tokens_out == null || !j.run_ms) continue;
    tokens += j.tokens_out;
    runMs += j.run_ms;
    n++;
  }
  return { rate: n && runMs > 0 ? tokens / (runMs / 1000) : null, jobs: n, tokens };
}

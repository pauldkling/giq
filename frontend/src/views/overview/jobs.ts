// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { ApiError, del } from "../../api/client";
import type { CancelResponse } from "../../api/types";

/* Cancel a queued job. Only pending jobs cancel: one that started in the
   meantime answers {cancelled: false, reason}, and one that already finished
   (or never existed) answers 404 — both are reported, neither is an error
   worth a dialog. */
export async function cancelJob(jobId: string): Promise<CancelResponse> {
  try {
    return await del<CancelResponse>(`/jobs/${encodeURIComponent(jobId)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return { cancelled: false, reason: typeof err.detail === "string" ? err.detail : "not found" };
    }
    throw err;
  }
}

/** The /stats/timeline bucket for a window: hours up to a day, 6 h up to a week, days beyond. */
export function bucketFor(hours: number): number {
  return hours <= 24 ? 3600 : hours <= 168 ? 21_600 : 86_400;
}

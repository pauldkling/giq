// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Status } from "../api/types";

/* /status carries its state as an English sentence (state_message) and as
   the facts it was built from. The page says it in its own language from
   the facts, mirroring the server's branches, and keeps the server's
   sentence as the tooltip. It never translates the sentence itself: string
   matching on server text breaks the day the server rewords it.

   A running job's worker and model are only in the server's sentence (the
   facts carry job ids), so the translated line counts jobs instead; the
   overview's queue card names them. */

export interface StateMessage {
  /** A key under common:stateMessage. */
  key: "paused" | "running" | "loaded" | "queued" | "blocked" | "idle";
  params: Record<string, string | number>;
}

export function stateMessage(s: Status): StateMessage {
  if (s.paused) return { key: "paused", params: {} };
  if (s.jobs_running.length) return { key: "running", params: { count: s.jobs_running.length } };
  if (s.active_modality) return { key: "loaded", params: { worker: s.active_modality, model: s.active_recipe ?? "" } };
  if (s.jobs_pending.length) {
    return s.vram_ok
      ? { key: "queued", params: { count: s.jobs_pending.length } }
      : { key: "blocked", params: { count: s.jobs_pending.length, free: blockedFree(s) } };
  }
  return { key: "idle", params: {} };
}

/* Free VRAM on the card the blocked job waits on. The one-card vram_free_gb
   is the default card's, which on a two-card machine can be the card with
   plenty of room — "waiting for VRAM (20 GB free)" for a job bound to the
   other one. */
function blockedFree(s: Status): number {
  const card = s.gpus?.find((g) => g.uuid === s.vram_blocked_gpu);
  return card ? card.vram_free_gb : s.vram_free_gb;
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Catalog, CatalogModel, Status } from "../../api/types";

/* What is on the cards right now — both kinds. Keep-warm models the
   residents loop holds, and the on-demand model in the batch slot, which is
   just as loaded. This list once carried every model the registry *declares*
   resident, so a demoted one kept a play button under a "resident" heading
   on a rig where nothing was pinned at all. Residency is set per model on the
   Models view; this section reports, and each row says which kind it is,
   because they behave differently when a card gets tight: a resident comes
   back after an eviction, the batch slot does not.

   Rows come from the catalog (keep-warm) and /status.active (the slot), so
   the list follows the 3 s status poll rather than the 60 s catalog refresh:
   an on-demand load has to appear while it is loading, not a minute after it
   answered. */

export type LaneState = "ready" | "loading" | "evicted";

export interface LaneRow {
  key: string;
  model: CatalogModel;
  /** Held by the residents loop (policy pinned), as opposed to the batch slot. */
  warm: boolean;
  ready: boolean;
  state: LaneState;
  /** worker/model the card was given up for, when state is "evicted". */
  evictedFor: string | null;
  /** The card it is on: the slot's own device, or where a resident lands. */
  device: string | null;
}

export const laneKey = (worker: string, model: string) => `${worker}/${model}`;

export function laneRows(catalog: Catalog | undefined, status: Status | undefined): LaneRow[] {
  if (!catalog) return [];
  const rows: LaneRow[] = [];
  /* Pinned but not loaded is either coming up or evicted for batch work.
     The difference matters: one resolves on its own in seconds, the other
     waits out someone else's render. */
  const batch =
    status?.active_worker != null ? laneKey(status.active_worker, status.active_model ?? "?") : null;
  for (const m of catalog.models) {
    if (!m.resident) continue;
    const evicted = !m.ready && batch !== null;
    rows.push({
      key: laneKey(m.worker, m.model),
      model: m,
      warm: true,
      ready: m.ready,
      state: m.ready ? "ready" : evicted ? "evicted" : "loading",
      evictedFor: evicted ? batch : null,
      device: m.effective_device,
    });
  }
  for (const a of status?.active ?? []) {
    const m = catalog.models.find((x) => x.worker === a.worker && x.model === a.model);
    if (!m || m.resident) continue;
    rows.push({
      key: laneKey(m.worker, m.model),
      model: m,
      warm: false,
      ready: a.ready,
      state: a.ready ? "ready" : "loading",
      evictedFor: null,
      // Where the slot *is*, not where the catalog says it would land.
      device: a.device,
    });
  }
  return rows;
}

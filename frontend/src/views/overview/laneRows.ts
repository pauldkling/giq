// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type {
  InstancesResponse,
  RecipeEntry,
  RecipesResponse,
  Status,
} from "../../api/types";

/* What is on the cards right now — both kinds. Recipes kept loaded by the
   residents loop, and on-demand instances, which are just as loaded. This
   list once carried every recipe *declared* resident, so a demoted one kept
   a play button under a "resident" heading on a rig where nothing was pinned
   at all. Residency is set per recipe on the Recipes view; this section
   reports, and each row says which kind it is, because they behave
   differently when a card gets tight: a resident comes back after an
   eviction, an on-demand instance does not.

   Rows are the running instances (GET /instances, on the 3 s poll: a load
   has to appear while it is loading, not a minute after it answered), plus
   every pinned recipe that has none — coming up, or evicted for someone
   else's job. The recipes supply labels and residency. */

export type LaneState = "ready" | "loading" | "evicted";

export interface LaneRow {
  /** The recipe name. */
  key: string;
  recipe: RecipeEntry;
  /** Held by the residents loop (pinned), as opposed to loaded on demand. */
  warm: boolean;
  ready: boolean;
  state: LaneState;
  /** The recipe the card was given up for, when state is "evicted". */
  evictedFor: string | null;
  /** The card it is on: the instance's own, or where a pinned recipe lands. */
  device: string | null;
}

export function laneRows(
  recipes: RecipesResponse | undefined,
  instances: InstancesResponse | undefined,
  status: Status | undefined,
): LaneRow[] {
  if (!recipes) return [];
  const byName = new Map(recipes.recipes.map((r) => [r.name, r]));
  const rows: LaneRow[] = [];
  const running = new Set<string>();
  for (const i of instances?.instances ?? []) {
    const recipe = byName.get(i.recipe);
    if (!recipe) continue;
    running.add(i.recipe);
    rows.push({
      key: i.recipe,
      recipe,
      warm: i.residency === "resident",
      ready: i.state === "ready",
      state: i.state === "ready" ? "ready" : "loading",
      evictedFor: null,
      // Where the instance *is*, not where its recipe would land now.
      device: i.device,
    });
  }
  /* Pinned but not running is either coming up or evicted for on-demand
     work. The difference matters: one resolves on its own in seconds, the
     other waits out someone else's render. */
  const onDemand = status?.active_recipe ?? null;
  for (const recipe of recipes.recipes) {
    if (recipe.residency.policy !== "pinned" || running.has(recipe.name))
      continue;
    const evicted = onDemand !== null;
    rows.push({
      key: recipe.name,
      recipe,
      warm: true,
      ready: false,
      state: evicted ? "evicted" : "loading",
      evictedFor: evicted ? onDemand : null,
      device: recipe.card.effective,
    });
  }
  // Kept loaded first, in reload order; then what is loaded on demand.
  const order = (r: LaneRow) =>
    r.warm ? recipes.pinned.indexOf(r.key) : recipes.pinned.length;
  return rows.sort((a, b) => order(a) - order(b) || a.key.localeCompare(b.key));
}

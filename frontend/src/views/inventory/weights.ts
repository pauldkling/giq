// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { WeightsItem } from "../../api/types";

/* The Inventory view's pure logic, testable without a DOM. */

/** A checkpoint as the table names it: the repo, or the path under the models directory. */
export function weightsName(w: WeightsItem, modelsDir: string | null | undefined): string {
  if (w.repo) return w.repo;
  const path = w.path ?? "";
  const root = modelsDir ? modelsDir.replace(/\/+$/, "") + "/" : null;
  return root && path.startsWith(root) ? path.slice(root.length) : path;
}

/** The recipe a link asked for (#/inventory?recipe=…), or null. */
export function recipeFromHash(hash: string): string | null {
  const query = hash.split("?")[1];
  return query ? new URLSearchParams(query).get("recipe") : null;
}

/** On disk first, biggest first; then what is missing, by name. */
export function sortWeights(items: WeightsItem[], name: (w: WeightsItem) => string): WeightsItem[] {
  return [...items].sort(
    (a, b) => Number(b.on_disk) - Number(a.on_disk) || b.size_bytes - a.size_bytes || name(a).localeCompare(name(b)),
  );
}

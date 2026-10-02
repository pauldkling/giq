// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { WeightsItem } from "../../api/types";
import { recipeFromHash, sortWeights, weightsName } from "./weights";

const w = (over: Partial<WeightsItem>): WeightsItem =>
  ({ id: "x", path: null, repo: null, on_disk: true, size_bytes: 0, recipes: [], used_by: [], ...over }) as WeightsItem;

describe("weights", () => {
  it("names a checkpoint by its repo, or its path under the models directory", () => {
    expect(weightsName(w({ repo: "Systran/faster-whisper-tiny" }), "/m")).toBe("Systran/faster-whisper-tiny");
    expect(weightsName(w({ path: "/m/unsloth/q.gguf" }), "/m/")).toBe("unsloth/q.gguf");
    expect(weightsName(w({ path: "/elsewhere/q.gguf" }), "/m")).toBe("/elsewhere/q.gguf");
    expect(weightsName(w({ path: "/m/q.gguf" }), null)).toBe("/m/q.gguf");
  });

  it("reads the recipe a link asked for", () => {
    expect(recipeFromHash("#/inventory?recipe=flux_klein")).toBe("flux_klein");
    expect(recipeFromHash("#/inventory")).toBeNull();
  });

  it("lists what is on disk first, biggest first", () => {
    const items = [
      w({ id: "a", path: "/a", size_bytes: 1 }),
      w({ id: "b", path: "/b", on_disk: false }),
      w({ id: "c", path: "/c", size_bytes: 9 }),
    ];
    expect(sortWeights(items, (x) => x.path ?? "").map((x) => x.id)).toEqual(["c", "a", "b"]);
  });
});

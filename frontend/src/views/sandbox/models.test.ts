// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { RecipeEntry, RecipesResponse } from "../../api/types";
import { recipeEntry as m } from "../../api/testing";
import { disabledTabs, sandboxModels } from "./models";

const cat = (recipes: RecipeEntry[]): RecipesResponse => ({ recipes, cards: [], pinned: [] });

describe("sandboxModels", () => {
  it("defaults chat to loaded, then pinned, then resident by default, then first", () => {
    const a = m({ name: "a" });
    const b = m({ name: "b", residency: { default_resident: true } });
    const c = m({ name: "c", residency: { policy: "pinned" } });
    const d = m({ name: "d", fit: "loaded" });
    expect(sandboxModels(cat([a, b, c, d])).chatDefault).toBe("d");
    expect(sandboxModels(cat([a, b, c])).chatDefault).toBe("c");
    expect(sandboxModels(cat([a, b])).chatDefault).toBe("b");
    expect(sandboxModels(cat([a])).chatDefault).toBe("a");
  });

  it("drops recipes that never fit and marks weights on disk", () => {
    const s = sandboxModels(
      cat([
        m({ name: "seer", vision: true }),
        m({ name: "blind", vision: true, installed: false }),
        m({ name: "big", modalities: ["text2image"], fit: "never" }),
      ]),
    );
    expect(s.vision.map((o) => [o.model, o.onDisk])).toEqual([
      ["seer", true],
      ["blind", false],
    ]);
    expect(s.t2i).toEqual([]);
    expect(disabledTabs(s)).toEqual(new Set(["t2i", "edit", "tools"]));
  });

  it("offers a recipe in every modality it serves", () => {
    const s = sandboxModels(cat([m({ name: "klein", modalities: ["text2image", "image_edit"] })]));
    expect(s.t2i.map((o) => o.model)).toEqual(["klein"]);
    expect(s.edit.map((o) => o.model)).toEqual(["klein"]);
  });

  it("disables nothing before the catalog answers", () => {
    expect(disabledTabs(sandboxModels(undefined)).size).toBe(0);
  });
});

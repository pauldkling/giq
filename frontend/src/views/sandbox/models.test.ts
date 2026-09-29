// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { Catalog, CatalogModel, StorageResponse } from "../../api/types";
import { disabledTabs, sandboxModels } from "./models";

const m = (over: Partial<CatalogModel>): CatalogModel =>
  ({
    worker: "llm",
    model: "x",
    vram_gb: 8,
    fits: "fits_now",
    policy: "auto",
    reasoning: null,
    vision: false,
    resident: false,
    resident_default: false,
    ...over,
  }) as CatalogModel;

const cat = (models: CatalogModel[]) => ({ models }) as unknown as Catalog;

describe("sandboxModels", () => {
  it("defaults chat to loaded, then resident, then resident_default, then first", () => {
    const a = m({ model: "a" });
    const b = m({ model: "b", resident_default: true });
    const c = m({ model: "c", resident: true });
    const d = m({ model: "d", fits: "loaded" });
    expect(sandboxModels(cat([a, b, c, d]), undefined).chatDefault).toBe("d");
    expect(sandboxModels(cat([a, b, c]), undefined).chatDefault).toBe("c");
    expect(sandboxModels(cat([a, b]), undefined).chatDefault).toBe("b");
    expect(sandboxModels(cat([a]), undefined).chatDefault).toBe("a");
  });

  it("drops models that never fit and marks weights on disk", () => {
    const storage = {
      disks: [],
      models: [{ worker: "llm", model: "seer", on_disk: true, size_bytes: 1 }],
    } as unknown as StorageResponse;
    const s = sandboxModels(
      cat([
        m({ model: "seer", vision: true }),
        m({ model: "blind", vision: true }),
        m({ worker: "text2image", model: "big", fits: "never" }),
      ]),
      storage,
    );
    expect(s.vision.map((o) => [o.model, o.onDisk])).toEqual([
      ["seer", true],
      ["blind", false],
    ]);
    expect(s.t2i).toEqual([]);
    expect(disabledTabs(s)).toEqual(new Set(["t2i", "edit", "tools"]));
  });

  it("disables nothing before the catalog answers", () => {
    expect(disabledTabs(sandboxModels(undefined, undefined)).size).toBe(0);
  });
});

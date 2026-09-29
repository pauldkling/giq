// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { CatalogModel } from "../../api/types";
import {
  deleteBlock,
  engineVersions,
  facetCounts,
  joinStorage,
  matches,
  pinBlock,
  sandboxBlock,
} from "./catalog";

const model = (over: Partial<CatalogModel>): CatalogModel =>
  ({ worker: "llm", model: "m", backend: "llama.cpp", fits: "fits_now", policy: "auto", resident: false, ...over }) as CatalogModel;

describe("filters", () => {
  const ms = [model({ model: "a" }), model({ model: "b", worker: "tts", backend: "kokoro" }), model({ model: "c" })];
  it("counts facets over the whole catalog", () => {
    expect(facetCounts(ms, (m) => m.worker)).toEqual([["llm", 2], ["tts", 1]]);
  });
  it("treats an empty filter as everything", () => {
    const none = { modality: new Set<string>(), engine: new Set<string>() };
    expect(ms.filter((m) => matches(m, none))).toHaveLength(3);
    expect(ms.filter((m) => matches(m, { ...none, engine: new Set(["kokoro"]) })).map((m) => m.model)).toEqual(["b"]);
  });
  it("joins the disk report by worker/model", () => {
    const [e] = joinStorage([model({ model: "a" })], [{ worker: "llm", model: "a", size_bytes: 5 } as never]);
    expect(e!.s.size_bytes).toBe(5);
    expect(joinStorage([model({})], undefined)[0]!.s).toEqual({});
  });
});

describe("what a card offers", () => {
  it("blocks deleting kept-warm, loaded and absent weights", () => {
    expect(deleteBlock(model({ resident: true }), { size_bytes: 1 })).toBe("menu.deleteKeptWarm");
    expect(deleteBlock(model({ fits: "loaded" }), { size_bytes: 1 })).toBe("menu.deleteLoaded");
    expect(deleteBlock(model({}), {})).toBe("menu.deleteNothing");
    expect(deleteBlock(model({}), { size_bytes: 1 })).toBeNull();
  });
  it("blocks keeping warm what can never fit or has no weights, unless it already is", () => {
    expect(pinBlock(model({ fits: "never" }), { on_disk: true })).toBe("residency.tooLarge");
    expect(pinBlock(model({}), {})).toBe("residency.noWeights");
    expect(pinBlock(model({ policy: "pinned", fits: "never" }), {})).toBeNull();
  });
  it("offers the sandbox only with a panel, weights and a card it fits", () => {
    expect(sandboxBlock(model({ worker: "ocr" }), { on_disk: true })).toBe("menu.noPanel");
    expect(sandboxBlock(model({}), {})).toBe("menu.nothingToRun");
    expect(sandboxBlock(model({ fits: "never" }), { on_disk: true })).toBe("menu.tooLarge");
    expect(sandboxBlock(model({}), { on_disk: true })).toBeNull();
  });
});

describe("engines", () => {
  it("trims engine build strings and marks a missing binary", () => {
    const v = engineVersions({
      engines: [
        { name: "llama.cpp", binary: "x", present: true, version: "version: 0.2.0 (build 1)", error: null },
        { name: "sd.cpp", binary: "y", present: true, version: "stable-diffusion.cpp commit 2251699", error: null },
        { name: "da3", binary: null, present: false, version: null, error: "gone" },
      ],
    });
    expect(v.get("llama.cpp")).toBe("0.2.0 (build 1)");
    expect(v.get("sd.cpp")).toBe("commit 2251699");
    expect(v.get("da3")).toBeNull();
  });
});

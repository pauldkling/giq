// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { cardChoices, cardName, shortGpuName } from "./cards";

describe("cards", () => {
  it("drops the vendor prefix", () => {
    expect(shortGpuName("NVIDIA GeForce RTX 5090")).toBe("RTX 5090");
  });
  it("reads free VRAM from either endpoint's field name", () => {
    expect(cardChoices([{ uuid: "a", index: 0, name: "X", vram_free_gb: 3 }], undefined)[0]!.free).toBe(3);
    expect(cardChoices(undefined, [{ uuid: "a", index: 0, name: "X", free_gb: 4 }])[0]!.free).toBe(4);
  });
  it("adds the index only when two cards share a name", () => {
    const cs = cardChoices(undefined, [
      { uuid: "a", index: 0, name: "NVIDIA GeForce RTX 5090" },
      { uuid: "b", index: 1, name: "NVIDIA GeForce RTX 5090" },
      { uuid: "c", index: 2, name: "NVIDIA GeForce RTX 5060 Ti" },
    ]);
    expect(cs.map((c) => cardName(c, cs))).toEqual(["#0 RTX 5090", "#1 RTX 5090", "RTX 5060 Ti"]);
  });
});

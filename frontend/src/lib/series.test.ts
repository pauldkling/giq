// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { assignSeriesColors, seriesColor, workerColor } from "./series";

describe("series colours", () => {
  it("gives each worker its fixed slot, unknowns the neutral", () => {
    expect(workerColor("llm")).toBe("var(--s-llm)");
    expect(workerColor("martian")).toBe("var(--series-other)");
  });
  it("folds past the eighth slot", () => {
    expect(seriesColor(0)).toBe("var(--series-1)");
    expect(seriesColor(8)).toBe("var(--series-other)");
  });
  it("assigns alphabetically so colour follows the entity", () => {
    const a = assignSeriesColors(["b/x", "a/y"]);
    const b = assignSeriesColors(["a/y", "b/x", "b/x"]);
    expect(a.get("a/y")).toBe("var(--series-1)");
    expect(a).toEqual(b);
  });
});

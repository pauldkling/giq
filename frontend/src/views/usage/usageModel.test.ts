// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { GpuEra, StatsUsage } from "../../api/types";
import {
  bucketDate,
  bucketLabel,
  buildUsageChart,
  eraTokens,
  erasNewestFirst,
  isCurrentEra,
  predatesTokenAccounting,
  usageDomain,
} from "./usageModel";

const NOW = new Date(2026, 8, 28, 14, 30); // Sep 28 2026, 14:30 local

describe("usageDomain", () => {
  it("covers every hour of today up to now", () => {
    const d = usageDomain("day", [], NOW);
    expect(d).toHaveLength(15);
    expect(d[0]).toBe("2026-09-28 00:00");
    expect(d.at(-1)).toBe("2026-09-28 14:00");
  });
  it("covers the last 7 and 30 calendar days, ending today", () => {
    const w = usageDomain("week", [], NOW);
    expect(w).toEqual([
      "2026-09-22",
      "2026-09-23",
      "2026-09-24",
      "2026-09-25",
      "2026-09-26",
      "2026-09-27",
      "2026-09-28",
    ]);
    const m = usageDomain("month", [], NOW);
    expect(m).toHaveLength(30);
    expect(m[0]).toBe("2026-08-30");
  });
  it("uses only the months seen for all time, sorted and unique", () => {
    expect(usageDomain("all", ["2026-09", "2026-07", "2026-09"], NOW)).toEqual(["2026-07", "2026-09"]);
  });
});

describe("bucket labels", () => {
  it("parses every key shape as local time", () => {
    expect(bucketDate("2026-09-28 14:00")).toEqual(new Date(2026, 8, 28, 14));
    expect(bucketDate("2026-09-28")).toEqual(new Date(2026, 8, 28));
    expect(bucketDate("2026-09")).toEqual(new Date(2026, 8, 1));
  });
  it("formats per language", () => {
    expect(bucketLabel("2026-09-28 14:00", "day", "de")).toBe("14:00");
    expect(bucketLabel("2026-09-28", "week", "en")).toBe("Sep 28");
    expect(bucketLabel("2026-09-28", "week", "de")).toBe("28. Sept.");
    expect(bucketLabel("2026-09", "all", "en")).toBe("Sep 2026");
  });
});

const usage = (over: Partial<StatsUsage> = {}): StatsUsage => ({
  period: "week",
  gpu: null,
  since: 0,
  until: null,
  totals: { jobs: 0, failed: 0, tokens_in: 0, tokens_out: 0 },
  recipes: [],
  series: [],
  ...over,
});

describe("buildUsageChart", () => {
  const d = usage({
    recipes: [
      { modality: "llm", recipe: "zeta", jobs: 3, failed: 0, tasks: 3, tokens_in: 900, tokens_out: 100, last_ts: 1 },
      { modality: "llm", recipe: "alpha", jobs: 1, failed: 0, tasks: 1, tokens_in: 10, tokens_out: 5, last_ts: 1 },
      { modality: "text2image", recipe: "flux", jobs: 2, failed: 0, tasks: 2, tokens_in: null, tokens_out: null, last_ts: 1 },
    ],
    series: [
      { b: "2026-09-27", modality: "llm", recipe: "zeta", jobs: 3, tokens_in: 900, tokens_out: 100 },
      { b: "2026-09-27", modality: "llm", recipe: "alpha", jobs: 1, tokens_in: 10, tokens_out: 5 },
      { b: "2026-09-27", modality: "text2image", recipe: "flux", jobs: 2, tokens_in: null, tokens_out: null },
    ],
  });
  const c = buildUsageChart(d, "week", NOW);

  it("spans the whole domain, empty buckets included", () => {
    expect(c.buckets).toHaveLength(7);
    expect(c.buckets[0]?.segments).toEqual([]);
  });
  it("stacks only models with tokens, in the table's order", () => {
    expect(c.models.map((m) => m.recipe)).toEqual(["zeta", "alpha"]);
    expect(c.buckets[5]?.segments.map((s) => [s.id, s.value])).toEqual([
      ["llm/zeta", 1000],
      ["llm/alpha", 15],
    ]);
  });
  it("assigns colours alphabetically over every model in the window", () => {
    expect(c.colors.get("llm/alpha")).toBe("var(--series-1)");
    expect(c.colors.get("llm/zeta")).toBe("var(--series-2)");
    expect(c.colors.get("text2image/flux")).toBe("var(--series-3)");
  });
});

describe("token accounting hint", () => {
  it("fires for LLM calls without any token figures", () => {
    const m = { modality: "llm" as const, recipe: "x", jobs: 2, failed: 0, tasks: 2, last_ts: 1 };
    expect(predatesTokenAccounting(usage({ recipes: [{ ...m, tokens_in: null, tokens_out: null }] }))).toBe(true);
    expect(predatesTokenAccounting(usage({ recipes: [{ ...m, tokens_in: 5, tokens_out: null }] }))).toBe(false);
  });
});

const era = (over: Partial<GpuEra>): GpuEra => ({
  uuid: "GPU-a",
  name: "NVIDIA GeForce RTX 5090",
  total_gb: 32,
  first_seen: 100,
  last_seen: 200,
  jobs: 0,
  failed: 0,
  tokens_in: null,
  tokens_out: null,
  avg_run_ms: null,
  first_job: null,
  last_job: null,
  ...over,
});

describe("eras", () => {
  it("is current when the card is in the live GPU list", () => {
    expect(isCurrentEra(era({}), new Set(["GPU-a"]), 10_000)).toBe(true);
    expect(isCurrentEra(era({ last_seen: 9_999 }), new Set(["GPU-b"]), 10_000)).toBe(false);
  });
  it("falls back to recently seen without a live list", () => {
    expect(isCurrentEra(era({ last_seen: 9_900 }), null, 10_000)).toBe(true);
    expect(isCurrentEra(era({ last_seen: 9_000 }), null, 10_000)).toBe(false);
  });
  it("sorts newest first and sums tokens, null when never counted", () => {
    const list = erasNewestFirst([era({ uuid: "old", first_seen: 1 }), era({ uuid: "new", first_seen: 2 })]);
    expect(list.map((e) => e.uuid)).toEqual(["new", "old"]);
    expect(eraTokens(era({}))).toBeNull();
    expect(eraTokens(era({ tokens_in: 3, tokens_out: null }))).toBe(3);
  });
});

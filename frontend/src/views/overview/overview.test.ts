// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  InstanceEntry,
  JobRecord,
  RecipeEntry,
  RecipesResponse,
  Status,
} from "../../api/types";
import { recipeEntry } from "../../api/testing";
import { bucketFor, cancelJob } from "./jobs";
import { laneRows } from "./laneRows";
import { throughput } from "./throughput";

type Call = { url: string; method: string; body: unknown };

/** Answer fetch() from a queue of [status, body] replies, recording each call. */
function mockFetch(replies: [number, unknown][]): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({
      url,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const [status, body] = replies.shift() ?? [
      500,
      { detail: "unexpected call" },
    ];
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("cancelJob", () => {
  it("sends DELETE /jobs/{id}", async () => {
    const calls = mockFetch([[200, { cancelled: true }]]);
    expect(await cancelJob("ab12")).toEqual({ cancelled: true });
    expect(calls[0]).toMatchObject({ url: "/jobs/ab12", method: "DELETE" });
  });

  it("reports a job that is already gone instead of throwing", async () => {
    mockFetch([[404, { detail: "Job not found" }]]);
    expect(await cancelJob("gone")).toEqual({
      cancelled: false,
      reason: "Job not found",
    });
  });

  it("passes a started job's refusal through", async () => {
    mockFetch([[200, { cancelled: false, reason: "Job already running" }]]);
    expect(await cancelJob("x")).toEqual({
      cancelled: false,
      reason: "Job already running",
    });
  });
});

const job = (over: Partial<JobRecord>): JobRecord => ({
  t: 1000,
  job_id: "j",
  modality: "llm",
  recipe: "m",
  status: "completed",
  queue_ms: 1,
  run_ms: 1000,
  tasks: 1,
  error: null,
  tokens_in: 10,
  tokens_out: 50,
  ...over,
});

describe("throughput", () => {
  it("is output tokens over run time across the window", () => {
    const r = throughput(
      [
        job({ tokens_out: 100, run_ms: 1000 }),
        job({ tokens_out: 50, run_ms: 1500 }),
      ],
      1100,
    );
    expect(r).toEqual({ rate: 60, jobs: 2, tokens: 150 });
  });

  it("ignores old, failed and token-less jobs", () => {
    const r = throughput(
      [
        job({ t: 100 }),
        job({ status: "failed" }),
        job({ modality: "text2image", tokens_out: null }),
      ],
      1100,
    );
    expect(r.rate).toBeNull();
    expect(r.jobs).toBe(0);
  });
});

it("buckets the timeline like the old dashboard", () => {
  expect([24, 168, 720, 2160].map(bucketFor)).toEqual([
    3600, 21600, 86400, 86400,
  ]);
});

const instance = (over: Partial<InstanceEntry>): InstanceEntry =>
  ({
    recipe: "m",
    residency: "on_demand",
    state: "ready",
    device: "GPU-A",
    ...over,
  }) as InstanceEntry;

const recipes = (
  list: RecipeEntry[],
  pinned: string[] = [],
): RecipesResponse => ({ recipes: list, cards: [], pinned });

describe("laneRows", () => {
  const status = (over: Partial<Status>) =>
    ({
      active: [],
      active_modality: null,
      active_recipe: null,
      ...over,
    }) as Status;
  const pinned = {
    residency: { policy: "pinned" as const },
    card: { effective: "GPU-A" },
  };

  it("lists running instances and pinned recipes, and nothing else", () => {
    const all = recipes(
      [
        recipeEntry({ name: "warm", ...pinned }),
        recipeEntry({ name: "cold" }),
        recipeEntry({ name: "flux", modalities: ["text2image"] }),
      ],
      ["warm"],
    );
    const running = {
      instances: [
        instance({ recipe: "warm", residency: "resident", device: "GPU-A" }),
        instance({ recipe: "flux", state: "starting", device: "GPU-B" }),
      ],
    };
    const rows = laneRows(all, running, status({}));
    expect(rows.map((r) => [r.key, r.warm, r.state, r.device])).toEqual([
      ["warm", true, "ready", "GPU-A"],
      ["flux", false, "loading", "GPU-B"],
    ]);
  });

  it("says a pinned recipe with no instance was evicted for the on-demand job", () => {
    const all = recipes([recipeEntry({ name: "warm", ...pinned })], ["warm"]);
    const [row] = laneRows(
      all,
      { instances: [] },
      status({ active_modality: "text2image", active_recipe: "flux" }),
    );
    expect(row).toMatchObject({
      state: "evicted",
      evictedFor: "flux",
      device: "GPU-A",
    });
  });

  it("calls a pinned recipe with no instance and nothing else loaded coming up", () => {
    const all = recipes([recipeEntry({ name: "warm", ...pinned })], ["warm"]);
    const [row] = laneRows(all, { instances: [] }, status({}));
    expect(row).toMatchObject({ state: "loading", evictedFor: null });
  });
});

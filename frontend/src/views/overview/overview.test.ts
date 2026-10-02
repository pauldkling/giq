// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from "vitest";
import type { Catalog, CatalogModel, JobRecord, Status } from "../../api/types";
import { bucketFor, cancelJob } from "./jobs";
import { laneRows } from "./laneRows";
import { applyPolicy } from "./policy";
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
    const [status, body] = replies.shift() ?? [500, { detail: "unexpected call" }];
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const ok = { state: {}, pinned: [], pinned_vram_gb: 0, vram_total_gb: 32, pinned_by_device: {}, warnings: [] };
const force409 = { detail: "pinned set needs 40 GB of 32 GB; pass force=true to pin anyway" };

describe("applyPolicy", () => {
  it("posts the policy without force first", async () => {
    const calls = mockFetch([[200, ok]]);
    const confirm = vi.fn();
    const out = await applyPolicy("llm", "gemma", "off", confirm);
    expect(out.kind).toBe("applied");
    expect(calls).toEqual([{ url: "/control/models/llm/gemma", method: "POST", body: { policy: "off", force: false } }]);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks on a force-able 409 and retries with force when confirmed", async () => {
    const calls = mockFetch([[409, force409], [200, ok]]);
    const confirm = vi.fn(async () => true);
    const out = await applyPolicy("llm", "gemma", "pinned", confirm);
    expect(confirm).toHaveBeenCalledWith(force409.detail);
    expect(out.kind).toBe("applied");
    expect(calls.map((c) => (c.body as { force: boolean }).force)).toEqual([false, true]);
  });

  it("stops at the 409 when the operator declines", async () => {
    const calls = mockFetch([[409, force409]]);
    const out = await applyPolicy("llm", "gemma", "pinned", async () => false);
    expect(out).toEqual({ kind: "refused", detail: force409.detail });
    expect(calls).toHaveLength(1);
  });

  it("never offers the override on a 409 without force=true", async () => {
    mockFetch([[409, { detail: "two LLMs on one card" }]]);
    const confirm = vi.fn();
    await expect(applyPolicy("llm", "gemma", "pinned", confirm)).rejects.toMatchObject({ status: 409 });
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("cancelJob", () => {
  it("sends DELETE /jobs/{id}", async () => {
    const calls = mockFetch([[200, { cancelled: true }]]);
    expect(await cancelJob("ab12")).toEqual({ cancelled: true });
    expect(calls[0]).toMatchObject({ url: "/jobs/ab12", method: "DELETE" });
  });

  it("reports a job that is already gone instead of throwing", async () => {
    mockFetch([[404, { detail: "Job not found" }]]);
    expect(await cancelJob("gone")).toEqual({ cancelled: false, reason: "Job not found" });
  });

  it("passes a started job's refusal through", async () => {
    mockFetch([[200, { cancelled: false, reason: "Job already running" }]]);
    expect(await cancelJob("x")).toEqual({ cancelled: false, reason: "Job already running" });
  });
});

const job = (over: Partial<JobRecord>): JobRecord => ({
  t: 1000, job_id: "j", modality: "llm", recipe: "m", status: "completed", queue_ms: 1,
  run_ms: 1000, tasks: 1, error: null, tokens_in: 10, tokens_out: 50, ...over,
});

describe("throughput", () => {
  it("is output tokens over run time across the window", () => {
    const r = throughput([job({ tokens_out: 100, run_ms: 1000 }), job({ tokens_out: 50, run_ms: 1500 })], 1100);
    expect(r).toEqual({ rate: 60, jobs: 2, tokens: 150 });
  });

  it("ignores old, failed and token-less jobs", () => {
    const r = throughput(
      [job({ t: 100 }), job({ status: "failed" }), job({ modality: "text2image", tokens_out: null })],
      1100,
    );
    expect(r.rate).toBeNull();
    expect(r.jobs).toBe(0);
  });
});

it("buckets the timeline like the old dashboard", () => {
  expect([24, 168, 720, 2160].map(bucketFor)).toEqual([3600, 21600, 86400, 86400]);
});

const model = (over: Partial<CatalogModel>): CatalogModel =>
  ({ worker: "llm", model: "m", resident: false, ready: false, effective_device: "GPU-A", ...over }) as CatalogModel;

describe("laneRows", () => {
  const status = (over: Partial<Status>) => ({ active: [], active_worker: null, active_model: null, ...over }) as Status;

  it("lists residents and the batch slot, and nothing else", () => {
    const catalog = {
      models: [
        model({ model: "warm", resident: true, ready: true }),
        model({ model: "cold" }),
        model({ worker: "text2image", model: "flux" }),
      ],
    } as Catalog;
    const rows = laneRows(
      catalog,
      status({ active: [{ device: "GPU-B", modality: "text2image", recipe: "flux", ready: false }] }),
    );
    expect(rows.map((r) => [r.key, r.warm, r.state, r.device])).toEqual([
      ["llm/warm", true, "ready", "GPU-A"],
      ["text2image/flux", false, "loading", "GPU-B"],
    ]);
  });

  it("says a missing resident was evicted for the batch job", () => {
    const catalog = { models: [model({ model: "warm", resident: true })] } as Catalog;
    const [row] = laneRows(catalog, status({ active_modality: "text2image", active_recipe: "flux" }));
    expect(row).toMatchObject({ state: "evicted", evictedFor: "text2image/flux" });
  });
});

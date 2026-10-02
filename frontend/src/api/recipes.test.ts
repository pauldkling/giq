// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearResidency,
  deleteWeights,
  setCard,
  setResidency,
} from "./recipes";

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

const ok = { recipe: {}, cards: [], warnings: [] };
const force409 = {
  detail: "pinned set needs 40 GB of 32 GB; pass force=true to pin anyway",
};

describe("setResidency", () => {
  it("puts the policy without force first", async () => {
    const calls = mockFetch([[200, ok]]);
    const confirm = vi.fn();
    const out = await setResidency("gemma", "off", confirm);
    expect(out.ok).toBe(true);
    expect(calls).toEqual([
      {
        url: "/recipes/gemma/residency",
        method: "PUT",
        body: { policy: "off", force: false },
      },
    ]);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("asks on a force-able 409 and retries with force when confirmed", async () => {
    const calls = mockFetch([
      [409, force409],
      [200, ok],
    ]);
    const confirm = vi.fn(async () => true);
    const out = await setResidency("gemma", "pinned", confirm);
    expect(confirm).toHaveBeenCalledWith(force409.detail);
    expect(out).toMatchObject({ ok: true, forced: true });
    expect(calls.map((c) => (c.body as { force: boolean }).force)).toEqual([
      false,
      true,
    ]);
  });

  it("stops at the 409 when the operator declines", async () => {
    const calls = mockFetch([[409, force409]]);
    const out = await setResidency("gemma", "pinned", async () => false);
    expect(out).toEqual({ ok: false, declined: force409.detail });
    expect(calls).toHaveLength(1);
  });

  it("never offers the override on a 409 without force=true", async () => {
    mockFetch([[409, { detail: "two LLMs on one card" }]]);
    const confirm = vi.fn();
    await expect(
      setResidency("gemma", "pinned", confirm),
    ).rejects.toMatchObject({ status: 409 });
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("the other writes", () => {
  it("binds, clears and deletes by name and id", async () => {
    const calls = mockFetch([
      [200, ok],
      [200, ok],
      [
        200,
        { id: "abc", recipes: [], deleted: [], missing: [], freed_bytes: 0 },
      ],
    ]);
    await setCard("flux_klein", "GPU-1", vi.fn());
    await clearResidency("flux_klein");
    await deleteWeights("abc");
    expect(calls.map((c) => [c.method, c.url, c.body])).toEqual([
      ["PUT", "/recipes/flux_klein/card", { device: "GPU-1", force: false }],
      ["DELETE", "/recipes/flux_klein/residency", undefined],
      ["DELETE", "/weights/abc", undefined],
    ]);
  });
});

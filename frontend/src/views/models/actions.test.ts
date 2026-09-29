// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import i18next from "i18next";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import type { DeleteWeightsResponse } from "../../api/types";
import de from "../../locales/de/models.json";
import en from "../../locales/en/models.json";
import { deleteSummary, deleteWeights, revertPolicy, setDevice, setPolicy } from "./actions";

/* The mutations against a mocked fetch: nothing here reaches a giq. */

type Call = { url: string; method: string; body: unknown };

function mockFetch(...responses: [number, unknown][]) {
  const calls: Call[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({
      url,
      method: init.method ?? "GET",
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const [status, body] = responses.shift() ?? [500, { detail: "unexpected call" }];
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const OVERCOMMIT = "pinning qwen needs 30.0 GB, 24.0 GB free on RTX 5090; retry with force=true to pin anyway";
const policyOk = { state: { device_name: "NVIDIA GeForce RTX 5090" }, warnings: ["over budget"] };

describe("setPolicy — the 409 force protocol", () => {
  it("confirms an over-commit with the server's detail, then retries with force", async () => {
    const calls = mockFetch([409, { detail: OVERCOMMIT }], [200, policyOk]);
    const confirm = vi.fn(async () => true);
    const r = await setPolicy("llm", "qwen3.8-27b", "pinned", confirm);
    expect(confirm).toHaveBeenCalledExactlyOnceWith(OVERCOMMIT);
    expect(r).toEqual({ ok: true, result: policyOk, forced: true });
    expect(calls).toEqual([
      { url: "/control/models/llm/qwen3.8-27b", method: "POST", body: { policy: "pinned", force: false } },
      { url: "/control/models/llm/qwen3.8-27b", method: "POST", body: { policy: "pinned", force: true } },
    ]);
  });

  it("stops when the operator declines, without a second request", async () => {
    const calls = mockFetch([409, { detail: OVERCOMMIT }]);
    const r = await setPolicy("llm", "qwen3.8-27b", "pinned", async () => false);
    expect(r).toEqual({ ok: false, declined: OVERCOMMIT });
    expect(calls).toHaveLength(1);
  });

  it("offers no override for a 409 without force=true", async () => {
    mockFetch([409, { detail: "another LLM is already bound to this card" }]);
    const confirm = vi.fn(async () => true);
    const err = await setPolicy("llm", "a", "pinned", confirm).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("passes a success straight through", async () => {
    const calls = mockFetch([200, policyOk]);
    const confirm = vi.fn(async () => true);
    const r = await setPolicy("tts", "kokoro", "off", confirm);
    expect(r).toEqual({ ok: true, result: policyOk, forced: false });
    expect(confirm).not.toHaveBeenCalled();
    expect(calls[0]!.body).toEqual({ policy: "off", force: false });
  });

  it("throws when the forced retry fails too", async () => {
    mockFetch([409, { detail: OVERCOMMIT }], [500, { detail: "boom" }]);
    await expect(setPolicy("llm", "a", "pinned", async () => true)).rejects.toMatchObject({ status: 500 });
  });
});

describe("setDevice", () => {
  it("binds with the same force protocol on …/device", async () => {
    const calls = mockFetch([409, { detail: "does not fit; force=true binds anyway" }], [200, policyOk]);
    const r = await setDevice("llm", "gemma-4-12b", "GPU-1", async () => true);
    expect(r.ok).toBe(true);
    expect(calls.map((c) => [c.url, c.body])).toEqual([
      ["/control/models/llm/gemma-4-12b/device", { device: "GPU-1", force: false }],
      ["/control/models/llm/gemma-4-12b/device", { device: "GPU-1", force: true }],
    ]);
  });

  it("sends null to unbind", async () => {
    const calls = mockFetch([200, policyOk]);
    await setDevice("llm", "gemma-4-12b", null, async () => true);
    expect(calls[0]!.body).toEqual({ device: null, force: false });
  });
});

describe("revertPolicy", () => {
  it("DELETEs the override", async () => {
    const calls = mockFetch([200, {}]);
    await revertPolicy("audio", "whisper-large-v3");
    expect(calls).toEqual([{ url: "/control/models/audio/whisper-large-v3", method: "DELETE", body: undefined }]);
  });
});

const deleted: DeleteWeightsResponse = {
  worker: "llm",
  model: "gemma-4-31b-it",
  deleted: ["/m/a.gguf"],
  skipped_shared: [
    { path: "/m/b", shared_with: ["x/y"] },
    { path: "/m/c", shared_with: ["x/y"] },
  ],
  missing: [],
  freed_bytes: 18_323_726_560,
};

describe("deleteWeights", () => {
  it("DELETEs /storage/models/{w}/{m}, encoding the name", async () => {
    const calls = mockFetch([200, deleted]);
    const r = await deleteWeights("text2image", "flux klein");
    expect(r).toEqual(deleted);
    expect(calls).toEqual([{ url: "/storage/models/text2image/flux%20klein", method: "DELETE", body: undefined }]);
  });

  it("surfaces the server's refusal", async () => {
    mockFetch([409, { detail: "model is loaded" }]);
    await expect(deleteWeights("llm", "a")).rejects.toMatchObject({ status: 409, detail: "model is loaded" });
  });
});

describe("deleteSummary", () => {
  const i18n = i18next.createInstance();
  beforeAll(async () => {
    await i18n.init({
      lng: "en",
      resources: { en: { models: en }, de: { models: de } },
      defaultNS: "models",
      interpolation: { escapeValue: false },
    });
  });
  const bytes = (b: number) => `${(b / 1e9).toFixed(1)} GB`;

  it("counts files with the right plural, in English and German", async () => {
    const one = { ...deleted, skipped_shared: [] };
    await i18n.changeLanguage("en");
    expect(deleteSummary(i18n.t, "llm/x", one, bytes)).toBe("llm/x: deleted 1 file, freed 18.3 GB.");
    expect(deleteSummary(i18n.t, "llm/x", { ...deleted, deleted: ["a", "b"] }, bytes)).toBe(
      "llm/x: deleted 2 files, freed 18.3 GB. Kept 2 shared files.",
    );
    await i18n.changeLanguage("de");
    expect(deleteSummary(i18n.t, "llm/x", deleted, bytes)).toBe(
      "llm/x: 1 Datei gelöscht, 18.3 GB frei geworden. 2 geteilte Dateien behalten.",
    );
  });
});

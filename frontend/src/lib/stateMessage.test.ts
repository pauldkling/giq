// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { Status } from "../api/types";
import { stateMessage } from "./stateMessage";

const status = (over: Partial<Status>): Status =>
  ({
    paused: false,
    jobs_running: [],
    jobs_pending: [],
    active_worker: null,
    active_model: null,
    vram_ok: true,
    vram_free_gb: 20,
    ...over,
  }) as Status;

describe("stateMessage", () => {
  it("follows the server's branches, in its order", () => {
    expect(stateMessage(status({})).key).toBe("idle");
    expect(stateMessage(status({ paused: true, jobs_running: ["a"] })).key).toBe("paused");
    expect(stateMessage(status({ jobs_running: ["a", "b"], active_modality: "llm" }))).toEqual({
      key: "running",
      params: { count: 2 },
    });
    expect(stateMessage(status({ active_modality: "llm", active_recipe: "m", jobs_pending: ["x"] }))).toEqual({
      key: "loaded",
      params: { worker: "llm", model: "m" },
    });
    expect(stateMessage(status({ jobs_pending: ["x"] }))).toEqual({ key: "queued", params: { count: 1 } });
    expect(stateMessage(status({ jobs_pending: ["x", "y"], vram_ok: false, vram_free_gb: 1.5 }))).toEqual({
      key: "blocked",
      params: { count: 2, free: 1.5 },
    });
  });

  it("quotes the free VRAM of the card the blocked job waits on", () => {
    const gpus = [
      { uuid: "big", vram_free_gb: 27.1 },
      { uuid: "small", vram_free_gb: 3.2 },
    ] as Status["gpus"];
    const s = status({ jobs_pending: ["x"], vram_ok: false, vram_free_gb: 27.1, vram_blocked_gpu: "small", gpus });
    expect(stateMessage(s)).toEqual({ key: "blocked", params: { count: 1, free: 3.2 } });
  });
});

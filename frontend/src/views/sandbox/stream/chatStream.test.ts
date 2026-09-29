// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { ApiError } from "../../../api/client";
import type { ChatChunk } from "../../../api/types";
import {
  initialStreamState,
  runChatStream,
  streamReducer,
  streamSummary,
  type StreamEvent,
  type StreamState,
} from "./chatStream";

const think = (t: string): ChatChunk => ({ choices: [{ index: 0, delta: { reasoning_content: t } }] });
const say = (t: string): ChatChunk => ({ choices: [{ index: 0, delta: { content: t } }] });
const fin = (reason: string, tokens = 10): ChatChunk => ({
  choices: [{ index: 0, delta: {}, finish_reason: reason }],
  usage: { prompt_tokens: 3, completion_tokens: tokens, total_tokens: tokens + 3 },
});

/** Run a scripted stream through the reducer; `between` may inject UI events mid-stream. */
async function play(
  chunks: (ChatChunk | Error)[],
  opts: { abortAfter?: number; between?: (i: number) => StreamEvent | null } = {},
): Promise<{ state: StreamState; trail: StreamState[] }> {
  let state = initialStreamState;
  const trail: StreamState[] = [];
  const ctrl = new AbortController();
  let clock = 1000;
  async function* gen(signal: AbortSignal): AsyncGenerator<ChatChunk> {
    for (let i = 0; i < chunks.length; i++) {
      if (opts.abortAfter === i) ctrl.abort();
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      const c = chunks[i]!;
      if (c instanceof Error) throw c;
      yield c;
      const extra = opts.between?.(i);
      if (extra) state = streamReducer(state, extra);
    }
  }
  await runChatStream({
    open: gen,
    signal: ctrl.signal,
    now: () => (clock += 500),
    dispatch: (e) => {
      state = streamReducer(state, e);
      trail.push(state);
    },
  });
  return { state, trail };
}

describe("chat stream state machine", () => {
  it("reveals the thought, then folds it when the answer starts", async () => {
    const { state, trail } = await play([think("Hmm, "), think("light scatters."), say("Rayleigh "), say("scattering."), fin("stop", 42)]);
    const firstThink = trail.find((s) => s.thought)!;
    expect(firstThink.thoughtVisible).toBe(true);
    expect(firstThink.thoughtOpen).toBe(true);
    expect(state.thought).toBe("Hmm, light scatters.");
    expect(state.answer).toBe("Rayleigh scattering.");
    expect(state.thoughtOpen).toBe(false);
    expect(state.phase).toBe("done");
    const sum = streamSummary(state);
    expect(sum.tokens).toBe(42);
    expect(sum.thoughtChars).toBe(20);
    expect(sum.seconds).toBeCloseTo(0.5, 5); // the clock is read at start and end only
    expect(sum.tokPerSec).toBeCloseTo(84, 5);
    expect(sum.empty).toBeNull();
  });

  it("keeps the thought open when the reader scrolled away from the tail", async () => {
    const { state } = await play([think("a"), think("b"), say("answer"), fin("stop")], {
      between: (i) => (i === 1 ? { type: "follow", following: false } : null),
    });
    expect(state.thoughtOpen).toBe(true);
  });

  it("stops on abort and reports it", async () => {
    const { state } = await play([say("partial "), say("more"), say("never")], { abortAfter: 2 });
    expect(state.phase).toBe("stopped");
    expect(state.answer).toBe("partial more");
    const sum = streamSummary(state);
    expect(sum.stopped).toBe(true);
    expect(sum.empty).toBeNull();
  });

  it("turns an in-band error into the error phase", async () => {
    const { state } = await play([say("half"), new ApiError(200, "llama-server crashed")]);
    expect(state.phase).toBe("error");
    expect(state.error).toBe("llama-server crashed");
  });

  it("explains an empty answer truncated at the token ceiling", async () => {
    const { state } = await play([think("round and round"), fin("length", 32768)]);
    expect(state.answer).toBe("");
    expect(streamSummary(state).empty).toBe("length");
    expect(state.thoughtOpen).toBe(true);
  });

  it("tells an answer cut off at the ceiling from a plain empty one", async () => {
    const cut = await play([say("It is because"), fin("length")]);
    expect(streamSummary(cut.state).cutOff).toBe(true);
    const empty = await play([fin("stop")]);
    expect(streamSummary(empty.state).empty).toBe("plain");
  });

  it("starts each run from a clean slate", () => {
    const dirty: StreamState = { ...initialStreamState, answer: "old", thought: "old", phase: "done" };
    const s = streamReducer(dirty, { type: "start", at: 5 });
    expect(s).toMatchObject({ answer: "", thought: "", phase: "running", startedAt: 5 });
  });
});

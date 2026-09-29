// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import type { ChatCompletion, ChatMessage } from "../../../api/types";
import { THINKING_TOKEN_FLOOR } from "../constants";
import { execTool, runToolsLoop, type ToolStep } from "./toolsLoop";

const reply = (message: Partial<ChatMessage>): ChatCompletion => ({
  id: "x",
  model: "m",
  choices: [{ index: 0, message: { role: "assistant", content: null, ...message }, finish_reason: "stop" }],
});

const call = (id: string, name: string, args: string) => ({
  id,
  type: "function" as const,
  function: { name, arguments: args },
});

const env = { now: () => new Date(Date.UTC(2026, 0, 2, 3, 4, 5)), random: () => 0.5 };

describe("runToolsLoop", () => {
  it("runs requested tools in the browser and returns the final answer", async () => {
    const bodies: Record<string, unknown>[] = [];
    const replies = [
      reply({ tool_calls: [call("a", "roll_dice", '{"n":2,"sides":6}'), call("b", "get_current_time", "")] }),
      reply({ content: "You rolled 8." }),
    ];
    const steps: ToolStep[] = [];
    const out = await runToolsLoop({
      model: "gemma-4-12b",
      prompt: "roll",
      env,
      post: async (b) => {
        bodies.push(structuredClone(b));
        return replies.shift()!;
      },
      onStep: (s) => steps.push(s),
    });
    expect(out).toEqual({ answer: "You rolled 8.", rounds: 2 });
    expect(steps.map((s) => s.kind)).toEqual(["call", "result", "call", "result"]);
    expect(steps[1]).toEqual({ kind: "result", name: "roll_dice", value: '{"rolls":[4,4],"total":8}' });
    expect(bodies[0]).toMatchObject({ model: "gemma-4-12b", max_tokens: THINKING_TOKEN_FLOOR });
    const second = bodies[1]!.messages as ChatMessage[];
    expect(second.map((m) => m.role)).toEqual(["user", "assistant", "tool", "tool"]);
    expect(second[2]).toMatchObject({ tool_call_id: "a", content: '{"rolls":[4,4],"total":8}' });
  });

  it("gives up after the round limit", async () => {
    const out = await runToolsLoop({
      model: "m",
      prompt: "loop",
      env,
      maxRounds: 4,
      post: async () => reply({ tool_calls: [call("c", "get_current_time", "{}")] }),
      onStep: () => {},
    });
    expect(out).toEqual({ answer: null, rounds: 4 });
  });

  it("surfaces unparseable arguments and server errors", async () => {
    await expect(
      runToolsLoop({ model: "m", prompt: "", env, post: async () => reply({ tool_calls: [call("d", "roll_dice", "{nope")] }), onStep: () => {} }),
    ).rejects.toThrow(/not JSON/);
    await expect(
      runToolsLoop({ model: "m", prompt: "", env, post: async () => Promise.reject(new Error("503 paused")), onStep: () => {} }),
    ).rejects.toThrow("503 paused");
  });
});

describe("execTool", () => {
  it("answers unknown tools with an error object", () => {
    expect(execTool("rm_rf", {}, env)).toEqual({ error: "unknown tool" });
  });
});

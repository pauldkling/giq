// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ChatCompletion, ChatMessage } from "../../../api/types";
import { THINKING_TOKEN_FLOOR, TOOLS_MAX_ROUNDS } from "../constants";

/* OpenAI-style tool calling (the MCP wire pattern): the model asks for a
   tool, the sandbox runs it here in the browser, the result goes back as a
   `tool` message, and the model composes the answer. Kept free of fetch and
   React so the loop is testable with scripted replies. */

export const TOOLS = [
  {
    type: "function",
    function: {
      name: "get_current_time",
      description: "Current local date and time",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "roll_dice",
      description: "Roll N dice with S sides, returns the individual rolls",
      parameters: {
        type: "object",
        properties: {
          n: { type: "integer", description: "number of dice" },
          sides: { type: "integer", description: "sides per die" },
        },
        required: ["n", "sides"],
      },
    },
  },
] as const;

export interface ToolEnv {
  now: () => Date;
  random: () => number;
}

const browserEnv: ToolEnv = { now: () => new Date(), random: Math.random };

export function execTool(name: string, args: Record<string, unknown>, env: ToolEnv = browserEnv): unknown {
  if (name === "get_current_time") return { now: env.now().toString() };
  if (name === "roll_dice") {
    // Bounded: the arguments are model output, and a wild n should not hang the tab.
    const n = Math.min(100, Math.max(1, Math.floor(Number(args.n) || 1)));
    const sides = Math.min(1000, Math.max(2, Math.floor(Number(args.sides) || 6)));
    const rolls = Array.from({ length: n }, () => 1 + Math.floor(env.random() * sides));
    return { rolls, total: rolls.reduce((a, b) => a + b, 0) };
  }
  return { error: "unknown tool" };
}

export type ToolStep =
  | { kind: "call"; name: string; args: string }
  | { kind: "result"; name: string; value: string };

export interface ToolsOutcome {
  /** The model's final text; null when it was still calling tools after the last round. */
  answer: string | null;
  rounds: number;
}

export async function runToolsLoop(opts: {
  model: string;
  prompt: string;
  post: (body: Record<string, unknown>) => Promise<ChatCompletion>;
  onStep: (step: ToolStep) => void;
  env?: ToolEnv;
  maxRounds?: number;
}): Promise<ToolsOutcome> {
  const { model, prompt, post, onStep, env, maxRounds = TOOLS_MAX_ROUNDS } = opts;
  // `name` on a tool message is what older OpenAI clients send; llama-server accepts it.
  const messages: (ChatMessage & { name?: string })[] = [{ role: "user", content: prompt }];
  for (let round = 1; round <= maxRounds; round++) {
    // Same floor as the chat panel: the tool model thinks by default and this panel never opts out.
    const d = await post({ model, messages, tools: TOOLS, max_tokens: THINKING_TOKEN_FLOOR });
    const msg = d.choices[0]?.message;
    if (!msg) throw new Error("no choices in the response");
    if (msg.tool_calls?.length) {
      messages.push(msg);
      for (const tc of msg.tool_calls) {
        const raw = tc.function.arguments || "{}";
        onStep({ kind: "call", name: tc.function.name, args: raw });
        let args: Record<string, unknown>;
        try {
          args = JSON.parse(raw) as Record<string, unknown>;
        } catch {
          throw new Error(`${tc.function.name}: arguments are not JSON: ${raw.slice(0, 200)}`);
        }
        const value = JSON.stringify(execTool(tc.function.name, args, env));
        onStep({ kind: "result", name: tc.function.name, value });
        messages.push({ role: "tool", tool_call_id: tc.id, name: tc.function.name, content: value });
      }
      continue;
    }
    return { answer: typeof msg.content === "string" ? msg.content : "", rounds: round };
  }
  return { answer: null, rounds: maxRounds };
}

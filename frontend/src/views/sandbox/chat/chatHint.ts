// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Fit, Policy } from "../../../api/types";
import { THINKING_TOKEN_FLOOR } from "../constants";
import type { ModelOption } from "../models";

/* Thinking needs both halves: the request has to ask for it, and the server
   has to have been started in a state that allows it.

   Verified on qwen3.6-27b, launched with `--reasoning on`: a request
   carrying chat_template_kwargs.enable_thinking=false still came back with
   no reasoning and a complete answer inside 512 tokens. The per-request
   opt-out wins over the server flag, so "the model can reason" is NOT on its
   own a reason to inflate the budget — this panel opts out by default. A
   model launched --reasoning off stays quiet either way. */
export const mayThink = (thinking: boolean, reasoning: ModelOption["reasoning"] | undefined) =>
  thinking && reasoning !== "off";

/** The max_tokens to use after the model or the Thinking switch changed: raised to the floor, never lowered. */
export function raisedMaxTokens(
  thinking: boolean,
  reasoning: ModelOption["reasoning"] | undefined,
  maxTokens: number,
): number {
  // A bigger budget set by hand stands.
  return mayThink(thinking, reasoning) && maxTokens < THINKING_TOKEN_FLOOR ? THINKING_TOKEN_FLOOR : maxTokens;
}

export type LoadHint = "off" | "loaded" | "evicts" | "loads";
export type ThinkHint = "raised" | "canThink" | "noEffect" | null;

export interface ChatHint {
  load: LoadHint;
  think: ThinkHint;
}

export function chatHint(opts: {
  fit: Fit | undefined;
  policy: Policy | undefined;
  reasoning: ModelOption["reasoning"] | undefined;
  thinking: boolean;
  /** max_tokens was just raised to the floor by the last change. */
  raised: boolean;
}): ChatHint {
  const canThink = opts.reasoning !== "off";
  /* An `off` model does not load at all — it refuses the job. Saying "waits
     for it to load" would send you off to watch a spinner that never ends. */
  if (opts.policy === "off") return { load: "off", think: null };
  const load: LoadHint =
    opts.fit === "loaded" ? "loaded" : opts.fit === "fits_after_eviction" ? "evicts" : "loads";
  const think: ThinkHint = opts.raised
    ? "raised"
    : canThink && !opts.thinking
      ? "canThink"
      : !canThink && opts.thinking
        ? "noEffect"
        : null;
  return { load, think };
}

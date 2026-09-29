// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { errorText, isAbort } from "../../../api/client";
import type { ChatChunk, ChatUsage } from "../../../api/types";

/* The state machine behind every panel that streams a chat completion (chat,
   image + question): a live answer, a folded thinking channel, an elapsed
   clock that starts before the first token, and a Stop that reaches the GPU.
   Panels differ only in what they send. It is plain data plus a reducer so
   the transitions are testable without a DOM. */

export type StreamPhase = "idle" | "running" | "done" | "stopped" | "error";

export interface StreamState {
  phase: StreamPhase;
  thought: string;
  answer: string;
  /** The thinking block appears on the first thought and stays for the run. */
  thoughtVisible: boolean;
  thoughtOpen: boolean;
  /** Following the tail of the thought (the reader has not scrolled up). */
  following: boolean;
  /** Stop was pressed and the abort is on its way. */
  stopping: boolean;
  usage: ChatUsage | null;
  /* Dropping finish_reason is how a run that hit the token ceiling looks
     identical to one that simply had nothing to say. */
  finishReason: string | null;
  error: string | null;
  /** performance.now() at Run, and at the end. */
  startedAt: number;
  endedAt: number | null;
}

export const initialStreamState: StreamState = {
  phase: "idle",
  thought: "",
  answer: "",
  thoughtVisible: false,
  thoughtOpen: false,
  following: true,
  stopping: false,
  usage: null,
  finishReason: null,
  error: null,
  startedAt: 0,
  endedAt: null,
};

export type StreamEvent =
  | { type: "start"; at: number }
  | { type: "think"; text: string }
  | { type: "answer"; text: string }
  | { type: "meta"; usage?: ChatUsage | null; finishReason?: string | null }
  | { type: "stopping" }
  | { type: "end"; at: number; stopped: boolean }
  | { type: "error"; at: number; message: string }
  | { type: "toggleThought"; open: boolean }
  | { type: "follow"; following: boolean };

export function streamReducer(s: StreamState, e: StreamEvent): StreamState {
  switch (e.type) {
    case "start":
      return { ...initialStreamState, phase: "running", startedAt: e.at };
    case "think":
      if (!s.thoughtVisible) {
        /* Revealed (and labelled) on the first thought, not at the end: with
           thinking on the answer can be minutes away (measured 153 s for a
           13k-token think), and an unlabelled box for all of it reads as a
           stuck UI. */
        return { ...s, thoughtVisible: true, thoughtOpen: true, following: true, thought: e.text };
      }
      return { ...s, thought: s.thought + e.text };
    case "answer": {
      /* Fold the thought away when the answer starts — you wanted to know it
         was thinking, not to keep reading it afterwards. Unless you are
         mid-read: having scrolled up is exactly the signal that collapsing
         the box would be the wrong thing to do. Only the first answer token
         folds it: reopened by hand afterwards, it stays open. */
      const fold = s.answer === "" && s.thoughtVisible && s.thoughtOpen && s.following;
      return { ...s, answer: s.answer + e.text, thoughtOpen: fold ? false : s.thoughtOpen };
    }
    case "meta":
      return {
        ...s,
        usage: e.usage ?? s.usage,
        finishReason: e.finishReason ?? s.finishReason,
      };
    case "stopping":
      return { ...s, stopping: true };
    case "end":
      return { ...s, phase: e.stopped ? "stopped" : "done", stopping: false, endedAt: e.at };
    case "error":
      return { ...s, phase: "error", stopping: false, error: e.message, endedAt: e.at };
    case "toggleThought":
      return { ...s, thoughtOpen: e.open };
    case "follow":
      return { ...s, following: e.following };
  }
}

/** Route one SSE chunk: answer and thought arrive on separate delta channels. */
export function chunkEvents(chunk: ChatChunk): StreamEvent[] {
  const out: StreamEvent[] = [];
  const choice = chunk.choices?.[0];
  /* The final chunk carries usage — the only place a streamed response
     reports its token count — and finish_reason says why it stopped. */
  if (chunk.usage || choice?.finish_reason) {
    out.push({ type: "meta", usage: chunk.usage ?? null, finishReason: choice?.finish_reason ?? null });
  }
  const delta = choice?.delta;
  if (delta?.reasoning_content) out.push({ type: "think", text: delta.reasoning_content });
  if (delta?.content) out.push({ type: "answer", text: delta.content });
  return out;
}

export interface RunStreamArgs {
  /** Opens the stream (normally api.stream on /v1/chat/completions). */
  open: (signal: AbortSignal) => AsyncIterable<ChatChunk>;
  dispatch: (e: StreamEvent) => void;
  signal: AbortSignal;
  now?: () => number;
}

/** Drive one run to its end. Never throws: failures become an "error" event. */
export async function runChatStream({ open, dispatch, signal, now = () => performance.now() }: RunStreamArgs) {
  dispatch({ type: "start", at: now() });
  try {
    for await (const chunk of open(signal)) {
      for (const e of chunkEvents(chunk)) dispatch(e);
    }
    dispatch({ type: "end", at: now(), stopped: false });
  } catch (err) {
    if (isAbort(err) || signal.aborted) dispatch({ type: "end", at: now(), stopped: true });
    /* A job that fails after headers are sent reports itself in-band, and
       api.stream throws it; without that the answer would just stop and
       look complete. */
    else dispatch({ type: "error", at: now(), message: errorText(err) });
  }
}

export interface StreamSummary {
  seconds: number;
  tokens: number | null;
  tokPerSec: number | null;
  thoughtChars: number;
  stopped: boolean;
  /** The answer exists but was cut off at max_tokens. */
  cutOff: boolean;
  /* "It stopped and there is nothing here" is the one outcome that needs
     explaining, and the server always says why. A thinking model that hits
     the ceiling mid-thought returns finish_reason "length" with an empty
     answer — measured live, a thought can run the full 32,768 tokens and
     never open the answer channel. */
  empty: "length" | "plain" | null;
}

/** The final stats line and the empty-answer diagnosis of a finished run. */
export function streamSummary(s: StreamState, at: number = s.endedAt ?? 0): StreamSummary {
  const seconds = Math.max(0, (at - s.startedAt) / 1000);
  const tokens = s.usage?.completion_tokens || null;
  const stopped = s.phase === "stopped";
  const length = s.finishReason === "length";
  return {
    seconds,
    tokens,
    tokPerSec: tokens && seconds > 0 ? tokens / seconds : null,
    thoughtChars: s.thought.length,
    stopped,
    cutOff: length && s.answer !== "",
    empty: s.answer || stopped || s.phase !== "done" ? null : length ? "length" : "plain",
  };
}

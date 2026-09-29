// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { stream } from "../../../api/client";
import type { ChatChunk } from "../../../api/types";
import { initialStreamState, runChatStream, streamReducer, type StreamEvent, type StreamState } from "./chatStream";

/** How often the elapsed clock redraws while a run is live. */
const TICK_MS = 100;

export interface ChatStream {
  state: StreamState;
  /** performance.now(), refreshed every 100 ms while running. */
  now: number;
  running: boolean;
  run: (body: Record<string, unknown>) => Promise<void>;
  /** Abort the request; llama-server stops generating when the connection drops. */
  stop: () => void;
  dispatch: (e: StreamEvent) => void;
}

export function useChatStream(): ChatStream {
  const [state, dispatch] = useReducer(streamReducer, initialStreamState);
  const [now, setNow] = useState(0);
  const ctrl = useRef<AbortController | null>(null);
  const running = state.phase === "running";

  /* Elapsed ticks from the moment Run is pressed, not from the first token —
     the wait for a queue slot or a 26 GB load is part of what you are
     watching, and it is the part that used to look like nothing happening. */
  useEffect(() => {
    if (!running) return;
    setNow(performance.now());
    const id = setInterval(() => setNow(performance.now()), TICK_MS);
    return () => clearInterval(id);
  }, [running]);

  // Leaving the sandbox ends the generation rather than leaving it running unseen.
  useEffect(() => () => ctrl.current?.abort(), []);

  const run = useCallback(async (body: Record<string, unknown>) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    await runChatStream({
      open: (signal) => stream<ChatChunk>("/v1/chat/completions", { ...body, stream: true }, { signal }),
      dispatch: (e) => {
        if (ctrl.current === c) dispatch(e);
      },
      signal: c.signal,
    });
  }, []);

  const stop = useCallback(() => {
    if (!ctrl.current || ctrl.current.signal.aborted) return;
    dispatch({ type: "stopping" });
    ctrl.current.abort();
  }, []);

  useDevFixture(dispatch);

  return { state, now, running, run, stop, dispatch };
}

/* Dev-only: #/sandbox/<tab>?fixture=1 plays a canned conversation into the
   panel so its rendering can be looked at without sending a request to a
   live GPU. Compiled out of the production build. */
function useDevFixture(dispatch: (e: StreamEvent) => void) {
  useEffect(() => {
    if (!import.meta.env.DEV || !/[?&]fixture=1\b/.test(window.location.hash)) return;
    void import("./devFixture").then(({ FIXTURE_EVENTS }) => FIXTURE_EVENTS.forEach(dispatch));
  }, [dispatch]);
}

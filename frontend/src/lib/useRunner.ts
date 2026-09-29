// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { errorText, isAbort } from "../api/client";

/* One request at a time for a panel that waits for a whole result (images,
   transcripts, audio): busy flag, latency, error, and the result. The
   request is aborted when the sandbox goes away; for /run?wait=true giq
   cancels the job on disconnect while it is still queued, and a job already
   on the GPU runs to completion unseen. */

export interface RunnerState<T> {
  busy: boolean;
  result: T | null;
  error: string | null;
  /** Wall time of the last finished run, request to response. */
  ms: number | null;
  /** A run has been started at least once (the output card is shown). */
  started: boolean;
}

export function useRunner<T>() {
  const [s, set] = useState<RunnerState<T>>({ busy: false, result: null, error: null, ms: null, started: false });
  const ctrl = useRef<AbortController | null>(null);
  useEffect(() => () => ctrl.current?.abort(), []);

  const run = useCallback(async (work: (signal: AbortSignal) => Promise<T>) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    set((p) => ({ ...p, busy: true, error: null, started: true }));
    const t0 = performance.now();
    try {
      const result = await work(c.signal);
      if (!c.signal.aborted) set({ busy: false, result, error: null, ms: performance.now() - t0, started: true });
    } catch (e) {
      if (c.signal.aborted || isAbort(e)) return;
      set({ busy: false, result: null, error: errorText(e), ms: null, started: true });
    }
  }, []);

  return { ...s, run };
}

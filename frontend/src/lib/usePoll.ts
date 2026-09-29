// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";

/* Poll an async source on an interval. Visibility-aware: a hidden tab stops
   asking (a dashboard left open in a background tab should not keep a GPU
   host's nvidia-smi busy) and catches up the moment it is shown again.
   refresh() fetches now and restarts the interval. A response that arrives
   after a newer request was started is dropped, so a slow poll can never
   overwrite a fresher one. */

export interface PollState<T> {
  data: T | undefined;
  error: unknown;
  /** True until the first response (or error) arrives. */
  loading: boolean;
  /** Epoch ms of the last successful fetch. */
  updatedAt: number | null;
  refresh: () => Promise<void>;
}

export interface PollOptions {
  /** 0 or Infinity = fetch once (and on refresh()). */
  intervalMs: number;
  /** false suspends polling and leaves the last data in place. */
  enabled?: boolean;
}

export function usePoll<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  { intervalMs, enabled = true }: PollOptions,
): PollState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const schedule = useCallback(
    (run: () => void) => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      if (!enabledRef.current || !intervalMs || !Number.isFinite(intervalMs)) return;
      if (typeof document !== "undefined" && document.hidden) return;
      timer.current = setTimeout(run, intervalMs);
    },
    [intervalMs],
  );

  const run = useCallback(async (): Promise<void> => {
    const mine = ++seq.current;
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    try {
      const result = await fetcherRef.current(ctl.signal);
      if (mine !== seq.current) return;
      setData(result);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (e) {
      if (mine !== seq.current || ctl.signal.aborted) return;
      setError(e);
    } finally {
      if (mine === seq.current) {
        setLoading(false);
        schedule(() => void run());
      }
    }
  }, [schedule]);

  useEffect(() => {
    if (!enabled) return;
    void run();
    const onVisible = () => {
      if (!document.hidden) void run();
      else if (timer.current) clearTimeout(timer.current);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      if (timer.current) clearTimeout(timer.current);
      seq.current++;
      controller.current?.abort();
    };
  }, [enabled, run]);

  return { data, error, loading, updatedAt, refresh: run };
}

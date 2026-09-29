// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef } from "react";
import { getJSON } from "../api/client";
import { usePoll, type PollOptions, type PollState } from "./usePoll";

export interface Tagged<T> {
  path: string;
  body: T;
}

/* usePoll over a GET whose URL follows the view's state (a range button, a
   filter). A new URL fetches at once instead of waiting out the interval,
   and each response carries the URL it answered, so a view can tell a reply
   for the old filter from one for the new and dim it rather than present it
   as the answer. The first render's URL is covered by usePoll's own first
   fetch; the effect only reacts to a change. */
export function usePathPoll<T>(path: string, { intervalMs, enabled = true }: PollOptions): PollState<Tagged<T>> {
  const current = useRef(path);
  current.current = path;
  const poll = usePoll(
    useCallback(async (signal: AbortSignal) => {
      const p = current.current;
      return { path: p, body: await getJSON<T>(p, { signal }) };
    }, []),
    { intervalMs, enabled },
  );
  const fetchedFor = useRef(path);
  const refresh = poll.refresh;
  useEffect(() => {
    if (fetchedFor.current === path) return;
    fetchedFor.current = path;
    if (enabled) void refresh();
  }, [path, enabled, refresh]);
  return poll;
}

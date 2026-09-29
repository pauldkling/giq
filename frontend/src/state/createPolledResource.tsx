// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { createContext, useCallback, useContext, type ReactNode } from "react";
import { getJSON } from "../api/client";
import { usePoll, type PollState } from "../lib/usePoll";

/* One poller per resource for the whole app. Views and components read the
   shared result through the hook; none of them starts its own interval for
   /status or /gpus, so opening three widgets does not triple the requests.
   Each resource gets its own context so a 3 s /status tick re-renders the
   status readers only, not every catalog consumer. */

export type Resource<T> = PollState<T>;

export function createPolledResource<T>(name: string, path: string, intervalMs: number) {
  const Ctx = createContext<Resource<T> | null>(null);
  Ctx.displayName = name;

  function Provider({ children }: { children: ReactNode }) {
    const fetcher = useCallback((signal: AbortSignal) => getJSON<T>(path, { signal }), []);
    const state = usePoll(fetcher, { intervalMs });
    return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
  }
  Provider.displayName = `${name}Provider`;

  function useResource(): Resource<T> {
    const v = useContext(Ctx);
    if (!v) throw new Error(`${name} used outside DataProvider`);
    return v;
  }

  return [Provider, useResource] as const;
}

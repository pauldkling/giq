// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { ApiError, getJSON } from "../../api/client";
import type { JobStatusResponse, Modality } from "../../api/types";

export interface JobInfo {
  worker: Modality;
  model: string;
}

/** undefined = still looking it up; null = the job is gone (finished and dropped, or cancelled). */
export type JobLookup = Record<string, JobInfo | null | undefined>;

/* /status lists queued and running jobs by id only. What each one is comes
   from GET /jobs/{id}, asked once per id: a job's worker and model never
   change, so a queue that sits for minutes does not cost a request per job
   every 3 s. Ids that leave the queue drop out of the cache. */
export function useJobDetails(ids: readonly string[]): JobLookup {
  const [known, setKnown] = useState<JobLookup>({});
  const asked = useRef(new Set<string>());
  const key = ids.join(",");

  useEffect(() => {
    const live = new Set(ids);
    for (const id of asked.current) if (!live.has(id)) asked.current.delete(id);
    setKnown((k) => {
      const kept = Object.fromEntries(Object.entries(k).filter(([id]) => live.has(id)));
      return Object.keys(kept).length === Object.keys(k).length ? k : kept;
    });
    for (const id of ids) {
      if (asked.current.has(id)) continue;
      asked.current.add(id);
      getJSON<JobStatusResponse>(`/jobs/${encodeURIComponent(id)}`)
        .then((j) => setKnown((k) => ({ ...k, [id]: { worker: j.modality, model: j.model } })))
        .catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 404) setKnown((k) => ({ ...k, [id]: null }));
          else asked.current.delete(id); // a network blip: ask again when the queue next changes
        });
    }
    // Keyed on the list's content: /status hands over a new array every 3 s.
  }, [key]);

  return known;
}

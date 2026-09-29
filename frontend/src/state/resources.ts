// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Catalog, EnginesResponse, GpusResponse, Status, StorageResponse } from "../api/types";
import { createPolledResource } from "./createPolledResource";

/** Poll cadence of /status and /gpus; the page header quotes it. */
export const LIVE_POLL_MS = 3000;
/** The catalog and disk report change on operator action, not by the second. */
export const SLOW_POLL_MS = 60_000;

/** GET /status every 3 s: service state, queue, pause, access posture, version. */
export const [StatusProvider, useStatus] = createPolledResource<Status>("Status", "/status", LIVE_POLL_MS);

/** GET /gpus every 3 s: per-card telemetry. */
export const [GpusProvider, useGpus] = createPolledResource<GpusResponse>("Gpus", "/gpus", LIVE_POLL_MS);

/** GET /stats/models every 60 s: the model catalog with fit, policy and binding. Call refresh() after changing a model. */
export const [CatalogProvider, useCatalog] = createPolledResource<Catalog>(
  "Catalog",
  "/stats/models",
  SLOW_POLL_MS,
);

/** GET /storage every 60 s: weights on disk and per-mount usage. Call refresh() after deleting weights. */
export const [StorageProvider, useStorage] = createPolledResource<StorageResponse>(
  "Storage",
  "/storage",
  SLOW_POLL_MS,
);

/** GET /engines once: engine binaries and their build strings (they change only on redeploy). */
export const [EnginesProvider, useEngines] = createPolledResource<EnginesResponse>(
  "Engines",
  "/engines",
  0,
);

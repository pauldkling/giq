// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { del, needsForce, postJSON } from "../../api/client";
import type { DeleteWeightsResponse, ModelPolicyResponse, Policy } from "../../api/types";

/* The Models view's mutations, free of React so the force protocol and the
   delete call are testable with a mocked fetch. The hook in
   useModelActions.ts binds them to the dialogs and the refreshes. */

const path = (worker: string, model: string) =>
  `/control/models/${encodeURIComponent(worker)}/${encodeURIComponent(model)}`;

export type Forced<T> = { ok: true; result: T; forced: boolean } | { ok: false; declined: string };

/* A change that would over-commit a card comes back 409 with "force=true"
   in the detail. The server's detail is the explanation, so it goes to the
   operator verbatim; confirming repeats the call with force. Any other
   failure — including a 409 without that marker, such as two LLMs on one
   card — throws, with no override offered. */
export async function withForce<T>(
  call: (force: boolean) => Promise<T>,
  confirmForce: (detail: string) => Promise<boolean>,
): Promise<Forced<T>> {
  try {
    return { ok: true, result: await call(false), forced: false };
  } catch (err) {
    if (!needsForce(err)) throw err;
    const detail = err.detail as string;
    if (!(await confirmForce(detail))) return { ok: false, declined: detail };
    return { ok: true, result: await call(true), forced: true };
  }
}

/** POST /control/models/{w}/{m} {policy, force}, confirming an over-commit. */
export function setPolicy(
  worker: string,
  model: string,
  policy: Policy,
  confirmForce: (detail: string) => Promise<boolean>,
): Promise<Forced<ModelPolicyResponse>> {
  return withForce(
    (force) => postJSON<ModelPolicyResponse>(path(worker, model), { policy, force }),
    confirmForce,
  );
}

/** POST /control/models/{w}/{m}/device {device, force}; null device = follow the default card. */
export function setDevice(
  worker: string,
  model: string,
  device: string | null,
  confirmForce: (detail: string) => Promise<boolean>,
): Promise<Forced<ModelPolicyResponse>> {
  return withForce(
    (force) => postJSON<ModelPolicyResponse>(`${path(worker, model)}/device`, { device, force }),
    confirmForce,
  );
}

/** DELETE /control/models/{w}/{m}: drop the operator's override, back to the configured default. */
export function revertPolicy(worker: string, model: string): Promise<unknown> {
  return del(path(worker, model));
}

/** DELETE /storage/models/{w}/{m}: remove the weights; files shared with other models stay. */
export function deleteWeights(worker: string, model: string): Promise<DeleteWeightsResponse> {
  return del<DeleteWeightsResponse>(
    `/storage/models/${encodeURIComponent(worker)}/${encodeURIComponent(model)}`,
  );
}

type T = (key: string, opts?: Record<string, unknown>) => string;

/** The result line after deleting weights, with plural-correct counts. */
export function deleteSummary(t: T, key: string, r: DeleteWeightsResponse, bytes: (b: number) => string): string {
  const done = t("delete.done", { key, count: r.deleted.length, freed: bytes(r.freed_bytes) });
  return r.skipped_shared.length
    ? `${done} ${t("delete.keptShared", { count: r.skipped_shared.length })}`
    : done;
}

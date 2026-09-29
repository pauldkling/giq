// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { needsForce, postJSON } from "../../api/client";
import type { ModelPolicyResponse, Policy } from "../../api/types";

export type PolicyOutcome =
  | { kind: "applied"; response: ModelPolicyResponse }
  /** The server refused (409 without an override, or the operator declined it). */
  | { kind: "refused"; detail: string };

/* Set a model's residency policy. A change that would over-commit a card
   comes back 409 with "force=true" in the detail: the operator sees that
   detail and may insist, in which case the call repeats with force. The
   server's refusal is surfaced verbatim rather than silently forced. Other
   failures throw (ApiError) for the caller to report. */
export async function applyPolicy(
  worker: string,
  model: string,
  policy: Policy,
  confirmForce: (detail: string) => Promise<boolean>,
): Promise<PolicyOutcome> {
  const path = `/control/models/${encodeURIComponent(worker)}/${encodeURIComponent(model)}`;
  try {
    return { kind: "applied", response: await postJSON<ModelPolicyResponse>(path, { policy, force: false }) };
  } catch (err) {
    if (!needsForce(err)) throw err;
    const detail = err.detail as string;
    if (!(await confirmForce(detail))) return { kind: "refused", detail };
    return { kind: "applied", response: await postJSON<ModelPolicyResponse>(path, { policy, force: true }) };
  }
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useFormat } from "../lib/useFormat";

/** A failure count: zero stays quiet, anything else in the critical ink. */
export function FailedCount({ n }: { n: number }) {
  const f = useFormat();
  return n ? <span className="text-critical">{f.num(n)}</span> : <>{f.num(0)}</>;
}

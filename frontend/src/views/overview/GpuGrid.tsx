// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { errorText, getJSON } from "../../api/client";
import type { StatsGpus } from "../../api/types";
import { EmptyState } from "../../components/EmptyState";
import { usePoll } from "../../lib/usePoll";
import { SLOW_POLL_MS, useGpus } from "../../state";
import { GpuCard } from "./GpuCard";
import type { LaneRow } from "./laneRows";

/* One card per GPU, keyed by UUID: a card that disappears or reorders keeps
   its identity, and the 3 s telemetry tick updates values in place. The
   six-hour trends are sampled server-side and refresh with the slow poll. */
export function GpuGrid({ rows }: { rows: LaneRow[] }) {
  const { t } = useTranslation("overview");
  const gpus = useGpus();
  const history = usePoll(
    useCallback((signal: AbortSignal) => getJSON<StatsGpus>("/stats/gpus?hours=6", { signal }), []),
    { intervalMs: SLOW_POLL_MS },
  );
  const byUuid = new Map(history.data?.gpus.map((h) => [h.uuid, h]));
  const nowS = (gpus.updatedAt ?? Date.now()) / 1000;
  const list = gpus.data?.gpus ?? [];

  if (!gpus.data) {
    return <EmptyState>{gpus.error ? t("common:empty.failed", { error: errorText(gpus.error) }) : t("gpus.loading")}</EmptyState>;
  }
  if (!list.length) return <EmptyState>{t("gpus.none")}</EmptyState>;
  return (
    <div className="ov-gpu-grid">
      {list.map((g) => (
        <GpuCard
          key={g.uuid}
          gpu={g}
          rows={rows.filter((r) => r.device === g.uuid)}
          history={byUuid.get(g.uuid)}
          nowS={nowS}
        />
      ))}
    </div>
  );
}

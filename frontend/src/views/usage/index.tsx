// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { UsagePeriod } from "../../api/types";
import { errorText } from "../../api/client";
import { PageHeader } from "../../components";
import { useGpus } from "../../state";
import { CallsWall } from "./CallsWall";
import { ErasTable } from "./ErasTable";
import { ModelsTable } from "./ModelsTable";
import { TokensChart } from "./TokensChart";
import { UsageFilters } from "./UsageFilters";
import { UsageKpis } from "./UsageKpis";
import { erasNewestFirst, isCurrentEra } from "./usageModel";
import { useUsageData } from "./useUsageData";
import "./Usage.css";

/* Usage: what ran, how much it cost in tokens, and on which card. Period
   and GPU filter the totals, the chart and the per-model table; the GPU
   also filters the call wall (which is always the last hundred, whatever
   the period); the card table is the machine's whole history either way. */
export default function UsageView() {
  const { t } = useTranslation("usage");
  const [period, setPeriod] = useState<UsagePeriod>("week");
  const [gpu, setGpu] = useState("");
  const { eras, usage, jobs, stale } = useUsageData(period, gpu);
  const gpus = useGpus();

  const liveUuids = useMemo(
    () => (gpus.data ? new Set(gpus.data.gpus.map((g) => g.uuid)) : null),
    [gpus.data],
  );
  const eraRows = useMemo(
    () =>
      eras.data
        ? erasNewestFirst(eras.data.eras).map((era) => ({ era, current: isCurrentEra(era, liveUuids) }))
        : undefined,
    [eras.data, liveUuids],
  );

  // Until the refetch for a new filter lands, the figures on screen belong
  // to the old one: dim them rather than present them as the answer.
  const error = usage.error ?? jobs.error ?? eras.error;

  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          <UsageFilters
            period={period}
            onPeriod={setPeriod}
            gpu={gpu}
            onGpu={setGpu}
            eras={eraRows ?? []}
          />
        }
      />
      {error ? (
        <p className="error-box" role="alert">
          {t("common:empty.failed", { error: errorText(error) })}
        </p>
      ) : null}
      <div className={`us-view stack${stale ? " us-stale" : ""}`} aria-busy={stale}>
        <UsageKpis totals={usage.data?.totals} />
        <TokensChart data={usage.data} period={period} />
        <ErasTable eras={eraRows} />
        <ModelsTable data={usage.data} />
        <CallsWall jobs={jobs.data} />
      </div>
    </>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { getJSON } from "../../api/client";
import type { JobRecord } from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { PauseControl } from "../../components/PauseControl";
import { usePoll } from "../../lib/usePoll";
import { useCatalog, useStatus } from "../../state";
import { GpuGrid } from "./GpuGrid";
import { JobQueue } from "./JobQueue";
import { KpiRow } from "./KpiRow";
import { laneRows } from "./laneRows";
import { ModelsInRam } from "./ModelsInRam";
import { UsageSection } from "./UsageSection";
import "./Overview.css";

/* The job log feeds both the throughput tile and the recent-jobs table.
   It is polled faster than the charts so the throughput window stays
   current, and deep enough that a busy five minutes is not cut short. */
const JOBS_POLL_MS = 15_000;
const JOBS_LIMIT = 100;

/** The control surface: the machine now (tiles, cards, loaded models, queue), then its recent history. */
export default function OverviewView() {
  const { t } = useTranslation();
  const rows = laneRows(useCatalog().data, useStatus().data);
  const jobs = usePoll(
    useCallback((signal: AbortSignal) => getJSON<JobRecord[]>(`/stats/jobs?limit=${JOBS_LIMIT}`, { signal }), []),
    { intervalMs: JOBS_POLL_MS },
  );
  return (
    <>
      <PageHeader title={t("nav.overview")} actions={<PauseControl />} />
      <KpiRow jobs={jobs.data} />
      <GpuGrid rows={rows} />
      <div className="ov-split">
        <ModelsInRam rows={rows} />
        <JobQueue />
      </div>
      <UsageSection jobs={jobs.data} />
    </>
  );
}

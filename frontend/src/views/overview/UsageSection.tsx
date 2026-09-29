// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { JobRecord, StatsSummary, StatsTimeline, StatsVram } from "../../api/types";
import { RangeButtons, type RangeHours } from "../../components/RangeButtons";
import { useFormat } from "../../lib/useFormat";
import { SLOW_POLL_MS } from "../../state";
import { bucketFor } from "./jobs";
import { JobsByWorker } from "./JobsByWorker";
import { LatencyByModel } from "./LatencyByModel";
import { RecentJobs } from "./RecentJobs";
import { usePathPoll } from "../../lib/usePathPoll";
import { VramHistory } from "./VramHistory";
import "./UsageSection.css";

/* The recent history under the live state: jobs over the chosen window,
   VRAM over six hours, which models are slow, and the latest jobs. The job
   and eviction counts for the window sit beside the range they belong to. */
export function UsageSection({ jobs }: { jobs: JobRecord[] | undefined }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const [hours, setHours] = useState<RangeHours>(24);
  const timelinePath = `/stats/timeline?hours=${hours}&bucket_s=${bucketFor(hours)}`;
  const summaryPath = `/stats/summary?hours=${hours}`;
  const timeline = usePathPoll<StatsTimeline>(timelinePath, { intervalMs: SLOW_POLL_MS });
  const summary = usePathPoll<StatsSummary>(summaryPath, { intervalMs: SLOW_POLL_MS });
  const vram = usePathPoll<StatsVram>("/stats/vram?hours=6", { intervalMs: SLOW_POLL_MS });
  // A reply for the previous range is not drawn against the new one.
  const tl = timeline.data?.path === timelinePath ? timeline.data.body : undefined;
  const sm = summary.data?.path === summaryPath ? summary.data.body : undefined;
  const total = sm?.models.reduce((a, m) => a + m.jobs, 0);

  return (
    <section className="ov-usage" aria-labelledby="ov-usage-title">
      <div className="ov-usage-head">
        <h2 className="section-title" id="ov-usage-title">
          {t("usage.title")}
        </h2>
        <RangeButtons value={hours} onChange={setHours} />
        {sm && total != null && (
          <span className="ov-usage-meta">
            {t("usage.jobs", { count: total, formatted: f.num(total) })} ·{" "}
            {t("usage.evictions", { count: sm.evictions, formatted: f.num(sm.evictions) })}
          </span>
        )}
      </div>
      <div className="ov-charts">
        <JobsByWorker timeline={tl} hours={hours} />
        <VramHistory vram={vram.data?.body} />
        <LatencyByModel summary={sm} />
        <RecentJobs jobs={jobs?.slice(0, 30)} />
      </div>
    </section>
  );
}

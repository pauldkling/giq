// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { StatsSummary } from "../../api/types";
import { Card } from "../../components/Card";
import { HBars } from "../../components/charts";
import { workerColor } from "../../lib/series";
import { useFormat } from "../../lib/useFormat";

type ModelStats = StatsSummary["models"][number];

/* The six busiest models (the server's order), ranked by their average run
   time. The worker's colour marks the bar; the name says which model. */
export function LatencyByModel({ summary }: { summary: StatsSummary | undefined }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const models = (summary?.models ?? [])
    .filter((m): m is ModelStats & { avg_run_ms: number } => m.avg_run_ms != null)
    .slice(0, 6)
    .sort((a, b) => b.avg_run_ms - a.avg_run_ms);
  const byId = new Map(models.map((m) => [`${m.worker}/${m.model}`, m]));
  const jobs = (n: number) => t("common:units.jobs", { count: n });
  return (
    <Card title={t("usage.latency")}>
      <HBars
        ariaLabel={t("usage.latencyLabel")}
        rows={models.map((m) => ({
          id: `${m.worker}/${m.model}`,
          label: m.model,
          value: m.avg_run_ms,
          color: workerColor(m.worker),
          valueLabel: t("usage.latencyValue", { dur: f.dur(m.avg_run_ms), jobs: jobs(m.jobs) }),
        }))}
        tooltip={(r) => {
          const m = byId.get(r.id)!;
          return (
            <>
              <b>{r.id}</b>
              <div>{t("usage.latencyTip", { jobs: jobs(m.jobs), failed: t("common:chart.failed", { count: m.failed }) })}</div>
              <div>{t("usage.latencyAvg", { avg: f.dur(m.avg_run_ms), max: f.dur(m.max_run_ms) })}</div>
              {m.avg_queue_ms != null && <div>{t("usage.latencyQueue", { wait: f.dur(m.avg_queue_ms) })}</div>}
            </>
          );
        }}
        emptyText={t("common:empty.noJobs")}
      />
    </Card>
  );
}

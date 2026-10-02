// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { JobRecord } from "../../api/types";
import { KpiTile } from "../../components/KpiTile";
import { useFormat } from "../../lib/useFormat";
import { useGpus, useInstances, useRecipes, useStatus } from "../../state";
import { DiskKpi } from "./DiskKpi";
import { laneRows } from "./laneRows";
import { THROUGHPUT_WINDOW_S, throughput } from "./throughput";
import { VramSplit } from "./VramSplit";
import "./KpiRow.css";

const MINUTES = THROUGHPUT_WINDOW_S / 60;

/* The machine at a glance. VRAM and power are every card summed: on a
   two-card rig a figure for the default card alone answers a question
   nobody asked, and the per-card breakdown is right below. */
export function KpiRow({ jobs }: { jobs: JobRecord[] | undefined }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const gpus = useGpus().data?.gpus ?? [];
  const status = useStatus().data;
  const rows = laneRows(useRecipes().data, useInstances().data, status);

  const draws = gpus.map((g) => g.power_draw_w).filter((w): w is number => w != null);
  const limits = gpus.map((g) => g.power_limit_w).filter((w): w is number => w != null);
  const power = draws.length ? draws.reduce((a, b) => a + b, 0) : null;
  const limit = limits.length ? limits.reduce((a, b) => a + b, 0) : null;

  const used = gpus.reduce((a, g) => a + g.vram_used_gb, 0);
  const total = gpus.reduce((a, g) => a + g.vram_total_gb, 0);
  const mine = gpus.reduce((a, g) => a + (g.vram_giq_gb ?? 0), 0);
  const other = gpus.reduce((a, g) => a + (g.vram_other_gb ?? g.vram_used_gb), 0);

  const warm = rows.filter((r) => r.warm);
  const loaded = rows.filter((r) => r.ready).length;
  const running = status?.jobs_running.length ?? 0;

  const tp = jobs ? throughput(jobs, Date.now() / 1000) : null;

  return (
    <div className="ov-kpi-row">
      <KpiTile label={t("kpi.power")} value={power == null ? "–" : f.num(power)} unit={power == null ? undefined : "W"}>
        {power == null
          ? gpus.length > 0 && t("kpi.powerNone")
          : limit != null && t("kpi.powerLimit", { limit: f.watts(limit) })}
      </KpiTile>
      <KpiTile
        label={t("kpi.vram")}
        value={gpus.length ? f.num(used, 1) : "–"}
        unit={gpus.length ? t("kpi.vramOf", { total: f.gb(total) }) : undefined}
      >
        {gpus.length > 0 && <VramSplit mine={mine} other={other} breakdown={gpus.flatMap((g) => g.giq)} />}
      </KpiTile>
      <KpiTile label={t("kpi.resident")} value={status ? f.num(loaded) : "–"} unit={t("kpi.residentUnit")}>
        {/* "0 / 0" reads like a failure; nothing pinned is a choice, not a shortfall. */}
        {warm.length
          ? t("kpi.residentWarm", { ready: f.num(warm.filter((r) => r.ready).length), warm: f.num(warm.length) })
          : status && t("kpi.residentNone")}
      </KpiTile>
      <KpiTile label={t("kpi.queue")} value={status ? f.num(status.queue_depth) : "–"} unit={t("kpi.queueUnit")}>
        {status && (running ? t("kpi.queueRunning", { count: running }) : t("kpi.queueIdle"))}
      </KpiTile>
      <KpiTile
        label={t("kpi.throughput")}
        value={f.rate(tp?.rate)}
        unit={t("common:units.tokPerSec")}
        title={t(tp?.rate == null ? "kpi.throughputEmptyTitle" : "kpi.throughputTitle", { minutes: MINUTES })}
      >
        {tp &&
          (tp.rate == null
            ? t("kpi.throughputNone", { minutes: MINUTES })
            : t("kpi.throughputSub", { count: tp.jobs, minutes: MINUTES }))}
      </KpiTile>
      <DiskKpi />
    </div>
  );
}

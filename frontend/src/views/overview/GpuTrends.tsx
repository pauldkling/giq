// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { StatsGpus } from "../../api/types";
import { Sparkline } from "../../components/charts";
import type { TimePoint } from "../../components/charts";
import { useFormat } from "../../lib/useFormat";

type History = StatsGpus["gpus"][number];

const SIX_HOURS = 6 * 3600;

/* Temperature and power over the last six hours. The x-domain is the whole
   window, not the samples' extent, so a gap (giq was down, the card was
   gone) reads as a gap. The power trend carries the card's limit as a
   dashed reference. */
export function GpuTrends({ index, history, nowS }: { index: number; history: History | undefined; nowS: number }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const samples = history?.samples ?? [];
  const temps: TimePoint[] = samples.flatMap((s) => (s.temp == null ? [] : [{ t: s.t, v: s.temp }]));
  const pows: TimePoint[] = samples.flatMap((s) => (s.power == null ? [] : [{ t: s.t, v: s.power }]));
  const domain: [number, number] = [nowS - SIX_HOURS, nowS];
  const range = (pts: TimePoint[], fmt: (v: number) => string) =>
    pts.length
      ? t("gpus.range", { lo: fmt(Math.min(...pts.map((p) => p.v))), hi: fmt(Math.max(...pts.map((p) => p.v))) })
      : "";
  return (
    <div className="ov-gpu-trends">
      <div className="ov-gpu-trend">
        <div className="ov-gpu-trend-head">
          <span>{t("gpus.tempTrend")}</span>
          <span>{range(temps, f.temp)}</span>
        </div>
        <Sparkline
          points={temps}
          domain={domain}
          ariaLabel={t("gpus.tempTrendLabel", { index })}
          formatValue={f.temp}
          formatTime={(ts) => f.time(ts)}
        />
      </div>
      <div className="ov-gpu-trend">
        <div className="ov-gpu-trend-head">
          <span>{t("gpus.powerTrend")}</span>
          <span>{range(pows, f.watts)}</span>
        </div>
        <Sparkline
          points={pows}
          domain={domain}
          refLine={history?.power_limit ?? null}
          ariaLabel={t("gpus.powerTrendLabel", { index })}
          formatValue={f.watts}
          formatTime={(ts) => f.time(ts)}
        />
      </div>
    </div>
  );
}

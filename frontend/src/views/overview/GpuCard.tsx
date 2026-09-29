// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { WarningIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { Gpu, StatsGpus } from "../../api/types";
import { Icon } from "../../components/Icon";
import { ProgressBar } from "../../components/ProgressBar";
import { Tag } from "../../components/Tag";
import { WorkerIcon } from "../../components/WorkerIcon";
import { shortGpuName } from "../../lib/cards";
import { useFormat } from "../../lib/useFormat";
import { GpuTrends } from "./GpuTrends";
import type { LaneRow } from "./laneRows";
import { VramSplit } from "./VramSplit";
import "./GpuCard.css";

const TEMP_WARN = 75;
const TEMP_CRIT = 85;

export interface GpuCardProps {
  gpu: Gpu;
  /** What is loaded (or loading) on this card. */
  rows: LaneRow[];
  history: StatsGpus["gpus"][number] | undefined;
  nowS: number;
}

export function GpuCard({ gpu: g, rows, history, nowS }: GpuCardProps) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const temp = g.temperature_c;
  const heat = temp == null ? null : temp >= TEMP_CRIT ? "crit" : temp >= TEMP_WARN ? "warn" : null;
  // Idle clocks are normal life; only warnings and critical reasons earn a chip.
  const throttles = g.throttle.filter((x) => x.severity !== "info");
  const vram = t("gpus.vramValue", { used: f.num(g.vram_used_gb, 1), total: f.gb(g.vram_total_gb) });

  return (
    <article className="card elev-sm giq-card ov-gpu-card" aria-label={t("common:gpu.label", { index: g.index })}>
      <header className="ov-gpu-head">
        <span className="card-kicker">{t("common:gpu.label", { index: g.index })}</span>
        <span className="ov-gpu-name" title={t("gpus.uuidTitle", { name: g.name, uuid: g.uuid })}>
          {shortGpuName(g.name)}
        </span>
        <span
          className={`ov-gpu-temp${heat ? " ov-gpu-temp-" + heat : ""}`}
          title={heat ? t(heat === "crit" ? "gpus.tempCrit" : "gpus.tempWarn") : t("common:gpu.temp")}
        >
          {heat && <Icon as={WarningIcon} size={12} label={t(heat === "crit" ? "gpus.tempCrit" : "gpus.tempWarn")} />}
          {f.temp(temp)}
        </span>
      </header>

      <div className="ov-gpu-metric">
        <div className="ov-gpu-metric-row">
          <span>{t("common:gpu.vram")}</span>
          <span className="ov-gpu-metric-value">{vram}</span>
        </div>
        <ProgressBar value={g.vram_used_gb} max={g.vram_total_gb} label={t("gpus.vramLabel", { index: g.index })} valueText={vram} />
        <VramSplit mine={g.vram_giq_gb ?? 0} other={g.vram_other_gb ?? g.vram_used_gb} breakdown={g.giq} />
      </div>

      <div className="ov-gpu-metric">
        <div className="ov-gpu-metric-row">
          <span>{t("common:gpu.load")}</span>
          <span className="ov-gpu-metric-value">{f.pct(g.utilization_pct)}</span>
        </div>
        <ProgressBar value={g.utilization_pct ?? 0} variant="neutral" label={t("gpus.loadLabel", { index: g.index })} />
      </div>

      <div className="ov-gpu-metric-row">
        <span>{t("common:gpu.power")}</span>
        <span className="ov-gpu-metric-value">
          {f.watts(g.power_draw_w)}
          {g.power_limit_w != null && <span className="ov-gpu-limit"> / {f.watts(g.power_limit_w)}</span>}
        </span>
      </div>
      {g.fan_pct != null && (
        <div className="ov-gpu-metric-row">
          <span>{t("common:gpu.fan")}</span>
          <span className="ov-gpu-metric-value">{f.pct(g.fan_pct)}</span>
        </div>
      )}

      {throttles.length > 0 && (
        <div className="ov-gpu-tags">
          {throttles.map((x) => (
            <Tag key={x.reason} tone={x.severity === "critical" ? "critical" : "warning"} icon={x.severity === "critical" ? <Icon as={WarningIcon} size={11} /> : undefined}>
              {x.reason}
            </Tag>
          ))}
        </div>
      )}

      {/* What the card is holding: with two cards the first question is "what is on it". */}
      <div className="ov-gpu-tags" aria-label={t("gpus.residents")}>
        {rows.length ? (
          rows.map((r) => (
            <Tag
              key={r.key}
              tone={r.ready ? "neutral" : "outline"}
              icon={<WorkerIcon worker={r.model.worker} size={12} />}
              title={
                r.warm
                  ? t("gpus.residentTitle", { key: r.key, gb: f.gb(r.model.vram_gb) })
                  : t("gpus.slotTitle", { key: r.key })
              }
            >
              {r.model.label || r.model.model}
            </Tag>
          ))
        ) : (
          <span className="subtle">{t("gpus.nothingLoaded")}</span>
        )}
      </div>

      <GpuTrends index={g.index} history={history} nowS={nowS} />
    </article>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { PushPinIcon, StopIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { Gpu, Policy } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Tag, type TagTone } from "../../components/Tag";
import { WorkerIcon } from "../../components/WorkerIcon";
import { shortGpuName } from "../../lib/cards";
import { useFormat } from "../../lib/useFormat";
import type { LaneRow } from "./laneRows";

const POLICY_TONE: Record<Policy, TagTone> = { pinned: "accent", auto: "neutral", off: "outline" };

export interface ModelRowProps {
  row: LaneRow;
  card: Gpu | undefined;
  lastUsed: number | null | undefined;
  /** An action on this row is in flight. */
  busy: boolean;
  /** Another row's action is in flight: one change at a time. */
  locked: boolean;
  onPolicy: (policy: Policy) => void;
}

export function ModelRow({ row, card, lastUsed, busy, locked, onPolicy }: ModelRowProps) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const m = row.model;
  const policy: Policy = m.policy;
  const stateText =
    row.state === "evicted"
      ? t("models.evicted", { job: row.evictedFor })
      : row.state === "loading"
        ? t("models.loading")
        : null;
  return (
    <tr>
      <td className="ov-mir-model" title={m.detail ? `${row.key} · ${m.detail}` : row.key}>
        <WorkerIcon worker={m.vision ? "vision" : m.worker} size={14} />
        <span>{m.label || m.model}</span>
      </td>
      <td className="muted">{t(`common:worker.${m.worker}`, { defaultValue: m.worker })}</td>
      <td className="mono muted" title={m.backend}>
        {m.engine ?? m.runtime}
      </td>
      <td
        className="muted"
        title={
          card ? t(m.device ? "models.bound" : "models.defaultCard", { name: shortGpuName(card.name) }) : undefined
        }
      >
        {card ? t("common:gpu.label", { index: card.index }) : "–"}
      </td>
      <td className="num muted" title={m.measured ? undefined : t("models.estimate")}>
        {m.measured ? "" : "≈ "}
        {f.gb(m.vram_gb)}
      </td>
      <td>
        <span className="ov-mir-residency">
          <Tag tone={POLICY_TONE[policy]} title={t(`common:policy.${policy}Help`)}>
            {t(`common:policy.${policy}`)}
          </Tag>
          {stateText && (
            <span className="ov-mir-state" title={stateText}>
              {stateText}
            </span>
          )}
        </span>
      </td>
      <td className="muted">{f.ago(lastUsed)}</td>
      <td className="ov-mir-actions">
        {/* One verb per row, and it is the one that is not already true. */}
        {row.warm ? (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            title={t("models.stopTitle")}
            disabled={busy || locked}
            onClick={() => onPolicy("off")}
          >
            <Icon as={StopIcon} size={12} />
            {busy ? t("models.stopping") : t("models.stop")}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            title={t("models.warmTitle")}
            disabled={busy || locked}
            onClick={() => onPolicy("pinned")}
          >
            <Icon as={PushPinIcon} size={12} />
            {busy ? t("models.pinning") : t("models.warm")}
          </button>
        )}
      </td>
    </tr>
  );
}

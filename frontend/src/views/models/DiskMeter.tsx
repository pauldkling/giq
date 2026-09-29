// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { Disk } from "../../api/types";
import { useTooltip } from "../../components/TooltipProvider";
import { useFormat } from "../../lib/useFormat";

/* A disk as three segments: giq's weights, everything else, free. Each
   segment keeps a sliver when non-zero so a small models share does not
   vanish on a big disk. The breakdown is in the hover tooltip and, for a
   screen reader, in the label. */
export function DiskMeter({ disk: d }: { disk: Disk }) {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const tip = useTooltip();
  const lines: [string, string, string][] = [
    ["md-disk-models", t("disk.models"), fmt.bytes(d.models_bytes)],
    ["md-disk-other", t("disk.other"), fmt.bytes(d.other_bytes)],
    ["md-disk-free", t("disk.free"), fmt.bytes(d.free_bytes)],
  ];
  const content = (
    <div className="md-disk-tip">
      <strong>{d.mount}</strong>
      {lines.map(([cls, label, value]) => (
        <div key={cls} className="md-disk-tip-row">
          <span className={`md-disk-swatch ${cls}`} />
          {label}
          <span className="md-disk-tip-v">{value}</span>
        </div>
      ))}
      <div className="subtle">{t("disk.total", { total: fmt.bytes(d.total_bytes) })}</div>
    </div>
  );
  // Shares of the disk, not raw bytes: a flex-grow of 10^12 overflows the
  // layout engine and the meter collapses to nothing.
  const share = (b: number) => Math.max(b / Math.max(d.total_bytes, 1), 0.001);
  return (
    <div
      className="md-disk-meter"
      role="img"
      aria-label={`${d.mount}: ${lines.map(([, l, v]) => `${l} ${v}`).join(", ")}`}
      onPointerMove={(e) => tip.show(e, content)}
      onPointerLeave={tip.hide}
    >
      <span className="md-disk-models" style={{ flex: share(d.models_bytes) }} />
      <span className="md-disk-other" style={{ flex: share(d.other_bytes) }} />
      <span className="md-disk-free" style={{ flex: share(d.free_bytes) }} />
    </div>
  );
}

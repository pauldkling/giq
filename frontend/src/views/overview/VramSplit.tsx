// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { GpuProcess } from "../../api/types";
import { useFormat } from "../../lib/useFormat";

/* "Is this card full because of me?" is a different question from "is it
   full", and only the first tells the operator whether giq can do anything
   about it: used VRAM split into giq's processes and everything else. */
export function VramSplit({ mine, other, breakdown }: { mine: number; other: number; breakdown: GpuProcess[] }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const detail = breakdown.map((b) => `${b.label} ${f.gb(b.gb)}`).join("\n");
  return (
    <span className="ov-vram-split">
      <span title={detail || t("split.nothingLoaded")}>{t("split.giq", { gb: f.gb(mine) })}</span>
      <span title={t("common:gpu.otherTitle")}>{t("split.other", { gb: f.gb(other) })}</span>
    </span>
  );
}

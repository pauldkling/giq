// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { CatalogModel, StorageModel } from "../../api/types";
import { useFormat } from "../../lib/useFormat";
import { hasWeights } from "./catalog";

/* The card's numbers on one wrapping line: VRAM, disk, last use, lanes. An
   unmeasured VRAM figure gets a tilde rather than an "est." badge beside the
   model name: it qualifies one number, so it belongs on that number. */
export function ModelFacts({ m, s }: { m: CatalogModel; s: Partial<StorageModel> }) {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const shared = s.shared_with ?? [];
  return (
    <div className="md-model-facts">
      {m.measured ? (
        <span>{t("card.vram", { vram: fmt.gb(m.vram_gb) })}</span>
      ) : (
        <span title={t("card.estimatedTitle")}>{t("card.vramEstimated", { vram: fmt.gb(m.vram_gb) })}</span>
      )}
      <span title={(s.paths ?? []).join("\n") || undefined}>
        {hasWeights(s) ? t("card.onDisk", { size: fmt.bytes(s.size_bytes ?? 0) }) : t("card.noDisk")}
        {shared.length > 0 && (
          <span className="md-model-shared" title={t("card.sharedTitle", { others: shared.join(", ") })}>
            {" "}
            · {t("card.shared")}
          </span>
        )}
      </span>
      <span>{s.last_used ? t("catalog.lastUsed", { ago: fmt.ago(s.last_used) }) : t("catalog.neverUsed")}</span>
      {m.lanes > 1 && <span title={t("card.lanesTitle")}>{t("card.lanes", { count: m.lanes })}</span>}
    </div>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipeEntry } from "../../api/types";
import { useFormat } from "../../lib/useFormat";

/* The card's numbers on one wrapping line: VRAM, disk, last use, lanes. An
   unmeasured VRAM figure gets a tilde rather than an "est." badge beside the
   recipe name: it qualifies one number, so it belongs on that number. Disk
   is the recipe's weights as the inventory counts them; a checkpoint
   another recipe also loads is marked shared. */
export function RecipeFacts({ r, weights }: { r: RecipeEntry; weights: { bytes: number; sharedWith: string[] } }) {
  const { t } = useTranslation("recipes");
  const fmt = useFormat();
  const shared = weights.sharedWith;
  return (
    <div className="rc-recipe-facts">
      {r.measured ? (
        <span>{t("card.vram", { vram: fmt.gb(r.vram_gb) })}</span>
      ) : (
        <span title={t("card.estimatedTitle")}>{t("card.vramEstimated", { vram: fmt.gb(r.vram_gb) })}</span>
      )}
      <span>
        {r.installed ? t("card.onDisk", { size: fmt.bytes(weights.bytes) }) : t("card.noDisk")}
        {shared.length > 0 && (
          <span className="rc-recipe-shared" title={t("card.sharedTitle", { others: shared.join(", ") })}>
            {" "}
            · {t("card.shared")}
          </span>
        )}
      </span>
      <span>{r.last_used ? t("catalog.lastUsed", { ago: fmt.ago(r.last_used) }) : t("catalog.neverUsed")}</span>
      {r.lanes > 1 && <span title={t("card.lanesTitle")}>{t("card.lanes", { count: r.lanes })}</span>}
    </div>
  );
}

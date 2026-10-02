// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipeEntry } from "../../api/types";
import { WorkerIcon } from "../../components/WorkerIcon";
import { primaryModality } from "../../lib/recipes";
import { useFormat } from "../../lib/useFormat";

/* A recipe with no weights on disk has nothing to run, nothing to delete and
   nothing worth binding — every control on a full card would be inert. What
   is still worth knowing is that giq knows about it and what getting it back
   would cost, so: one pill each. */
export function TinyRecipePill({ r }: { r: RecipeEntry }) {
  const { t } = useTranslation("recipes");
  const fmt = useFormat();
  const last = r.last_used ? t("catalog.lastUsed", { ago: fmt.ago(r.last_used) }) : t("catalog.neverUsed");
  return (
    <li
      className="rc-tiny-pill"
      title={t("catalog.absentTitle", { key: r.name, engine: r.engine, vram: fmt.gb(r.vram_gb), last })}
    >
      <WorkerIcon worker={primaryModality(r)} size={13} labelled />
      <span className="rc-tiny-name">{r.name}</span>
      <span className="rc-tiny-meta">
        {fmt.gb(r.vram_gb)} · {r.engine}
        {r.vision && ` · ${t("card.vision")}`}
      </span>
    </li>
  );
}

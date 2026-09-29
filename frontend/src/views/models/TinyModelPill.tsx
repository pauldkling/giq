// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { CatalogModel, StorageModel } from "../../api/types";
import { WorkerIcon } from "../../components/WorkerIcon";
import { useFormat } from "../../lib/useFormat";
import { modelKey } from "./catalog";

/* A model with no weights on disk has nothing to run, nothing to delete and
   nothing worth binding — every control on a full card would be inert. What
   is still worth knowing is that giq knows about it and what getting it back
   would cost, so: one pill each. */
export function TinyModelPill({ m, s }: { m: CatalogModel; s: Partial<StorageModel> }) {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const last = s.last_used ? t("catalog.lastUsed", { ago: fmt.ago(s.last_used) }) : t("catalog.neverUsed");
  return (
    <li
      className="md-tiny-pill"
      title={t("catalog.absentTitle", { key: modelKey(m), engine: m.backend, vram: fmt.gb(m.vram_gb), last })}
    >
      <WorkerIcon worker={m.worker} size={13} labelled />
      <span className="md-tiny-name">{m.model}</span>
      <span className="md-tiny-meta">
        {fmt.gb(m.vram_gb)} · {m.backend}
        {m.vision && ` · ${t("card.vision")}`}
      </span>
    </li>
  );
}

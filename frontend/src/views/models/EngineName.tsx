// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { CatalogModel } from "../../api/types";
import { Tag } from "../../components/Tag";
import { BUILT_ENGINES, ENGINE_NOTE_KEY } from "./catalog";

export interface EngineNameProps {
  m: CatalogModel;
  /** runtime → build string; null when the binary is missing. */
  versions: Map<string, string | null>;
}

/* Which runtime executes the model. Two models of one modality can run on
   different engines (Unlimited-OCR and GLM-OCR) with different VRAM behaviour
   and different things to upgrade, so the engine is worth seeing per card. The
   build rides along for engines that are a build of ours: a llama.cpp whose
   source tree is gone can keep serving for months unnoticed otherwise. */
export function EngineName({ m, versions }: EngineNameProps) {
  const { t } = useTranslation("models");
  const noteKey = ENGINE_NOTE_KEY[m.backend];
  const note = noteKey ? t(`engineNote.${noteKey}`) : t("engine.fallback");
  const known = versions.has(m.runtime);
  const version = versions.get(m.runtime);
  const missing = known && version === null;
  return (
    <span className="md-engine-name" title={version ? `${note} — ${version}` : note}>
      <span className="mono">{m.backend}</span>
      {BUILT_ENGINES.has(m.runtime) && version && <span className="md-engine-version subtle">{version}</span>}
      {missing && (
        <Tag tone="critical" title={t("engine.missingTitle")}>
          {t("engine.missing")}
        </Tag>
      )}
    </span>
  );
}

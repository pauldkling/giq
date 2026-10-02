// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipeEntry } from "../../api/types";
import { Tag } from "../../components/Tag";
import { BUILT_ENGINES, ENGINE_NOTE_KEY } from "./catalog";

export interface EngineNameProps {
  r: RecipeEntry;
  /** runtime → build string; null when the binary is missing. */
  versions: Map<string, string | null>;
}

/* Which runtime executes the recipe. Two recipes of one modality can run on
   different engines (Unlimited-OCR and GLM-OCR) with different VRAM behaviour
   and different things to upgrade, so the engine is worth seeing per card. The
   build rides along for engines that are a build of ours: a llama.cpp whose
   source tree is gone can keep serving for months unnoticed otherwise. */
export function EngineName({ r, versions }: EngineNameProps) {
  const { t } = useTranslation("recipes");
  const noteKey = ENGINE_NOTE_KEY[r.engine];
  const note = noteKey ? t(`engineNote.${noteKey}`) : t("engine.fallback");
  const known = versions.has(r.runtime);
  const version = versions.get(r.runtime);
  const missing = known && version === null;
  return (
    <span className="rc-engine-name" title={version ? `${note} — ${version}` : note}>
      <span className="mono">{r.engine}</span>
      {BUILT_ENGINES.has(r.runtime) && version && <span className="rc-engine-version subtle">{version}</span>}
      {missing && (
        <Tag tone="critical" title={t("engine.missingTitle")}>
          {t("engine.missing")}
        </Tag>
      )}
    </span>
  );
}

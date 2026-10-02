// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { Card } from "../../components/Card";
import { Tag } from "../../components/Tag";
import { useEngines, useRecipes } from "../../state";
import "./EnginesCard.css";

/* The runtimes on this machine: which binary or interpreter each engine is,
   which build, and how many recipes run on it. A missing binary is the
   failure a recipe only reveals at its first load, so it is flagged here
   before anyone asks for that recipe. */
export function EnginesCard() {
  const { t } = useTranslation("inventory");
  const engines = useEngines().data?.engines ?? [];
  const recipes = useRecipes().data?.recipes ?? [];
  const uses = new Map<string, number>();
  for (const r of recipes) uses.set(r.runtime, (uses.get(r.runtime) ?? 0) + 1);
  return (
    <Card kicker={t("engines.title")} className="inv-engines">
      <ul className="inv-engines-list">
        {engines.map((e) => (
          <li key={e.name} className="inv-engine">
            <div className="inv-engine-head">
              <span className="mono inv-engine-name">{e.name}</span>
              {!e.present && (
                <Tag tone="critical" title={t("engines.missingTitle")}>
                  {t("engines.missing")}
                </Tag>
              )}
              <span className="subtle inv-engine-uses">{t("engines.recipes", { count: uses.get(e.name) ?? 0 })}</span>
            </div>
            {e.binary && (
              <div className="mono subtle inv-engine-binary" title={e.binary}>
                {e.binary}
              </div>
            )}
            {e.version && <div className="subtle inv-engine-version">{e.version}</div>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

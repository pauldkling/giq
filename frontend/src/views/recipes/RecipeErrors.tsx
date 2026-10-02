// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipesInfo } from "../../api/types";
import { Card } from "../../components/Card";
import "./RecipeErrors.css";

/* Operator recipe files that failed validation are logged and left out,
   and the catalog simply lacks them (or still shows the built-in of that
   name) — nothing on this page would say a file was ignored. This card is
   where it is said, with giq's own reason for each file, and it is gone
   once every file loads. */
export function RecipeErrors({ recipes }: { recipes: RecipesInfo | undefined }) {
  const { t } = useTranslation("recipes");
  const errors = recipes?.errors ?? [];
  if (errors.length === 0) return null;
  return (
    <div role="alert">
      <Card
        className="rc-recipe-errors"
        kicker={t("recipeErrors.kicker")}
        title={t("recipeErrors.title", { count: errors.length })}
      >
        <p className="hint">{t("recipeErrors.body", { dir: recipes?.dir ?? "" })}</p>
        <ul className="rc-recipe-errors-list">
          {errors.map((e, i) => (
            <li key={`${e.file ?? ""}-${i}`}>
              <div className="rc-recipe-errors-file mono">{e.file ?? t("recipeErrors.several")}</div>
              <div className="rc-recipe-errors-msg">{e.message}</div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

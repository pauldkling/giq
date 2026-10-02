// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { EmptyState } from "../../components/EmptyState";
import { ActionStatus } from "./ActionStatus";
import type { CardChoice } from "../../lib/cards";
import type { RecipeEntry, WeightsItem } from "../../api/types";
import { RecipeCard } from "./RecipeCard";
import { TinyRecipePill } from "./TinyRecipePill";
import type { RecipeActions } from "./useRecipeActions";
import "./RecipeCatalog.css";

export interface RecipeCatalogProps {
  /** The entries passing the filters. */
  entries: RecipeEntry[];
  weights: WeightsItem[] | undefined;
  total: number;
  filtered: boolean;
  onClearFilters: () => void;
  cards: CardChoice[];
  versions: Map<string, string | null>;
  actions: RecipeActions;
}

/* The catalog: full cards for installed recipes, then one line of pills for
   the ones giq knows but has nothing on disk for. */
export function RecipeCatalog({ entries, weights, total, filtered, onClearFilters, cards, versions, actions }: RecipeCatalogProps) {
  const { t } = useTranslation("recipes");
  const present = entries.filter((r) => r.installed);
  const absent = entries.filter((r) => !r.installed);
  return (
    <section className="rc-recipe-catalog" aria-labelledby="rc-recipe-catalog-title">
      <div className="rc-catalog-bar">
        <h2 id="rc-recipe-catalog-title" className="section-title rc-catalog-title">
          {t("catalog.title")}
        </h2>
        <span className="rc-catalog-count">
          {filtered
            ? t("count.filtered", { count: entries.length, total })
            : t("count.all", { count: entries.length })}
        </span>
      </div>
      <ActionStatus message={actions.message} onDismiss={actions.dismiss} />
      {entries.length === 0 ? (
        <EmptyState
          action={
            filtered && (
              <button type="button" className="btn btn-secondary" onClick={onClearFilters}>
                {t("catalog.clearFilters")}
              </button>
            )
          }
        >
          {t("catalog.noMatch")}
        </EmptyState>
      ) : (
        <div className="rc-recipe-grid">
          {present.map((r) => (
            <RecipeCard key={r.name} r={r} weights={weights} cards={cards} versions={versions} actions={actions} />
          ))}
        </div>
      )}
      {absent.length > 0 && (
        <div className="rc-absent">
          <h3 className="section-title rc-absent-title">{t("catalog.absent", { count: absent.length })}</h3>
          <p className="rc-absent-hint">{t("catalog.absentHint")}</p>
          <ul className="rc-tiny-list">
            {absent.map((r) => (
              <TinyRecipePill key={r.name} r={r} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

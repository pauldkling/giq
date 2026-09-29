// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { EmptyState } from "../../components/EmptyState";
import { ActionStatus } from "./ActionStatus";
import type { CardChoice } from "../../lib/cards";
import { hasWeights, type ModelEntry } from "./catalog";
import { ModelCard } from "./ModelCard";
import { TinyModelPill } from "./TinyModelPill";
import type { ModelActions } from "./useModelActions";
import "./ModelCatalog.css";

export interface ModelCatalogProps {
  /** The entries passing the filters. */
  entries: ModelEntry[];
  total: number;
  filtered: boolean;
  onClearFilters: () => void;
  cards: CardChoice[];
  versions: Map<string, string | null>;
  actions: ModelActions;
}

/* The catalog: full cards for models with weights, then one line of pills
   for the ones giq knows but has nothing on disk for. */
export function ModelCatalog({ entries, total, filtered, onClearFilters, cards, versions, actions }: ModelCatalogProps) {
  const { t } = useTranslation("models");
  const present = entries.filter((e) => hasWeights(e.s));
  const absent = entries.filter((e) => !hasWeights(e.s));
  return (
    <section className="md-model-catalog" aria-labelledby="md-model-catalog-title">
      <div className="md-catalog-bar">
        <h2 id="md-model-catalog-title" className="section-title md-catalog-title">
          {t("catalog.title")}
        </h2>
        <span className="md-catalog-count">
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
        <div className="md-model-grid">
          {present.map((e) => (
            <ModelCard key={`${e.m.worker}/${e.m.model}`} entry={e} cards={cards} versions={versions} actions={actions} />
          ))}
        </div>
      )}
      {absent.length > 0 && (
        <div className="md-absent">
          <h3 className="section-title md-absent-title">{t("catalog.absent", { count: absent.length })}</h3>
          <p className="md-absent-hint">{t("catalog.absentHint")}</p>
          <ul className="md-tiny-list">
            {absent.map((e) => (
              <TinyModelPill key={`${e.m.worker}/${e.m.model}`} m={e.m} s={e.s} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

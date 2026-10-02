// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { useStorage, useWeights } from "../../state";
import { useWeightsActions } from "./useWeightsActions";
import { sortWeights, weightsName } from "./weights";
import { WeightsRow } from "./WeightsRow";
import "./WeightsTable.css";

/* Every checkpoint the recipes name, once each, however many recipes load
   it — the one place weights are deleted, since deleting is an act on files
   rather than on a recipe. A link from a recipe card narrows the table to
   that recipe's weights; "show all" widens it again. */
export function WeightsTable({ recipe, onShowAll }: { recipe: string | null; onShowAll: () => void }) {
  const { t } = useTranslation("inventory");
  const weights = useWeights();
  const modelsDir = useStorage().data?.paths?.models;
  const actions = useWeightsActions();
  const name = (w: Parameters<typeof weightsName>[0]) => weightsName(w, modelsDir);
  const all = weights.data?.weights ?? [];
  const shown = sortWeights(recipe ? all.filter((w) => w.recipes.includes(recipe)) : all, name);

  return (
    <Card
      id="inventory-weights"
      kicker={t("weights.title")}
      actions={
        recipe ? (
          <span className="inv-weights-filter">
            {t("weights.only", { recipe })}{" "}
            <button type="button" className="btn btn-ghost btn-sm" onClick={onShowAll}>
              {t("weights.showAll")}
            </button>
          </span>
        ) : (
          weights.data && t("weights.count", { count: all.length })
        )
      }
    >
      <p className="hint">{t("weights.hint")}</p>
      {actions.message && (
        <p className="inv-weights-message" role="status">
          {actions.message}{" "}
          <button type="button" className="btn btn-ghost btn-sm" onClick={actions.dismiss}>
            {t("common:actions.dismiss")}
          </button>
        </p>
      )}
      {!weights.data ? (
        <EmptyState compact>
          {weights.error
            ? t("common:empty.failed", { error: errorText(weights.error) })
            : t("common:empty.loading")}
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState compact>{t("weights.noneKnown")}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table inv-weights-table">
            <thead>
              <tr>
                <th>{t("weights.colWhat")}</th>
                <th>{t("weights.colFormat")}</th>
                <th>{t("weights.colLicence")}</th>
                <th>{t("weights.colUsedBy")}</th>
                <th className="num">{t("weights.colSize")}</th>
                <th>
                  <span className="sr-only">{t("common:actions.more")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((w) => (
                <WeightsRow
                  key={w.id}
                  w={w}
                  name={name(w)}
                  busy={actions.busy !== null}
                  onDelete={() => void actions.remove(w, name(w))}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

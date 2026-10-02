// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { StatsUsage } from "../../api/types";
import { Card, EmptyState, FailedCount, ModelLabel } from "../../components";
import { assignSeriesColors } from "../../lib/series";
import { useFormat } from "../../lib/useFormat";
import { modelKey } from "./usageModel";
import "./Usage.css";

/* The window per model, in the server's order (most tokens first). The
   swatch uses the chart's colour assignment, over the same set of models,
   so a row and its stack segment match. A model without token accounting
   (image, speech) shows dashes, not zeros: nothing was counted. */
export function ModelsTable({ data }: { data: StatsUsage | undefined }) {
  const { t } = useTranslation("usage");
  const f = useFormat();
  const models = data?.recipes;
  const colors = useMemo(() => assignSeriesColors((models ?? []).map(modelKey)), [models]);
  return (
    <Card
      kicker={t("models.kicker")}
      actions={models ? t("models.meta", { count: models.length }) : undefined}
    >
      {!models ? (
        <EmptyState compact>{t("common:empty.loading")}</EmptyState>
      ) : models.length === 0 ? (
        <EmptyState compact>{t("models.empty")}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table us-table">
            <thead>
              <tr>
                <th>{t("models.model")}</th>
                <th className="num">{t("models.calls")}</th>
                <th className="num">{t("models.failed")}</th>
                <th className="num">{t("models.tasks")}</th>
                <th className="num">{t("models.tokensIn")}</th>
                <th className="num">{t("models.tokensOut")}</th>
                <th className="num">{t("models.total")}</th>
                <th className="us-gap">{t("models.lastUsed")}</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m) => {
                const counted = m.tokens_in != null || m.tokens_out != null;
                return (
                  <tr key={modelKey(m)}>
                    <td className="us-nowrap">
                      <ModelLabel worker={m.modality} model={m.recipe} color={colors.get(modelKey(m))} showWorker />
                    </td>
                    <td className="num">{f.num(m.jobs)}</td>
                    <td className="num">
                      <FailedCount n={m.failed} />
                    </td>
                    <td className="num">{f.num(m.tasks)}</td>
                    <td className="num">{f.tok(m.tokens_in)}</td>
                    <td className="num">{f.tok(m.tokens_out)}</td>
                    <td className="num">
                      {counted ? f.tok((m.tokens_in ?? 0) + (m.tokens_out ?? 0)) : "–"}
                    </td>
                    <td className="us-nowrap us-gap" title={m.last_ts ? f.dateTime(m.last_ts) : undefined}>
                      {f.ago(m.last_ts)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

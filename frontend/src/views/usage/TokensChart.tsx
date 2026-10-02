// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import type { StatsUsage, UsagePeriod } from "../../api/types";
import { Card, ModelLabel } from "../../components";
import { Legend, StackedBars } from "../../components/charts";
import { useFormat } from "../../lib/useFormat";
import {
  bucketLabel,
  bucketTitle,
  buildUsageChart,
  modelKey,
  predatesTokenAccounting,
} from "./usageModel";
import "./Usage.css";

export interface TokensChartProps {
  data: StatsUsage | undefined;
  period: UsagePeriod;
}

/* Tokens per bucket, stacked by model. The domain is the whole window, so
   quiet hours and days are gaps; the column's tooltip lists each model's
   total with its in/out split and call count. */
export function TokensChart({ data, period }: TokensChartProps) {
  const { t } = useTranslation("usage");
  const f = useFormat();
  const chart = useMemo(() => (data ? buildUsageChart(data, period) : null), [data, period]);
  const keys = chart?.keys ?? [];
  const first = keys[0];
  const last = keys[keys.length - 1];

  return (
    <Card kicker={t("chart.kicker")} actions={t(`chart.bucketNote.${period}`)}>
      <StackedBars
        buckets={chart?.buckets ?? []}
        ariaLabel={t("chart.aria")}
        height={200}
        formatY={(v) => f.tok(Math.round(v))}
        emptyText={data ? t("chart.empty") : t("common:empty.loading")}
        xLabels={{
          start: first ? bucketLabel(first, period, f.lang) : undefined,
          end: last ? bucketLabel(last, period, f.lang) : undefined,
        }}
        tooltip={(_, i) => {
          const key = keys[i];
          const pts = chart?.points[i] ?? [];
          if (!key || !chart) return null;
          return (
            <>
              <b>{bucketTitle(key, period, f.lang)}</b>
              {[...pts].reverse().map((p) => (
                <div key={modelKey(p)}>
                  <span className="tip-swatch" style={{ background: chart.colors.get(modelKey(p)) }} />
                  {p.recipe}:{" "}
                  <span className="tip-muted">
                    {t("chart.segment", {
                      total: f.tok((p.tokens_in ?? 0) + (p.tokens_out ?? 0)),
                      in: f.tok(p.tokens_in),
                      out: f.tok(p.tokens_out),
                      calls: t("calls", { count: p.jobs, n: f.num(p.jobs) }),
                    })}
                  </span>
                </div>
              ))}
            </>
          );
        }}
      />
      {chart && chart.models.length > 0 && (
        <Legend
          label={t("common:chart.legend")}
          items={chart.models.map((m) => ({
            id: modelKey(m),
            color: chart.colors.get(modelKey(m)) ?? "var(--series-other)",
            label: <ModelLabel worker={m.modality} model={m.recipe} />,
          }))}
        />
      )}
      {data && predatesTokenAccounting(data) && <p className="hint">{t("chart.hint")}</p>}
    </Card>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { GpuEra } from "../../api/types";
import { Card, EmptyState, FailedCount, Tag } from "../../components";
import { shortGpuName } from "../../lib/cards";
import { useFormat } from "../../lib/useFormat";
import { eraTokens } from "./usageModel";
import "./Usage.css";

export interface ErasTableProps {
  /** Newest first, each with whether its card is installed now. */
  eras: { era: GpuEra; current: boolean }[] | undefined;
}

/* Every card this machine has had: the permanent record of which hardware
   ran what, outliving the GPU samples' retention. An era's dates are its
   first and last job where it ran any (when the card did work), otherwise
   when it was first and last seen. */
export function ErasTable({ eras }: ErasTableProps) {
  const { t } = useTranslation("usage");
  const f = useFormat();
  return (
    <Card
      kicker={t("eras.kicker")}
      actions={eras ? t("eras.meta", { count: eras.length }) : undefined}
    >
      {!eras ? (
        <EmptyState compact>{t("common:empty.loading")}</EmptyState>
      ) : eras.length === 0 ? (
        <EmptyState compact>{t("eras.empty")}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table us-table">
            <thead>
              <tr>
                <th>{t("eras.card")}</th>
                <th className="num">{t("eras.vram")}</th>
                <th className="us-gap">{t("eras.from")}</th>
                <th>{t("eras.to")}</th>
                <th className="num">{t("eras.jobs")}</th>
                <th className="num">{t("eras.failed")}</th>
                <th className="num">{t("eras.tokens")}</th>
                <th className="num">{t("eras.avgRun")}</th>
              </tr>
            </thead>
            <tbody>
              {eras.map(({ era: e, current }) => {
                const tok = eraTokens(e);
                return (
                  <tr key={e.uuid} className={current ? "us-era-current" : undefined}>
                    <td className="us-nowrap" title={e.name}>
                      {shortGpuName(e.name)}{" "}
                      {current && <Tag tone="accent">{t("eras.current")}</Tag>}
                    </td>
                    <td className="num">{e.total_gb ? f.gb(e.total_gb) : "–"}</td>
                    <td className="us-nowrap us-gap">{f.day(e.first_job ?? e.first_seen)}</td>
                    <td className="us-nowrap">
                      {current ? t("eras.now") : f.day(e.last_job ?? e.last_seen)}
                    </td>
                    <td className="num">{f.num(e.jobs)}</td>
                    <td className="num">
                      <FailedCount n={e.failed} />
                    </td>
                    <td className="num" title={tok ? f.num(tok) : undefined}>
                      {tok ? f.tok(tok) : "–"}
                    </td>
                    <td className="num">{f.dur(e.avg_run_ms)}</td>
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

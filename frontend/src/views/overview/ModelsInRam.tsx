// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { useFormat } from "../../lib/useFormat";
import { useGpus } from "../../state";
import type { LaneRow } from "./laneRows";
import { ModelRow } from "./ModelRow";
import { useLaneActions } from "./useLaneActions";
import "./ModelsInRam.css";

/* What is loaded, where, and how it is held — with the one action each row
   offers. The status line under the table narrates a change until the
   catalog shows it settled. */
export function ModelsInRam({ rows }: { rows: LaneRow[] }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const gpus = useGpus().data?.gpus ?? [];
  const actions = useLaneActions();
  const vram = rows.filter((r) => r.ready).reduce((a, r) => a + r.recipe.vram_gb, 0);

  return (
    <Card
      id="models-in-ram"
      kicker={t("models.title")}
      actions={rows.length > 0 && t("models.totalVram", { gb: f.gb(vram) })}
      className="ov-mir"
    >
      {rows.length ? (
        <div className="table-wrap">
          <table className="table ov-mir-table">
            <thead>
              <tr>
                <th>{t("models.colModel")}</th>
                <th>{t("models.colModality")}</th>
                <th>{t("models.colEngine")}</th>
                <th>{t("models.colGpu")}</th>
                <th className="num">{t("models.colVram")}</th>
                <th>{t("models.colResidency")}</th>
                <th>{t("models.colLast")}</th>
                <th>
                  <span className="sr-only">{t("models.colActions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <ModelRow
                  key={r.key}
                  row={r}
                  card={gpus.find((g) => g.uuid === r.device)}
                  lastUsed={r.recipe.last_used}
                  busy={actions.busy === r.key}
                  locked={actions.busy !== null && actions.busy !== r.key}
                  onPolicy={(p) => void actions.setPolicy(r.key, p)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState compact>
          <span>
            {t("models.empty")} <a href="#/recipes">{t("models.emptyLink")}</a>.
          </span>
        </EmptyState>
      )}
      {actions.message && (
        <p className={`ov-mir-message ov-mir-message-${actions.message.tone}`} role="status">
          {actions.message.text}
        </p>
      )}
    </Card>
  );
}

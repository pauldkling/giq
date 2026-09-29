// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { JobRecord } from "../../api/types";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { JobStatus } from "../../components/JobStatus";
import { ModelLabel } from "../../components/ModelLabel";
import { useFormat } from "../../lib/useFormat";

/** The latest jobs, newest first; a failed row carries its error as the row's tooltip. */
export function RecentJobs({ jobs }: { jobs: JobRecord[] | undefined }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  return (
    <Card title={t("usage.recent")}>
      {!jobs || !jobs.length ? (
        <EmptyState compact>{jobs ? t("usage.noRecent") : t("common:empty.loading")}</EmptyState>
      ) : (
        <div className="table-wrap ov-recent">
          <table className="table">
            <thead>
              <tr>
                <th>{t("usage.colWhen")}</th>
                <th>{t("usage.colModel")}</th>
                <th>{t("usage.colStatus")}</th>
                <th className="num">{t("usage.colQueue")}</th>
                <th className="num">{t("usage.colRun")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.job_id} title={j.error ?? undefined}>
                  <td className="muted" title={f.dateTime(j.t)}>
                    {f.ago(j.t)}
                  </td>
                  <td>
                    <ModelLabel worker={j.worker} model={j.model} />
                  </td>
                  <td>
                    <JobStatus status={j.status} error={j.error} />
                  </td>
                  <td className="num">{f.dur(j.queue_ms)}</td>
                  <td className="num">{f.dur(j.run_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

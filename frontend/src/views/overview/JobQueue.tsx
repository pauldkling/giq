// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText, getJSON } from "../../api/client";
import type { StatsSummary } from "../../api/types";
import { Card } from "../../components/Card";
import { useConfirm } from "../../components/DialogProvider";
import { useFormat } from "../../lib/useFormat";
import { usePoll } from "../../lib/usePoll";
import { SLOW_POLL_MS, useStatus } from "../../state";
import { cancelJob } from "./jobs";
import { QueuedJob } from "./QueuedJob";
import { useJobDetails } from "./useJobDetails";
import "./JobQueue.css";

const MAX_SUMMARY_HOURS = 24 * 365;

/* Running and waiting jobs, straight from /status. "Completed since boot"
   is the job log's count over the process's uptime; a giq too old to report
   its uptime gets no such line rather than a guess. */
export function JobQueue() {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const confirm = useConfirm();
  const status = useStatus();
  const running = status.data?.jobs_running ?? [];
  const pending = status.data?.jobs_pending ?? [];
  const info = useJobDetails([...running, ...pending]);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const uptime = useRef<number | undefined>(undefined);
  uptime.current = status.data?.uptime_s;
  const sinceBoot = usePoll(
    useCallback(async (signal: AbortSignal) => {
      const hours = Math.min(Math.max((uptime.current ?? 0) / 3600, 0.01), MAX_SUMMARY_HOURS);
      const s = await getJSON<StatsSummary>(`/stats/summary?hours=${hours.toFixed(4)}`, { signal });
      return s.recipes.reduce((a, m) => a + m.jobs - m.failed, 0);
    }, []),
    { intervalMs: SLOW_POLL_MS, enabled: typeof status.data?.uptime_s === "number" },
  );

  const cancel = async (id: string, pos: number) => {
    const job = info[id];
    const ok = await confirm({
      title: t("queue.cancelTitle", { id }),
      body: t("queue.cancelBody", { job: job ? `${job.worker}/${job.model}` : id, pos }),
      confirmLabel: t("queue.cancelConfirm"),
      cancelLabel: t("queue.keep"),
      danger: true,
    });
    if (!ok) return;
    setCancelling(id);
    try {
      const r = await cancelJob(id);
      setMessage(
        r.cancelled ? t("queue.cancelled", { id }) : t("queue.notCancelled", { id, reason: r.reason ?? "" }),
      );
    } catch (err) {
      setMessage(t("queue.cancelFailed", { id, error: errorText(err) }));
    } finally {
      setCancelling(null);
      void status.refresh();
    }
  };

  const completed = typeof status.data?.uptime_s === "number" ? sinceBoot.data : undefined;
  return (
    <Card
      id="job-queue"
      kicker={t("queue.title")}
      actions={completed != null && t("queue.completedSinceBoot", { count: completed, formatted: f.num(completed) })}
      className="ov-jq"
    >
      {running.length > 0 && (
        <ul className="ov-jq-list">
          {running.map((id, i) => (
            <QueuedJob key={id} id={id} pos={i + 1} info={info[id]} running />
          ))}
        </ul>
      )}
      {pending.length > 0 && (
        <ul className="ov-jq-list ov-jq-pending">
          {pending.map((id, i) => (
            <QueuedJob
              key={id}
              id={id}
              pos={i + 1}
              info={info[id]}
              running={false}
              cancelling={cancelling === id}
              onCancel={() => void cancel(id, i + 1)}
            />
          ))}
        </ul>
      )}
      {!running.length && !pending.length && <p className="ov-jq-empty">{t("queue.empty")}</p>}
      {message && (
        <p className="ov-jq-message" role="status">
          {message}
        </p>
      )}
    </Card>
  );
}

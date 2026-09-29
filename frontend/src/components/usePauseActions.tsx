// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText, postJSON } from "../api/client";
import type { PauseRequest, PauseResponse } from "../api/types";
import { useCatalog, useStatus } from "../state";
import { useConfirm, useNotify } from "./DialogProvider";

export type PauseBusy = "resume" | "graceful" | "force" | null;

/* Pause and resume, with the old dashboard's protocol: a force pause asks
   first, warnings from a pause are shown (a pause that could not drain in
   time says so), and afterwards the status and catalog are re-read at once
   rather than on their next tick, so the page does not claim models are
   still loaded for a minute. */
export function usePauseActions() {
  const { t } = useTranslation();
  const status = useStatus();
  const catalog = useCatalog();
  const confirm = useConfirm();
  const notify = useNotify();
  const [busy, setBusy] = useState<PauseBusy>(null);

  async function run(action: "pause" | "resume", force = false) {
    setBusy(action === "resume" ? "resume" : force ? "force" : "graceful");
    try {
      const body: PauseRequest | undefined = action === "pause" ? { force } : undefined;
      const res = await postJSON<PauseResponse>(`/control/${action}`, body);
      if (res.warnings?.length) {
        await notify({
          title: t("pause.warningsTitle"),
          body: (
            <ul>
              {res.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          ),
        });
      }
    } catch (e) {
      await notify({
        title: action === "resume" ? t("pause.resumeFailed") : t("pause.pauseFailed"),
        body: errorText(e),
      });
    } finally {
      setBusy(null);
      void status.refresh();
      void catalog.refresh();
    }
  }

  return {
    paused: !!status.data?.paused,
    busy,
    /** Button text while a call is in flight, else null. */
    busyLabel:
      busy === "resume"
        ? t("pause.resuming")
        : busy === "force"
          ? t("pause.unloading")
          : busy === "graceful"
            ? t("pause.draining")
            : null,
    resume: () => run("resume"),
    pauseGraceful: () => run("pause", false),
    pauseForce: async () => {
      const ok = await confirm({
        title: t("pause.forceConfirmTitle"),
        body: t("pause.forceConfirmBody"),
        confirmLabel: t("pause.forceConfirm"),
        danger: true,
      });
      if (ok) await run("pause", true);
    },
  };
}

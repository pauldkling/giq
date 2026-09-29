// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import type { Policy } from "../../api/types";
import { useConfirm } from "../../components/DialogProvider";
import { useCatalog, useStatus, useStorage } from "../../state";
import { laneKey } from "./laneRows";
import { applyPolicy } from "./policy";

export type LaneMessageTone = "info" | "warn" | "error";
export interface LaneMessage {
  tone: LaneMessageTone;
  text: string;
}

interface Watch {
  worker: string;
  model: string;
  wantReady: boolean;
  tries: number;
}

const WATCH_MS = 3000;

/* The two verbs of a loaded-model row, both about a model that is already
   on a card: keep the on-demand one, stop the resident. Starting a cold model
   is a residency change and lives on the Models view.

   Stop means `off`, not `auto`: with `auto` the next request from any client
   (an agent harness, a batch job) would pull the model straight back in,
   which is the opposite of what taking it out to free the card was for. */
export function useLaneActions() {
  const { t } = useTranslation("overview");
  const confirm = useConfirm();
  const catalog = useCatalog();
  const storage = useStorage();
  const status = useStatus();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<LaneMessage | null>(null);
  const [watch, setWatch] = useState<Watch | null>(null);
  const refreshCatalog = catalog.refresh;

  // Settled once the catalog shows the state asked for.
  useEffect(() => {
    if (!watch) return;
    const m = catalog.data?.models.find((x) => x.worker === watch.worker && x.model === watch.model);
    if (m && (watch.wantReady ? m.ready : !m.ready)) {
      const key = laneKey(watch.worker, watch.model);
      setMessage({ tone: "info", text: t(watch.wantReady ? "models.settledWarm" : "models.settledOff", { key }) });
      setWatch(null);
      void status.refresh();
    }
  }, [catalog.data, watch, t, status.refresh]);

  /* An unload waits out in-flight work, so it is not done when the POST
     returns: re-read the catalog every 3 s until the row settles rather than
     leaving it mid-state until the next 60 s refresh. Pinning gets the longer
     budget: the residents loop cannot take over a worker the batch slot is
     holding, so an already-loaded model goes resident only after the 120 s
     warm timeout drops the slot — the same weights come back seconds later. */
  useEffect(() => {
    if (!watch) return;
    if (watch.tries <= 0) {
      setMessage({ tone: "warn", text: t("models.notSettled", { key: laneKey(watch.worker, watch.model) }) });
      setWatch(null);
      return;
    }
    const id = setTimeout(() => {
      void refreshCatalog();
      setWatch((w) => w && { ...w, tries: w.tries - 1 });
    }, WATCH_MS);
    return () => clearTimeout(id);
  }, [watch, refreshCatalog, t]);

  const setPolicy = useCallback(
    async (worker: string, model: string, policy: Policy) => {
      const key = laneKey(worker, model);
      const label = t(`common:policy.${policy}`);
      const pinning = policy === "pinned";
      setBusy(key);
      setWatch(null);
      setMessage({ tone: "info", text: t("models.setting", { key, policy: label }) });
      try {
        const out = await applyPolicy(worker, model, policy, (detail) =>
          confirm({
            title: t(pinning ? "models.forceTitle" : "models.stopForceTitle"),
            body: detail,
            confirmLabel: t(pinning ? "models.forceConfirm" : "models.stopForceConfirm"),
            danger: true,
          }),
        );
        if (out.kind === "refused") {
          setMessage({ tone: "warn", text: t("models.refused", { detail: out.detail }) });
          return;
        }
        const base = t(pinning ? "models.appliedPinned" : policy === "off" ? "models.appliedOff" : "models.applied", {
          key,
          policy: label,
        });
        const warnings = out.response.warnings ?? [];
        setMessage({
          tone: warnings.length ? "warn" : "info",
          text: warnings.length ? t("models.warnings", { text: base, warnings: warnings.join(" · ") }) : base,
        });
        await Promise.all([refreshCatalog(), storage.refresh(), status.refresh()]);
        setWatch({ worker, model, wantReady: pinning, tries: pinning ? 80 : 20 });
      } catch (err) {
        setMessage({ tone: "error", text: t("models.failed", { key, error: errorText(err) }) });
        void refreshCatalog();
      } finally {
        setBusy(null);
      }
    },
    [t, confirm, refreshCatalog, storage.refresh, status.refresh],
  );

  return { busy, message, watching: watch ? laneKey(watch.worker, watch.model) : null, setPolicy };
}

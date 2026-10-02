// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { setResidency } from "../../api/recipes";
import type { Policy } from "../../api/types";
import { useConfirm } from "../../components/DialogProvider";
import { useInstances, useRecipes, useStatus, useStorage } from "../../state";

export type LaneMessageTone = "info" | "warn" | "error";
export interface LaneMessage {
  tone: LaneMessageTone;
  text: string;
}

interface Watch {
  /** The recipe name. */
  key: string;
  wantReady: boolean;
  tries: number;
}

const WATCH_MS = 3000;

/* The two verbs of a loaded row, both about a recipe already on a card:
   keep the on-demand one, stop the resident. Starting a cold recipe is a
   residency change and lives on the Recipes view.

   Stop means `off`, not `auto`: with `auto` the next request from any client
   (an agent harness, a batch job) would pull the model straight back in,
   which is the opposite of what taking it out to free the card was for. */
export function useLaneActions() {
  const { t } = useTranslation("overview");
  const confirm = useConfirm();
  const recipes = useRecipes();
  const instances = useInstances();
  const storage = useStorage();
  const status = useStatus();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<LaneMessage | null>(null);
  const [watch, setWatch] = useState<Watch | null>(null);
  const refreshRecipes = recipes.refresh;
  const refreshInstances = instances.refresh;

  // Settled once the instances show the state asked for.
  useEffect(() => {
    if (!watch || !instances.data) return;
    const ready = instances.data.instances.some((i) => i.recipe === watch.key && i.state === "ready");
    if (watch.wantReady ? ready : !ready) {
      setMessage({
        tone: "info",
        text: t(watch.wantReady ? "models.settledWarm" : "models.settledOff", { key: watch.key }),
      });
      setWatch(null);
      void status.refresh();
      void refreshRecipes();
    }
  }, [instances.data, watch, t, status.refresh, refreshRecipes]);

  /* An unload waits out in-flight work, so it is not done when the POST
     returns: re-read the instances every 3 s until the row settles rather than
     leaving it mid-state until the next 60 s refresh. Pinning gets the longer
     budget: the residents loop cannot take over a worker the batch slot is
     holding, so an already-loaded model goes resident only after the 120 s
     warm timeout drops the slot — the same weights come back seconds later. */
  useEffect(() => {
    if (!watch) return;
    if (watch.tries <= 0) {
      setMessage({ tone: "warn", text: t("models.notSettled", { key: watch.key }) });
      setWatch(null);
      return;
    }
    const id = setTimeout(() => {
      void refreshInstances();
      setWatch((w) => w && { ...w, tries: w.tries - 1 });
    }, WATCH_MS);
    return () => clearTimeout(id);
  }, [watch, refreshInstances, t]);

  const setPolicy = useCallback(
    async (key: string, policy: Policy) => {
      const label = t(`common:policy.${policy}`);
      const pinning = policy === "pinned";
      setBusy(key);
      setWatch(null);
      setMessage({ tone: "info", text: t("models.setting", { key, policy: label }) });
      try {
        const out = await setResidency(key, policy, (detail) =>
          confirm({
            title: t(pinning ? "models.forceTitle" : "models.stopForceTitle"),
            body: detail,
            confirmLabel: t(pinning ? "models.forceConfirm" : "models.stopForceConfirm"),
            danger: true,
          }),
        );
        if (!out.ok) {
          setMessage({ tone: "warn", text: t("models.refused", { detail: out.declined }) });
          return;
        }
        const base = t(pinning ? "models.appliedPinned" : policy === "off" ? "models.appliedOff" : "models.applied", {
          key,
          policy: label,
        });
        const warnings = out.result.warnings;
        setMessage({
          tone: warnings.length ? "warn" : "info",
          text: warnings.length ? t("models.warnings", { text: base, warnings: warnings.join(" · ") }) : base,
        });
        await Promise.all([refreshRecipes(), refreshInstances(), storage.refresh(), status.refresh()]);
        setWatch({ key, wantReady: pinning, tries: pinning ? 80 : 20 });
      } catch (err) {
        setMessage({ tone: "error", text: t("models.failed", { key, error: errorText(err) }) });
        void refreshRecipes();
      } finally {
        setBusy(null);
      }
    },
    [t, confirm, refreshRecipes, refreshInstances, storage.refresh, status.refresh],
  );

  return { busy, message, watching: watch ? watch.key : null, setPolicy };
}

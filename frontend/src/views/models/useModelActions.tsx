// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import type { CatalogModel, Policy } from "../../api/types";
import { useConfirm, useNotify } from "../../components/DialogProvider";
import { useFormat } from "../../lib/useFormat";
import { useCatalog, useStatus, useStorage } from "../../state";
import { deleteSummary, deleteWeights, revertPolicy, setDevice, setPolicy } from "./actions";
import { modelKey } from "./catalog";

export interface ActionMessage {
  text: string;
  tone: "info" | "good" | "warning";
}

export interface ModelActions {
  /** Whether a change to this model is in flight (its controls are disabled meanwhile). */
  isBusy: (m: CatalogModel) => boolean;
  /** The last action's outcome, shown above the catalog. */
  message: ActionMessage | null;
  dismiss: () => void;
  changePolicy: (m: CatalogModel, policy: Policy) => Promise<void>;
  revert: (m: CatalogModel) => Promise<void>;
  /** device null = unbind; cardText names the target in the result line. */
  bind: (m: CatalogModel, device: string | null, cardText: string | null) => Promise<void>;
  removeWeights: (m: CatalogModel, sizeText: string) => Promise<void>;
}

/* The card's mutations bound to the dialogs and the shared data. After any
   change the catalog, the disk report and /status are fetched again at once
   rather than on their next tick: a residency or binding change moves the
   budgets, and a stale card right after a click reads as "it didn't work". */
export function useModelActions(): ModelActions {
  const { t } = useTranslation("models");
  const confirm = useConfirm();
  const notify = useNotify();
  const fmt = useFormat();
  const catalog = useCatalog();
  const storage = useStorage();
  const status = useStatus();
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [message, setMessage] = useState<ActionMessage | null>(null);

  const refresh = useCallback(
    () => Promise.all([catalog.refresh(), storage.refresh(), status.refresh()]).then(() => undefined),
    [catalog.refresh, storage.refresh, status.refresh],
  );

  /* Runs one change for one model: marks it busy, reports a failure as a
     dialog with the server's detail, and refreshes whatever happened —
     a refused change still needs the controls re-synced to the server. */
  const run = useCallback(
    async (m: CatalogModel, failTitle: string, body: (key: string) => Promise<void>) => {
      const key = modelKey(m);
      setBusy((b) => new Set(b).add(key));
      setMessage({ text: t("status.working", { key }), tone: "info" });
      try {
        await body(key);
      } catch (err) {
        setMessage(null);
        await notify({ title: failTitle, body: errorText(err) });
      } finally {
        setBusy((b) => {
          const next = new Set(b);
          next.delete(key);
          return next;
        });
        await refresh();
      }
    },
    [t, notify, refresh],
  );

  const warn = useCallback(
    (title: string, warnings: string[]) =>
      warnings.length ? notify({ title, body: warnings.join("\n") }) : Promise.resolve(),
    [notify],
  );

  // The 409 detail is the server's explanation of the over-commit: shown as is.
  const forceDialog = useCallback(
    (title: string, confirmLabel: string) => (detail: string) =>
      confirm({ title, body: detail, confirmLabel }),
    [confirm],
  );

  return useMemo<ModelActions>(
    () => ({
      isBusy: (m) => busy.has(modelKey(m)),
      message,
      dismiss: () => setMessage(null),

      changePolicy: (m, policy) =>
        run(m, t("residency.failed"), async (key) => {
          const r = await setPolicy(
            m.worker,
            m.model,
            policy,
            forceDialog(t("residency.forceTitle"), t("residency.forceConfirm")),
          );
          if (!r.ok) {
            setMessage({ text: t("residency.declined", { key }), tone: "info" });
            return;
          }
          setMessage({ text: t(`residency.done.${policy}`, { key }), tone: "good" });
          await warn(t("residency.warningsTitle"), r.result.warnings);
        }),

      revert: (m) =>
        run(m, t("residency.revertFailed"), async (key) => {
          await revertPolicy(m.worker, m.model);
          setMessage({ text: t("residency.reverted", { key }), tone: "good" });
        }),

      bind: (m, device, cardText) =>
        run(m, t("device.failed"), async (key) => {
          const r = await setDevice(
            m.worker,
            m.model,
            device,
            forceDialog(t("device.forceTitle"), t("device.forceConfirm")),
          );
          if (!r.ok) {
            setMessage({ text: t("device.declined", { key }), tone: "info" });
            return;
          }
          const card = r.result.state.device_name ?? cardText ?? t("device.defaultCard");
          setMessage({ text: t("device.done", { key, card }), tone: "good" });
          await warn(t("device.warningsTitle"), r.result.warnings);
        }),

      removeWeights: async (m, sizeText) => {
        const key = modelKey(m);
        const ok = await confirm({
          title: t("delete.confirmTitle", { key }),
          body: t("delete.confirmBody", { size: sizeText }),
          confirmLabel: t("delete.confirm"),
          danger: true,
        });
        if (!ok) return;
        await run(m, t("delete.failed"), async () => {
          const r = await deleteWeights(m.worker, m.model);
          setMessage({ text: deleteSummary(t, key, r, fmt.bytes), tone: "good" });
        });
      },
    }),
    [busy, message, run, t, confirm, forceDialog, warn, fmt.bytes],
  );
}

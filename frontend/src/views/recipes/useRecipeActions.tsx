// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { clearResidency, setCard, setResidency } from "../../api/recipes";
import type { Policy, RecipeEntry } from "../../api/types";
import { useConfirm, useNotify } from "../../components/DialogProvider";
import { useInstances, useRecipes, useStatus } from "../../state";

export interface ActionMessage {
  text: string;
  tone: "info" | "good" | "warning";
}

export interface RecipeActions {
  /** Whether a change to this recipe is in flight (its controls are disabled meanwhile). */
  isBusy: (r: RecipeEntry) => boolean;
  /** The last action's outcome, shown above the catalog. */
  message: ActionMessage | null;
  dismiss: () => void;
  changePolicy: (r: RecipeEntry, policy: Policy) => Promise<void>;
  revert: (r: RecipeEntry) => Promise<void>;
  /** device null = unbind; cardText names the target in the result line. */
  bind: (r: RecipeEntry, device: string | null, cardText: string | null) => Promise<void>;
}

/* The card's mutations bound to the dialogs and the shared data. After any
   change the recipes, the instances and /status are fetched again at once
   rather than on their next tick: a residency or binding change moves the
   budgets, and a stale card right after a click reads as "it didn't work".
   Deleting weights is the Inventory view's: weights are not a recipe's. */
export function useRecipeActions(): RecipeActions {
  const { t } = useTranslation("recipes");
  const confirm = useConfirm();
  const notify = useNotify();
  const recipes = useRecipes();
  const instances = useInstances();
  const status = useStatus();
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [message, setMessage] = useState<ActionMessage | null>(null);

  const refresh = useCallback(
    () => Promise.all([recipes.refresh(), instances.refresh(), status.refresh()]).then(() => undefined),
    [recipes.refresh, instances.refresh, status.refresh],
  );

  /* Runs one change for one recipe: marks it busy, reports a failure as a
     dialog with the server's detail, and refreshes whatever happened —
     a refused change still needs the controls re-synced to the server. */
  const run = useCallback(
    async (r: RecipeEntry, failTitle: string, body: (key: string) => Promise<void>) => {
      const key = r.name;
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

  return useMemo<RecipeActions>(
    () => ({
      isBusy: (r) => busy.has(r.name),
      message,
      dismiss: () => setMessage(null),

      changePolicy: (recipe, policy) =>
        run(recipe, t("residency.failed"), async (key) => {
          const r = await setResidency(
            recipe.name,
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

      revert: (recipe) =>
        run(recipe, t("residency.revertFailed"), async (key) => {
          await clearResidency(recipe.name);
          setMessage({ text: t("residency.reverted", { key }), tone: "good" });
        }),

      bind: (recipe, device, cardText) =>
        run(recipe, t("device.failed"), async (key) => {
          const r = await setCard(
            recipe.name,
            device,
            forceDialog(t("device.forceTitle"), t("device.forceConfirm")),
          );
          if (!r.ok) {
            setMessage({ text: t("device.declined", { key }), tone: "info" });
            return;
          }
          const card = r.result.recipe.card.name ?? cardText ?? t("device.defaultCard");
          setMessage({ text: t("device.done", { key, card }), tone: "good" });
          await warn(t("device.warningsTitle"), r.result.warnings);
        }),

    }),
    [busy, message, run, t, forceDialog, warn],
  );
}

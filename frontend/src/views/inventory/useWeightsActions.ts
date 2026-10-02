// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { deleteWeights } from "../../api/recipes";
import type { WeightsItem } from "../../api/types";
import { useConfirm, useNotify } from "../../components/DialogProvider";
import { useFormat } from "../../lib/useFormat";
import { useRecipes, useStorage, useWeights } from "../../state";

/* Deleting one checkpoint, bound to the dialogs. The server refuses while a
   recipe that uses it is resident or loaded; that refusal is its own
   explanation and is shown as is. Afterwards the weights, the recipes (which
   may now be uninstalled) and the disk report are re-read at once. */
export function useWeightsActions() {
  const { t } = useTranslation("inventory");
  const confirm = useConfirm();
  const notify = useNotify();
  const fmt = useFormat();
  const weights = useWeights();
  const recipes = useRecipes();
  const storage = useStorage();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const remove = useCallback(
    async (w: WeightsItem, what: string) => {
      const ok = await confirm({
        title: t("delete.confirmTitle", { what }),
        body: t("delete.confirmBody", {
          count: w.recipes.length,
          size: fmt.bytes(w.size_bytes),
          recipes: w.recipes.join(", "),
        }),
        confirmLabel: t("delete.confirm"),
        danger: true,
      });
      if (!ok) return;
      setBusy(w.id);
      try {
        const r = await deleteWeights(w.id);
        setMessage(t("delete.done", { what, freed: fmt.bytes(r.freed_bytes) }));
      } catch (err) {
        await notify({ title: t("delete.failed"), body: errorText(err) });
      } finally {
        setBusy(null);
        await Promise.all([weights.refresh(), recipes.refresh(), storage.refresh()]);
      }
    },
    [t, confirm, notify, fmt, weights.refresh, recipes.refresh, storage.refresh],
  );

  return { busy, message, dismiss: () => setMessage(null), remove };
}

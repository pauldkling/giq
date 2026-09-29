// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import type { Catalog } from "../../api/types";
import { navigateReplace } from "./navigate";
import type { SandboxModels } from "./models";
import type { SandboxRoute } from "../../lib/sandboxLink";
import { isSelectTab, TAB_FOR_WORKER, type SelectTab, type Tab } from "./tabs";

/* "Test in sandbox" arrives as #/sandbox/<tab>?model=<name>. Once the
   catalog is known the model is chosen in that panel and the query leaves
   the address, so the link is consumed once and a later catalog refresh
   cannot re-apply it over a choice made by hand. Nothing runs: pressing Run
   is what loads the model. A link without a tab goes to the panel for the
   model's worker. Returns the model (and its panel) when the panel cannot
   take it — never-fits, or no such model — so the view can say so. */
export interface PreselectMiss {
  tab: Tab;
  model: string;
}

export function usePreselect(
  route: SandboxRoute,
  catalog: Catalog | undefined,
  models: SandboxModels,
  choose: (tab: SelectTab, model: string) => void,
): PreselectMiss | null {
  const [missed, setMissed] = useState<PreselectMiss | null>(null);
  const { model } = route;

  useEffect(() => {
    if (!model || !catalog) return;
    const worker = catalog.models.find((m) => m.model === model)?.worker;
    const tab: Tab = route.tab ?? (worker && TAB_FOR_WORKER[worker]) ?? "chat";
    if (isSelectTab(tab)) {
      const ok = models[tab].some((o) => o.model === model);
      if (ok) choose(tab, model);
      setMissed(ok ? null : { tab, model });
    } else {
      // Speech panels have no model select; they open, and run what the lane has.
      setMissed(null);
    }
    navigateReplace(tab);
  }, [model, route.tab, catalog, models, choose]);

  return missed;
}

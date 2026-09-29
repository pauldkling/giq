// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useState } from "react";
import type { SandboxModels } from "./models";
import type { SelectTab } from "./tabs";

/* The model chosen in each panel that has a model select. A choice survives
   catalog refreshes; when the chosen model leaves the list (deleted, switched
   to never-fits) the panel falls back to its default until it returns. The
   default is the first option, except chat, which prefers whatever answers
   soonest (see sandboxModels). */
export function useModelChoices(models: SandboxModels) {
  const [chosen, setChosen] = useState<Partial<Record<SelectTab, string>>>({});

  /* Chat's default is taken once, when the catalog first answers: a later
     refresh that finds another model loaded must not swap the model under a
     prompt being typed. (Setting state during render is React's pattern for
     state derived from props; the guard makes it fire once.) */
  if (chosen.chat === undefined && models.chatDefault) {
    setChosen((p) => ({ ...p, chat: p.chat ?? models.chatDefault ?? undefined }));
  }

  const value = (tab: SelectTab): string => {
    const opts = models[tab];
    const c = chosen[tab];
    if (c && opts.some((o) => o.model === c)) return c;
    const def = tab === "chat" ? models.chatDefault : null;
    return def ?? opts[0]?.model ?? "";
  };

  const choose = useCallback((tab: SelectTab, model: string) => {
    setChosen((p) => ({ ...p, [tab]: model }));
  }, []);

  return { value, choose };
}

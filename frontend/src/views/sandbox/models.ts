// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Fit, Modality, Policy, RecipeEntry, RecipesResponse } from "../../api/types";
import { TOOLS_MODEL } from "./constants";
import type { Tab } from "./tabs";

/* What each panel can offer, derived from the shared recipe list on every
   refresh (the old page read it once at load, so a recipe loaded or pinned
   since stayed labelled with its stale fit until a reload). */

export interface ModelOption {
  /** The recipe name: what a request sends as `model`. */
  model: string;
  vram_gb: number;
  fits: Fit;
  policy: Policy;
  reasoning: RecipeEntry["reasoning"];
  /** Weights present on disk. */
  onDisk: boolean;
}

export interface SandboxModels {
  /** The recipes have answered; before that, nothing is "missing". */
  ready: boolean;
  chat: ModelOption[];
  t2i: ModelOption[];
  edit: ModelOption[];
  vision: ModelOption[];
  /** The chat panel's starting choice. */
  chatDefault: string | null;
  /** The tool-calling recipe exists and can load. */
  toolsAvailable: boolean;
}

const usable = (r: RecipeEntry) => r.fit !== "never";

/* A recipe can serve several modalities (ADR-003): flux_klein renders and
   edits from one process, so it belongs in both image tabs. */
export const serves = (r: RecipeEntry, modality: Modality): boolean => r.modalities.includes(modality);

function option(r: RecipeEntry): ModelOption {
  return {
    model: r.name,
    vram_gb: r.vram_gb,
    fits: r.fit,
    policy: r.residency.policy,
    reasoning: r.reasoning,
    onDisk: r.installed,
  };
}

export function sandboxModels(recipes: RecipesResponse | undefined): SandboxModels {
  if (!recipes) {
    return { ready: false, chat: [], t2i: [], edit: [], vision: [], chatDefault: null, toolsAvailable: true };
  }
  const usableRecipes = recipes.recipes.filter(usable);
  const of = (pred: (r: RecipeEntry) => boolean) => usableRecipes.filter(pred).map(option);
  /* Every LLM that can load is selectable (the panel was once pinned to one
     model, so "test" on any other LLM card had nowhere to land). */
  const llms = usableRecipes.filter((r) => serves(r, "llm"));
  /* Default to whatever answers soonest: already loaded, else kept warm,
     else one resident by default. Alphabetical order (the fallback) picks an
     18 GB recipe nobody asked for. */
  const preferred =
    llms.find((r) => r.fit === "loaded") ??
    llms.find((r) => r.residency.policy === "pinned") ??
    llms.find((r) => r.residency.default_resident) ??
    llms[0];
  return {
    ready: true,
    chat: llms.map(option),
    t2i: of((r) => serves(r, "text2image")),
    edit: of((r) => serves(r, "image_edit")),
    vision: of((r) => r.vision),
    chatDefault: preferred?.name ?? null,
    toolsAvailable: llms.some((r) => r.name === TOOLS_MODEL && r.residency.policy !== "off"),
  };
}

/** Tabs with nothing to run: greyed out in the tab bar once the catalog is known. */
export function disabledTabs(m: SandboxModels): Set<Tab> {
  const off = new Set<Tab>();
  if (!m.ready) return off;
  if (!m.chat.length) off.add("chat");
  if (!m.toolsAvailable) off.add("tools");
  if (!m.t2i.length) off.add("t2i");
  if (!m.edit.length) off.add("edit");
  if (!m.vision.length) off.add("vision");
  return off;
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Catalog, CatalogModel, Fit, Policy, StorageResponse } from "../../api/types";
import { TOOLS_MODEL } from "./constants";
import type { Tab } from "./tabs";

/* What each panel can offer, derived from the shared catalog and disk report
   on every refresh (the old page read them once at load, so a model loaded
   or pinned since stayed labelled with its stale fit until a reload). */

export interface ModelOption {
  model: string;
  vram_gb: number;
  fits: Fit;
  policy: Policy;
  reasoning: CatalogModel["reasoning"];
  /** Weights present on disk; null while /storage has not answered. */
  onDisk: boolean | null;
}

export interface SandboxModels {
  /** The catalog has answered; before that, nothing is "missing". */
  ready: boolean;
  chat: ModelOption[];
  t2i: ModelOption[];
  edit: ModelOption[];
  vision: ModelOption[];
  /** The chat panel's starting choice. */
  chatDefault: string | null;
  /** The tool-calling model is registered and can load. */
  toolsAvailable: boolean;
}

const usable = (m: CatalogModel) => m.fits !== "never";

function option(m: CatalogModel, disk: Map<string, boolean> | null): ModelOption {
  return {
    model: m.model,
    vram_gb: m.vram_gb,
    fits: m.fits,
    policy: m.policy,
    reasoning: m.reasoning,
    onDisk: disk ? (disk.get(`${m.worker}/${m.model}`) ?? false) : null,
  };
}

export function sandboxModels(
  catalog: Catalog | undefined,
  storage: StorageResponse | undefined,
): SandboxModels {
  if (!catalog) {
    return { ready: false, chat: [], t2i: [], edit: [], vision: [], chatDefault: null, toolsAvailable: true };
  }
  /* Whether the weights exist is a /storage fact, and the vision panel needs
     it: a registered model with nothing on disk cannot load, and "asking
     loads it first" would send you to watch a failure. */
  const disk = storage
    ? new Map(storage.models.map((s) => [`${s.worker}/${s.model}`, !!(s.on_disk || s.size_bytes)]))
    : null;
  const models = catalog.models.filter(usable);
  const of = (pred: (m: CatalogModel) => boolean) => models.filter(pred).map((m) => option(m, disk));
  /* Every LLM that can load is selectable (the panel was once pinned to one
     model, so "test" on any other LLM card had nowhere to land). */
  const llms = models.filter((m) => m.worker === "llm");
  /* Default to whatever answers soonest: already loaded, else kept warm,
     else the registry's intended resident. Alphabetical order (the
     fallback) picks an 18 GB model nobody asked for. */
  const preferred =
    llms.find((m) => m.fits === "loaded") ??
    llms.find((m) => m.resident) ??
    llms.find((m) => m.resident_default) ??
    llms[0];
  return {
    ready: true,
    chat: llms.map((m) => option(m, disk)),
    t2i: of((m) => m.worker === "text2image"),
    edit: of((m) => m.worker === "image_edit"),
    vision: of((m) => m.vision),
    chatDefault: preferred?.model ?? null,
    toolsAvailable: llms.some((m) => m.model === TOOLS_MODEL && m.policy !== "off"),
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

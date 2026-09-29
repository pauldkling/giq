// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { CatalogModel, EnginesResponse, Fit, StorageModel } from "../../api/types";
import type { TagTone } from "../../components/Tag";
import { SANDBOX_TAB_FOR_WORKER } from "../../lib/sandboxLink";

/* The Models view's pure logic: joining the catalog with the disk report,
   the facets, and the small tables that decide what a card offers. Kept out
   of the components so it is testable without a DOM. */

/** "worker/model", the key /storage and the pinned lists use. */
export const modelKey = (m: { worker: string; model: string }): string => `${m.worker}/${m.model}`;

/** A catalog entry with what is on disk for it (an empty record when /storage has not answered). */
export interface ModelEntry {
  m: CatalogModel;
  s: Partial<StorageModel>;
}

/** Weights present: a model with none has nothing to run, delete or bind. */
export const hasWeights = (s: Partial<StorageModel>): boolean => Boolean(s.on_disk || s.size_bytes);

export function joinStorage(models: CatalogModel[], storage: StorageModel[] | undefined): ModelEntry[] {
  const disk = new Map((storage ?? []).map((s) => [modelKey(s), s]));
  return models.map((m) => ({ m, s: disk.get(modelKey(m)) ?? {} }));
}

export interface Filters {
  modality: ReadonlySet<string>;
  engine: ReadonlySet<string>;
}

/* Nothing selected means everything: an empty filter is not an empty result. */
export function matches(m: CatalogModel, f: Filters): boolean {
  return (!f.modality.size || f.modality.has(m.worker)) && (!f.engine.size || f.engine.has(m.backend));
}

/** Facet values with their counts over the whole catalog, sorted by name. */
export function facetCounts(models: CatalogModel[], pick: (m: CatalogModel) => string): [string, number][] {
  const n = new Map<string, number>();
  for (const m of models) n.set(pick(m), (n.get(pick(m)) ?? 0) + 1);
  return [...n.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

/* Fit badge tones. "fits" is the ordinary case and stays neutral; only the
   answers that change what happens next (a load evicts something, or it
   cannot load) carry a status colour. */
export const FIT_TONE: Record<Fit, TagTone> = {
  loaded: "good",
  fits_now: "neutral",
  fits_after_eviction: "serious",
  wont_fit_now: "critical",
  never: "critical",
};

/** Why "Test in sandbox" is unavailable, as a models.json key; null when it is available. */
export function sandboxBlock(m: CatalogModel, s: Partial<StorageModel>): string | null {
  if (!SANDBOX_TAB_FOR_WORKER[m.worker]) return "menu.noPanel";
  if (!s.on_disk) return "menu.nothingToRun";
  if (m.fits === "never") return "menu.tooLarge";
  return null;
}

/* Why weights cannot be deleted, as a models.json key; null when they can.
   A kept-warm model would be reloaded on the next scheduler tick, so it has
   to be let go first; a loaded one holds the files open. */
export function deleteBlock(m: CatalogModel, s: Partial<StorageModel>): string | null {
  if (m.resident) return "menu.deleteKeptWarm";
  if (m.fits === "loaded") return "menu.deleteLoaded";
  if (!s.size_bytes) return "menu.deleteNothing";
  return null;
}

/* Keeping a model warm that cannot fit its card, or has no weights to load,
   would only make the resident set unsatisfiable; switching it off is always
   allowed. Returns the models.json key of the reason, or null. */
export function pinBlock(m: CatalogModel, s: Partial<StorageModel>): string | null {
  if (m.policy === "pinned") return null;
  if (m.fits === "never") return "residency.tooLarge";
  if (!hasWeights(s)) return "residency.noWeights";
  return null;
}

/* The runtime whose build is worth showing beside the engine name. "Which
   llama.cpp" changes behaviour and is easy to lose track of; for an
   interpreter-hosted backend the Python version is not the library version,
   and showing it would read as if it were. */
export const BUILT_ENGINES: ReadonlySet<string> = new Set(["llama.cpp", "sd.cpp"]);

/** runtime → its build string (prefix noise trimmed), or null when the binary is missing. */
export function engineVersions(e: EnginesResponse | undefined): Map<string, string | null> {
  return new Map(
    (e?.engines ?? []).map((x) => [
      x.name,
      x.present
        ? (x.version ?? "").replace(/^version:\s*/i, "").replace(/^stable-diffusion\.cpp\s*/i, "")
        : null,
    ]),
  );
}

/* Engine explanations live in models.json under engineNote.<key>; backend
   names contain dots, which i18next reads as nesting, so they map to keys. */
export const ENGINE_NOTE_KEY: Record<string, string> = {
  "llama.cpp": "llamaCpp",
  "sd.cpp": "sdCpp",
  "faster-whisper+pyannote": "fasterWhisperPyannote",
  speechbrain: "speechbrain",
  "faster-whisper": "fasterWhisper",
  kokoro: "kokoro",
  transformers: "transformers",
  "transformers-4.57": "transformers457",
  da3: "da3",
};

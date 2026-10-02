// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/* How a GPU is named anywhere in the dashboard. One place, so the overview's
   cards, the models view's picker and the usage filter never disagree about
   what a card is called. */

/** "RTX 5090" from "NVIDIA GeForce RTX 5090": the vendor prefix is on every card. */
export function shortGpuName(name: string): string {
  return name.replace(/^NVIDIA (GeForce )?/, "");
}

/** A card as the GPU picker needs it; free VRAM from whichever endpoint has it. */
export interface CardChoice {
  uuid: string;
  index: number;
  name: string;
  free: number | null;
}

/* The card list arrives from two endpoints with two names for free VRAM
   (/gpus says vram_free_gb, /recipes says free_gb). /gpus is polled
   every 3 s and so is fresher; the catalog's list is the fallback. */
export function cardChoices(
  gpus: { uuid: string; index: number; name: string; vram_free_gb?: number }[] | undefined,
  catalogCards: { uuid: string; index: number; name: string; free_gb?: number }[] | undefined,
): CardChoice[] {
  const src = gpus?.length ? gpus : (catalogCards ?? []);
  return src.map((c) => ({
    uuid: c.uuid,
    index: c.index,
    name: c.name,
    free:
      ("vram_free_gb" in c ? c.vram_free_gb : undefined) ??
      ("free_gb" in c ? c.free_gb : undefined) ??
      null,
  }));
}

/* A card by name ("RTX 5060 Ti"), not by index: "#1" is not something an
   operator knows. Two of the same card is what names alone can't carry, so
   the index comes back only when a name is ambiguous. */
export function cardName(c: CardChoice, all: CardChoice[]): string {
  const dupe = all.filter((x) => x.name === c.name).length > 1;
  return `${dupe ? `#${c.index} ` : ""}${shortGpuName(c.name)}`;
}

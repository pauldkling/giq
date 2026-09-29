// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { SandboxTab as Tab } from "../../lib/sandboxLink";

/* The tab list and the worker → tab map are the sandbox's address contract,
   shared with the views that link here (lib/sandboxLink.ts). */
export {
  DEFAULT_SANDBOX_TAB as DEFAULT_TAB,
  isSandboxTab as isTab,
  SANDBOX_TAB_FOR_WORKER as TAB_FOR_WORKER,
  SANDBOX_TABS as TABS,
  type SandboxTab as Tab,
} from "../../lib/sandboxLink";

/** The WorkerIcon key each tab shows. */
export const TAB_ICON: Record<Tab, string> = {
  chat: "llm",
  tools: "llm",
  t2i: "text2image",
  edit: "image_edit",
  vision: "vision",
  asr: "audio",
  tts: "tts",
  voice: "embed",
};

/** Tabs that pick their model from a dropdown, and so can take one from the URL. */
export const SELECT_TABS = ["chat", "t2i", "edit", "vision"] as const;
export type SelectTab = (typeof SELECT_TABS)[number];

export const isSelectTab = (t: Tab): t is SelectTab =>
  (SELECT_TABS as readonly string[]).includes(t);

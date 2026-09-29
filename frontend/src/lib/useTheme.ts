// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useSyncExternalStore } from "react";

/* Theme choice: system (no attribute, follow the OS), light or dark. The
   stored choice is applied before first paint by the inline script in
   index.html; this hook keeps <html data-theme> and localStorage in step
   after that. Charts need no re-render on a switch: they paint with
   var(--…) and follow the tokens by themselves. */

export type ThemeChoice = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const KEY = "giq-theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];
const listeners = new Set<() => void>();

function readChoice(): ThemeChoice {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" || attr === "dark" ? attr : "system";
}

function systemTheme(): ResolvedTheme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  const mq = window.matchMedia?.("(prefers-color-scheme: light)");
  mq?.addEventListener("change", cb);
  return () => {
    listeners.delete(cb);
    mq?.removeEventListener("change", cb);
  };
}

export function setThemeChoice(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    if (choice === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, choice);
  } catch {
    /* storage disabled: the choice lasts for this page only */
  }
  listeners.forEach((l) => l());
}

export function useTheme(): {
  choice: ThemeChoice;
  resolved: ResolvedTheme;
  setChoice: (c: ThemeChoice) => void;
  cycle: () => void;
} {
  const choice = useSyncExternalStore(subscribe, readChoice, () => "system" as ThemeChoice);
  const system = useSyncExternalStore(subscribe, systemTheme, () => "dark" as ResolvedTheme);
  const cycle = useCallback(() => {
    const next = ORDER[(ORDER.indexOf(readChoice()) + 1) % ORDER.length]!;
    setThemeChoice(next);
  }, []);
  return {
    choice,
    resolved: choice === "system" ? system : choice,
    setChoice: setThemeChoice,
    cycle,
  };
}

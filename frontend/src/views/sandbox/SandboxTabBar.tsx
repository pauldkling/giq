// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { WorkerIcon } from "../../components/WorkerIcon";
import { TAB_ICON, TABS, type Tab } from "./tabs";
import "./SandboxTabBar.css";

export interface SandboxTabBarProps {
  active: Tab;
  disabled: Set<Tab>;
  onSelect: (tab: Tab) => void;
}

export const tabId = (tab: Tab) => `sbx-tab-${tab}`;
export const panelId = (tab: Tab) => `sbx-panel-${tab}`;

/* ARIA tabs: one tab stop, arrow keys move between the enabled tabs (and
   select them, since each is a cheap view switch), Home/End jump. A tab
   with nothing to run is disabled with a title saying why. */
export function SandboxTabBar({ active, disabled, onSelect }: SandboxTabBarProps) {
  const { t } = useTranslation("sandbox");
  const refs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({});
  const enabled = TABS.filter((x) => !disabled.has(x));

  // On a phone the strip scrolls sideways; keep the open tab in view (deep links land off-screen otherwise).
  useEffect(() => {
    refs.current[active]?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [active]);

  const onKey = (e: KeyboardEvent) => {
    const i = enabled.indexOf(active);
    const next =
      e.key === "ArrowRight" ? enabled[(i + 1) % enabled.length]
      : e.key === "ArrowLeft" ? enabled[(i - 1 + enabled.length) % enabled.length]
      : e.key === "Home" ? enabled[0]
      : e.key === "End" ? enabled[enabled.length - 1]
      : undefined;
    if (!next) return;
    e.preventDefault();
    onSelect(next);
    refs.current[next]?.focus();
  };

  return (
    <div className="sbx-tabs" role="tablist" aria-label={t("tabsLabel")} onKeyDown={onKey}>
      {TABS.map((tab) => {
        const off = disabled.has(tab);
        const on = tab === active;
        return (
          <button
            key={tab}
            ref={(el) => {
              refs.current[tab] = el;
            }}
            type="button"
            role="tab"
            id={tabId(tab)}
            aria-selected={on}
            aria-controls={panelId(tab)}
            tabIndex={on ? 0 : -1}
            disabled={off}
            title={off ? t("tabDisabled") : undefined}
            className={`sbx-tab${on ? " sbx-tab-active" : ""}`}
            onClick={() => onSelect(tab)}
          >
            <WorkerIcon worker={TAB_ICON[tab]} size={14} colored={on} />
            {t(`tab.${tab}`)}
          </button>
        );
      })}
    </div>
  );
}

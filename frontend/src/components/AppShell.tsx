// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { ListIcon, XIcon } from "@phosphor-icons/react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { View } from "../lib/useHashRoute";
import { Icon } from "./Icon";
import { PauseBanner } from "./PauseBanner";
import { Sidebar } from "./Sidebar";
import "./AppShell.css";

/* The frame every view renders in: the sidebar (a drawer with a top bar
   under ~900px), the app-wide pause banner, and the scrolling main column. */
export function AppShell({ view, children }: { view: View; children: ReactNode }) {
  const { t } = useTranslation();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawer(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        {t("app.skipToContent")}
      </a>
      <div className="topbar">
        <button
          type="button"
          className="btn btn-ghost btn-icon"
          aria-expanded={drawer}
          aria-controls="giq-sidebar"
          aria-label={drawer ? t("nav.closeMenu") : t("nav.openMenu")}
          onClick={() => setDrawer((d) => !d)}
        >
          <Icon as={drawer ? XIcon : ListIcon} size={20} />
        </button>
        <span className="brand-mark">
          giq<span className="brand-cursor">_</span>
        </span>
      </div>
      <Sidebar id="giq-sidebar" view={view} open={drawer} onNavigate={() => setDrawer(false)} />
      {drawer && <div className="shell-scrim" onClick={() => setDrawer(false)} aria-hidden />}
      <main className="shell-main" id="main" tabIndex={-1}>
        <PauseBanner />
        {children}
      </main>
    </div>
  );
}

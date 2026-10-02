// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { PageHeader } from "../../components/PageHeader";
import { useHashRoute } from "../../lib/useHashRoute";
import { DiskDetail } from "./DiskDetail";
import { EnginesCard } from "./EnginesCard";
import { recipeFromHash } from "./weights";
import { WeightsTable } from "./WeightsTable";
import "./InventoryView.css";

/* The inventory (ADR-003): what this machine has to run recipes with — the
   weights on disk, once per checkpoint, and the engines. The checkpoints are
   the page; the disks they sit on and the engine builds are its context. */
export default function InventoryView() {
  const { t } = useTranslation();
  const { navigate } = useHashRoute();
  const recipe = recipeFromHash(window.location.hash);
  return (
    <>
      <PageHeader title={t("nav.inventory")} />
      <div className="inv-layout">
        <div className="inv-main">
          <WeightsTable recipe={recipe} onShowAll={() => navigate("inventory", null, { replace: true })} />
        </div>
        <aside className="inv-context">
          <DiskDetail />
          <EnginesCard />
        </aside>
      </div>
    </>
  );
}

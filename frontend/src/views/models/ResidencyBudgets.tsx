// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { Catalog } from "../../api/types";
import { Card } from "../../components/Card";
import { BudgetRow, type BudgetRowProps } from "./BudgetRow";
import { modelKey } from "./catalog";
import "./ResidencyBudgets.css";

/* What is kept warm, per card, against what the card holds. A rig reports
   one budget per card; a catalog without a card list (no GPU visible) still
   has its global figures, shown as one unnamed row. */
export function ResidencyBudgets({ catalog }: { catalog: Catalog | undefined }) {
  const { t } = useTranslation("models");
  let body;
  if (!catalog) {
    body = <p className="subtle">{t("common:empty.loading")}</p>;
  } else {
    const byKey = new Map(catalog.models.map((m) => [modelKey(m), m]));
    const order = new Map(catalog.pinned.map((k, i) => [k, i]));
    const cards: BudgetRowProps["card"][] = catalog.cards.length
      ? catalog.cards
      : [
          {
            index: null,
            name: "",
            total_gb: catalog.total_gb,
            free_gb: catalog.free_gb,
            pinned_gb: catalog.pinned_gb,
            pinned_needed_gb: catalog.pinned_needed_gb,
            pinned_fits: catalog.pinned_fits,
            pinned: catalog.pinned,
            reserve_gb: 0,
            default: true,
          },
        ];
    body = cards.map((c, i) => {
      const pinned = [...c.pinned]
        .sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99))
        .flatMap((k) => byKey.get(k) ?? []);
      return <BudgetRow key={c.index ?? i} card={c} pinned={pinned} />;
    });
  }
  return (
    <Card kicker={t("sidebar.residency")} className="md-budgets-card">
      <div className="md-budgets">{body}</div>
      <p className="md-budgets-hint">{t("residency.hint")}</p>
    </Card>
  );
}

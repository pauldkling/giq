// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipesResponse } from "../../api/types";
import { Card } from "../../components/Card";
import { BudgetRow } from "./BudgetRow";
import "./ResidencyBudgets.css";

/* What is kept warm, per card, against what the card holds: one budget per
   card, since two cards' pinned recipes do not compete. */
export function ResidencyBudgets({ recipes }: { recipes: RecipesResponse | undefined }) {
  const { t } = useTranslation("recipes");
  let body;
  if (!recipes) {
    body = <p className="subtle">{t("common:empty.loading")}</p>;
  } else if (!recipes.cards.length) {
    body = <p className="subtle">{t("device.noGpu")}</p>;
  } else {
    const byName = new Map(recipes.recipes.map((r) => [r.name, r]));
    const order = new Map(recipes.pinned.map((k, i) => [k, i]));
    body = recipes.cards.map((c) => {
      const pinned = [...c.pinned]
        .sort((a, b) => (order.get(a) ?? 99) - (order.get(b) ?? 99))
        .flatMap((k) => byName.get(k) ?? []);
      return <BudgetRow key={c.uuid} card={c} pinned={pinned} />;
    });
  }
  return (
    <Card kicker={t("sidebar.residency")} className="rc-budgets-card">
      <div className="rc-budgets">{body}</div>
      <p className="rc-budgets-hint">{t("residency.hint")}</p>
    </Card>
  );
}

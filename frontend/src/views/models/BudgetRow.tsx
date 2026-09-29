// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { CardBudget, CatalogModel } from "../../api/types";
import { shortGpuName } from "../../lib/cards";
import { useFormat } from "../../lib/useFormat";
import { workerColor } from "../../lib/series";

export interface BudgetRowProps {
  /** index null: the single-card fallback with no card name to show. */
  card: Omit<CardBudget, "uuid" | "index"> & { index: number | null };
  /** The card's kept-warm models, in reload priority order. */
  pinned: CatalogModel[];
}

/* One card's residency budget: a bar of what is kept warm on it, one segment
   per model in its worker's colour, then what is left for on-demand loads.
   Reload priority is the bar's order and its tooltips; spelling the chain
   out again does not fit the sidebar and was never the headline. */
export function BudgetRow({ card: c, pinned }: BudgetRowProps) {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const free = Math.max(c.total_gb - c.pinned_needed_gb, 0);
  const over = !c.pinned_fits;
  const name = shortGpuName(c.name);
  return (
    <div className="md-budget-row">
      {c.index != null && (
        <div className="md-budget-card">
          {name}
          {c.default && <span className="subtle"> · {t("budget.default")}</span>}
          {c.reserve_gb > 0 && (
            <span className="subtle"> · {t("budget.reserved", { reserve: fmt.gb(c.reserve_gb) })}</span>
          )}
        </div>
      )}
      <div
        className={`md-budget-bar${over ? " md-budget-over" : ""}`}
        role="img"
        aria-label={t("budget.barLabel", { card: name, used: fmt.gb(c.pinned_gb), total: fmt.gb(c.total_gb) })}
      >
        {pinned.map((m, i) => (
          <span
            key={`${m.worker}/${m.model}`}
            style={{ flex: m.vram_gb, background: over ? undefined : workerColor(m.worker) }}
            title={t("budget.segment", { rank: i + 1, key: `${m.worker}/${m.model}`, vram: fmt.gb(m.vram_gb) })}
          />
        ))}
        <span className="md-budget-free" style={{ flex: free }} />
      </div>
      {over ? (
        <p className="md-budget-note md-budget-note-over">
          <strong>{t("budget.over", { needed: fmt.gb(c.pinned_needed_gb), total: fmt.gb(c.total_gb) })}</strong>{" "}
          {t("budget.overHint")}
        </p>
      ) : (
        <p className="md-budget-note">
          <strong>{fmt.gb(c.pinned_gb)}</strong>{" "}
          {t("budget.kept", { total: fmt.gb(c.total_gb), free: fmt.gb(free) })}
          {pinned.length === 0 && <> · {t("budget.nothing")}</>}
        </p>
      )}
    </div>
  );
}

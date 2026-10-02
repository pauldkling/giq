// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "../../components/Card";
import "./FacetFilter.css";

export interface FacetFilterProps {
  title: string;
  /** [value, count] pairs over the whole catalog. */
  items: [string, number][];
  selected: ReadonlySet<string>;
  onToggle: (value: string) => void;
  onClear: () => void;
  renderLabel: (value: string) => ReactNode;
  titleFor?: (value: string) => string | undefined;
}

/* Filter chips, because the sets are small and stable. Toggle buttons
   (aria-pressed) rather than checkboxes: nothing selected means everything,
   which a row of unticked boxes would misstate as "nothing". */
export function FacetFilter({ title, items, selected, onToggle, onClear, renderLabel, titleFor }: FacetFilterProps) {
  const { t } = useTranslation("recipes");
  return (
    <Card
      kicker={title}
      className="rc-facet-card"
      actions={
        selected.size > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClear}>
            {t("sidebar.showAll")}
          </button>
        )
      }
    >
      <div className="rc-facet-list" role="group" aria-label={title}>
        {items.map(([value, n]) => (
          <button
            key={value}
            type="button"
            className="rc-facet-chip"
            aria-pressed={selected.has(value)}
            title={titleFor?.(value)}
            onClick={() => onToggle(value)}
          >
            <span className="rc-facet-label">{renderLabel(value)}</span>
            <span className="rc-facet-n">{n}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

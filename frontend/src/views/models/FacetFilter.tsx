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
  const { t } = useTranslation("models");
  return (
    <Card
      kicker={title}
      className="md-facet-card"
      actions={
        selected.size > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClear}>
            {t("sidebar.showAll")}
          </button>
        )
      }
    >
      <div className="md-facet-list" role="group" aria-label={title}>
        {items.map(([value, n]) => (
          <button
            key={value}
            type="button"
            className="md-facet-chip"
            aria-pressed={selected.has(value)}
            title={titleFor?.(value)}
            onClick={() => onToggle(value)}
          >
            <span className="md-facet-label">{renderLabel(value)}</span>
            <span className="md-facet-n">{n}</span>
          </button>
        ))}
      </div>
    </Card>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import "./KpiTile.css";

export interface KpiTileProps {
  label: ReactNode;
  /** The headline figure, already formatted. */
  value: ReactNode;
  /** Muted suffix after the value ("W", "/ 64 GB", "waiting"). */
  unit?: ReactNode;
  /** A line under the figure: a split note, a meter, a caveat. */
  children?: ReactNode;
  /** Makes the whole tile a link (e.g. the disk tile → #/inventory). */
  href?: string;
  /** Makes the whole tile a button. Ignored when href is set. */
  onClick?: () => void;
  title?: string;
  className?: string;
}

/* A stat tile: the number is the chart. Link or button when it leads
   somewhere, so it is reachable by keyboard and announced as such (a
   clickable div is neither). */
export function KpiTile({ label, value, unit, children, href, onClick, title, className }: KpiTileProps) {
  const body = (
    <>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">
        {value}
        {unit != null && <span className="kpi-unit"> {unit}</span>}
      </span>
      {children != null && <span className="kpi-extra">{children}</span>}
    </>
  );
  const cls = `kpi${href || onClick ? " kpi-action" : ""}${className ? " " + className : ""}`;
  if (href) {
    return (
      <a className={cls} href={href} title={title}>
        {body}
      </a>
    );
  }
  if (onClick) {
    return (
      <button type="button" className={cls} onClick={onClick} title={title}>
        {body}
      </button>
    );
  }
  return (
    <div className={cls} title={title}>
      {body}
    </div>
  );
}

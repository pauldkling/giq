// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import "./Card.css";

export interface CardProps {
  /** Small uppercase accent label (Nocturne .card-kicker). */
  kicker?: ReactNode;
  title?: ReactNode;
  /** Right-aligned in the header row: a meta note, buttons, a menu. */
  actions?: ReactNode;
  className?: string;
  /** Renders as <section> with this id for aria-labelledby, when the card is a page region. */
  id?: string;
  children?: ReactNode;
}

export function Card({ kicker, title, actions, className, id, children }: CardProps) {
  const headingId = id ? `${id}-title` : undefined;
  const hasHead = kicker != null || title != null || actions != null;
  return (
    <section
      className={`card elev-sm giq-card${className ? " " + className : ""}`}
      id={id}
      aria-labelledby={title != null || kicker != null ? headingId : undefined}
    >
      {hasHead && (
        <header className="giq-card-head">
          <div className="giq-card-heading" id={headingId}>
            {kicker != null && <span className="card-kicker">{kicker}</span>}
            {title != null && <span className="card-title">{title}</span>}
          </div>
          {actions != null && <div className="giq-card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

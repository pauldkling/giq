// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { LiveStatus } from "./LiveStatus";
import "./PageHeader.css";

export interface PageHeaderProps {
  title: ReactNode;
  /** Right-aligned: the pause control on the control surface, filters elsewhere. */
  actions?: ReactNode;
  /** Replace the live status line (default: <LiveStatus />); pass null to hide it. */
  status?: ReactNode;
}

/** Each view's heading row: title, live status, actions. */
export function PageHeader({ title, actions, status = <LiveStatus /> }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h1 className="page-title">{title}</h1>
      {status}
      {actions != null && <div className="page-actions">{actions}</div>}
    </header>
  );
}

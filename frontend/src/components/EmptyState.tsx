// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import "./EmptyState.css";

export interface EmptyStateProps {
  icon?: ReactNode;
  children: ReactNode;
  /** A button or link offering the way out. */
  action?: ReactNode;
  compact?: boolean;
}

export function EmptyState({ icon, children, action, compact }: EmptyStateProps) {
  return (
    <div className={`empty${compact ? " empty-compact" : ""}`}>
      {icon}
      <span>{children}</span>
      {action}
    </div>
  );
}

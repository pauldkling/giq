// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";

export interface MenuItemProps {
  onSelect: () => void;
  /** First line, in the body weight. */
  children: ReactNode;
  /** A second, muted line explaining what the item does. */
  description?: ReactNode;
  icon?: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  title?: string;
}

/** One entry of a Menu: a real button with role="menuitem". */
export function MenuItem({ onSelect, children, description, icon, danger, disabled, title }: MenuItemProps) {
  return (
    <button
      type="button"
      role="menuitem"
      tabIndex={-1}
      className={`menu-item${danger ? " menu-danger" : ""}`}
      disabled={disabled}
      title={title}
      onClick={onSelect}
    >
      {icon && <span className="menu-icon">{icon}</span>}
      <span className="menu-text">
        <span className="menu-label">{children}</span>
        {description && <span className="menu-desc">{description}</span>}
      </span>
    </button>
  );
}

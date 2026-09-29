// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import "./Tag.css";

export type TagTone = "accent" | "neutral" | "outline" | "good" | "warning" | "serious" | "critical";

export interface TagProps {
  tone?: TagTone;
  icon?: ReactNode;
  title?: string;
  className?: string;
  children: ReactNode;
}

/** Nocturne's .tag, plus giq's status tones. A status tone always carries a label (and ideally an icon), never colour alone. */
export function Tag({ tone = "neutral", icon, title, className, children }: TagProps) {
  return (
    <span className={`tag tag-${tone} giq-tag${className ? " " + className : ""}`} title={title}>
      {icon}
      {children}
    </span>
  );
}

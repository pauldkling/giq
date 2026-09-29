// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import "./ViewSkeleton.css";

/* What a view shows while its chunk loads: the page's rough shape (a header
   line, a row of blocks) rather than a spinner, so the layout does not jump
   when the view arrives. Usually on screen for a frame or two. */
export function ViewSkeleton() {
  const { t } = useTranslation();
  return (
    <div className="view-skeleton" role="status" aria-live="polite">
      <span className="sr-only">{t("empty.loading")}</span>
      <div className="view-skeleton-title" />
      <div className="view-skeleton-row">
        <div />
        <div />
        <div />
      </div>
      <div className="view-skeleton-block" />
    </div>
  );
}

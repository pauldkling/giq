// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "../../../components/Card";

export interface OutputCardProps {
  /** The latency / stats line; live while a run is going. */
  status?: ReactNode;
  /** An error message (server text, rendered as text). */
  error?: string | null;
  /** Mark the region busy for assistive tech while a run is live. */
  busy?: boolean;
  children?: ReactNode;
}

/** Where a panel's result lands: a card that appears with the first run. */
export function OutputCard({ status, error, busy, children }: OutputCardProps) {
  const { t } = useTranslation("sandbox");
  return (
    <Card className="sbx-out-card" kicker={t("out.kicker")} actions={status != null ? <span className="sbx-status">{status}</span> : undefined}>
      <div className="sbx-out" aria-live="polite" aria-busy={busy || undefined}>
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        {children}
      </div>
    </Card>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";

export interface RunButtonProps {
  busy: boolean;
  label: ReactNode;
  busyLabel: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}

/** The panel's one primary action; shows what it is doing while it runs. */
export function RunButton({ busy, label, busyLabel, disabled, onClick }: RunButtonProps) {
  return (
    <button type="button" className="btn btn-primary sbx-run" disabled={busy || disabled} onClick={onClick}>
      {busy ? busyLabel : label}
    </button>
  );
}

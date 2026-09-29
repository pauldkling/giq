// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useId, type ReactNode } from "react";
import "./Field.css";

export interface FieldProps {
  label: ReactNode;
  /** Renders the control; receives the id the label points at. */
  children: (id: string) => ReactNode;
  /** A validation message under the control (replaces the old alert()). */
  error?: string | null;
  hint?: ReactNode;
  className?: string;
}

/** Nocturne's .field: a label over one control, with an optional inline error. */
export function Field({ label, children, error, hint, className }: FieldProps) {
  const id = useId();
  return (
    <div className={`field form-field${className ? " " + className : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children(id)}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      {hint != null && !error && <p className="hint">{hint}</p>}
    </div>
  );
}

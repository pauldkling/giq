// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import "./ConfirmDialog.css";

export interface ConfirmDialogProps {
  title: ReactNode;
  body?: ReactNode;
  confirmLabel: string;
  /** Omit for a notice with a single button. */
  cancelLabel?: string;
  /** The confirm action destroys or interrupts something. */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/* Nocturne's .dialog as a modal alertdialog. Focus goes to the safe choice
   (cancel when there is one) so an Enter pressed out of habit does not
   confirm a force-pause; Escape and a backdrop click cancel; Tab stays
   inside the dialog. */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel,
  danger,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const titleId = useId();
  const bodyId = useId();
  const box = useRef<HTMLDivElement>(null);
  const safe = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    safe.current?.focus();
    return () => previous?.focus?.();
  }, []);

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    } else if (e.key === "Tab") {
      const f = Array.from(box.current?.querySelectorAll<HTMLElement>("button") ?? []);
      if (!f.length) return;
      const first = f[0]!;
      const last = f[f.length - 1]!;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  return (
    <div
      className="dialog-backdrop giq-dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        ref={box}
        className="dialog giq-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={body ? bodyId : undefined}
        onKeyDown={onKey}
      >
        <div className="dialog-title" id={titleId}>
          {title}
        </div>
        {body && (
          <div className="dialog-body" id={bodyId}>
            {body}
          </div>
        )}
        <div className="dialog-actions">
          {cancelLabel && (
            <button ref={safe} type="button" className="btn btn-secondary" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
          <button
            ref={cancelLabel ? undefined : safe}
            type="button"
            className={`btn btn-primary${danger ? " giq-btn-danger" : ""}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

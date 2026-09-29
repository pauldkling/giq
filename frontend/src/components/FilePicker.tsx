// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { UploadSimpleIcon } from "@phosphor-icons/react";
import { useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";
import "./FilePicker.css";

export interface FilePickerProps {
  id: string;
  accept: string;
  onChange: (file: File | null) => void;
  invalid?: boolean;
}

/* A drop box around a visually hidden native file input. The browser's own
   "Choose File / No file chosen" speaks the browser's language, not the
   page's, so the button and the file name are drawn here; the input stays
   the focus target, so keyboard and screen readers get the native control. */
export function FilePicker({ id, accept, onChange, invalid }: FilePickerProps) {
  const { t } = useTranslation();
  const [name, setName] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  const pick = (f: File | null) => {
    setName(f?.name ?? null);
    onChange(f);
  };
  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files[0];
    if (f) pick(f);
  };

  return (
    <div
      className={`filebox${invalid ? " filebox-invalid" : ""}${over ? " filebox-over" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <input
        id={id}
        type="file"
        className="sr-only"
        accept={accept}
        aria-invalid={invalid || undefined}
        onChange={(e) => pick(e.target.files?.[0] ?? null)}
      />
      <label htmlFor={id} className="btn btn-secondary btn-sm filebox-btn">
        <Icon as={UploadSimpleIcon} size={14} />
        {t("file.choose")}
      </label>
      <span className={`filebox-name${name ? "" : " muted"}`}>{name ?? t("file.none")}</span>
    </div>
  );
}

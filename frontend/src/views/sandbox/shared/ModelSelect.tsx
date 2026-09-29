// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { useFormat } from "../../../lib/useFormat";
import type { ModelOption } from "../models";

export interface ModelSelectProps {
  id: string;
  options: ModelOption[];
  value: string;
  onChange: (model: string) => void;
  /** Label models whose weights are missing (the vision panel needs them on disk). */
  showDisk?: boolean;
}

/** "name (8,0 GB · fits)": the size and whether it can load now, per option. */
export function ModelSelect({ id, options, value, onChange, showDisk }: ModelSelectProps) {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  if (!options.length) {
    return (
      <select id={id} className="input" disabled value="">
        <option value="">{t("model.none")}</option>
      </select>
    );
  }
  return (
    <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o.model} value={o.model}>
          {t("model.option", {
            model: o.model,
            size: f.gb(o.vram_gb),
            fit: showDisk && o.onDisk === false ? t("model.notOnDisk") : t(`common:fit.${o.fits}`),
          })}
        </option>
      ))}
    </select>
  );
}

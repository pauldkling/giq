// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { LANGUAGES } from "../i18n";
import { SegmentedControl } from "./SegmentedControl";

/** EN | DE. Lists whatever i18n/LANGUAGES holds; the choice persists (giq-lang). */
export function LanguageSwitch() {
  const { t, i18n } = useTranslation();
  const current = i18n.resolvedLanguage ?? "en";
  return (
    <SegmentedControl
      size="sm"
      label={t("language.label")}
      value={current}
      onChange={(code) => void i18n.changeLanguage(code)}
      options={LANGUAGES.map((l) => ({ value: l.code as string, label: l.label }))}
    />
  );
}

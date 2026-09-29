// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { CircleHalfIcon, MoonIcon, SunIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { useTheme, type ThemeChoice } from "../lib/useTheme";
import { Icon } from "./Icon";
import { SegmentedControl } from "./SegmentedControl";

const ICONS = { system: CircleHalfIcon, light: SunIcon, dark: MoonIcon } as const;

/** System / light / dark as three explicit options (a cycling button hides the one you want). */
export function ThemeSwitch() {
  const { t } = useTranslation();
  const { choice, setChoice } = useTheme();
  const options = (["system", "light", "dark"] as ThemeChoice[]).map((c) => ({
    value: c,
    title: t(`theme.${c}`),
    label: (
      <>
        <Icon as={ICONS[c]} size={14} />
        <span className="sr-only">{t(`theme.${c}`)}</span>
      </>
    ),
  }));
  return <SegmentedControl size="sm" label={t("theme.label")} value={choice} onChange={setChoice} options={options} />;
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { SegmentedControl } from "./SegmentedControl";

/** The time windows the dashboard offers, in hours. */
export const RANGE_HOURS = [24, 168, 720, 2160] as const;
export type RangeHours = (typeof RANGE_HOURS)[number];

const KEY: Record<RangeHours, string> = { 24: "range.h24", 168: "range.d7", 720: "range.d30", 2160: "range.d90" };

export interface RangeButtonsProps {
  value: RangeHours;
  onChange: (hours: RangeHours) => void;
  options?: readonly RangeHours[];
}

export function RangeButtons({ value, onChange, options = RANGE_HOURS }: RangeButtonsProps) {
  const { t } = useTranslation();
  return (
    <SegmentedControl
      size="sm"
      label={t("range.label")}
      value={value}
      onChange={onChange}
      options={options.map((h) => ({ value: h, label: t(KEY[h]) }))}
    />
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Icon as PhosphorIcon, IconProps } from "@phosphor-icons/react";

/* Phosphor, bundled (no icon font from a CDN: giq renders offline). This
   wrapper only fixes the defaults every use wants — decorative unless given
   a label, sized for 13–14px text, stroke weight "regular". */
export interface AppIconProps extends Omit<IconProps, "ref"> {
  as: PhosphorIcon;
  /** Accessible name; without one the icon is hidden from assistive tech. */
  label?: string;
}

export function Icon({ as: Glyph, label, size = 16, ...rest }: AppIconProps) {
  return label ? (
    <Glyph size={size} role="img" aria-label={label} {...rest} />
  ) : (
    <Glyph size={size} aria-hidden focusable={false} {...rest} />
  );
}

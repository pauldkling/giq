// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { Modality } from "../api/types";

/** A recipe's first modality: the one its icon, label and defaults follow. Every recipe has one. */
export const primaryModality = (r: { modalities: Modality[] }): Modality =>
  r.modalities[0] ?? "llm";

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { hrefFor } from "../../lib/useHashRoute";
import type { Tab } from "./tabs";

/** Point the address at a sandbox tab without a history entry (and tell the hash subscribers). */
export function navigateReplace(tab: Tab): void {
  history.replaceState(null, "", hrefFor("sandbox", tab));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

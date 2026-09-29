// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from "react";
import {
  CatalogProvider,
  EnginesProvider,
  GpusProvider,
  StatusProvider,
  StorageProvider,
} from "./resources";

/** Mounts every shared poller once, around the whole app. */
export function DataProvider({ children }: { children: ReactNode }) {
  return (
    <StatusProvider>
      <GpusProvider>
        <CatalogProvider>
          <StorageProvider>
            <EnginesProvider>{children}</EnginesProvider>
          </StorageProvider>
        </CatalogProvider>
      </GpusProvider>
    </StatusProvider>
  );
}

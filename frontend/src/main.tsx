// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { DialogProvider } from "./components/DialogProvider";
import { TooltipProvider } from "./components/TooltipProvider";
import "./i18n";
import { DataProvider } from "./state";
import "./styles/nocturne.css";
import "./styles/tokens.css";
import "./styles/base.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DataProvider>
      <TooltipProvider>
        <DialogProvider>
          <App />
        </DialogProvider>
      </TooltipProvider>
    </DataProvider>
  </StrictMode>,
);

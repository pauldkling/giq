// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { ToolStep } from "./toolsLoop";
import "./ToolTrace.css";

/* The exchange between model and sandbox: each call, and what the sandbox
   answered. Call arguments are model output, so they are rendered as plain
   text next to the translated label, never parsed as markup. */
export function ToolTrace({ steps }: { steps: ToolStep[] }) {
  const { t } = useTranslation("sandbox");
  if (!steps.length) return null;
  return (
    <ol className="sbx-trace">
      {steps.map((s, i) => (
        <li key={i} className={`sbx-trace-step sbx-trace-${s.kind}`}>
          {s.kind === "call" ? t("tools.call") : t("tools.result")}{" "}
          <code>{s.kind === "call" ? `${s.name}(${s.args})` : s.value}</code>
        </li>
      ))}
    </ol>
  );
}

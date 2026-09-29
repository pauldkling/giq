// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { Trans, useTranslation } from "react-i18next";
import { useFormat } from "../../../lib/useFormat";
import { THINKING_TOKEN_FLOOR } from "../constants";
import type { ChatHint as Hint } from "./chatHint";

/** What pressing Run will cost with this model, and what Thinking will do. */
export function ChatHint({ model, hint }: { model: string; hint: Hint }) {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  if (!model) return null;
  const strong = { b: <strong />, link: <a href="#/models" /> };
  return (
    <p className="hint" aria-live="polite">
      <Trans t={t} i18nKey={`chat.load.${hint.load}`} values={{ model }} components={strong} />
      {hint.think && " "}
      {hint.think && (
        <Trans
          t={t}
          i18nKey={`chat.think.${hint.think}`}
          values={{ floor: f.num(THINKING_TOKEN_FLOOR) }}
          components={strong}
        />
      )}
    </p>
  );
}

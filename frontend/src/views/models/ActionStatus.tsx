// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { CheckCircleIcon, InfoIcon, XIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Icon } from "../../components/Icon";
import type { ActionMessage } from "./useModelActions";

/* The outcome of the last card action, in a live region above the catalog:
   what changed and when it takes effect ("loads on the next tick"). Failures
   and server warnings go to a dialog instead, since they need reading. */
export function ActionStatus({ message, onDismiss }: { message: ActionMessage | null; onDismiss: () => void }) {
  const { t } = useTranslation("models");
  return (
    <div className="md-action-status-slot" role="status" aria-live="polite">
      {message && (
        <div className={`md-action-status md-action-${message.tone}`}>
          <Icon as={message.tone === "good" ? CheckCircleIcon : InfoIcon} size={14} />
          <span>{message.text}</span>
          <button
            type="button"
            className="btn btn-icon btn-ghost btn-sm md-action-dismiss"
            aria-label={t("status.dismiss")}
            title={t("status.dismiss")}
            onClick={onDismiss}
          >
            <Icon as={XIcon} size={12} />
          </button>
        </div>
      )}
    </div>
  );
}

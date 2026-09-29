// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { StopIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Icon } from "../../../components/Icon";
import type { ChatStream } from "./useChatStream";

/** Stop a streaming run; dropping the connection is what stops the GPU. */
export function StopButton({ chat }: { chat: ChatStream }) {
  const { t } = useTranslation("sandbox");
  if (!chat.running) return null;
  return (
    <button type="button" className="btn btn-secondary" disabled={chat.state.stopping} onClick={chat.stop}>
      <Icon as={StopIcon} size={14} />
      {chat.state.stopping ? t("run.stopping") : t("run.stop")}
    </button>
  );
}

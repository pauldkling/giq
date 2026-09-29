// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { ShieldCheckIcon, WarningIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { useStatus } from "../state";
import { Icon } from "./Icon";
import { Tag } from "./Tag";

/* Who can reach this host. Silent on loopback, because that is the
   assumption everyone already has; visible the moment it stops being true.
   Read off the running server rather than inferred from the address bar —
   behind a reverse proxy the URL says nothing about what the socket is
   bound to. */
export function AccessChip() {
  const { t } = useTranslation();
  const a = useStatus().data?.access;
  if (!a || a.loopback_only) return null;
  return a.exposed ? (
    <Tag
      tone="critical"
      icon={<Icon as={WarningIcon} size={12} />}
      title={t("access.exposedTitle", { host: a.bound_host })}
    >
      {t("access.exposed")}
    </Tag>
  ) : (
    <Tag tone="good" icon={<Icon as={ShieldCheckIcon} size={12} />} title={t("access.tokenTitle", { host: a.bound_host })}>
      {t("access.token")}
    </Tag>
  );
}

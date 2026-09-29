// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { CheckIcon, XIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";
import { Tag } from "./Tag";

/* A finished job's outcome in a table cell: a quiet check when it worked, a
   critical tag when it did not. The error itself is server text and goes in
   the tooltip, never into the layout. */
export function JobStatus({ status, error }: { status: string; error?: string | null }) {
  const { t } = useTranslation();
  if (status === "completed") {
    return <Icon as={CheckIcon} size={14} className="text-good" label={t("job.completed")} />;
  }
  return (
    <Tag tone="critical" icon={<Icon as={XIcon} size={11} />} title={error ?? undefined}>
      {status === "failed" ? t("job.failed") : status}
    </Tag>
  );
}

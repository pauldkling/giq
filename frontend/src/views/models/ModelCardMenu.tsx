// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { DotsThreeIcon, FlaskIcon, TrashIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { CatalogModel, StorageModel } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Menu } from "../../components/Menu";
import { MenuItem } from "../../components/MenuItem";
import { useFormat } from "../../lib/useFormat";
import { SANDBOX_TAB_FOR_WORKER, sandboxHref } from "../../lib/sandboxLink";
import { deleteBlock, modelKey, sandboxBlock } from "./catalog";

export interface ModelCardMenuProps {
  m: CatalogModel;
  s: Partial<StorageModel>;
  busy: boolean;
  onDelete: (sizeText: string) => void;
}

/* The card's ⋯ menu: one entry per thing done *to* the model rather than a
   setting of it. Unavailable entries stay listed, disabled, with the reason
   as their description — a missing entry would leave the operator guessing
   whether it exists at all. Entries are ordered from harmless to
   destructive; model-level editors slot in above the delete. */
export function ModelCardMenu({ m, s, busy, onDelete }: ModelCardMenuProps) {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const key = modelKey(m);
  const tab = SANDBOX_TAB_FOR_WORKER[m.worker];
  const noTest = sandboxBlock(m, s);
  const noDelete = deleteBlock(m, s);
  const size = fmt.bytes(s.size_bytes ?? 0);
  return (
    <Menu
      label={<Icon as={DotsThreeIcon} size={16} weight="bold" />}
      ariaLabel={t("menu.label", { key })}
      title={t("common:actions.more")}
      buttonClassName="btn btn-icon btn-ghost model-menu-btn"
    >
      <MenuItem
        icon={<Icon as={FlaskIcon} size={14} />}
        disabled={noTest != null}
        description={noTest ? t(noTest) : t("menu.testHelp", { panel: t(`panel.${tab}`) })}
        // Navigates only; the sandbox preselects the model and waits for Run.
        onSelect={() => {
          if (tab) window.location.hash = sandboxHref(tab, m.model);
        }}
      >
        {t("menu.test")}
      </MenuItem>
      <MenuItem
        icon={<Icon as={TrashIcon} size={14} />}
        danger
        disabled={busy || noDelete != null}
        description={noDelete ? t(noDelete) : t("menu.deleteHelp", { size })}
        onSelect={() => onDelete(size)}
      >
        {t("menu.delete")}
      </MenuItem>
    </Menu>
  );
}

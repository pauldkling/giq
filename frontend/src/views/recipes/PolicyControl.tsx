// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { Policy, RecipeEntry } from "../../api/types";
import { Icon } from "../../components/Icon";
import { SegmentedControl, type SegmentOption } from "../../components/SegmentedControl";
import { pinBlock } from "./catalog";

const POLICIES: readonly Policy[] = ["pinned", "auto", "off"];

export interface PolicyControlProps {
  r: RecipeEntry;
  busy: boolean;
  onChange: (policy: Policy) => void;
  onRevert: () => void;
}

/* Keep warm / on demand / off. The labels describe the behaviour, not the
   mechanism: "pin" and "auto" are what the scheduler calls them, but what
   an operator chooses between is a recipe that stays warm and one that loads
   when asked. The revert button appears only when the operator has
   overridden the configured default. */
export function PolicyControl({ r, busy, onChange, onRevert }: PolicyControlProps) {
  const { t } = useTranslation("recipes");
  const blocked = pinBlock(r);
  const { policy, source, reason } = r.residency;
  const options: SegmentOption<Policy>[] = POLICIES.map((p) => {
    const disabled = p === "pinned" && blocked != null;
    return {
      value: p,
      label: t(`common:policy.${p}`),
      title: disabled ? t(blocked!) : t(`common:policy.${p}Help`),
      disabled,
    };
  });
  const key = r.name;
  const revertTitle = reason ? t("residency.revertReason", { reason }) : t("residency.revert");
  return (
    <div className="rc-policy-control">
      <SegmentedControl
        size="sm"
        className={`rc-policy-seg rc-policy-${policy}`}
        label={t("residency.label", { key })}
        options={options}
        value={policy}
        disabled={busy}
        onChange={(p) => p !== policy && onChange(p)}
      />
      {source === "override" && (
        <button
          type="button"
          className="btn btn-icon btn-ghost btn-sm rc-policy-revert"
          title={revertTitle}
          aria-label={revertTitle}
          disabled={busy}
          onClick={onRevert}
        >
          <Icon as={ArrowCounterClockwiseIcon} size={13} />
        </button>
      )}
    </div>
  );
}

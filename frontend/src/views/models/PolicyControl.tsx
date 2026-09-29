// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { CatalogModel, Policy, StorageModel } from "../../api/types";
import { Icon } from "../../components/Icon";
import { SegmentedControl, type SegmentOption } from "../../components/SegmentedControl";
import { modelKey, pinBlock } from "./catalog";

const POLICIES: readonly Policy[] = ["pinned", "auto", "off"];

export interface PolicyControlProps {
  m: CatalogModel;
  s: Partial<StorageModel>;
  busy: boolean;
  onChange: (policy: Policy) => void;
  onRevert: () => void;
}

/* Keep warm / on demand / off. The labels describe the behaviour, not the
   mechanism: "pin" and "auto" are what the scheduler calls them, but what
   an operator chooses between is a model that stays warm and one that loads
   when asked. The revert button appears only when the operator has
   overridden the configured default. */
export function PolicyControl({ m, s, busy, onChange, onRevert }: PolicyControlProps) {
  const { t } = useTranslation("models");
  const blocked = pinBlock(m, s);
  const options: SegmentOption<Policy>[] = POLICIES.map((p) => {
    const disabled = p === "pinned" && blocked != null;
    return {
      value: p,
      label: t(`common:policy.${p}`),
      title: disabled ? t(blocked!) : t(`common:policy.${p}Help`),
      disabled,
    };
  });
  const key = modelKey(m);
  const revertTitle = m.policy_reason
    ? t("residency.revertReason", { reason: m.policy_reason })
    : t("residency.revert");
  return (
    <div className="md-policy-control">
      <SegmentedControl
        size="sm"
        className={`md-policy-seg md-policy-${m.policy}`}
        label={t("residency.label", { key })}
        options={options}
        value={m.policy}
        disabled={busy}
        onChange={(p) => p !== m.policy && onChange(p)}
      />
      {m.policy_source === "override" && (
        <button
          type="button"
          className="btn btn-icon btn-ghost btn-sm md-policy-revert"
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

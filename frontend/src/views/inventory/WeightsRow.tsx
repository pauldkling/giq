// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { TrashIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import type { WeightsItem } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Tag } from "../../components/Tag";
import { useFormat } from "../../lib/useFormat";

export interface WeightsRowProps {
  w: WeightsItem;
  /** How the table names it: the repo, or the path under the models directory. */
  name: string;
  busy: boolean;
  onDelete: () => void;
}

/* One checkpoint: where it is, what it is, who loads it, what it takes. The
   recipes link back to their cards; the delete is the row's only verb. */
export function WeightsRow({ w, name, busy, onDelete }: WeightsRowProps) {
  const { t } = useTranslation("inventory");
  const f = useFormat();
  const where = w.repo ? `${t("weights.inCache")} · ${w.source ?? ""}` : (w.path ?? "");
  return (
    <tr className={w.on_disk ? undefined : "inv-weights-absent"}>
      <td className="mono inv-weights-name" title={where}>
        {name}
        {w.revision && <span className="subtle inv-weights-rev"> @{w.revision.slice(0, 8)}</span>}
      </td>
      <td className="muted">{w.format ?? "–"}</td>
      <td className="muted">{w.licence ?? "–"}</td>
      <td>
        <span className="inv-weights-users" title={w.used_by.join("\n")}>
          {w.recipes.map((r) => (
            <a key={r} className="inv-weights-user mono" href="#/recipes">
              {r}
            </a>
          ))}
        </span>
      </td>
      <td className="num">{w.on_disk ? f.bytes(w.size_bytes) : <Tag tone="outline">{t("weights.notOnDisk")}</Tag>}</td>
      <td className="inv-weights-actions">
        <button
          type="button"
          className="btn btn-icon btn-ghost btn-sm"
          title={w.on_disk ? t("delete.label", { what: name }) : t("delete.nothing")}
          aria-label={t("delete.label", { what: name })}
          disabled={busy || !w.on_disk}
          onClick={onDelete}
        >
          <Icon as={TrashIcon} size={14} />
        </button>
      </td>
    </tr>
  );
}

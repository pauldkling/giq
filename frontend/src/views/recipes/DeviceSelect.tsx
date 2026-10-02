// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { RecipeEntry } from "../../api/types";
import { shortGpuName } from "../../lib/cards";
import { useFormat } from "../../lib/useFormat";
import { cardName, type CardChoice } from "../../lib/cards";

export interface DeviceSelectProps {
  r: RecipeEntry;
  cards: CardChoice[];
  busy: boolean;
  onBind: (device: string | null, cardText: string | null) => void;
}

/* Which card a recipe loads on: a dropdown of card names with free VRAM
   alongside, because the question behind the choice is almost always "will
   it fit". "auto" follows giq's default card and says which one that is.
   The select is controlled by the catalog, so a refused binding snaps back
   to the server's answer on the refresh that follows. With one card there
   is nothing to choose, and the row just names it. */
export function DeviceSelect({ r, cards, busy, onBind }: DeviceSelectProps) {
  const card = r.card;
  const { t } = useTranslation("recipes");
  const fmt = useFormat();
  if (cards.length < 2) {
    return <span className="muted">{cards[0] ? shortGpuName(cards[0].name) : t("device.noGpu")}</span>;
  }
  const label = (c: CardChoice) =>
    c.free != null ? t("device.free", { card: cardName(c, cards), free: fmt.gb(c.free) }) : cardName(c, cards);
  const landsOn = cards.find((c) => c.uuid === card.effective);
  const boundName = card.name ? shortGpuName(card.name) : "";
  const why = card.device
    ? t(card.source === "config" ? "device.boundConfig" : "device.bound", { card: boundName })
    : t("device.unbound");
  return (
    <select
      className={`input rc-device-select${card.device ? " rc-device-bound" : ""}`}
      aria-label={t("device.label", { key: r.name })}
      title={why}
      value={card.device ?? ""}
      disabled={busy}
      onChange={(e) => {
        const uuid = e.target.value || null;
        const target = cards.find((c) => c.uuid === uuid);
        onBind(uuid, target ? cardName(target, cards) : null);
      }}
    >
      <option value="">{landsOn ? t("device.autoOn", { card: label(landsOn) }) : t("device.auto")}</option>
      {cards.map((c) => (
        <option key={c.uuid} value={c.uuid}>
          {label(c)}
        </option>
      ))}
    </select>
  );
}

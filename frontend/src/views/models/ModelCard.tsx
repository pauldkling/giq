// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { EyeIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Icon } from "../../components/Icon";
import { Tag } from "../../components/Tag";
import { WorkerIcon } from "../../components/WorkerIcon";
import { DeviceSelect } from "./DeviceSelect";
import { EngineName } from "./EngineName";
import type { CardChoice } from "../../lib/cards";
import { FIT_TONE, type ModelEntry } from "./catalog";
import { ModelCardMenu } from "./ModelCardMenu";
import { ModelFacts } from "./ModelFacts";
import { PolicyControl } from "./PolicyControl";
import type { ModelActions } from "./useModelActions";
import "./ModelCard.css";

export interface ModelCardProps {
  entry: ModelEntry;
  cards: CardChoice[];
  versions: Map<string, string | null>;
  actions: ModelActions;
}

/* One model, one card. A row per model in a wide table made every model look
   like a spreadsheet line; the unit of work on this page is one model: what
   it is, whether it fits, how it is kept, where it runs, what runs it. */
export function ModelCard({ entry: { m, s }, cards, versions, actions }: ModelCardProps) {
  const { t } = useTranslation("models");
  const busy = actions.isBusy(m);
  return (
    <article className={`card elev-sm md-model-card${m.policy === "off" ? " md-model-off" : ""}`} aria-busy={busy}>
      <header className="md-model-head">
        <WorkerIcon worker={m.worker} size={16} labelled />
        <h3 className="md-model-name">{m.model}</h3>
        <span className="md-model-badges">
          {m.resident && (
            <Tag tone="accent" title={t("card.keptWarmTitle")}>
              {t("card.keptWarm")}
            </Tag>
          )}
          {/* A capability that changes what you can send it; same class of
              fact as the engine row and the tilde on estimated VRAM. */}
          {m.vision && (
            <Tag tone="outline" icon={<Icon as={EyeIcon} size={12} />} title={t("card.visionTitle")}>
              {t("card.vision")}
            </Tag>
          )}
          <Tag tone={FIT_TONE[m.fits] ?? "neutral"}>{t(`common:fit.${m.fits}`, { defaultValue: m.fits })}</Tag>
        </span>
        <ModelCardMenu m={m} s={s} busy={busy} onDelete={(size) => void actions.removeWeights(m, size)} />
      </header>
      <p className="md-model-meta">
        {t(`common:worker.${m.worker}`, { defaultValue: m.worker })}
        {m.detail && m.detail !== m.worker && <> · {m.detail}</>}
      </p>
      <ModelFacts m={m} s={s} />
      <dl className="md-model-rows">
        <div className="md-model-row">
          <dt>{t("card.residency")}</dt>
          <dd>
            <PolicyControl
              m={m}
              s={s}
              busy={busy}
              onChange={(p) => void actions.changePolicy(m, p)}
              onRevert={() => void actions.revert(m)}
            />
          </dd>
        </div>
        <div className="md-model-row">
          <dt>{t("card.gpu")}</dt>
          <dd>
            <DeviceSelect m={m} cards={cards} busy={busy} onBind={(d, name) => void actions.bind(m, d, name)} />
          </dd>
        </div>
        <div className="md-model-row">
          <dt>{t("card.engine")}</dt>
          <dd>
            <EngineName m={m} versions={versions} />
          </dd>
        </div>
      </dl>
    </article>
  );
}

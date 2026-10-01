// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { WorkerIcon } from "../../components/WorkerIcon";
import { useCatalog, useEngines, useGpus, useStorage } from "../../state";
import { cardChoices } from "../../lib/cards";
import { ENGINE_NOTE_KEY, engineVersions, facetCounts, joinStorage, matches, toggled } from "./catalog";
import { DiskDetail } from "./DiskDetail";
import { FacetFilter } from "./FacetFilter";
import { RecipeErrors } from "./RecipeErrors";
import { ModelCatalog } from "./ModelCatalog";
import { ResidencyBudgets } from "./ResidencyBudgets";
import { useModelActions } from "./useModelActions";
import "./ModelsView.css";

const EMPTY: ReadonlySet<string> = new Set();

/* The Models page: context on the left (filters, what is kept warm per
   card, what is on disk) beside the thing being worked on. Disk and
   residency used to be full-width sections above the catalog, which pushed
   the models — the reason to open the page — below the fold. On a narrow
   screen the filters stay on top and the context moves under the catalog. */
export default function ModelsView() {
  const { t } = useTranslation("models");
  const catalog = useCatalog();
  const storage = useStorage();
  const gpus = useGpus();
  const engines = useEngines();
  const actions = useModelActions();
  const [modality, setModality] = useState<ReadonlySet<string>>(EMPTY);
  const [engine, setEngine] = useState<ReadonlySet<string>>(EMPTY);

  const models = catalog.data?.models ?? [];
  const entries = useMemo(() => joinStorage(models, storage.data?.models), [models, storage.data]);
  const shown = entries.filter((e) => matches(e.m, { modality, engine }));
  const cards = useMemo(() => cardChoices(gpus.data?.gpus, catalog.data?.cards), [gpus.data, catalog.data]);
  const versions = useMemo(() => engineVersions(engines.data), [engines.data]);
  const noteFor = (backend: string) =>
    ENGINE_NOTE_KEY[backend] ? t(`engineNote.${ENGINE_NOTE_KEY[backend]}`) : undefined;
  const clear = () => {
    setModality(EMPTY);
    setEngine(EMPTY);
  };

  return (
    <>
      <PageHeader title={t("common:nav.models")} />
      <div className="md-view">
        <div className="md-layout">
          <aside className="md-filters" aria-label={t("sidebar.label")}>
            <FacetFilter
              title={t("sidebar.modality")}
              items={facetCounts(models, (m) => m.worker)}
              selected={modality}
              onToggle={(v) => setModality((s) => toggled(s, v))}
              onClear={() => setModality(EMPTY)}
              renderLabel={(w) => (
                <>
                  <WorkerIcon worker={w} size={14} />
                  {t(`common:worker.${w}`, { defaultValue: w })}
                </>
              )}
            />
            <FacetFilter
              title={t("sidebar.engine")}
              items={facetCounts(models, (m) => m.backend)}
              selected={engine}
              onToggle={(v) => setEngine((s) => toggled(s, v))}
              onClear={() => setEngine(EMPTY)}
              renderLabel={(e) => <span className="mono">{e}</span>}
              titleFor={noteFor}
            />
          </aside>
          <div className="md-main">
            <RecipeErrors recipes={storage.data?.recipes} />
            {catalog.data ? (
              <ModelCatalog
                entries={shown}
                total={models.length}
                filtered={modality.size > 0 || engine.size > 0}
                onClearFilters={clear}
                cards={cards}
                versions={versions}
                actions={actions}
              />
            ) : (
              <EmptyState>
                {catalog.error
                  ? t("common:empty.failed", { error: errorText(catalog.error) })
                  : t("common:empty.loading")}
              </EmptyState>
            )}
          </div>
          <aside className="md-context" aria-label={t("sidebar.residency")}>
            <ResidencyBudgets catalog={catalog.data} />
            <DiskDetail />
          </aside>
        </div>
      </div>
    </>
  );
}

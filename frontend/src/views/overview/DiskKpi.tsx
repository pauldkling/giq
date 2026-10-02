// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { KpiTile } from "../../components/KpiTile";
import { Gauge } from "../../components/charts";
import { useFormat } from "../../lib/useFormat";
import { useStorage } from "../../state";

/* Weights on disk, the hint that leads to model management: the tile is a
   link to #/inventory. One thin meter per mount — giq's models, everything
   else, free — with the figures in each segment's tooltip. */
export function DiskKpi() {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const { data } = useStorage();
  const disks = data?.disks ?? [];
  const models = disks.length ? disks.reduce((a, d) => a + d.models_bytes, 0) : null;
  return (
    <KpiTile label={t("kpi.disk")} value={f.bytes(models)} href="#/inventory" title={t("kpi.diskTitle")}>
      {disks.map((d) => {
        const tip = t("kpi.diskTip", {
          mount: d.mount,
          models: f.bytes(d.models_bytes),
          other: f.bytes(d.other_bytes),
          free: f.bytes(d.free_bytes),
          total: f.bytes(d.total_bytes),
        });
        return (
          <Fragment key={d.mount}>
            <Gauge
              total={d.total_bytes}
              ariaLabel={tip}
              height={4}
              segments={[
                { id: "models", value: d.models_bytes, color: "var(--chart-seq)", label: tip },
                { id: "other", value: d.other_bytes, color: "var(--series-other)", label: tip },
              ]}
            />
            <span className="ov-disk-note">{t("kpi.diskFree", { free: f.bytes(d.free_bytes), mount: d.mount })}</span>
          </Fragment>
        );
      })}
    </KpiTile>
  );
}

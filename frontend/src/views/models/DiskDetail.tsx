// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { errorText } from "../../api/client";
import { Card } from "../../components/Card";
import { useFormat } from "../../lib/useFormat";
import { useStorage } from "../../state";
import { DiskMeter } from "./DiskMeter";
import "./DiskDetail.css";

/** Per-disk breakdown of where the weights live, compact enough for the sidebar. */
export function DiskDetail() {
  const { t } = useTranslation("models");
  const fmt = useFormat();
  const { data, error } = useStorage();
  return (
    <Card kicker={t("sidebar.disk")}>
      {!data ? (
        <p className="subtle">
          {error ? t("common:empty.failed", { error: errorText(error) }) : t("common:empty.loading")}
        </p>
      ) : (
        data.disks.map((d) => (
          <div key={d.mount} className="md-disk-row">
            <div className="md-disk-mount mono">{d.mount}</div>
            <DiskMeter disk={d} />
            <div className="md-disk-summary">
              {t("disk.summary", {
                models: fmt.bytes(d.models_bytes),
                free: fmt.bytes(d.free_bytes),
                total: fmt.bytes(d.total_bytes),
              })}
            </div>
          </div>
        ))
      )}
    </Card>
  );
}

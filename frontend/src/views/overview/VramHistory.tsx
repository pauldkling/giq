// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { StatsVram } from "../../api/types";
import { Card } from "../../components/Card";
import { AreaLine } from "../../components/charts";
import { useFormat } from "../../lib/useFormat";

const SIX_HOURS = 6 * 3600;

/** VRAM in use on the default card over six hours, against the card's size. */
export function VramHistory({ vram }: { vram: StatsVram | undefined }) {
  const { t } = useTranslation("overview");
  const f = useFormat();
  const nowS = Date.now() / 1000;
  const points = (vram?.samples ?? []).map((s) => ({ t: s.t, v: s.used, active: s.active, ready: s.ready }));
  return (
    <Card title={t("usage.vram6h")}>
      <AreaLine
        points={points}
        domain={[nowS - SIX_HOURS, nowS]}
        yMax={vram?.total_gb || undefined}
        ariaLabel={t("usage.vramLabel")}
        formatY={(v) => f.num(v)}
        xLabels={{ start: f.time(nowS - SIX_HOURS), end: t("common:chart.now") }}
        tooltip={(p) => (
          <>
            <b>{f.time(p.t, true)}</b>
            <div>{f.gb(p.v)}</div>
            {p.active && <div>{t("usage.vramBatch", { job: p.active })}</div>}
            <div>{t("usage.vramReady", { count: p.ready })}</div>
          </>
        )}
      />
    </Card>
  );
}

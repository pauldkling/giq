// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { InstancesInfo } from "../../api/types";
import { Card } from "../../components/Card";
import "./InstanceErrors.css";

/* Operator instance files that failed validation are logged and left out,
   and the catalog simply lacks them (or still shows the built-in of that
   name) — nothing on this page would say a file was ignored. This card is
   where it is said, with giq's own reason for each file, and it is gone
   once every file loads. */
export function InstanceErrors({ instances }: { instances: InstancesInfo | undefined }) {
  const { t } = useTranslation("models");
  const errors = instances?.errors ?? [];
  if (errors.length === 0) return null;
  return (
    <div role="alert">
      <Card
        className="md-instance-errors"
        kicker={t("instanceErrors.kicker")}
        title={t("instanceErrors.title", { count: errors.length })}
      >
        <p className="hint">{t("instanceErrors.body", { dir: instances?.dir ?? "" })}</p>
        <ul className="md-instance-errors-list">
          {errors.map((e, i) => (
            <li key={`${e.file ?? ""}-${i}`}>
              <div className="md-instance-errors-file mono">{e.file ?? t("instanceErrors.several")}</div>
              <div className="md-instance-errors-msg">{e.message}</div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

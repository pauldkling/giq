// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { ProgressBar } from "../../../components/ProgressBar";
import { Tag, type TagTone } from "../../../components/Tag";
import { useFormat } from "../../../lib/useFormat";
import { verdict, type Verdict } from "./cosine";

const TONE: Record<Verdict, TagTone> = { same: "good", inconclusive: "warning", different: "neutral" };

/** The similarity as a number, a gauge and a plain-language verdict. */
export function CosineResult({ cos }: { cos: number }) {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  const v = verdict(cos);
  const pct = Math.max(0, Math.min(100, cos * 100));
  return (
    <div className="sbx-cos">
      <div className="sbx-cos-head">
        <span className="sbx-cos-value">{t("voice.cosine", { value: f.num(cos, 3) })}</span>
        <Tag tone={TONE[v]}>{t(`voice.tag.${v}`)}</Tag>
      </div>
      <ProgressBar value={pct} label={t("voice.gauge")} valueText={f.num(cos, 3)} height={8} />
      <p className="sbx-answer">{t(`voice.verdict.${v}`)}</p>
    </div>
  );
}

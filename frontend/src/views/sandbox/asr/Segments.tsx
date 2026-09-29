// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import type { Transcription } from "../../../api/types";
import { useFormat } from "../../../lib/useFormat";
import "./Segments.css";

/* Transcript text is whatever was said into the microphone — untrusted —
   so it only ever reaches the page as React text. */
export function Segments({ segments }: { segments: Transcription["segments"] }) {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  if (!segments.length) return <p className="muted">{t("asr.noSpeech")}</p>;
  const showSpeaker = segments.some((s) => s.speaker);
  return (
    <div className="table-wrap">
      <table className="table sbx-segs">
        <thead>
          <tr>
            <th className="num">{t("asr.time")}</th>
            {showSpeaker && <th>{t("asr.speaker")}</th>}
            <th>{t("asr.text")}</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s, i) => (
            <tr key={i}>
              <td className="num sbx-seg-time">
                {t("asr.span", { start: f.num(s.start, 1), end: f.num(s.end, 1) })}
              </td>
              {showSpeaker && <td>{s.speaker && <span className="tag tag-outline sbx-spk">{s.speaker}</span>}</td>}
              <td className="sbx-seg-text">{s.text}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

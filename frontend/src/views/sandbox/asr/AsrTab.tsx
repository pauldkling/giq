// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { postForm } from "../../../api/client";
import type { Transcription } from "../../../api/types";
import { SegmentedControl } from "../../../components/SegmentedControl";
import { useFormat } from "../../../lib/useFormat";
import { Field } from "../../../components/Field";
import { FilePicker } from "../../../components/FilePicker";
import { OutputCard } from "../shared/OutputCard";
import { RunButton } from "../shared/RunButton";
import { useRunner } from "../../../lib/useRunner";
import { MicButton } from "./MicButton";
import { Segments } from "./Segments";
import { useRecorder } from "./useRecorder";

export function AsrTab() {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  const rec = useRecorder();
  const [file, setFile] = useState<File | null>(null);
  const [missing, setMissing] = useState(false);
  const [lang, setLang] = useState("");
  const [diarize, setDiarize] = useState(true);
  const runner = useRunner<Transcription>();

  const go = () => {
    // A picked file wins over a recording, as before.
    const audio = file ?? rec.blob;
    if (!audio) return setMissing(true);
    const fd = new FormData();
    fd.append("file", audio, file?.name ?? "mic.webm");
    fd.append("response_format", "verbose_json");
    if (lang.trim()) fd.append("language", lang.trim());
    void runner.run((signal) =>
      postForm<Transcription>(`/v1/audio/transcriptions?diarize=${diarize}`, fd, { signal }),
    );
  };

  const d = runner.result;
  const status =
    runner.busy
      ? t("run.transcribing")
      : d && runner.ms != null
        ? [
            t("out.latency", { value: f.dur(runner.ms) }),
            d.duration != null && t("asr.audio", { value: f.num(d.duration, 1) }),
            d.language && t("asr.lang", { lang: d.language }),
            d.speakers.length > 0 && t("asr.speakers", { count: d.speakers.length }),
          ]
            .filter(Boolean)
            .join(" · ")
        : null;

  return (
    <div className="sbx-panel">
      <div className="card elev-sm sbx-form">
        <Field
          label={t("field.audio")}
          error={missing && !file && !rec.blob ? t("asr.needAudio") : rec.error ? t("asr.micFailed", { error: rec.error }) : null}
          hint={rec.available ? t("asr.recordHint") : t("asr.secureHint")}
        >
          {(id) => (
            <div className="sbx-audio-row">
              <FilePicker
                id={id}
                accept="audio/*"
                invalid={missing && !file && !rec.blob}
                onChange={(next) => {
                  setFile(next);
                  setMissing(false);
                }}
              />
              {rec.available && <MicButton rec={rec} />}
            </div>
          )}
        </Field>
        <div className="sbx-row">
          <Field label={t("field.language")} className="sbx-grow">
            {(id) => (
              <input id={id} className="input" type="text" placeholder={t("field.languageAuto")} value={lang} onChange={(e) => setLang(e.target.value)} />
            )}
          </Field>
          <div className="field form-field">
            <span className="form-label" aria-hidden>{t("field.diarize")}</span>
            <SegmentedControl
              label={t("field.diarize")}
              value={diarize ? "on" : "off"}
              options={[
                { value: "on", label: t("toggle.on") },
                { value: "off", label: t("toggle.off") },
              ]}
              onChange={(v) => setDiarize(v === "on")}
            />
          </div>
        </div>
        <div className="sbx-actions">
          <RunButton busy={runner.busy} label={t("run.asr")} busyLabel={t("run.transcribing")} onClick={go} />
        </div>
      </div>
      {runner.started && (
        <OutputCard busy={runner.busy} error={runner.error} status={status}>
          {d && !runner.busy && <Segments segments={d.segments} />}
        </OutputCard>
      )}
    </div>
  );
}

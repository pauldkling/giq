// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { postBlob } from "../../../api/client";
import { useFormat } from "../../../lib/useFormat";
import { TTS_DEFAULT_VOICE, TTS_MODEL, TTS_VOICES } from "../constants";
import { Field } from "../../../components/Field";
import { OutputCard } from "../shared/OutputCard";
import { RunButton } from "../shared/RunButton";
import { useRunner } from "../../../lib/useRunner";

export function TtsTab() {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  const [text, setText] = useState(() => t("tts.defaultText"));
  const [voice, setVoice] = useState<string>(TTS_DEFAULT_VOICE);
  const runner = useRunner<Blob>();
  const [url, setUrl] = useState<string | null>(null);

  // One object URL per result, released when the next replaces it.
  useEffect(() => {
    if (!runner.result) return;
    const u = URL.createObjectURL(runner.result);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [runner.result]);

  const go = () =>
    void runner.run((signal) => postBlob("/v1/audio/speech", { input: text, voice, model: TTS_MODEL }, { signal }));

  return (
    <div className="sbx-panel">
      <div className="card elev-sm sbx-form">
        <Field label={t("field.text")}>
          {(id) => <textarea id={id} className="input" value={text} onChange={(e) => setText(e.target.value)} />}
        </Field>
        <Field label={t("field.voice")} className="sbx-narrow">
          {(id) => (
            <select id={id} className="input" value={voice} onChange={(e) => setVoice(e.target.value)}>
              {TTS_VOICES.map((v) => (
                <option key={v} value={v}>
                  {v === TTS_DEFAULT_VOICE ? t("tts.defaultVoice", { voice: v }) : v}
                </option>
              ))}
            </select>
          )}
        </Field>
        <p className="hint">{t("tts.hint", { model: TTS_MODEL, size: f.gb(0.5) })}</p>
        <div className="sbx-actions">
          <RunButton busy={runner.busy} label={t("run.tts")} busyLabel={t("run.synthesizing")} onClick={go} />
        </div>
      </div>
      {runner.started && (
        <OutputCard
          busy={runner.busy}
          error={runner.error}
          status={runner.busy ? t("run.synthesizing") : runner.ms != null ? t("out.latency", { value: f.dur(runner.ms) }) : null}
        >
          {url && !runner.busy && !runner.error && <audio className="sbx-audio" controls src={url} />}
        </OutputCard>
      )}
    </div>
  );
}

// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { THINKING_TOKEN_FLOOR } from "../constants";
import type { ModelOption } from "../models";
import { Field } from "../../../components/Field";
import { fileB64 } from "../shared/fileB64";
import { FilePicker } from "../../../components/FilePicker";
import { ModelSelect } from "../shared/ModelSelect";
import { RunButton } from "../shared/RunButton";
import { StopButton } from "../stream/StopButton";
import { StreamOutput } from "../stream/StreamOutput";
import { useChatStream } from "../stream/useChatStream";

export interface VisionTabProps {
  options: ModelOption[];
  model: string;
  onModel: (m: string) => void;
}

/* Image + question, routed through /v1/chat/completions with OpenAI content
   parts — what llama-server understands once --mmproj is loaded. */
export function VisionTab({ options, model, onModel }: VisionTabProps) {
  const { t } = useTranslation("sandbox");
  const chat = useChatStream();
  const [file, setFile] = useState<File | null>(null);
  const [missing, setMissing] = useState(false);
  const [question, setQuestion] = useState(() => t("vision.defaultPrompt"));
  const opt = options.find((o) => o.model === model);
  const noWeights = opt?.onDisk === false;

  const go = async () => {
    if (!file) return setMissing(true);
    const b64 = await fileB64(file);
    await chat.run({
      model,
      max_tokens: THINKING_TOKEN_FLOOR,
      messages: [
        {
          role: "user",
          content: [
            { type: "text", text: question },
            { type: "image_url", image_url: { url: `data:${file.type || "image/png"};base64,${b64}` } },
          ],
        },
      ],
    });
  };

  const warning = !options.length
    ? t("vision.none")
    : noWeights
      ? t("vision.noWeights", { model })
      : opt && opt.fits !== "loaded"
        ? t("vision.loadsFirst")
        : null;

  return (
    <div className="sbx-panel">
      <div className="card elev-sm sbx-form">
        <Field label={t("field.model")}>
          {(id) => <ModelSelect id={id} options={options} value={model} onChange={onModel} showDisk />}
        </Field>
        <Field label={t("field.image")} error={missing && !file ? t("vision.needImage") : null}>
          {(id) => (
            <FilePicker
              id={id}
              accept="image/*"
              invalid={missing && !file}
              onChange={(next) => {
                setFile(next);
                setMissing(false);
              }}
            />
          )}
        </Field>
        <Field label={t("field.question")}>
          {(id) => <textarea id={id} className="input" value={question} onChange={(e) => setQuestion(e.target.value)} />}
        </Field>
        {warning && <p className={noWeights || !options.length ? "warn" : "hint"}>{warning}</p>}
        <div className="sbx-actions">
          <RunButton
            busy={chat.running}
            label={t("run.vision")}
            busyLabel={t("run.generating")}
            disabled={!model || noWeights}
            onClick={() => void go()}
          />
          <StopButton chat={chat} />
        </div>
      </div>
      <StreamOutput chat={chat} />
    </div>
  );
}

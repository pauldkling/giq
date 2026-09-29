// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SegmentedControl } from "../../../components/SegmentedControl";
import type { ModelOption } from "../models";
import { Field } from "../../../components/Field";
import { ModelSelect } from "../shared/ModelSelect";
import { StreamOutput } from "../stream/StreamOutput";
import { StopButton } from "../stream/StopButton";
import { useChatStream } from "../stream/useChatStream";
import { RunButton } from "../shared/RunButton";
import { ChatHint } from "./ChatHint";
import { chatHint, raisedMaxTokens } from "./chatHint";

export interface ChatTabProps {
  options: ModelOption[];
  model: string;
  onModel: (m: string) => void;
}

export function ChatTab({ options, model, onModel }: ChatTabProps) {
  const { t } = useTranslation("sandbox");
  const chat = useChatStream();
  const [prompt, setPrompt] = useState(() => t("chat.defaultPrompt"));
  const [temp, setTemp] = useState("0.7");
  const [maxTokens, setMaxTokens] = useState("2048");
  const [thinking, setThinking] = useState(false);
  const [raised, setRaised] = useState(false);
  const opt = options.find((o) => o.model === model);

  /* The budget is re-checked where the old page did it — when the model or
     the Thinking switch changes — so typing a smaller number by hand after
     that is respected. */
  const recheck = (nextThinking: boolean, next: ModelOption | undefined) => {
    const cur = Number(maxTokens) || 0;
    const up = raisedMaxTokens(nextThinking, next?.reasoning, cur);
    if (up !== cur) setMaxTokens(String(up));
    setRaised(up !== cur);
  };

  /* A model change from anywhere — the select, or a "Test in sandbox" link —
     re-checks the budget against the new model's reasoning mode (and only
     that: the Thinking switch re-checks in its own handler). */
  const recheckRef = useRef(recheck);
  recheckRef.current = recheck;
  const reasoning = opt?.reasoning;
  useEffect(() => {
    if (model) recheckRef.current(thinking, opt);
  }, [model, reasoning]);

  const hint = chatHint({ fit: opt?.fits, policy: opt?.policy, reasoning: opt?.reasoning, thinking, raised });

  const send = () =>
    void chat.run({
      model,
      messages: [{ role: "user", content: prompt }],
      temperature: Number(temp),
      max_tokens: Number(maxTokens),
      chat_template_kwargs: { enable_thinking: thinking },
    });

  return (
    <div className="sbx-panel">
      <div className="card elev-sm sbx-form">
        <Field label={t("field.prompt")}>
          {(id) => <textarea id={id} className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} />}
        </Field>
        <div className="sbx-row">
          <Field label={t("field.model")} className="sbx-grow">
            {(id) => (
              <ModelSelect
                id={id}
                options={options}
                value={model}
                onChange={onModel}
              />
            )}
          </Field>
          <Field label={t("field.temperature")}>
            {(id) => (
              <input id={id} className="input" type="number" step="0.1" min="0" max="2" value={temp} onChange={(e) => setTemp(e.target.value)} />
            )}
          </Field>
          <Field label={t("field.maxTokens")}>
            {(id) => (
              <input id={id} className="input" type="number" step="64" min="16" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
            )}
          </Field>
          <div className="field form-field">
            <span className="form-label" aria-hidden>{t("field.thinking")}</span>
            <SegmentedControl
              label={t("field.thinking")}
              value={thinking ? "on" : "off"}
              options={[
                { value: "off", label: t("toggle.off") },
                { value: "on", label: t("toggle.on") },
              ]}
              onChange={(v) => {
                setThinking(v === "on");
                recheck(v === "on", opt);
              }}
            />
          </div>
        </div>
        <ChatHint model={model} hint={hint} />
        <div className="sbx-actions">
          <RunButton busy={chat.running} label={t("run.chat")} busyLabel={t("run.generating")} disabled={!model} onClick={send} />
          <StopButton chat={chat} />
        </div>
      </div>
      <StreamOutput chat={chat} />
    </div>
  );
}

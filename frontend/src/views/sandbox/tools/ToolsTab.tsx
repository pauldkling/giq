// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { postJSON } from "../../../api/client";
import type { ChatCompletion } from "../../../api/types";
import { useFormat } from "../../../lib/useFormat";
import { TOOLS_MAX_ROUNDS, TOOLS_MODEL } from "../constants";
import { Field } from "../../../components/Field";
import { OutputCard } from "../shared/OutputCard";
import { RunButton } from "../shared/RunButton";
import { useRunner } from "../../../lib/useRunner";
import { ToolTrace } from "./ToolTrace";
import { runToolsLoop, type ToolsOutcome, type ToolStep } from "./toolsLoop";

export function ToolsTab({ available }: { available: boolean }) {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  const [prompt, setPrompt] = useState(() => t("tools.defaultPrompt"));
  const [steps, setSteps] = useState<ToolStep[]>([]);
  const runner = useRunner<ToolsOutcome>();

  const go = () => {
    setSteps([]);
    void runner.run((signal) =>
      runToolsLoop({
        model: TOOLS_MODEL,
        prompt,
        post: (body) => postJSON<ChatCompletion>("/v1/chat/completions", body, { signal }),
        // The trace fills in as the calls happen, not all at once at the end.
        onStep: (s) => setSteps((prev) => [...prev, s]),
      }),
    );
  };

  const out = runner.result;
  return (
    <div className="sbx-panel">
      <div className="card elev-sm sbx-form">
        <Field
          label={
            <Trans t={t} i18nKey="tools.promptLabel" components={{ code: <code /> }} />
          }
        >
          {(id) => <textarea id={id} className="input" value={prompt} onChange={(e) => setPrompt(e.target.value)} />}
        </Field>
        <p className="hint">
          <Trans t={t} i18nKey="tools.hint" values={{ model: TOOLS_MODEL }} components={{ code: <code /> }} />
        </p>
        {!available && <p className="warn">{t("tools.unavailable", { model: TOOLS_MODEL })}</p>}
        <div className="sbx-actions">
          <RunButton busy={runner.busy} label={t("run.tools")} busyLabel={t("run.running")} disabled={!available} onClick={go} />
        </div>
      </div>
      {runner.started && (
        <OutputCard
          busy={runner.busy}
          error={runner.error}
          status={runner.ms != null ? t("out.latency", { value: f.dur(runner.ms) }) : runner.busy ? t("run.running") : null}
        >
          <ToolTrace steps={steps} />
          {out && (
            <div className="sbx-answer">
              {out.answer == null ? (
                <span className="muted">{t("tools.noAnswer", { count: TOOLS_MAX_ROUNDS })}</span>
              ) : (
                out.answer || <span className="muted">{t("stream.empty")}</span>
              )}
            </div>
          )}
        </OutputCard>
      )}
    </div>
  );
}

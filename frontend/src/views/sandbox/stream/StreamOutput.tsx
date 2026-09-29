// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { Trans, useTranslation } from "react-i18next";
import { OutputCard } from "../shared/OutputCard";
import { streamSummary } from "./chatStream";
import { ThoughtBlock } from "./ThoughtBlock";
import type { ChatStream } from "./useChatStream";
import { useStreamStatus } from "./useStreamStatus";
import "./StreamOutput.css";

/** The live answer of a streamed chat completion, with its folded thought. Shared by chat and vision. */
export function StreamOutput({ chat }: { chat: ChatStream }) {
  const { t } = useTranslation("sandbox");
  const { state, now, dispatch } = chat;
  const status = useStreamStatus(state, now);
  if (state.phase === "idle") return null;
  const live = state.phase === "running";
  const summary = state.phase === "done" ? streamSummary(state) : null;
  return (
    <OutputCard status={status} error={state.error} busy={live}>
      {state.thoughtVisible && (
        <ThoughtBlock
          text={state.thought}
          open={state.thoughtOpen}
          following={state.following}
          live={live && state.answer === ""}
          stopped={state.phase === "stopped"}
          onToggle={(open) => dispatch({ type: "toggleThought", open })}
          onFollow={(following) => dispatch({ type: "follow", following })}
        />
      )}
      {(state.answer || live) && (
        <div className={`sbx-answer${live && (state.answer || !state.thoughtVisible) ? " sbx-cursor" : ""}`}>
          {state.answer}
        </div>
      )}
      {summary?.empty === "length" && (
        <p className="sbx-answer">
          <Trans t={t} i18nKey="stream.emptyLength" components={{ err: <span className="text-critical" /> }} />
        </p>
      )}
      {summary?.empty === "plain" && <p className="sbx-answer muted">{t("stream.empty")}</p>}
    </OutputCard>
  );
}

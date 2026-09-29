// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useTranslation } from "react-i18next";
import { useFormat } from "../../../lib/useFormat";
import { streamSummary, type StreamState } from "./chatStream";

/** The line above a streamed answer: the live clock while running, the run's stats after. */
export function useStreamStatus(state: StreamState, now: number): string | null {
  const { t } = useTranslation("sandbox");
  const f = useFormat();
  if (state.phase === "idle") return null;
  const secs = (at: number) => t("stream.secs", { value: f.num(Math.max(0, (at - state.startedAt) / 1000), 1) });
  if (state.phase === "running") {
    const started = state.answer !== "" || state.thought !== "";
    return started ? secs(now) : t("stream.waiting", { elapsed: secs(now) });
  }
  const s = streamSummary(state);
  const parts = [secs(state.endedAt ?? now)];
  if (state.phase === "error") return parts[0]!;
  if (s.tokens) {
    parts.push(t("stream.tokens", { count: s.tokens, n: f.num(s.tokens) }));
    if (s.tokPerSec != null) parts.push(t("stream.rate", { value: f.num(s.tokPerSec) }));
  }
  if (s.thoughtChars) parts.push(t("stream.thoughtChars", { count: s.thoughtChars, n: f.num(s.thoughtChars) }));
  if (s.stopped) parts.push(t("stream.stopped"));
  if (s.cutOff) parts.push(t("stream.cutOff"));
  return parts.join(" · ");
}

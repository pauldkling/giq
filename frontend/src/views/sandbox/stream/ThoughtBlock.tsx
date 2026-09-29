// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

/* Follow-the-tail, the way a terminal does it: keep pinned to the bottom
   while you are already at the bottom, and stop the instant you scroll up to
   read. A thought arrives at ~60 tokens/s, so unconditional autoscroll makes
   it unreadable — every token drags you back down mid-sentence. No setting
   to remember: scrolling away is the opt-out, and the button is the way back. */
const FOLLOW_SLACK_PX = 24; // rounding and sub-pixel line heights

const atBottom = (el: HTMLElement) => el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX;

export interface ThoughtBlockProps {
  text: string;
  open: boolean;
  following: boolean;
  /** Still arriving (shows the cursor and the "thinking…" label). */
  live: boolean;
  stopped: boolean;
  onToggle: (open: boolean) => void;
  onFollow: (following: boolean) => void;
}

/* The model's scratchpad, not its answer: dimmer, smaller and folded away —
   but present, because watching it is how you tell a long think from a hang,
   and it is most of what a reasoning model spends your tokens on. */
export function ThoughtBlock({ text, open, following, live, stopped, onToggle, onFollow }: ThoughtBlockProps) {
  const { t } = useTranslation("sandbox");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = box.current;
    if (el && open && following) el.scrollTop = el.scrollHeight;
  }, [text, open, following]);

  const label = live ? t("stream.thinkingLive") : stopped ? t("stream.thinkingStopped") : t("stream.thinking");
  return (
    <details
      className="sbx-think"
      open={open}
      onToggle={(e) => {
        const next = e.currentTarget.open;
        if (next !== open) onToggle(next);
      }}
    >
      <summary>{label}</summary>
      <div
        ref={box}
        className={`sbx-think-text${live ? " sbx-cursor" : ""}`}
        tabIndex={0}
        onScroll={(e) => {
          /* Programmatic scrolls land at the bottom and so re-arm following;
             only a scroll that leaves the bottom counts as "let me read". */
          const f = atBottom(e.currentTarget);
          if (f !== following) onFollow(f);
        }}
      >
        {text}
      </div>
      {!following && (
        <button
          type="button"
          className="btn btn-secondary btn-sm sbx-follow"
          onClick={() => {
            if (box.current) box.current.scrollTop = box.current.scrollHeight;
            onFollow(true);
          }}
        >
          {t("stream.jump")}
        </button>
      )}
    </details>
  );
}

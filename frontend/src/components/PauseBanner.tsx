// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { PlayIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { useFormat } from "../lib/useFormat";
import { useStatus } from "../state";
import { Icon } from "./Icon";
import { usePauseActions } from "./usePauseActions";
import "./PauseBanner.css";

/** App-wide notice while serving is paused, on every view, with its own resume button. */
export function PauseBanner() {
  const { t } = useTranslation();
  const f = useFormat();
  const { data } = useStatus();
  const p = usePauseActions();
  if (!data?.paused) return null;

  const since = data.paused_since ? Date.parse(data.paused_since) / 1000 : null;
  // A graceful pause reports paused the moment it starts draining; say so
  // rather than claiming the VRAM is already back.
  const draining = !!data.active_worker || data.jobs_running.length > 0;
  // A pause unloads every card, so what it frees is the machine's, not the
  // default card's.
  const cards = data.gpus?.length ? data.gpus : [data];
  const freed = {
    free: cards.reduce((a, g) => a + g.vram_free_gb, 0),
    total: cards.reduce((a, g) => a + g.vram_total_gb, 0),
  };
  const parts = [
    since != null && !Number.isNaN(since) ? t("pause.bannerSince", { time: f.time(since) }) : null,
    draining
      ? t("pause.bannerDraining")
      : t("pause.bannerFreed", { free: f.gb(freed.free), total: f.gb(freed.total) }),
    t("pause.banner503"),
    data.pause_reason,
  ].filter(Boolean);

  return (
    <div className="pause-banner" role="status">
      <span>
        <strong>{t("pause.bannerTitle")}</strong> <span className="pause-why">{parts.join(" · ")}</span>
      </span>
      <button
        type="button"
        className="btn btn-primary"
        disabled={p.busy !== null}
        onClick={() => void p.resume()}
      >
        <Icon as={PlayIcon} size={14} />
        {p.busyLabel ?? t("pause.resume")}
      </button>
    </div>
  );
}

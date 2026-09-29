// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { PauseIcon, PlayIcon } from "@phosphor-icons/react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";
import { Menu } from "./Menu";
import { MenuItem } from "./MenuItem";
import { usePauseActions } from "./usePauseActions";

/* Pause/Resume serving. Paused, the button resumes directly; serving, it
   opens the choice between waiting for in-flight work and tearing down now,
   because the two differ in what fails and the operator should pick. */
export function PauseControl() {
  const { t } = useTranslation();
  const p = usePauseActions();

  if (p.paused || p.busy === "resume") {
    return (
      <button
        type="button"
        className="btn btn-primary"
        title={t("pause.resumeTitle")}
        disabled={p.busy !== null}
        onClick={() => void p.resume()}
      >
        <Icon as={PlayIcon} size={14} />
        {p.busyLabel ?? t("pause.resume")}
      </button>
    );
  }

  return (
    <Menu
      title={t("pause.pauseTitle")}
      disabled={p.busy !== null}
      label={
        <>
          <Icon as={PauseIcon} size={14} />
          {p.busyLabel ?? t("pause.pause")}
        </>
      }
    >
      <MenuItem onSelect={() => void p.pauseGraceful()} description={t("pause.gracefulHelp")}>
        {t("pause.graceful")}
      </MenuItem>
      <MenuItem danger onSelect={() => void p.pauseForce()} description={t("pause.forceHelp")}>
        {t("pause.force")}
      </MenuItem>
      <div className="menu-note">{t("pause.hint")}</div>
    </Menu>
  );
}

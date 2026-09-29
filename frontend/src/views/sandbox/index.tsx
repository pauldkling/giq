// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "../../components/PageHeader";
import { useHashRoute } from "../../lib/useHashRoute";
import { useCatalog, useStorage } from "../../state";
import { AsrTab } from "./asr/AsrTab";
import { ChatTab } from "./chat/ChatTab";
import { EditTab } from "./edit/EditTab";
import { disabledTabs, sandboxModels } from "./models";
import { parseSandboxHash } from "../../lib/sandboxLink";
import { panelId, SandboxTabBar, tabId } from "./SandboxTabBar";
import { T2iTab } from "./t2i/T2iTab";
import { DEFAULT_TAB, TABS, type Tab } from "./tabs";
import { ToolsTab } from "./tools/ToolsTab";
import { TtsTab } from "./tts/TtsTab";
import { useModelChoices } from "./useModelChoices";
import { usePreselect } from "./usePreselect";
import { VisionTab } from "./vision/VisionTab";
import { VoiceTab } from "./voice/VoiceTab";
import "./Sandbox.css";

/* Standard workflows with no knobs beyond the basics, one panel per tab.
   A panel stays mounted once opened, so switching tabs keeps its prompt,
   its result and a generation still streaming — as the old single page did. */
export default function SandboxView() {
  const { t } = useTranslation("sandbox");
  const { navigate } = useHashRoute(); // re-renders on every hash change
  const route = parseSandboxHash(window.location.hash);
  const active = route.tab ?? DEFAULT_TAB;

  const catalog = useCatalog();
  const storage = useStorage();
  const models = useMemo(() => sandboxModels(catalog.data, storage.data), [catalog.data, storage.data]);
  const disabled = useMemo(() => disabledTabs(models), [models]);
  const { value, choose } = useModelChoices(models);
  const missed = usePreselect(route, catalog.data, models, choose);

  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([active]));
  if (!visited.has(active)) setVisited(new Set(visited).add(active));

  const panel = (tab: Tab) => {
    switch (tab) {
      case "chat":
        return <ChatTab options={models.chat} model={value("chat")} onModel={(m) => choose("chat", m)} />;
      case "tools":
        return <ToolsTab available={!disabled.has("tools")} />;
      case "t2i":
        return <T2iTab options={models.t2i} model={value("t2i")} onModel={(m) => choose("t2i", m)} />;
      case "edit":
        return <EditTab options={models.edit} model={value("edit")} onModel={(m) => choose("edit", m)} />;
      case "vision":
        return <VisionTab options={models.vision} model={value("vision")} onModel={(m) => choose("vision", m)} />;
      case "asr":
        return <AsrTab />;
      case "tts":
        return <TtsTab />;
      case "voice":
        return <VoiceTab />;
    }
  };

  return (
    <>
      <PageHeader title={t("common:nav.sandbox")} />
      <p className="sbx-lede">{t("lede")}</p>
      <SandboxTabBar active={active} disabled={disabled} onSelect={(tab) => navigate("sandbox", tab)} />
      {catalog.error != null && !catalog.data && <p className="warn">{t("catalogFailed")}</p>}
      {missed?.tab === active && <p className="warn">{t("preselectMissed", { model: missed.model })}</p>}
      {TABS.filter((tab) => visited.has(tab)).map((tab) => (
        <div key={tab} role="tabpanel" id={panelId(tab)} aria-labelledby={tabId(tab)} hidden={tab !== active}>
          {panel(tab)}
        </div>
      ))}
    </>
  );
}

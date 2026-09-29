// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";
import { THINKING_TOKEN_FLOOR } from "../constants";
import { chatHint, raisedMaxTokens } from "./chatHint";

describe("raisedMaxTokens", () => {
  it("raises to the floor when thinking can happen, never lowers", () => {
    expect(raisedMaxTokens(true, "on", 2048)).toBe(THINKING_TOKEN_FLOOR);
    expect(raisedMaxTokens(true, "template", 2048)).toBe(THINKING_TOKEN_FLOOR);
    expect(raisedMaxTokens(true, "on", 65536)).toBe(65536);
    expect(raisedMaxTokens(false, "on", 2048)).toBe(2048);
    expect(raisedMaxTokens(true, "off", 2048)).toBe(2048);
  });
});

describe("chatHint", () => {
  const base = { fit: "fits_now" as const, policy: "auto" as const, reasoning: "on" as const, thinking: false, raised: false };
  it("refuses to promise a load for a switched-off model", () => {
    expect(chatHint({ ...base, policy: "off" })).toEqual({ load: "off", think: null });
  });
  it("describes load and thinking", () => {
    expect(chatHint({ ...base, fit: "loaded" })).toEqual({ load: "loaded", think: "canThink" });
    expect(chatHint({ ...base, fit: "fits_after_eviction", thinking: true, raised: true }).think).toBe("raised");
    expect(chatHint({ ...base, reasoning: "off", thinking: true })).toEqual({ load: "loads", think: "noEffect" });
    expect(chatHint({ ...base, thinking: true }).think).toBeNull();
  });
});

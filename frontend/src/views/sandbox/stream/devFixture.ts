// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

import type { StreamEvent } from "./chatStream";

/** A canned thinking-then-answer run for looking at the stream UI in dev. Never shipped. */
export const FIXTURE_EVENTS: StreamEvent[] = [
  { type: "start", at: 0 },
  {
    type: "think",
    text:
      "The user wants two sentences. Blue sky: Rayleigh scattering, intensity ∝ 1/λ⁴, " +
      "so short wavelengths scatter more. Why not violet? The sun emits less violet, " +
      "some is absorbed high up, and the eye is less sensitive to it. Keep it to two sentences.",
  },
  { type: "toggleThought", open: false },
  {
    type: "answer",
    text:
      "Sunlight scatters off the molecules of the air, and short (blue) wavelengths scatter far " +
      "more strongly than long (red) ones — Rayleigh scattering goes as 1/λ⁴.\n\nSo blue light " +
      "reaches your eye from every direction of the sky, while violet, though scattered even more, " +
      "is weaker in sunlight and the eye is less sensitive to it.",
  },
  { type: "meta", usage: { prompt_tokens: 24, completion_tokens: 187, total_tokens: 211 }, finishReason: "stop" },
  { type: "end", at: 3400, stopped: false },
];

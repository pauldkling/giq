# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Catching a thought that has stopped going anywhere.

A thinking model can enter a state that is locally fluent and globally static:
it keeps emitting well-formed sentences, and none of them is new. Observed on
qwen3.8-27b — four consecutive fragments of a thought, identical but for one
slot:

    Need maybe include "If you mean '... with no tax on Greece', maybe if entity."
    Need maybe include "If you mean '... with no tax on Bulgaria', maybe if entity."
    Need maybe include "If you mean '... with no tax on Romania', maybe if entity."
    Need maybe include "If you mean '... with no tax on Serbia', maybe if entity."

Left alone this runs to the token ceiling and returns finish_reason "length"
with an empty answer: the whole budget spent, nothing written.

Why shingles. The obvious detectors both fail on that sample. Exact line
matching sees four *different* lines, because one word differs. Pairwise
difflib across a thought that can reach 100k characters is quadratic in the
thing that is already too long. Hashed word n-grams are neither: a 10-word
window covering "legally, with no tax on" is byte-identical in all four
fragments, only the three windows containing the country name differ, and the
whole measure is one pass and a Counter.

So the question this asks is not "did a line repeat" but "how much of the
recent thought is new" — and a loop answers it very clearly. Ordinary prose,
even prose circling a hard question, sits near 1.0 distinct shingles per
shingle; the sample above sits near 0.25.

The thresholds are deliberately reluctant. A thought is not judged before it
has run 6,000 characters (a model restating its constraints is working, not
looping), a verdict is drawn from a window rather than the whole thought (a
loop entered late must not be diluted by the coherent thinking before it), and
two consecutive verdicts have to agree before the guard trips. The cost of a
false positive is a thought cut short; the cost of a false negative is one
wasted generation. Neither is bad enough to justify a hair trigger.

This module only measures. What to do about it — see LlamaCppAdapter's use of
llama.cpp's reasoning_end control — is the caller's decision.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# ~4 chars/token, so roughly 1,500 tokens of thought before anything is judged.
MIN_THOUGHT_CHARS = 6000

# How much of the recent thought each verdict is drawn from. Long enough to
# hold several repetitions of a paragraph-sized fragment, short enough that a
# loop starting at character 40,000 is not averaged away by what came before.
WINDOW_CHARS = 6000

# Words per shingle. Long enough that ordinary connective phrases ("on the
# other hand", "so the answer is") do not collide across unrelated sentences,
# short enough to sit inside one repeated fragment rather than spanning two.
SHINGLE_WORDS = 10

# Verdicts are drawn this often, not on every delta: re-hashing the window for
# each ~4-character token would be pure waste.
CHECK_EVERY_CHARS = 500

# A window needs at least this many shingles before its novelty means anything.
MIN_SHINGLES = 150

# Distinct shingles as a fraction of all shingles in the window: the signal.
# Calibrated against four synthetic thoughts of the shapes that matter (see
# tests/test_loopguard.py, which holds the samples and re-checks the numbers):
#
#     the measured loop                 0.35
#     the same loop run 4x longer       0.35   (it is a steady state, not a drift)
#     enumeration on a fixed scaffold   0.83
#     long unresolved reasoning         0.88
#
# 0.55 sits in the gap, with room on both sides. The first draft used 0.35,
# which is the loop's own value — no margin at all — on an estimate that a loop
# would score near 0.05. It does not: every fragment carries one genuinely new
# word, so a third of the shingles really are unique. Guessed, then measured.
MIN_NOVELTY = 0.55

# The backstop, for the shape novelty cannot see: a refrain interleaved with
# real progress, where the window keeps filling with new material and one run
# keeps coming back anyway. Occurrences of the single most-repeated shingle.
#
# The band here is narrow and worth stating plainly. Enumeration on a fixed
# scaffold measured 27, and the loop measured 40, so anything catching the loop
# on this signal alone is within striking distance of a false positive — which
# is why it is the backstop and not the trigger. It was 6 in the first draft,
# where ordinary varied prose measured 6 and tripped it every time.
MAX_REPEATS = 40

# Consecutive verdicts that must agree. One window can be unlucky; two windows
# 500 characters apart agreeing is a state, not a coincidence.
CONFIRMATIONS = 2

_WORDS = re.compile(r"\w+")


@dataclass
class LoopGuard:
    """A running verdict on whether a thought has stopped going anywhere.

    Fed the reasoning deltas as they arrive; `feed` returns True the moment the
    thought reads as a loop, and keeps returning True after that, so a caller
    can act exactly once without tracking that itself.
    """

    min_thought_chars: int = MIN_THOUGHT_CHARS
    window_chars: int = WINDOW_CHARS
    shingle_words: int = SHINGLE_WORDS
    check_every_chars: int = CHECK_EVERY_CHARS
    min_shingles: int = MIN_SHINGLES
    min_novelty: float = MIN_NOVELTY
    max_repeats: int = MAX_REPEATS
    confirmations: int = CONFIRMATIONS

    #: Characters of thought seen, across the whole generation.
    total_chars: int = field(default=0, init=False)
    #: Latched once the guard has tripped.
    tripped: bool = field(default=False, init=False)
    #: Distinct shingles / all shingles, from the most recent verdict.
    novelty: float | None = field(default=None, init=False)
    #: Occurrences of the most-repeated shingle, from the most recent verdict.
    repeats: int = field(default=0, init=False)

    _window: str = field(default="", init=False, repr=False)
    _since_check: int = field(default=0, init=False, repr=False)
    _agreed: int = field(default=0, init=False, repr=False)

    def feed(self, delta: str) -> bool:
        """Take the next piece of thought. True once it reads as a loop."""
        if not delta:
            return self.tripped

        self.total_chars += len(delta)
        # Sliced every delta rather than kept in a deque of pieces: the window
        # is a few kB and the slice is memcpy, while a piecewise buffer would
        # need reassembling on every verdict anyway.
        self._window = (self._window + delta)[-self.window_chars :]
        self._since_check += len(delta)

        if self.tripped:
            return True
        if self.total_chars < self.min_thought_chars:
            return False
        if self._since_check < self.check_every_chars:
            return False
        self._since_check = 0

        if self._verdict():
            self._agreed += 1
            if self._agreed >= self.confirmations:
                self.tripped = True
        else:
            # Consecutive, not cumulative: a thought that produced one dense
            # window and then moved on is not looping, and must be able to
            # clear the count rather than carry it for the rest of the run.
            self._agreed = 0

        return self.tripped

    def _verdict(self) -> bool:
        """Is this window mostly re-emitting itself?

        Case and punctuation are dropped before shingling. The repetition that
        matters here is semantic — the same sentence re-typed — and a model
        varying its commas between two otherwise identical lines should not be
        able to hide behind that.
        """
        words = _WORDS.findall(self._window.lower())
        k = self.shingle_words
        if len(words) <= k:
            return False

        counts = Counter(tuple(words[i : i + k]) for i in range(len(words) - k + 1))
        total = sum(counts.values())
        if total < self.min_shingles:
            return False

        self.novelty = len(counts) / total
        self.repeats = max(counts.values())
        return self.novelty < self.min_novelty or self.repeats >= self.max_repeats

    @property
    def evidence(self) -> dict:
        """What the verdict was made on, for the log and the stored result.

        Numbers only. The thought itself is the user's text and does not go
        anywhere giq writes down — same rule as giq.privacy.
        """
        return {
            "thought_chars": self.total_chars,
            "novelty": round(self.novelty, 3) if self.novelty is not None else None,
            "max_repeats": self.repeats,
        }

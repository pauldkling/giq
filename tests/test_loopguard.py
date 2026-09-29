# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""The measure that tells a thought going nowhere from one still going.

The failure this defends against is not a crash. A looping thinking model
produces well-formed sentences at full speed for as long as it is allowed to,
and then returns an empty answer because the token ceiling arrived first — the
whole budget spent on text that stopped carrying information thousands of
tokens earlier.

So the tests come in pairs, and the negative half is the load-bearing one.
Catching a loop is easy; not catching the thought that was getting somewhere is
the whole difficulty, because a guard that fires on real reasoning is worse
than no guard at all.

The four samples below are the calibration set, and the thresholds in
loopguard.py were read off them rather than guessed — the first draft was
guessed, and both of its thresholds were wrong in opposite directions:

    TIGHT        novelty 0.01   repeats 149    a short phrase cycling
    LOOP         novelty 0.35   repeats  40    the measured failure
    TEMPLATED    novelty 0.85   repeats  27    enumeration on a fixed scaffold
    REALISTIC    novelty 0.89   repeats   7    long reasoning that never resolves

Novelty separates those by better than 2x. The repeat count does not — 27
against 40 — which is why it is the backstop and not the trigger.
"""

import random

from giq.loopguard import LoopGuard

# The measured sample, qwen3.8-27b: one fragment re-emitted with a
# single slot varying. Only the country changes, which is what defeats the two
# obvious detectors — every line is unique, so line-level dedup sees nothing,
# and a thought this long is too big to compare against itself pairwise.
COUNTRIES = (
    "Greece Bulgaria Romania Serbia Croatia Hungary Slovakia Slovenia Estonia Latvia "
    "Lithuania Poland Czechia Austria Portugal Ireland Finland Denmark Sweden Norway "
    "Cyprus Malta Albania Moldova Georgia Armenia Iceland Belgium Luxembourg Netherlands "
    "Switzerland Liechtenstein Monaco Andorra Montenegro Kosovo Ukraine Belarus Turkey "
    "Israel Morocco Tunisia Egypt Jordan Panama Uruguay Chile Singapore Thailand Vietnam"
).split()

_SUBJECT = (
    "the residency test|a permanent establishment|withholding at source|"
    "the participation exemption|trade tax|transfer pricing|thin capitalisation|"
    "exit taxation|the CFC rules|substance|VAT grouping|loss carry-forward|"
    "the anti-hybrid rules|beneficial ownership|the reorganisation relief|stamp duty|"
    "the general anti-abuse rule|advance pricing agreements"
).split("|")
_VERB = (
    "hinges on|turns on|is decided by|comes down to|depends on|is governed by|"
    "is settled by|follows from|rests on|is driven by|is constrained by|is triggered by"
).split("|")
_OBJECT = (
    "where the board actually meets|a fixed place of business|"
    "the treaty article that applies|a twelve-month holding period|"
    "the municipal multiplier|what a stranger would have charged|"
    "deductible interest against EBITDA|gains crystallising on a move|"
    "passive income attributed upward|whether anyone works there|control across the chain|"
    "a change of ownership|a mismatch between two systems|who really receives the money|"
    "continuity of the business|the form the instrument takes|"
    "whether there was a commercial reason|a bargain struck in advance"
).split("|")
_MISSING = (
    "I do not have enough to settle that|the file does not say which|"
    "nobody has told me the counterparty|that fact is missing here|"
    "I would need the second jurisdiction|the dates are not in front of me|"
    "the shareholding is unstated|I cannot see the contract|"
    "that is precisely what is unclear|no one specified the amounts"
).split("|")
_CONNECTIVE = (
    "So|Then again|But|Although|Granted|Still|On the other hand|Which means|"
    "Meanwhile|Suppose instead"
).split("|")


def looping_thought(fragments: int = 45) -> str:
    """The measured failure."""
    return "\n\n".join(
        f"Need maybe include \"If you mean 'I want to make 2k into 4k in a German "
        f"entity as fast as possible, legally, with no tax on "
        f"{COUNTRIES[i % len(COUNTRIES)]}', maybe if entity.\""
        for i in range(fragments)
    )


def realistic_thought(steps: int = 60, seed: int = 7) -> str:
    """Long reasoning that circles a question without resolving it — fluent and
    on-track, which is exactly what the reasoning-budget note in llm.py says a
    102k-character thought looked like. This is the thought a guard must not
    cut off."""
    rng = random.Random(seed)
    return "\n\n".join(
        f"{rng.choice(_CONNECTIVE)} {rng.choice(_SUBJECT)} {rng.choice(_VERB)} "
        f"{rng.choice(_OBJECT)}, and {rng.choice(_MISSING)}. "
        f"{rng.choice(_CONNECTIVE)} if I assume the opposite, {rng.choice(_SUBJECT)} "
        f"{rng.choice(_VERB)} {rng.choice(_OBJECT)} instead, which moves the answer "
        f"somewhere else entirely; {rng.choice(_MISSING)}."
        for _ in range(steps)
    )


def templated_thought(cases: int = 70, seed: int = 3) -> str:
    """The hard negative: real enumeration, each case carrying new content, all
    of them on a shared twelve-word scaffold. Structurally this is what a loop
    looks like from a distance, and the repeat count cannot tell them apart."""
    rng = random.Random(seed)
    return "\n\n".join(
        f"Case {i}: let me work through this one carefully and see where it lands. "
        f"{rng.choice(_SUBJECT)} {rng.choice(_VERB)} {rng.choice(_OBJECT)}, so the "
        f"outcome for {COUNTRIES[i % len(COUNTRIES)]} is different again and "
        f"{rng.choice(_MISSING)}."
        for i in range(cases)
    )


def feed(guard: LoopGuard, text: str, chunk: int = 20) -> bool:
    """Deltas, not one blob: the guard sees a few characters at a time in
    production, and its checkpointing has to survive arriving that way."""
    tripped = False
    for i in range(0, len(text), chunk):
        tripped = guard.feed(text[i : i + chunk]) or tripped
    return tripped


# --- what it must catch ------------------------------------------------------


def test_the_measured_loop_is_caught():
    guard = LoopGuard()

    assert feed(guard, looping_thought())
    assert guard.novelty < LoopGuard.min_novelty


def test_no_two_fragments_of_the_loop_are_identical():
    """Why shingles at all. Exact matching sees 45 different lines and reports
    nothing; the repetition is inside them, not between them."""
    lines = looping_thought().split("\n\n")

    assert len(set(lines)) == len(lines)
    assert feed(LoopGuard(), looping_thought())


def test_a_longer_loop_does_not_drift_out_of_range():
    """The verdict is drawn from a window, so a loop that has been running for
    30,000 characters must read the same as one that just started. If it drifted
    the thresholds would only hold for the length they were measured at."""
    short = LoopGuard()
    long = LoopGuard()
    feed(short, looping_thought(45))
    feed(long, looping_thought(200))

    assert short.tripped and long.tripped
    assert abs(short.novelty - long.novelty) < 0.05


def test_a_tight_loop_is_caught_by_the_same_signal():
    """A short phrase cycling forever. It needs no separate rule — a window
    holding seven distinct shingles has almost no novelty by construction."""
    guard = LoopGuard()

    assert feed(guard, "Wait, let me reconsider that once more. " * 400)
    assert guard.novelty < 0.05


def test_the_verdict_latches_so_a_caller_acts_once():
    guard = LoopGuard()
    feed(guard, looping_thought())

    assert guard.tripped
    assert guard.feed("something entirely new and quite unlike anything before it")


def test_it_keeps_measuring_after_it_trips():
    """Evidence has to describe the whole thought. Stop feeding at the verdict
    and every loop in the log looks like it ended the moment it was noticed."""
    guard = LoopGuard()
    feed(guard, looping_thought())
    at_trip = guard.evidence["thought_chars"]

    guard.feed("x" * 500)

    assert guard.evidence["thought_chars"] == at_trip + 500


# --- what it must not catch --------------------------------------------------


def test_a_long_unresolved_thought_is_left_alone():
    """The expensive false positive. Cutting this off is worse than letting a
    loop run: the loop wastes one generation, this destroys a good one."""
    guard = LoopGuard()

    assert not feed(guard, realistic_thought())
    assert guard.total_chars > guard.min_thought_chars, "sample must be long enough to judge"
    assert guard.novelty > LoopGuard.min_novelty


def test_enumeration_on_a_fixed_scaffold_is_left_alone():
    """Seventy cases sharing a twelve-word preamble. The repeat count reaches 27
    here against the loop's 40 — close enough that this is the sample keeping
    MAX_REPEATS honest."""
    guard = LoopGuard()

    assert not feed(guard, templated_thought())
    assert guard.repeats > 20, "sample must actually stress the repeat signal"


def test_a_short_thought_is_never_judged():
    """Restating the question, or re-listing the constraints, is working."""
    guard = LoopGuard()

    assert not feed(guard, "The user asked about German entities. " * 100)
    assert guard.novelty is None, "nothing under the floor should even be measured"


def test_one_dense_window_does_not_trip_it_on_its_own():
    """Confirmation, on a guard shrunk so a window is reachable in a test. A
    model quoting something repetitive — a table, a list of near-identical
    cases — produces one dense verdict and then moves on."""
    small = {
        "min_thought_chars": 400,
        "window_chars": 400,
        "check_every_chars": 200,
        "min_shingles": 40,
    }
    guard = LoopGuard(**small)
    feed(guard, realistic_thought(steps=4, seed=1))

    assert not guard.feed("the very same clause again and again. " * 8)


def test_the_agreement_count_resets_rather_than_accumulating():
    """Two dense windows far apart are not a loop; two in a row are. Without the
    reset a thought would accumulate unrelated suspicions until it tripped on
    nothing in particular."""
    small = {
        "min_thought_chars": 400,
        "window_chars": 400,
        "check_every_chars": 200,
        "min_shingles": 40,
    }
    dense = "the very same clause again and again. " * 8
    varied = realistic_thought(steps=4, seed=2)

    alternating = LoopGuard(**small)
    feed(alternating, realistic_thought(steps=4, seed=1))
    for _ in range(3):
        alternating.feed(dense)
        alternating.feed(varied)
    assert not alternating.tripped

    consecutive = LoopGuard(**small)
    feed(consecutive, realistic_thought(steps=4, seed=1))
    assert feed(consecutive, dense * 4)


# --- the shape of the evidence -----------------------------------------------


def test_evidence_is_numbers_only():
    """It goes into the log and into the stored job result, and the thought is
    the user's own text — the rule giq.privacy enforces for errors holds here."""
    guard = LoopGuard()
    feed(guard, looping_thought())

    assert set(guard.evidence) == {"thought_chars", "novelty", "max_repeats"}
    for value in guard.evidence.values():
        assert value is None or isinstance(value, int | float)
        assert not isinstance(value, str)

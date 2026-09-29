# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Keeping the request out of the things giq writes down.

`runner._request_shape` handles the deliberate path: it measures a request
rather than recording it, and stays safe as fields are added because counting
an unknown field is still counting. This module handles the other path — the
one that does not go through the shape at all.

Errors are free text. `_log_inflight(..., error=...)` writes whatever it is
handed, and the same string is persisted forever in `stats.db.jobs.error`.
Almost every error is a CUDA message or a scheduler decision and belongs in
the log. But some exceptions quote their input: a validation error carries the
value that failed, and an engine that logs the prompt on a bad render puts it
in the stderr tail giq attaches to the failure. Nothing about the string says
which kind it is.

So rather than trying to recognise the dangerous ones, the rule here is a
property of the pair: **an error may not quote the request it came from.** The
request is right there — it can simply be checked, and a message that repeats
a run of it is withheld whole. That keeps working for exceptions nobody has
seen yet, which is the same reason the shape counts instead of redacting.
"""

from __future__ import annotations

from typing import Any

# The shortest run of shared text treated as a quotation rather than a
# coincidence. Model names, job ids and worker names are short and are not part
# of the haystack anyway; a run this long is the request being repeated back.
_MIN_ECHO = 16

# The scan steps rather than sliding one character at a time: any quoted run of
# _MIN_ECHO + _STEP characters or more still lands inside a window, at a
# fraction of the work.
_STEP = 8

# Errors are diagnostic, not narrative. Past this, a message is a dump.
_MAX_DETAIL = 2000

WITHHELD = "<withheld: the message quoted the request>"


def _collect(obj: Any, out: list[str]) -> None:
    """Every string the caller supplied, and nothing giq generated itself."""
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, out)


def request_text(request: Any) -> str:
    """The caller's own words, as one haystack.

    Deliberately only ``tasks`` and ``chat_request`` — the same two the shape
    walks. Worker and model names are giq's vocabulary, not the user's, and
    including them would withhold exactly the scheduler messages ("evicted for
    text2image/flux_klein") that the log exists to carry.
    """
    parts: list[str] = []
    _collect(getattr(request, "tasks", None), parts)
    _collect(getattr(request, "chat_request", None), parts)
    return "\x00".join(parts)


def echoes_request(text: str, request: Any) -> bool:
    """True when `text` repeats a run of what the caller sent."""
    if not text or request is None:
        return False
    haystack = request_text(request)
    if len(haystack) < _MIN_ECHO:
        return False
    scanned = text[:_MAX_DETAIL]
    for i in range(0, max(1, len(scanned) - _MIN_ECHO + 1), _STEP):
        if scanned[i : i + _MIN_ECHO] in haystack:
            return True
    return False


def safe_detail(text: str | None, request: Any) -> str | None:
    """An error string fit to write down: bounded, and not a quote."""
    if not text:
        return text
    if echoes_request(text, request):
        return WITHHELD
    return text if len(text) <= _MAX_DETAIL else text[:_MAX_DETAIL] + "…"


def safe_extra(extra: dict[str, Any], request: Any) -> dict[str, Any]:
    """Same treatment for every string a caller attaches to a log record.

    `_log_inflight` takes arbitrary keyword arguments and writes them out. That
    is a useful shape — a requeue reason today, something else next year — and
    it is also the one place the measurement discipline does not reach. Taking
    every string through the same check means a future caller cannot open the
    hole again by inventing a field.
    """
    return {k: safe_detail(v, request) if isinstance(v, str) else v for k, v in extra.items()}

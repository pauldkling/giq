# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""giq workers package."""

from giq.workers.llm import LLMWorker, LLMWorkerConfig

__all__ = [
    "LLMWorker",
    "LLMWorkerConfig",
    # Other workers imported lazily to avoid loading heavy deps unless needed:
    # - tts (kokoro)
    # - stt (faster-whisper)
]

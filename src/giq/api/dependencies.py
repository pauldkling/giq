# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

from giq.services.audio_cache import AudioCache
from giq.services.orchestration import Orchestrator

_audio_cache: AudioCache | None = None


def get_orchestrator() -> Orchestrator:
    """Get a fresh Orchestrator instance that uses the current queue."""
    return Orchestrator()


def get_audio_cache() -> AudioCache:
    global _audio_cache
    if _audio_cache is None:
        _audio_cache = AudioCache()
    return _audio_cache

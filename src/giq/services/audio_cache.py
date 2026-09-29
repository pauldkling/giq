# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

import logging
import time

logger = logging.getLogger(__name__)


class AudioCache:
    def __init__(self, ttl: int = 300):
        self._cache: dict[str, dict] = {}
        self.ttl = ttl

    async def cleanup(self):
        """Remove expired audio files from cache."""
        now = time.time()
        expired = [fid for fid, info in self._cache.items() if now > info["expires"]]
        for fid in expired:
            del self._cache[fid]
            logger.debug(f"Audio cache: expired {fid}")
        if expired:
            logger.info(
                f"Audio cache: cleaned {len(expired)} expired files, {len(self._cache)} remaining"
            )

    def get(self, file_id: str) -> dict | None:
        if file_id not in self._cache:
            return None

        info = self._cache[file_id]
        if time.time() > info["expires"]:
            del self._cache[file_id]
            return None

        return info

    def set(self, file_id: str, data: bytes, expires_in: int = None):
        now = time.time()
        ttl = expires_in if expires_in is not None else self.ttl
        self._cache[file_id] = {
            "data": data,
            "created": now,
            "expires": now + ttl,
        }
        logger.debug(f"Audio cache: stored {file_id} ({len(data)} bytes)")

    def delete(self, file_id: str):
        if file_id in self._cache:
            del self._cache[file_id]
            logger.debug(f"Audio cache: deleted {file_id}")

    def __contains__(self, file_id: str) -> bool:
        return file_id in self._cache

    @property
    def size(self) -> int:
        return len(self._cache)

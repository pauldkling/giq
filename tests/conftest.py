# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Shared test config."""

import os
import tempfile

# Keep test telemetry out of the production stats DB (data/stats.db). Set
# before any giq import can construct the StatsRecorder singleton — unit
# tests exercising eviction/jobs write through it.
os.environ.setdefault(
    "GIQ_STATS_DB", os.path.join(tempfile.mkdtemp(prefix="giq-test-stats-"), "stats.db")
)
# The in-flight log would otherwise land in the checkout's data/ directory.
os.environ.setdefault(
    "GIQ_INFLIGHT_LOG", os.path.join(tempfile.mkdtemp(prefix="giq-test-inflight-"), "inflight.log")
)
# Operator instance files would otherwise come from ~/.config/giq/instances
# and change the catalog under test; the built-ins are what the suite checks.
os.environ.setdefault("GIQ_INSTANCES_DIR", tempfile.mkdtemp(prefix="giq-test-instances-"))

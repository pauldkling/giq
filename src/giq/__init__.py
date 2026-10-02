# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""giq - GPU Inference Queue."""

from importlib.metadata import PackageNotFoundError, version

# pyproject.toml is the one place the version is written — CI checks the tag
# against it and the Makefile names the dashboard tarball from it. A literal
# here is a second copy that a release bump can miss, and /status would then
# report the old version on a new deploy. The installed metadata is the
# pyproject's version as of the last `uv sync`.
try:
    __version__ = version("giq")
except PackageNotFoundError:  # a source tree on sys.path that was never installed
    __version__ = "0+unknown"

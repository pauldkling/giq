# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""The ``giq`` command: ``giq serve`` (the default), ``giq init`` and
``giq prepare``.

``serve`` is imported only when serving, so ``giq init`` — run once by an
installer as the service user, before a config exists — never builds the
FastAPI app.
"""

from __future__ import annotations

import argparse
import os
import sys
from importlib import resources
from pathlib import Path

from giq import paths

TEMPLATE = "config.example.yaml"


def template_text() -> str:
    """The commented config template shipped in the package."""
    return resources.files("giq").joinpath("templates", TEMPLATE).read_text(encoding="utf-8")


def init_home(home: Path) -> list[str]:
    """Create a GIQ_HOME tree and its config.yaml. Never overwrites anything.

    The config is written first and then read, so a pre-existing config whose
    ``paths:`` block moves a directory elsewhere gets that directory created
    where it points. Returns a line per thing it created.
    """
    from giq.config import reload_config

    created: list[str] = []
    home = home.expanduser().absolute()
    os.environ["GIQ_HOME"] = str(home)
    if not home.is_dir():
        home.mkdir(parents=True)
        created.append(f"{home}/")

    config = paths.config_file().absolute()
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create: a config that appears between the check and the
        # write is someone else's and stays theirs.
        with open(config, "x", encoding="utf-8") as f:
            f.write(template_text())
        created.append(str(config))
    reload_config()

    dirs = [paths.models_dir(), paths.instances_dir(), paths.state_dir()]
    engines, cache = paths.engines_dir(), paths.cache_dir()
    dirs += [d for d in (engines, cache) if d is not None]
    if cache is not None:
        dirs.append(paths.hf_home())
    for d in dirs:
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(f"{d}/")
    return created


def _init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="giq init",
        description="Create the GIQ_HOME data tree (config.yaml, models/, instances/, "
        "engines/, state/, cache/). Existing files and directories are left as they are.",
    )
    parser.add_argument(
        "--home",
        default=os.environ.get("GIQ_HOME"),
        help="Data root to create (default: $GIQ_HOME)",
    )
    args = parser.parse_args(argv)
    if not args.home:
        parser.error("no data root: pass --home PATH or set GIQ_HOME")
    created = init_home(Path(args.home))
    for line in created:
        print(f"created {line}")
    if not created:
        print(f"{paths.home()}: nothing to do, everything exists")
    for key, value in paths.resolved().items():
        print(f"  {key:9} {value if value is not None else '-'}")
    return 0


def _prepare(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="giq prepare",
        description="One-off build steps an engine needs before it serves. `vllm` compiles "
        "FlashInfer's GEMM kernels for the card's architecture inside a RAM-capped scope, so "
        "no start or request ever has to. Already-built kernels are skipped.",
    )
    parser.add_argument("engine", choices=["vllm"], help="Engine to prepare")
    parser.add_argument(
        "--gpu",
        default=None,
        help="Card to build for, by index or UUID (default: every card, once per "
        "distinct compute capability)",
    )
    parser.add_argument(
        "--instance",
        action="append",
        default=[],
        metavar="NAME",
        help="also start this vllm instance once and stop it, so the compiles its first "
        "start needs (attention kernels, torch.compile, CUDA graphs) are done now; uses "
        "the GPU for a few minutes. Repeatable",
    )
    parser.add_argument(
        "--memory-max",
        default=None,
        help="RAM ceiling for the build (systemd MemoryMax; default 40G — two compile "
        "jobs peak near 15 GB each). `none` when the caller already runs this in a "
        "capped scope, as the installer does",
    )
    args = parser.parse_args(argv)
    from giq.workers.vllm import DEFAULT_MEMORY_MAX, VLLMConfigError, prepare, warm_up

    try:
        memory_max = args.memory_max or DEFAULT_MEMORY_MAX
        code = prepare(args.gpu, None if memory_max.lower() == "none" else memory_max)
    except (VLLMConfigError, FileNotFoundError) as e:
        print(f"giq prepare vllm: {e}", file=sys.stderr)
        return 2
    if code != 0:
        print(f"giq prepare vllm: build failed (exit {code})", file=sys.stderr)
        return code
    for name in args.instance:
        import asyncio

        from giq.gpus import resolve_device

        gpu = resolve_device(args.gpu) if args.gpu is not None else None
        print(f"warming up {name} (a full start, then stop) ...", flush=True)
        try:
            took = asyncio.run(warm_up(name, gpu.uuid if gpu else None))
        except Exception as e:
            print(f"giq prepare vllm: warm-up of {name} failed: {e}", file=sys.stderr)
            return 1
        print(f"{name}: started in {took:.0f}s; the next start reuses its caches", flush=True)
    return 0


def main(argv: list[str] | None = None) -> None:
    """Dispatch ``giq [serve|init|prepare] …``; bare options mean ``serve``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "init":
        sys.exit(_init(args[1:]))
    if args and args[0] == "prepare":
        sys.exit(_prepare(args[1:]))
    if args and args[0] == "serve":
        args = args[1:]
    from giq.main import cli

    cli(args)

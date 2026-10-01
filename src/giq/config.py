# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Configuration for giq service."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from giq import paths as giq_paths

logger = logging.getLogger(__name__)


@dataclass
class ImageModelConfig:
    """An image model's files, and the runtime that renders them.

    What ``giq.weights.image_files`` hands the image workers, built from the
    model's recipe file. As a ``config.yaml`` ``image_models`` entry it is
    deprecated (see :func:`warn_image_model`): such an entry still replaces
    the recipe's files, and its ``vram_gb``/``engine``, when given,
    overlay the recipe's.
    """

    diffusion: str
    text_encoder: str
    vae: str
    lora: str | None = None
    # None = the recipe's figure.
    vram_gb: float | None = None
    # Which runtime renders this model: "sd.cpp" (stable-diffusion.cpp's
    # sd-server child), the only image runtime; the old "sdcpp" is read as
    # "sd.cpp". None = the recipe's engine.
    engine: str | None = None


_warned_image_models: set[str] = set()


def warn_image_model(name: str, entry: ImageModelConfig) -> None:
    """Say once per process that ``image_models.<name>`` belongs in a recipe file.

    Warned where the entry is used (the catalog, a worker being built), not
    where the config is parsed, so the children that read config.yaml for
    their generation defaults do not repeat it.
    """
    if name in _warned_image_models:
        return
    _warned_image_models.add(name)
    from giq.engines import ENGINE_ALIASES
    from giq.recipes import builtin

    shipped = [
        (recipe, path)
        for (worker, model), (recipe, path) in builtin().items()
        if model == name and worker in ("text2image", "image_edit")
    ]
    parts = {"diffusion": entry.diffusion, "text_encoder": entry.text_encoder, "vae": entry.vae}
    if entry.lora:
        parts["lora"] = entry.lora
    equivalent = "weights: {parts: {" + ", ".join(f"{k}: {v}" for k, v in parts.items()) + "}}"
    # Only what differs from the shipped file needs saying.
    reference = shipped[0][0] if shipped else None
    engine = ENGINE_ALIASES.get(entry.engine or "", entry.engine)
    if engine and (reference is None or reference.engine != engine):
        equivalent += f", engine: {engine}"
    if entry.vram_gb is not None and (reference is None or reference.vram.gb != entry.vram_gb):
        equivalent += f", vram: {{gb: {entry.vram_gb}, measured: false}}"
    where = (
        "copy " + " and ".join(str(path) for _, path in shipped)
        if shipped
        else "write a recipe file"
    )
    logger.warning(
        f"config.yaml image_models.{name} is deprecated; it still overrides the recipe's files "
        "(and its engine and VRAM figure, where it sets them). Move it into a recipe file: "
        f"{where} to {giq_paths.recipes_dir()}, set {equivalent} there, and delete the "
        "image_models entry"
    )


@dataclass
class GpuConfig:
    """Which cards giq runs models on.

    ``device`` is the default card for models that name none — an index ("1")
    or an NVML UUID ("GPU-xxxx…"); UUID is the stable form and what giq reports
    back. Unset = the biggest card.

    ``bind`` maps "worker/model" to a card, for models that must live on a
    particular one. Operator overrides set through the API outrank this and
    persist in stats.db; this is the checked-in default.

    ``reserve`` maps a card to VRAM the scheduler leaves unclaimed — headroom
    on a card shared with a desktop, which can grow a gigabyte without asking.
    """

    device: str | None = None
    bind: dict[str, str] = field(default_factory=dict)
    reserve: dict[str, float] = field(default_factory=dict)


@dataclass
class ImageGenerationConfig:
    """Default generation parameters."""

    width: int = 1024
    height: int = 1024
    steps: int = 4
    cfg: float = 1.0
    sampler: str = "euler"
    scheduler: str = "simple"
    denoise: float = 1.0


@dataclass
class ProvenanceConfig:
    """AI-provenance marking of generated images. On by default."""

    mark_images: bool = True


@dataclass
class AccessConfig:
    """Who may reach giq, and from where.

    ``token`` is opt-in and empty by default: on a single-user host the caller is the
    owner, and making them carry a credential to talk to their own GPU buys
    little. It earns its place once giq is bound off loopback, which is why
    the startup banner names it then and only then.

    ``allow_hosts`` and ``allow_origins`` extend the built-in rules for setups
    the defaults cannot guess — a reverse proxy that rewrites Host, or a
    separate front-end origin that should be allowed to call this one.
    """

    token: str = ""
    allow_hosts: list[str] = field(default_factory=list)
    allow_origins: list[str] = field(default_factory=list)


@dataclass
class GiqConfig:
    """Main giq configuration."""

    gpu: GpuConfig = field(default_factory=GpuConfig)
    image_models: dict[str, ImageModelConfig] = field(default_factory=dict)
    image_generation: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)
    negative_prompt: str = ""
    provenance: ProvenanceConfig = field(default_factory=ProvenanceConfig)
    access: AccessConfig = field(default_factory=AccessConfig)
    # Models kept loaded whenever nothing else claims the VRAM, as
    # "worker/model" strings in reload-priority order. Empty = use the
    # registry's built-in set. Rig-specific, hence config rather than code.
    residents: list[str] = field(default_factory=list)
    # Engine name -> binary path, overriding giq.engines' built-ins. One
    # declared path per runtime; without one, the binary is looked up on PATH.
    engines: dict[str, str] = field(default_factory=dict)
    # Data directories (models, recipes, engines, state, cache), overriding
    # the GIQ_HOME layout and overridden by their GIQ_* variables. Resolved by
    # giq.paths, which is the only reader.
    paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "GiqConfig":
        """Load configuration from file and environment.

        Priority: env vars > config file > defaults
        """
        config = cls()

        # GIQ_CONFIG, else $GIQ_HOME/config.yaml, else ./config.yaml. Never
        # from the config itself, which is what keeps giq.paths acyclic.
        if config_path is None:
            config_path = giq_paths.config_file()

        config_path = Path(config_path)
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            config._load_from_dict(data)

        # Override with env vars
        if gpu_device := os.environ.get("GIQ_GPU_DEVICE"):
            config.gpu.device = gpu_device
        if token := os.environ.get("GIQ_TOKEN"):
            config.access.token = token

        return config

    def _load_from_dict(self, data: dict) -> None:
        """Load configuration from dict."""
        # GPU selection, per-model bindings, per-card reserves
        if "gpu" in data:
            gpu_data = data["gpu"] or {}
            device = gpu_data.get("device")
            self.gpu.device = str(device) if device is not None else None
            self.gpu.bind = {
                str(name): str(dev) for name, dev in (gpu_data.get("bind") or {}).items()
            }
            self.gpu.reserve = {
                str(name): float(gb) for name, gb in (gpu_data.get("reserve") or {}).items()
            }

        # Image models (deprecated: their files belong in the recipe files)
        if "image_models" in data:
            from giq.engines import canonical_engine

            for name, model_data in (data["image_models"] or {}).items():
                engine = model_data.get("engine")
                vram_gb = model_data.get("vram_gb")
                self.image_models[name] = ImageModelConfig(
                    diffusion=model_data["diffusion"],
                    text_encoder=model_data["text_encoder"],
                    vae=model_data["vae"],
                    lora=model_data.get("lora"),
                    vram_gb=float(vram_gb) if vram_gb is not None else None,
                    engine=(
                        canonical_engine(str(engine), f"config.yaml image_models.{name}")
                        if engine
                        else None
                    ),
                )

        # Image generation defaults
        if "image_generation" in data:
            gen_data = data["image_generation"]
            self.image_generation = ImageGenerationConfig(
                width=gen_data.get("width", 1024),
                height=gen_data.get("height", 1024),
                steps=gen_data.get("steps", 4),
                cfg=gen_data.get("cfg", 1.0),
                sampler=gen_data.get("sampler", "euler"),
                scheduler=gen_data.get("scheduler", "simple"),
                denoise=gen_data.get("denoise", 1.0),
            )

        # Negative prompt
        if "negative_prompt" in data:
            self.negative_prompt = data["negative_prompt"]

        # Resident set
        if "residents" in data:
            self.residents = list(data["residents"] or [])

        # Inference engines
        if "engines" in data:
            self.engines = {
                str(name): str((cfg or {}).get("binary") if isinstance(cfg, dict) else cfg)
                for name, cfg in (data["engines"] or {}).items()
                if cfg
            }

        # Data directories
        if "paths" in data:
            block = dict(data["paths"] or {})
            # ADR-003 renamed the instance files recipes; an old key still
            # points at the operator's files rather than being dropped as
            # unknown, which would make them vanish from the catalog.
            if "instances" in block and "recipes" not in block:
                logger.warning("config: paths.instances is now paths.recipes (ADR-003)")
                block["recipes"] = block.pop("instances")
            unknown = sorted(set(block) - set(giq_paths.LAYOUT))
            if unknown:
                logger.warning(
                    f"config: ignoring unknown paths: {', '.join(map(str, unknown))} "
                    f"(known: {', '.join(giq_paths.LAYOUT)})"
                )
            self.paths = {str(k): str(v) for k, v in block.items() if k in giq_paths.LAYOUT and v}

        # Access control
        if "access" in data:
            acc = data["access"] or {}
            self.access = AccessConfig(
                token=str(acc.get("token") or ""),
                allow_hosts=[str(h) for h in (acc.get("allow_hosts") or [])],
                allow_origins=[str(o) for o in (acc.get("allow_origins") or [])],
            )

        # Provenance marking
        if "provenance" in data:
            self.provenance = ProvenanceConfig(
                mark_images=data["provenance"].get("mark_images", True)
            )


# Global config recipe
_config: GiqConfig | None = None


def get_config() -> GiqConfig:
    """Get or load global config."""
    global _config
    if _config is None:
        _config = GiqConfig.load()
    return _config


def reload_config(config_path: str | Path | None = None) -> GiqConfig:
    """Reload configuration."""
    global _config
    _config = GiqConfig.load(config_path)
    return _config

# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Workers load the weights their instance names.

The failure this guards against is an instance file that adds a model to
the catalog which its worker then cannot load, because the worker looked its
weights up in a table of its own keyed by the built-in names.
"""

import pytest

from giq import weights
from giq.instances import InstanceError, load_file
from giq.paths import models_dir


@pytest.fixture
def operator_dir(tmp_path, monkeypatch):
    """An operator instances directory, with the catalog rebuilt around it."""
    from giq.registry import reload_registry

    directory = tmp_path / "instances"
    directory.mkdir()
    monkeypatch.setenv("GIQ_INSTANCES_DIR", str(directory))
    reload_registry()
    yield directory
    monkeypatch.undo()
    reload_registry()


def _add(directory, filename: str, text: str) -> None:
    from giq.registry import reload_registry

    (directory / filename).write_text(text)
    reload_registry()


# --- new names load -----------------------------------------------------------


def test_an_ocr_instance_under_a_new_name_loads_its_own_weights(operator_dir, monkeypatch):
    from giq.workers.ocr import OCRWorker, OCRWorkerConfig

    # The built-in's override is scoped to the built-in's name.
    monkeypatch.setenv("GIQ_OCR_MODEL_DIR", "/elsewhere/unlimited")
    _add(
        operator_dir,
        "ocr-ft.yaml",
        "name: unlimited-ocr-ft\nworker: ocr\nengine: transformers-4.57\n"
        "weights: {path: /srv/models/unlimited-ft}\nvram: {gb: 9.0}\n",
    )
    w = OCRWorker(OCRWorkerConfig(model="unlimited-ocr-ft"))
    assert w.child_module == "giq.workers._ocr_child"
    assert w.child_args() == ["--weights", "/srv/models/unlimited-ft"]
    assert OCRWorker(OCRWorkerConfig()).child_args() == ["--weights", "/elsewhere/unlimited"]


def test_a_layout_ocr_instance_reads_its_layout_part(operator_dir):
    from giq.workers.ocr import OCRWorker, OCRWorkerConfig

    _add(
        operator_dir,
        "glm-ft.yaml",
        "name: glm-ocr-ft\nworker: ocr\nengine: transformers\n"
        "weights:\n  path: glm-ft\n  parts: {layout: layout-v4}\nvram: {gb: 4.0}\n",
    )
    w = OCRWorker(OCRWorkerConfig(model="glm-ocr-ft"))
    assert w.child_module == "giq.workers._glm_ocr_child"
    assert w.child_args() == [
        "--weights",
        str(models_dir() / "glm-ft"),
        "--layout",
        str(models_dir() / "layout-v4"),
    ]


def test_a_layout_ocr_instance_without_its_layout_fails_at_construction(operator_dir):
    from giq.workers.ocr import OCRWorker, OCRWorkerConfig

    _add(
        operator_dir,
        "glm-ft.yaml",
        "name: glm-ocr-ft\nworker: ocr\nengine: transformers\n"
        "weights: {path: glm-ft}\nvram: {gb: 4.0}\n",
    )
    with pytest.raises(ValueError, match="weights.parts.layout"):
        OCRWorker(OCRWorkerConfig(model="glm-ocr-ft"))


def test_a_multiview_instance_under_a_new_name_loads_its_own_weights(operator_dir):
    from giq.workers.multiview import MultiviewWorker, MultiviewWorkerConfig

    _add(
        operator_dir,
        "da3.yaml",
        "name: da3-ft\nworker: multiview\nengine: da3\n"
        "weights: {path: ~/ckpt/da3-ft}\nvram: {gb: 7.0}\n",
    )
    w = MultiviewWorker(MultiviewWorkerConfig(model="da3-ft"))
    assert w.child_args()[-2:] == [
        "--weights",
        str(weights.resolve_path("multiview", "~/ckpt/da3-ft")),
    ]
    assert not w.child_args()[-1].startswith("~")


def test_an_instance_without_weights_fails_at_construction(operator_dir):
    from giq.workers.depth import DepthWorker, DepthWorkerConfig

    _add(
        operator_dir,
        "d.yaml",
        "name: depth-nowhere\nworker: depth\nengine: transformers\nvram: {gb: 1.0}\n",
    )
    with pytest.raises(ValueError, match="no weights.path"):
        DepthWorker(DepthWorkerConfig(model="depth-nowhere"))


def test_speech_models_load_the_repository_their_instance_names(operator_dir, monkeypatch):
    from giq.workers.audio import AudioWorker, AudioWorkerConfig, EmbedWorker, EmbedWorkerConfig
    from giq.workers.stt import model_ref
    from giq.workers.tts import TTSWorker, TTSWorkerConfig

    assert model_ref("large-v3") == "Systran/faster-whisper-large-v3"
    _add(
        operator_dir,
        "stt.yaml",
        "name: whisper-de\nworker: stt\nengine: faster-whisper\n"
        "weights: {path: /srv/ct2/whisper-de}\nvram: {gb: 3.0}\n",
    )
    assert model_ref("whisper-de") == "/srv/ct2/whisper-de"
    # No instance: faster-whisper's own size names still work.
    assert model_ref("distil-large-v3") == "distil-large-v3"

    monkeypatch.delenv("GIQ_AUDIO_WHISPER_MODEL", raising=False)
    monkeypatch.setenv("GIQ_AUDIO_DIAR_MODEL", "org/other-diarization")
    env = AudioWorker(AudioWorkerConfig())._spawn_env()
    assert env["GIQ_AUDIO_WHISPER_MODEL"] == "Systran/faster-whisper-large-v3"
    assert env["GIQ_AUDIO_DIAR_MODEL"] == "org/other-diarization"  # the environment wins
    monkeypatch.delenv("GIQ_EMBED_MODEL", raising=False)
    assert (
        EmbedWorker(EmbedWorkerConfig())._spawn_env()["GIQ_EMBED_MODEL"]
        == "speechbrain/spkrec-ecapa-voxceleb"
    )
    assert TTSWorker(TTSWorkerConfig()).child_args()[-2:] == ["--repo", "hexgrad/Kokoro-82M"]


def test_the_storage_catalog_finds_repositories_in_the_hf_cache(tmp_path, monkeypatch):
    from giq.storage import resolve_model_paths

    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path))
    resolved = resolve_model_paths()
    assert resolved[("audio", "whisper-large-v3")] == [
        (tmp_path / "models--Systran--faster-whisper-large-v3").resolve(),
        (tmp_path / "models--pyannote--speaker-diarization-community-1").resolve(),
    ]
    assert resolved[("stt", "large-v3")] == resolved[("audio", "whisper-large-v3")][:1]
    assert resolved[("tts", "kokoro")] == [(tmp_path / "models--hexgrad--Kokoro-82M").resolve()]


# --- image models -------------------------------------------------------------


def test_image_models_take_their_files_from_the_instance():
    from giq.weights import image_files
    from giq.workers.sdcpp import SdCppWorkerConfig

    cfg = SdCppWorkerConfig(model="flux_klein", device="GPU-x", port=1)
    assert cfg.diffusion == str(models_dir() / "diffusion_models/flux-2-klein-4b.safetensors")
    assert cfg.vae == str(models_dir() / "vae/flux2-vae.safetensors")
    files = image_files("text2image", "zimage")
    assert files.text_encoder == str(models_dir() / "text_encoders/qwen_3_4b.safetensors")
    assert files.lora is None


class _LegacyCfg:
    """config.yaml with an image_models entry, as before instance files."""

    def __init__(self, **entry):
        from giq.config import ImageModelConfig

        self.residents = []
        self.image_models = {
            "zimage": ImageModelConfig(
                diffusion="/old/z.safetensors", text_encoder="/old/te", vae="/old/vae", **entry
            )
        }


@pytest.fixture
def legacy_config(monkeypatch):
    from giq import config
    from giq.registry import reload_registry

    def install(**entry):
        cfg = _LegacyCfg(**entry)
        monkeypatch.setattr("giq.config.get_config", lambda: cfg)
        monkeypatch.setattr(config, "_warned_image_models", set())
        reload_registry()
        return cfg

    yield install
    monkeypatch.undo()
    reload_registry()


def test_a_config_image_model_still_overrides_with_one_warning(legacy_config, caplog):
    from giq.registry import get_spec
    from giq.weights import image_files

    legacy_config()
    files = image_files("text2image", "zimage")
    image_files("text2image", "zimage")
    assert files.diffusion == "/old/z.safetensors"
    warnings = [r for r in caplog.records if "image_models.zimage is deprecated" in r.message]
    assert len(warnings) == 1
    assert "diffusion: /old/z.safetensors" in warnings[0].message
    # Keys the entry leaves out keep the instance's values.
    spec = get_spec("text2image", "zimage")
    assert (spec.vram_gb, spec.backend, spec.measured) == (13.0, "sd.cpp", True)


def test_a_config_image_model_overlays_what_it_sets(legacy_config):
    from giq.registry import get_spec

    legacy_config(vram_gb=15.0)
    spec = get_spec("text2image", "zimage")
    assert (spec.vram_gb, spec.backend, spec.measured) == (15.0, "sd.cpp", False)


def test_an_image_instance_without_its_files_fails_at_construction(operator_dir):
    from giq.workers.sdcpp import SdCppWorkerConfig

    _add(
        operator_dir,
        "img.yaml",
        "name: sketchy\nworker: text2image\nengine: sd.cpp\n"
        "weights: {parts: {diffusion: d.gguf}}\nvram: {gb: 8.0}\n",
    )
    with pytest.raises(ValueError, match="weights.parts.text_encoder, weights.parts.vae"):
        SdCppWorkerConfig(model="sketchy", device="GPU-x", port=1)


# --- resolution ---------------------------------------------------------------


def test_env_outranks_the_instance_and_roots_apply_to_relative_paths(monkeypatch):
    monkeypatch.setenv("GIQ_GLM_LAYOUT_DIR", "/pinned/layout")
    assert weights.path_of("ocr", "glm-ocr", "layout") == "/pinned/layout"
    assert weights.path_of("ocr", "glm-ocr") == str(models_dir() / "zai-GLM-OCR")
    monkeypatch.setenv("GIQ_DEPTH_MODELS_DIR", "/depth-root")
    assert weights.path_of("depth", "depth-anything-v2-small") == (
        "/depth-root/depth-anything-Depth-Anything-V2-Small-hf"
    )
    # An absolute path in the file is not moved by a root.
    assert weights.resolve_path("depth", "/abs/snap") == "/abs/snap"


def test_unknown_models_and_parts_resolve_to_nothing():
    assert weights.path_of("ocr", "no-such-ocr") is None
    assert weights.path_of("ocr", "unlimited-ocr", "layout") is None
    with pytest.raises(ValueError, match="no instance file"):
        weights.require_path("ocr", "no-such-ocr")


def test_hub_sources_are_read_as_repositories():
    assert weights.hub_repo("hf:org/repo") == "org/repo"
    assert weights.hub_repo("https://example.org/x") is None
    assert weights.hub_repo(None) is None


# --- the schema ---------------------------------------------------------------

DEPTH = "name: d\nworker: {worker}\nengine: {engine}\nweights:\n{weights}vram: {{gb: 1.0}}\n"


def _load(tmp_path, worker, engine, weights_yaml):
    path = tmp_path / "i.yaml"
    path.write_text(DEPTH.format(worker=worker, engine=engine, weights=weights_yaml))
    return load_file(path)


def test_a_part_may_be_a_bare_path_or_carry_provenance(tmp_path):
    inst = _load(
        tmp_path,
        "text2image",
        "sd.cpp",
        "  parts:\n    diffusion: a.gguf\n"
        "    vae: {path: vae.safetensors, source: 'hf:org/klein', licence: apache-2.0}\n",
    )
    assert inst.weights.parts["diffusion"].path == "a.gguf"
    assert inst.weights.parts["vae"].licence == "apache-2.0"


@pytest.mark.parametrize(
    ("worker", "engine", "parts", "complaint"),
    [
        ("depth", "transformers", "{layout: x}", "reads no parts"),
        ("ocr", "transformers", "{lay0ut: x}", "reads only layout"),
        ("text2image", "sd.cpp", "{vae: {licence: mit}}", "a path or a source"),
        ("text2image", "sd.cpp", "{Vae: x}", "pattern"),
    ],
)
def test_parts_a_worker_does_not_read_are_refused(tmp_path, worker, engine, parts, complaint):
    with pytest.raises(InstanceError, match=complaint):
        _load(tmp_path, worker, engine, f"  parts: {parts}\n")


# --- one engine vocabulary ----------------------------------------------------


def test_the_old_sdcpp_spelling_is_read_as_sd_cpp_with_a_warning(tmp_path, caplog, monkeypatch):
    from giq import engines

    monkeypatch.setattr(engines, "_warned_aliases", set())
    inst = _load(
        tmp_path, "text2image", "sdcpp", "  parts: {diffusion: d, text_encoder: t, vae: v}\n"
    )
    assert inst.engine == "sd.cpp"
    assert any("'sdcpp' is deprecated, write 'sd.cpp'" in r.message for r in caplog.records)


def test_a_config_image_model_may_still_say_sdcpp(legacy_config):
    from giq.registry import get_spec

    legacy_config(engine="sdcpp")
    spec = get_spec("text2image", "zimage")
    # The registry reads the canonical name, whatever the file said.
    assert spec.engine == spec.backend == "sd.cpp"


def test_config_yaml_is_parsed_into_canonical_engine_names(tmp_path, monkeypatch):
    from giq import engines
    from giq.config import GiqConfig

    monkeypatch.setattr(engines, "_warned_aliases", set())
    path = tmp_path / "config.yaml"
    path.write_text(
        "image_models:\n  zimage: {diffusion: d, text_encoder: t, vae: v, engine: sdcpp}\n"
        "engines:\n  sdcpp: /opt/sd-server\n"
    )
    cfg = GiqConfig.load(path)
    assert cfg.image_models["zimage"].engine == "sd.cpp"
    monkeypatch.setattr("giq.config.get_config", lambda: cfg)
    assert engines.reload_engines()["sd.cpp"].binary == "/opt/sd-server"
    monkeypatch.undo()
    engines.reload_engines()

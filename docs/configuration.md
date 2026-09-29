<!--
SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)

SPDX-License-Identifier: Apache-2.0
-->

# Configuration

`config.yaml` in the working directory (or `GIQ_CONFIG`) holds engines,
GPU placement, residents, access and the data directories. The
checked-in file is annotated; adjust its paths to your system:

```yaml
engines:
  llama.cpp: /path/to/llama-server
  sd.cpp: /path/to/sd-server
```

What each model is — its weights, engine, parameters and VRAM figure — is not
in `config.yaml` but in its [instance file](#instances).

Engines are described in [engines.md](engines.md); `access:` in
[access-and-privacy.md](access-and-privacy.md).

## Where giq keeps its files

Set `GIQ_HOME` and everything that is not code lives under one directory —
`python -m giq init` creates it with a commented `config.yaml`:

```
$GIQ_HOME/
  config.yaml   the one config
  models/       weights
  instances/    model instance files (ADR-002)
  engines/      engine builds, e.g. engines/llama.cpp/bin/llama-server
  state/        stats.db, in-flight log
  cache/        Hugging Face and kernel caches
```

Each location resolves as: its environment variable, else the `paths:` block
in `config.yaml` (absolute, or relative to `GIQ_HOME`), else the `GIQ_HOME`
layout, else the defaults below. Without `GIQ_HOME` nothing moves: models in
`~/models`, state in the checkout's `data/`, `./config.yaml`. `GET /storage`
reports the resolved paths. A server install is described in
[deployment.md](deployment.md).

Environment variables:

| Variable | Default | What |
|----------|---------|------|
| `GIQ_HOME` | unset | Data root (layout above) |
| `GIQ_HOST`, `GIQ_PORT` | `127.0.0.1`, `8084` | Bind address (command-line flags win) |
| `GIQ_DATA_DIR` | `$GIQ_HOME/state`, else `data/` | Stats database and in-flight log |
| `GIQ_INSTANCES_DIR` | `$GIQ_HOME/instances`, else `~/.config/giq/instances` | Instance files |
| `GIQ_ENGINES_DIR` | `$GIQ_HOME/engines` | Engine builds, looked up before PATH |
| `GIQ_CACHE_DIR` | `$GIQ_HOME/cache` | Caches, exported to the workers as `HF_HOME`, `XDG_CACHE_HOME` and friends |
| `GIQ_MODELS_DIR` | `$GIQ_HOME/models`, else `~/models` | Root of the model store; relative weight paths in instance files resolve against it |
| `GIQ_CONFIG` | `$GIQ_HOME/config.yaml`, else `./config.yaml` | Config file |
| `GIQ_LLAMA_BINARY` | `llama-server` on PATH | llama.cpp server binary |
| `GIQ_SDCPP_BINARY` | `sd-server` on PATH | stable-diffusion.cpp server binary |
| `GIQ_UNLIMITED_OCR_PYTHON`, `GIQ_DA3_PYTHON` | `envs/*/.venv` | Interpreters for the OCR and multiview children |
| `GIQ_VLLM_PYTHON` | `envs/vllm/.venv/bin/python` | The vllm engine's interpreter; `vllm serve` is the console script beside it ([engines.md](engines.md#vllm)) |
| `GIQ_OCR_MODEL_DIR`, `GIQ_GLM_OCR_MODEL_DIR`, `GIQ_GLM_LAYOUT_DIR` | the instance's | The `unlimited-ocr` snapshot, the `glm-ocr` snapshot and its layout part; each outranks that built-in's `weights` (see [Weights](#weights)) |
| `GIQ_DEPTH_MODELS_DIR`, `GIQ_MULTIVIEW_MODELS_DIR` | `GIQ_MODELS_DIR` | Root for the relative weight paths of depth / multiview instances |
| `GIQ_AUDIO_WHISPER_MODEL`, `GIQ_AUDIO_DIAR_MODEL`, `GIQ_EMBED_MODEL` | the instance's | Repository or path the audio and voiceprint children load, outranking the instance's `weights` |
| `GIQ_GPU_DEVICE` | biggest card | Default GPU, index or NVML UUID |
| `GIQ_TOKEN` | unset | Shared access token (see [Access](access-and-privacy.md#access)) |
| `GIQ_STATS_DB` | `<data dir>/stats.db` | Stats database |
| `GIQ_INFLIGHT_LOG` | `<data dir>/inflight.log` | In-flight job log (job shapes only, see [Privacy](access-and-privacy.md#privacy)) |
| `GIQ_OCR_MAX_UPLOAD_MB`, `GIQ_OCR_MAX_PAGES` | 64, 200 | Upload limits (see [OCR](api.md#ocr)) |
| `GIQ_MULTIVIEW_MAX_VIEWS`, `GIQ_MULTIVIEW_MAX_TOKENS` | 32, 41472 | Multiview request limits |

## Instances

Every model giq serves is an **instance**: one YAML file naming the model,
its weights, the engine that runs them, that engine's parameters, residency
defaults and the VRAM figure the scheduler gates on
([ADR-002](ADR-002-model-instances.md)). Two places hold them:

- **Built-in** — one file per model shipped in the package,
  `src/giq/instances/<worker>.<name>.yaml`. Read them for the catalog giq
  ships and for why each model runs with the settings it does; the reasoning
  is in their comments. Don't edit them in an installed giq.
- **Yours** — `*.yaml` / `*.yml` directly in the instances directory
  (`GIQ_INSTANCES_DIR`, `paths.instances`, `$GIQ_HOME/instances`, else
  `~/.config/giq/instances`). File names are free; the contents say what the
  file defines.

An instance is identified by its `worker` and `name` together
(`text2image/flux_klein` and `image_edit/flux_klein` are two instances). A
file of yours with the same worker and name as a built-in **replaces** it
entirely — nothing is inherited, so parameters you leave out take the
engine's defaults, not the built-in's; copy the built-in file and change what
you need. A file with a new name **adds** a model. The log says at INFO which
file each of your instances came from and which built-ins they replace.

```yaml
# ~/.config/giq/instances/qwen3.8-27b.yaml — the built-in at 196k context
name: qwen3.8-27b
worker: llm
engine: llama.cpp
detail: "chat + vision · 192k ctx"
weights:
  path: unsloth-Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q6_K.gguf   # under GIQ_MODELS_DIR
  format: gguf
capabilities: [chat, vision]
params:
  ctx_size: 196608
  cache_type_k: q8_0
  cache_type_v: q8_0
  reasoning: "on"            # quoted: a bare on is YAML's true
  mmproj: unsloth-Qwen3.8-27B-GGUF/mmproj-F16.gguf
vram:
  gb: 29.0
  measured: false            # an upper-bound estimate until measured
max_batch: 32
```

| Key | What |
|-----|------|
| `name` | What clients send as `model`. Letters, digits, `.`, `_`, `-`. |
| `worker` | `llm`, `text2image`, `image_edit`, `tts`, `stt`, `audio`, `embed`, `ocr`, `depth`, `multiview` |
| `engine` | The runtime, which must be able to serve the worker: `llama.cpp` or `vllm` (llm); `sd.cpp` (image workers); `kokoro`, `faster-whisper`, `faster-whisper+pyannote`, `speechbrain`, `transformers`, `transformers-4.57`, `da3` for the rest |
| `label`, `detail` | Dashboard presentation; `label` defaults to the name |
| `weights.path` | The weights file (a checkpoint directory for `vllm`), relative to `GIQ_MODELS_DIR`; `~` or absolute is used as written. Required for `llama.cpp` and `vllm`; `vllm` also needs `format: safetensors` or `modelopt` |
| `weights.parts` | The other files the model needs, by the name its worker reads them under (see [Weights](#weights)) |
| `weights.source`, `revision`, `format`, `licence` | Provenance (`hf:org/repo`, a pinned revision, `gguf`/`safetensors`/`modelopt`). Recorded, never fetched |
| `capabilities` | `chat`, `vision`. For llama.cpp `vision` needs `params.mmproj` and vice versa; for vllm, leaving it out serves a multimodal checkpoint as text |
| `profile` | vllm only: a named parameter set (`interactive`, `throughput`) under `params`, which outrank it ([engines.md](engines.md#profiles)) |
| `params` | The engine's parameters, below. Unset ones take the engine's defaults |
| `request_defaults` | Body fields sent under each request; the caller's own values win. llama.cpp: samplers, `reasoning_budget_tokens`; vllm: `top_k`, `min_p`, `presence_penalty`, `frequency_penalty`, `repetition_penalty` |
| `residency.priority` | Position in the default resident set, lowest first; unset = loads on demand |
| `vram.gb`, `vram.measured` | The gate's figure, and whether it was observed on real hardware (`measured_on`, `notes` optional). vllm with a `kv_cache_memory` budget: `vram.weights_gb` + `vram.overhead_gb` instead, and `gb` is their sum with the budget |
| `aliases` | Other names clients may send |
| `lane_width`, `max_batch`, `voices` | Concurrent jobs on a resident's lane (default per worker; for vllm it is `params.max_num_seqs` and cannot be set), batch ceiling, TTS voices |

llama.cpp `params`: `ctx_size` (shared by the slots), `parallel` (slots;
more than one turns on continuous batching), `cache_type_k` and
`cache_type_v` (set together and equal — a mixed pair falls off the fused
attention kernel), `reasoning` (`on`, `off`, `auto`, or `template` to let the
chat template decide), `reasoning_budget`, `spec_type`, `mmproj`, `alias`,
`loop_guard`. vllm `params` — a VRAM budget (`kv_cache_memory`, preferred,
or `gpu_memory_utilization`; exactly one), `max_model_len` (required),
`max_num_seqs`, `max_num_batched_tokens`, `kv_cache_dtype`, `speculative`,
`enforce_eager`, `reasoning_parser`, `tool_call_parser`, `memory_max`,
`ready_timeout` — are described in [engines.md](engines.md#parameters). The
other engines take no parameters from an instance yet.

### Weights

Every worker loads the weights its instance names, so an instance file with
a new name is a new model — no table in giq's code has to know it. The main
weights are `weights.path`; the other files a model needs are
`weights.parts`, each a path or a mapping with its own provenance:

```yaml
weights:
  path: zai-GLM-OCR                      # under GIQ_MODELS_DIR
  source: hf:zai-org/GLM-OCR
  revision: ca5d8b3
  parts:
    layout:                              # a mapping, with its own provenance
      path: PaddlePaddle-PP-DocLayoutV3
      source: hf:PaddlePaddle/PP-DocLayoutV3_safetensors
      revision: 97d101e
```

| Worker | Main weights | Parts |
|--------|--------------|-------|
| `llm` | the GGUF | — (the projector is `params.mmproj`) |
| `text2image`, `image_edit` | — | `diffusion`, `text_encoder`, `vae` (required), `lora` |
| `ocr` | the snapshot directory | `layout` (engine `transformers`: GLM-OCR's layout model) |
| `depth`, `multiview` | the snapshot directory | — |
| `stt` | a CTranslate2 directory, else the `hf:` source | — |
| `audio` | — | `asr`, `diarization` (`hf:` sources) |
| `embed`, `tts` | the `hf:` source | — |

A part a worker does not read is refused, like an unknown key. The OCR child
is chosen by the engine: `transformers-4.57` runs Unlimited-OCR's pipeline,
`transformers` runs GLM-OCR behind its layout model — so an OCR instance of
your own is another checkpoint of one of the two.

The environment variables that located these snapshots before instance
files existed still work, and outrank the file: `GIQ_OCR_MODEL_DIR`,
`GIQ_GLM_OCR_MODEL_DIR` and `GIQ_GLM_LAYOUT_DIR` replace the paths of the
built-in `unlimited-ocr` and `glm-ocr` (and only theirs — an OCR instance
under another name is not redirected), `GIQ_DEPTH_MODELS_DIR` and
`GIQ_MULTIVIEW_MODELS_DIR` replace the models directory for their worker's
relative paths, and `GIQ_AUDIO_WHISPER_MODEL`, `GIQ_AUDIO_DIAR_MODEL` and
`GIQ_EMBED_MODEL` replace what the audio and voiceprint children load.
`GET /storage` reports each model's resolved paths.

### Image models

An image model's files are its instance's `weights.parts`. The built-ins
expect them under the models directory, one subfolder per part —
`diffusion_models/`, `text_encoders/`, `vae/`, `loras/`. To keep them
elsewhere, override the instance with absolute paths:

```yaml
# ~/.config/giq/instances/zimage.yaml
name: zimage
worker: text2image
engine: sd.cpp
weights:
  parts:
    diffusion: /srv/image-models/diffusion_models/z_image_turbo_bf16.safetensors
    text_encoder: /srv/image-models/text_encoders/qwen_3_4b.safetensors
    vae: /srv/image-models/vae/ae.safetensors
vram:
  gb: 13.0
  measured: true
max_batch: 8
```

`flux_klein` is two instances (`text2image` and `image_edit`) over the same
files; override both.

**`image_models` in `config.yaml` is deprecated.** It is still read: an
entry replaces the instance's files, and — where it sets them — its `engine`
and `vram_gb` are laid over the instance's (a config figure counts as
unmeasured). giq logs a warning once per model naming the built-in file to
copy and the `weights.parts` to put in it. The old engine spelling `sdcpp`
is read as `sd.cpp`, with a warning.

**Validation is strict.** An unknown key, a key given twice, a parameter the
engine does not have, a worker paired with an engine that cannot serve it,
and a setting giq does not honour yet (`profile` on an engine without
profiles, `residency.gpu`, `residency.default_policy: off`) are all errors, never silently ignored. A
file of yours that fails is logged as an error and left out — the built-in of
that name, if there is one, keeps serving — and two of your files defining
the same instance are both left out, since which one won would be an accident
of sorting. Instance files are read at startup; restart giq after changing
them. `GET /storage` lists the files that were left out with the reason
(its `instances` block), and the dashboard's Models view shows them as a
warning above the catalog.

## Residency

Every model has a residency policy, set per model in the dashboard's Models
view or with `POST /control/models/{worker}/{model}` (`{"policy": …}`):

- `pinned` (**keep warm**) — kept loaded whenever VRAM allows, reloaded after
  an eviction and on boot.
- `auto` (**on demand**, the default) — loads when a job arrives, is evictable,
  and unloads after two idle minutes.
- `off` — refuses jobs and cannot load by any path.

Overrides persist in `stats.db` and outrank `config.yaml`'s `residents:`, which
outranks the instances' `residency.priority` (among the built-ins:
`gemma-4-12b`, `whisper-large-v3`, `ecapa-tdnn`).
Before a load, giq gates on the model's declared VRAM figure (measured on
real hardware where the catalog says so) plus a margin against the card's
free VRAM, and evicts keep-warm models on that card when that is what it
takes.

## Multiple GPUs

Models that name no card run on the **default** card — the biggest one unless
you say otherwise, by index or NVML UUID:

```yaml
gpu:
  device: GPU-d0fda82c-452e-bbf7-561b-07d3a056ecfd   # or "1", or GIQ_GPU_DEVICE
```

**Bind a model to a card** and it is gated against that card's VRAM, loads
there, gets that card's server port, and can only ever evict residents that
share it — so a render on one card cannot cost you the LLM on the other:

```bash
curl -X POST localhost:8084/control/models/text2image/flux_klein/device \
  -H 'content-type: application/json' -d '{"device": "1"}'

curl -X POST localhost:8084/control/models/text2image/flux_klein/device \
  -H 'content-type: application/json' -d '{"device": null}'   # unbind
```

Bindings take an index or a UUID and are stored as the UUID; they persist in
`stats.db`, survive restarts and re-enumeration, and are independent of
residency (pinning does not bind, unbinding does not unpin). The dashboard
does the same thing visually: each GPU card lists what is loaded on it, the
residency budget is drawn per card, and the model catalog's GPU column binds
a model with one click. A checked-in default
lives under `gpu.bind` in `config.yaml`, and `gpu.reserve` leaves headroom on
a card shared with a desktop.

Every VRAM figure in the API describes one card: `/status.gpu` names the
default, each model's `device_name` in `/stats/models` names its own, and
`/gpus` has the per-card breakdown of the machine.

Used VRAM is reported split two ways — `vram_giq_gb` (models giq is holding,
with a per-process `giq[]` breakdown) and `vram_other_gb` (the desktop, other
CUDA apps, a game). Only the first is something giq can free by unloading, so
a full card and a full card *giq caused* are shown as different things. The
dashboard draws it as a two-segment gauge: ours solid, theirs hatched.

Workers are spawned with `CUDA_VISIBLE_DEVICES` set to their card. This matters
most for llama.cpp, whose default `-sm layer` otherwise spreads a model's
layers *and KV cache* across every visible GPU — half your LLM ends up on a
card giq is not scheduling against.

**Not implemented yet:** two *batch* jobs running at once on different cards.
Each card holds its own loaded worker, but job dispatch is still serialized,
so a render on one card and a batch on the other take turns. Resident models
(the pinned set) serve concurrently throughout, as they always have.

## Systemd service

For a server — a dedicated user, hardening, `GIQ_HOME` — use
`deploy/giq.service` and [deployment.md](deployment.md). On a desktop or
development checkout, a user unit is enough:

```bash
# Install service
make install-service

# Control
systemctl --user start giq
systemctl --user status giq
systemctl --user stop giq

# View logs
journalctl --user -u giq -f
```

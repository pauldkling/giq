<!--
SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)

SPDX-License-Identifier: Apache-2.0
-->

# API

giq listens on `http://localhost:8084` by default. Everything goes through
one job queue: the job API below, the OpenAI-compatible routes under `/v1`,
and the convenience endpoints for OCR, depth and multiview all submit jobs to
it. Access rules (Host/Origin checks, the optional token) are described in
[access-and-privacy.md](access-and-privacy.md).

## Submit a job

```bash
# LLM inference
curl -X POST http://localhost:8084/run \
  -H "Content-Type: application/json" \
  -d '{
    "worker": "llm",
    "model": "gemma-3-27b-it-qat",
    "tasks": [{"id": "1", "messages": [{"role": "user", "content": "Hello!"}]}]
  }'

# Image generation
curl -X POST http://localhost:8084/run \
  -H "Content-Type: application/json" \
  -d '{
    "worker": "text2image",
    "model": "zimage",
    "tasks": [{"id": "1", "prompt": "A sunset over mountains"}]
  }'
```

`/run` returns `{job_id, position}`. With `?wait=true` it blocks until the
job is done and returns the finished job instead.

## Check job status

```bash
curl http://localhost:8084/jobs/{job_id}
```

`DELETE /jobs/{job_id}` cancels a job that is still pending.

## Service status

```bash
curl http://localhost:8084/status
```

## Pause serving / free the GPU

Unloads every model — residents included — and hands the card back. While
paused, job submission returns `503` with `Retry-After` so clients back off
instead of blocking; nothing queues up behind the pause. Also a button in the
dashboard header.

```bash
# graceful: waits up to 60s for in-flight jobs and live chat sessions
curl -X POST http://localhost:8084/control/pause -d '{"reason":"gaming"}' \
  -H 'content-type: application/json'

# need the VRAM right now — kills in-flight work
curl -X POST http://localhost:8084/control/pause -d '{"force":true}' \
  -H 'content-type: application/json'

curl -X POST http://localhost:8084/control/resume   # residents reload in ~15s
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/run` | POST | Submit a job (`?wait=true` blocks until it finishes) |
| `/jobs/{id}` | GET | Get job status and results |
| `/jobs/{id}` | DELETE | Cancel a pending job |
| `/status` | GET | Active worker, VRAM per card (`gpus`; the `vram_*` scalars are the default card's), queue depth, pause state, access posture |
| `/gpus` | GET | Per-card telemetry; `selected` marks the default card |
| `/engines` | GET | Declared inference engines and the build each one reports |
| `/capabilities` | GET | Available workers and models |
| `/control/models` | GET | Residency policy and GPU binding of every model |
| `/control/models/{worker}/{model}` | POST | Set a model's residency policy (`pinned`, `auto`, `off`) |
| `/control/models/{worker}/{model}/device` | POST | Bind a model to a GPU (or unbind) |
| `/control/pause` | POST | Stop serving, unload everything, free VRAM |
| `/control/resume` | POST | Resume serving; residents reload |
| `/stats/models` | GET | The model catalog: VRAM needs, fit per card, policy, binding |
| `/stats/summary`, `/stats/timeline`, `/stats/usage`, `/stats/jobs` | GET | Job history (see [Privacy](access-and-privacy.md#privacy) for what is recorded) |
| `/stats/gpus`, `/stats/vram`, `/stats/gpus/eras` | GET | GPU telemetry history and per-card job totals |
| `/storage` | GET | Model weights on disk, per-mount usage, the resolved directories and the operator's instance files — see [Storage](#storage) |
| `/storage/models/{worker}/{model}` | DELETE | Delete a model's weights |
| `/v1/chat/completions` | POST | OpenAI-compatible chat, streaming and tool calls included |
| `/v1/responses` | POST | OpenAI Responses API, streaming and tool calls included — see [Responses API](#responses-api) |
| `/v1/models` | GET | The chat models whose weights are on disk |
| `/v1/audio/transcriptions` | POST | Speech to text with speaker diarization (faster-whisper + pyannote; `?diarize=false` skips it) |
| `/v1/audio/speech` | POST | Text to speech (Kokoro) |
| `/v1/audio/embeddings` | POST | Speaker voiceprint (ECAPA-TDNN) of an audio clip |
| `/dash` | GET | Dashboard (control surface, usage, models, sandbox; English/German; light/dark/system theme) |
| `/ocr` | POST | One PDF (multipart `file`) in, one HTML document out — see [OCR](#ocr) |
| `/depth` | POST | One image in, one 16-bit depth map out — see [Depth](#depth) |
| `/multiview` | POST | N images of one scene in; per-view depth, poses, intrinsics, optional GLB — see [Multiview](#multiview) |

## Workers

### LLM (`llm`)
- Models: the models declared by `llm` instance files (`giq/instances/llm.*.yaml`
  and your own, see [Instances](configuration.md#instances)) — GGUFs via
  llama.cpp, Hugging Face checkpoints via vllm; `/capabilities` lists them
- Task: `{id, messages[], temperature?, max_tokens?}`
- Result: `{id, text}`

A non-streaming request waits for its model to start and then for its answer:
the model's start budget (its instance's `ready_timeout`, or the engine's
default — minutes for vllm) plus the job's time limit. A cold model therefore
answers late rather than with a 504. Streaming requests send keepalives while
the model loads.

#### Responses API

`/v1/responses` speaks the OpenAI Responses interface — `input` plus
`instructions` in, a `response` object out, or the typed `response.*` SSE
event stream when `stream: true`. giq's engines speak Chat Completions, so this
is a translation rather than a proxy: `input` (a string or a list of
`message` / `function_call` / `function_call_output` items) and `instructions`
fold into a chat message list, `max_output_tokens` maps to `max_tokens`,
`tools` are renested, and `text.format` carries a JSON schema through to the
engine. Tool calls, reasoning and images work as they do on
`/v1/chat/completions`. A `developer` message joins the system prompt, which
is what the chat templates behind giq call it.

Thinking is controlled as on the chat path: `chat_template_kwargs` passes
through, and `reasoning.effort: "none"` or `"minimal"` turns thinking off
(the engines switch thinking rather than grade it, so the other levels leave
the model's default). The top-level `reasoning_budget_tokens` caps the
thought. The model's thinking comes back as a `reasoning` item whose
`content` holds the raw thought as `reasoning_text` — streamed as
`response.reasoning_text.delta` — rather than as a `summary`, which giq has
none of.

giq keeps no server-side conversation store, so `previous_response_id` and
stored responses are unavailable. A request that sets `previous_response_id`
or `store: true` is refused with 400; omitted `store` and `store: false` run
statelessly. Resend the prior turns in `input` to continue a conversation.
For the same reason there is no file store: an `input_image` that names a
`file_id`, or an `input_file` of any kind, is refused with 400 rather than
dropped — send the image inline as an `image_url` data URI. Only your own
function tools run: the tools OpenAI hosts (web search, file search, code
interpreter, MCP, image generation, computer use) are refused with 400 instead
of being accepted and never used. `tool_choice` takes the modes, a forced
function, or `allowed_tools` over those functions.

Responses streams end with their typed `response.completed`,
`response.incomplete`, or `response.failed` event, without the Chat Completions
`[DONE]` sentinel. A generation stopped by `max_output_tokens` returns
`status: incomplete` and `incomplete_details.reason: max_output_tokens`. A
generation cut short — the client stopped reading, or the job was cancelled —
ends as `response.failed` with error code `giq_stream_cancelled`, carrying
whatever was produced as incomplete items; a job that failed before or during
generation ends as `response.failed` with `giq_job_failed`.

### Text2Image (`text2image`)
- Models: `flux_klein` (FLUX.2 klein 4B, sd.cpp), `zimage` (Z-Image-Turbo,
  sd.cpp)
- Task: `{id, prompt, negative_prompt?, seed?}`
- Result: `{id, image_b64, seed}`

### Image Edit (`image_edit`)
- Models: `flux_klein` (reference edits via sd.cpp)
- Task: `{id, reference_image_b64, instruction, negative_prompt?}`
- Result: `{id, image_b64, seed}`

### OCR (`ocr`)
- Models: `unlimited-ocr` (baidu, 3B, one pass over many pages),
  `glm-ocr` (zai-org 0.9B behind PP-DocLayoutV3: layout, then each region
  read with the prompt for its kind — the stronger choice for tables)
- Task: `{id, pdf_b64 | images_b64[], dpi?, pages?, raw?, strip?, merge?}`
- Result: `{id, html, pages, blocks[], raw?, tokens_in, tokens_out, truncated}`

### Depth (`depth`)
- Models: `depth-anything-v2-small` (Apache-2.0, the default; Base and Large
  are CC-BY-NC-4.0 and not registered)
- Task: `{id, image_b64, visualize?}`
- Result: `{id, depth_b64, width, height, depth_min, depth_max, metric, visualization_b64?}`

### Multiview (`multiview`)
- Models: `da3-base` (Apache-2.0, the default) — Depth Anything 3, on its
  own interpreter (`envs/da3`, engine `da3`)
- Task: `{id, images_b64[], extrinsics?, intrinsics?, process_res?, use_ray_pose?,
  ref_view_strategy?, glb?, conf_percentile?, max_points?}`
- Result: `{id, views[{index, width, height, depth_b64, depth_min, depth_max,
  conf_b64, conf_min, conf_max, extrinsics, intrinsics}], metric, process_res, glb_b64?}`

### Audio, voiceprints, speech

The resident audio stack (`audio/whisper-large-v3`: faster-whisper plus
pyannote diarization), speaker voiceprints (`embed/ecapa-tdnn`) and text to
speech (`tts/kokoro`) are reached through the `/v1/audio/*` routes above.
Plain speech to text without diarization (`stt`, faster-whisper `tiny` …
`large-v3`) is a batch worker behind `/run`. `/capabilities` lists every
worker's models, and Kokoro's voices.

## OCR

PDF or page images in, a document out: layout-tagged text from
baidu/Unlimited-OCR, then page furniture (running headers, footers, page
numbers) dropped and a table or paragraph the page break cut in two
re-joined, rendered as an HTML fragment. Every element carries
`data-page` and `data-bbox` (0-999 page coordinates), tables pass through
as the model wrote them, everything else is escaped.

```bash
# the convenience form: the PDF is the body, options are query parameters
curl -s --data-binary @statement.pdf -H 'content-type: application/pdf' \
  'http://localhost:8084/ocr?model=glm-ocr&dpi=200' | jq -r .html
curl -s -F file=@statement.pdf 'http://localhost:8084/ocr?response_format=html'

# the generic form, for a consumer that already speaks /run
curl -X POST http://localhost:8084/run -H 'content-type: application/json' \
  -d '{"worker":"ocr","model":"unlimited-ocr",
       "tasks":[{"id":"1","pdf_b64":"...","dpi":200}]}'
```

Query parameters: `model` (`unlimited-ocr`, the default, or `glm-ocr`),
`dpi` (50-400, default 200), `pages` (`1-3,7`; default all), `strip=false` keeps the furniture, `merge=false` keeps page breaks,
`raw=true` adds the model's own tagged text, `response_format=html` returns
the fragment. Multipart is accepted for clients that only speak that; the
`file` part is the document and the filename is never read.

What is kept, and where. The document and its result live in memory only:
the upload is buffered in RAM (never spooled to `/tmp`, whatever its size),
the child rasterizes one pass of pages at a time and writes nothing, and the
finished job leaves the in-memory job store five minutes after completion.
The stats row records tokens in and out, timings and the GPU; the in-flight
log counts a PDF as one attachment; neither has a column a filename or a
line of text could go in. Two limits bound the RAM: `GIQ_OCR_MAX_UPLOAD_MB`
(default 64, the most a base64 task can be and still fit the parent→child
pipe; over it is a 413) and `GIQ_OCR_MAX_PAGES` (default 200, refused before
rendering). Both models run from local snapshots pinned to reviewed
revisions with the Hugging Face hub disabled in the child process
(Unlimited-OCR on its own transformers 4.57 interpreter, `envs/unlimited-ocr`,
because its remote code does not run on the transformers 5 the rest of giq
uses; `make sync` builds both); neither
engine touches the network (verified with strace), and zai-org's own
`glmocr` SDK is not used because it defaults to forwarding documents to
Zhipu's cloud API. Unlimited-OCR: ~80 tokens/s, a dozen pages in one pass,
longer documents in consecutive passes. GLM-OCR: ~100 tokens/s, a four-page
invoice in 16 s including layout, 3.2 GB peak (on an RTX 5090).

## Depth

One RGB image in, one depth map out at the image's own resolution, through
Depth Anything V2 (DINOv2 encoder, DPT head; native transformers, local
snapshots, hub disabled in the child).

```bash
curl -s -H 'Content-Type: image/jpeg' --data-binary @photo.jpg \
  'http://localhost:8084/depth' | jq '{width, height, depth_min, depth_max}'
curl -s -F file=@photo.jpg 'http://localhost:8084/depth?response_format=png' > depth16.png
curl -s -F file=@photo.jpg 'http://localhost:8084/depth?response_format=visualization' > depth.png
# or through the job API, several images per job:
curl -s -X POST localhost:8084/run?wait=true -H 'Content-Type: application/json' \
  -d '{"worker":"depth","model":"depth-anything-v2-small",
       "tasks":[{"id":"1","image_b64":"...","visualize":true}]}'
```

Query parameters: `model` (`depth-anything-v2-small`, the default and only
registered one), `visualize` (add a colour-mapped PNG, near red,
far blue), `response_format` (`json`, `png` for the 16-bit map itself,
`visualization` for the coloured one). PNG, JPEG and WebP in, as the body or
a multipart `file`; anything else is a 400 before it costs a job, and the
upload cap is the same `GIQ_OCR_MAX_UPLOAD_MB`.

What the map means: the model predicts **relative inverse depth** — larger
is nearer, no unit, an unknown scale and shift per image. The 16-bit PNG
spans `depth_min..depth_max` of that prediction linearly, so the model's own
values are `depth_min + png / 65535 * (depth_max - depth_min)`; `metric` is
false. That is what a ControlNet, a parallax effect or a relighting pass
wants; anything that needs metres wants a metric checkpoint (Depth Anything
V2 has indoor/outdoor ones; not registered yet).

Why not Marigold V2: it is a LoRA on
Qwen-Image-Edit-2509, a 20B diffusion transformer — 17 GB of VRAM at 1024²,
~40 GiB of weights, and a diffusers/bitsandbytes/peft stack giq does not
carry. It is sharper on hair and foliage edges and the paper puts it ahead of
Depth Anything V2 on the benchmarks (3.6 vs 4.5% AbsRel on NYUv2), but it
would evict the residents on every call where this one loads in 3 s and
sits beside them. Small: 1.2 GB peak, measured on an RTX 5090 with a
1280x2276 photo; it answers in under a second including the PNG encode.
Licences are part of the choice: only Small is Apache-2.0, so Base and Large
(CC-BY-NC-4.0, non-commercial) are not registered.

## Multiview

N images of one scene in; a depth map, a camera pose and intrinsics per
view out, all in one shared frame, through Depth Anything 3 (ByteDance-Seed,
arXiv 2511.10647): one transformer over every view's tokens at once, with or
without known poses. This is what a scan from many angles needs and what the
single-image `depth` worker cannot give, since its maps have an unknown
scale and shift per frame.

```bash
curl -s -F files=@v1.jpg -F files=@v2.jpg -F files=@v3.jpg \
  'http://localhost:8084/multiview' | jq '.views[] | {index, width, height, extrinsics}'
curl -s -F files=@v1.jpg -F files=@v2.jpg 'http://localhost:8084/multiview?response_format=glb' > scene.glb
# or through the job API, which also takes known poses:
curl -s -X POST localhost:8084/run?wait=true -H 'Content-Type: application/json' \
  -d '{"worker":"multiview","model":"da3-base",
       "tasks":[{"id":"1","images_b64":["..."],"glb":true}]}'
```

Query parameters: `model` (`da3-base`, the default and only registered one),
`process_res` (long side the views are resized to, 252-1008, default 504),
`use_ray_pose` (slower, more accurate poses), `glb` (add the model's own
fused, confidence-filtered point cloud with camera wireframes),
`response_format` (`json` or `glb`). Images go as repeated multipart
`files` parts, in any order; the model picks its own reference view.

What comes back per view: a 16-bit PNG of **depth along the ray** (real
depth, not inverse) at the model's working resolution, spanning
`depth_min..depth_max`; a confidence map the same way; the 3x4
world-to-camera matrix in OpenCV convention; and the 3x3 intrinsics for
that resolution. The scale is arbitrary but shared, so the views unproject
into one cloud; pass `extrinsics` and `intrinsics` through `/run` and the
prediction is aligned to them instead. `metric` is false (the metric
checkpoints are not registered).

Limits: 32 views and 41472 patch tokens per request (32 square views at
504 px, or fewer at a higher `process_res`); over either is a refusal
before the model runs. Measured on an RTX 5090: Base 1 GB idle, 4.4 GB peak
for 32 landscape views at 504 px, 6.6 GB at the token cap. Declared 7 GB.

Runtime: the package is not on PyPI, pins numpy below 2, and declares a
research toolkit (open3d, pycolmap, evo, e3nn, moviepy) as hard
dependencies, so it runs on its own interpreter, `envs/da3` (a uv project
on the same torch line; `make sync` builds it), declared as engine `da3`.
The Giant models need xformers and are not registered. Licences: Base is
Apache-2.0. Large-1.1 is not registered: its model card says Apache-2.0
while the repository README lists Large as CC BY-NC 4.0, and a licence that
unclear is not one giq offers for commercial use.

## Storage

`GET /storage` answers what is on disk and where giq looks:

- `models` — per model: its resolved `paths` (files, snapshot directories,
  or HF-cache directories for models loaded by repository), `size_bytes`,
  `on_disk` (every path present), `shared_with` (other models using the
  same files), `resident`, `last_used`.
- `disks` — per mount: total, free, and how much of it is model weights.
- `paths` — every data directory giq resolved (config, models, instances,
  engines, state, caches).
- `instances` — the operator's [instance files](configuration.md#instances):

```json
"instances": {
  "dir": "/home/me/.config/giq/instances",
  "builtin_dir": "/opt/giq/src/giq/instances",
  "files": [
    {"file": "/home/me/.config/giq/instances/gemma.yaml", "worker": "llm",
     "name": "gemma-4-12b", "replaces_builtin": true}
  ],
  "overrides": ["llm/gemma-4-12b"],
  "errors": [
    {"file": "/home/me/.config/giq/instances/broken.yaml",
     "message": "params.ctx: Extra inputs are not permitted"}
  ]
}
```

`files` are the operator files serving; `overrides` the built-ins they
replace; `errors` the files left out, each with giq's reason (`file` is
`null` when the problem is not one file's, such as two files defining one
instance). A file in `errors` is not served — a built-in of that name keeps
serving — until it is fixed and giq restarted.

## Vision

Models whose instance declares the `vision` capability accept images alongside text, via
llama.cpp's `--mmproj` projector. Send OpenAI-style content parts to
`/v1/chat/completions`:

```json
{"model": "...", "messages": [{"role": "user", "content": [
  {"type": "text", "text": "What is in this image?"},
  {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}]}
```

Requests carrying images are forwarded to llama-server intact. Aiming one at a
model without vision returns 400 rather than silently dropping the image. The
dashboard's sandbox has an **image + question** panel for it.

## Structured output

`/v1/chat/completions` forwards two constrained-decoding controls to the
engine, and takes one of them per request:

- `response_format` — the OpenAI spelling, `{"type": "json_object"}` or
  `{"type": "json_schema", "json_schema": {...}}`. Honoured by llama.cpp
  (GBNF) and vllm alike, and the portable choice. On `/v1/responses` the same
  thing arrives as `text.format`.
- `structured_outputs` — vllm's native knob (`json`, `regex`, `choice`,
  `grammar`), enforced at decode time. llama-server ignores it.

Sending both in one request is refused with 400: vllm folds `response_format`
into its own constraint set and then rejects the merged pair as mutually
exclusive, so the conflict is reported at the API edge instead of surfacing as
an opaque engine error.

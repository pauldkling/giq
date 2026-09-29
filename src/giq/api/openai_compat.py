# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

# OpenAI-compatible API router - consolidated
import asyncio
import base64
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from giq.api.dependencies import get_audio_cache, get_orchestrator
from giq.models import JobRequest
from giq.queue import Job
from giq.registry import ModelSpec, all_specs, get_spec
from giq.services.audio_cache import AudioCache
from giq.services.orchestration import Orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class ChatMessage(BaseModel):
    """OpenAI chat message format."""

    model_config = ConfigDict(extra="ignore")
    role: str
    content: str | list | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    name: str | None = None


def has_non_text_parts(content: str | list | None) -> bool:
    """True when a message carries something other than text — an image, say.

    `extract_text_content` keeps type == "text" blocks and drops the rest, so
    before this check an image_url part was discarded in silence and the model
    answered about nothing at all.
    """
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict) and block.get("type") not in (None, "text") for block in content
    )


def is_multimodal(messages: list) -> bool:
    return any(has_non_text_parts(m.content) for m in messages)


def format_messages(messages: list) -> list[dict]:
    """The message list as llama-server wants it, kept whole.

    The alternative — flattening to one {system, user} pair — loses the
    conversation, the tool results and any image parts, so every path that can
    afford to keep the list uses this.
    """
    formatted: list[dict] = []
    for m in messages:
        msg: dict = {"role": m.role}
        content_text = extract_text_content(m.content)
        if m.role == "assistant" and m.tool_calls:
            msg["content"] = content_text or None
            msg["tool_calls"] = m.tool_calls
        elif m.role == "tool":
            msg["content"] = content_text
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
        else:
            # Verbatim when it carries images: llama-server speaks the
            # OpenAI content-part shape natively once --mmproj is loaded.
            msg["content"] = m.content if has_non_text_parts(m.content) else content_text
        formatted.append(msg)
    return formatted


# How long the relay waits with nothing to send before emitting an SSE comment.
# A queued job or a cold model load produces no tokens for tens of seconds, and
# browsers and reverse proxies drop a connection that goes quiet. The comment
# is protocol-legal filler that every SSE client ignores.
SSE_KEEPALIVE_SECONDS = 10.0


async def _relay_stream(orch: Orchestrator, job_id: str, stream, model: str):
    """Turn a running job's chunks into an SSE response body.

    The job is an ordinary queued job — it waited its turn, it may have
    triggered an eviction, it is counted in the stats. This only changes when
    the caller sees the output: as it is produced, rather than at the end.
    """
    from giq.models import JobStatus

    try:
        while True:
            try:
                chunk = await asyncio.wait_for(stream.queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if chunk is None:
                break
            yield f"data: {json.dumps(chunk)}\n\n"

        # The sentinel says the job ended, not that it succeeded. A failure
        # after headers are sent cannot become an HTTP status, so it has to
        # ride the stream or the client would see a clean, silent truncation.
        job = await orch.queue.get(job_id)
        if job is not None and job.status == JobStatus.failed:
            error = {"error": {"message": job.error or "Job failed", "type": "giq_job_failed"}}
            yield f"data: {json.dumps(error)}\n\n"

        yield "data: [DONE]\n\n"
    finally:
        # Client gone, or we are done: either way stop generating. Draining
        # what is left unblocks a worker parked on a full buffer instead of
        # leaving it to time out.
        stream.cancel()
        while True:
            try:
                stream.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await orch.cancel_job(job_id)


def extract_text_content(content: str | list | None) -> str:
    """Extract text from message content (handles string or array of blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
        return "\n".join(texts)
    return str(content)


class ChatCompletionRequest(BaseModel):
    """OpenAI chat completion request format."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    model: str = Field(..., description="Model to use")
    messages: list[ChatMessage] = Field(..., description="Messages")
    # Unset means "as much as the model's context allows", which is what
    # OpenAI means by omitting it and what llama.cpp does with no n_predict.
    # It used to default to 2048 — a ceiling on thinking *and* answer, so on a
    # reasoning model the thought ate the budget and the answer came back
    # empty with finish_reason "length". 2048 was 1.5% of qwen3.8-27b's 131k
    # context. A caller that wants a smaller ceiling still says so.
    #
    # `max_completion_tokens` is the current OpenAI spelling (`max_tokens` is
    # deprecated) and is what LibreChat and the modern SDKs send. With
    # extra="ignore" it was being dropped in silence and the 2048 applied
    # anyway, so a client asking for a big budget got a small one.
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("max_tokens", "max_completion_tokens"),
        description="Max tokens to generate; unset = up to the model's context",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    stream: bool = Field(default=False, description="Stream response")
    tools: list[dict] | None = Field(default=None, description="Tool definitions")
    tool_choice: str | dict | None = Field(default=None, description="Tool choice mode")


class TTSRequest(BaseModel):
    """OpenAI TTS request format."""

    model: str = "tts-1"
    input: str = Field(..., description="Text to synthesize")
    voice: str = Field(default="alloy", description="Voice to use")
    language: str | None = Field(default=None, description="Language")
    response_format: str = Field(default="wav", description="Audio format")
    speed: float = Field(default=1.0, ge=0.25, le=4.0)


class RenderResponse(BaseModel):
    """Response for audio render endpoint."""

    url: str
    file_id: str
    size_bytes: int
    expires_in: int


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    raw_request: Request, orch: Orchestrator = Depends(get_orchestrator)
) -> dict | StreamingResponse:
    """Generate chat completion (OpenAI-compatible endpoint)."""
    body = await raw_request.json()
    try:
        request = ChatCompletionRequest(**body)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    model = request.model
    messages = request.messages

    if "/" in model:
        model = model.split("/", 1)[1]

    # Tool-calling path — and the multimodal path, which needs the same thing
    # from it: the message list forwarded to llama-server intact. The plain
    # path below flattens every message into one {system, user} pair, which
    # can carry neither an image nor a conversation.
    multimodal = is_multimodal(messages)
    if multimodal:
        spec = get_spec("llm", model)
        if spec is None or not spec.vision:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{model} has no vision support, and the images in this request would "
                    "be dropped silently. Use a model whose catalog entry says vision."
                ),
            )
    # Streaming: one path for every kind of request, because it needs the same
    # thing the tool path needs — the message list intact — and because a
    # streamed answer is the only way a long one arrives at all. A nine-minute
    # thought exceeds the browser, proxy and job timeouts a single response has
    # to survive; chunks reset all three.
    if request.stream:
        stream_request: dict = {
            "messages": format_messages(messages),
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if request.max_tokens is not None:
            stream_request["max_tokens"] = request.max_tokens
        if request.tools:
            stream_request["tools"] = request.tools
            if request.tool_choice is not None:
                stream_request["tool_choice"] = request.tool_choice
        ctk = body.get("chat_template_kwargs")
        if ctk:
            stream_request["chat_template_kwargs"] = ctk
        # Deadline on the *thought*, separate from max_tokens' ceiling on the
        # whole response; llama.cpp closes the thinking block when it is spent
        # rather than truncating, so the answer is written from the reasoning
        # already done. MODEL_REQUEST_DEFAULTS carries a per-model default and
        # this overrides it for one request — which is the point: an agent loop
        # wants a short leash per tool call, and the same client wants none on
        # a hard question. `thinking_budget_tokens` is llama.cpp's own alias.
        for key in ("reasoning_budget_tokens", "thinking_budget_tokens"):
            if isinstance(body.get(key), int):
                stream_request["reasoning_budget_tokens"] = body[key]
                break
        # The loop guard is on by default; a caller that wants the whole thought
        # however long it circles says so here. The worker pops it — it is
        # giq's field, not llama-server's.
        if isinstance(body.get("giq_loop_guard"), bool):
            stream_request["giq_loop_guard"] = body["giq_loop_guard"]

        job_id, _, stream = await orch.submit_streaming_job(
            JobRequest(worker="llm", model=model, chat_request=stream_request)
        )
        return StreamingResponse(
            _relay_stream(orch, job_id, stream, model),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # nginx buffers proxied responses by default, which would hold
                # every chunk until the answer finished and undo the point.
                "X-Accel-Buffering": "no",
            },
        )

    if request.tools or multimodal:
        formatted_messages = format_messages(messages)

        llm_request: dict = {
            "messages": formatted_messages,
            "tools": request.tools,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if request.max_tokens is not None:
            llm_request["max_tokens"] = request.max_tokens
        if request.tool_choice is not None:
            llm_request["tool_choice"] = request.tool_choice
        # Parity with the streaming branch above. These were honoured when
        # streaming and silently dropped when not, which is the worst shape for
        # a knob to have: a client that turns thinking off gets it turned off
        # or not depending on a flag it set for an unrelated reason.
        ctk = body.get("chat_template_kwargs")
        if ctk:
            llm_request["chat_template_kwargs"] = ctk
        for key in ("reasoning_budget_tokens", "thinking_budget_tokens"):
            if isinstance(body.get(key), int):
                llm_request["reasoning_budget_tokens"] = body[key]
                break
        # giq_loop_guard is deliberately NOT forwarded here. It is giq's own
        # field, popped by the worker's streaming loop; the non-streaming
        # worker forwards its request body to llama-server verbatim, so an
        # unknown key would reach llama-server instead of being consumed.

        job_id, _ = await orch.submit_job(
            JobRequest(worker="llm", model=model, chat_request=llm_request)
        )
        completed_job = await orch.wait_for_job(job_id)

        if not completed_job.results:
            raise HTTPException(status_code=500, detail="No response generated")

        result = completed_job.results[0]

        return result

    # Non-tool path
    system_msg = None
    user_msg = ""
    for msg in messages:
        if msg.role == "system":
            system_msg = extract_text_content(msg.content)
        elif msg.role == "user":
            user_msg = extract_text_content(msg.content)

    if not user_msg:
        raise HTTPException(status_code=400, detail="No user message found")

    params: dict = {
        "temperature": request.temperature,
        "top_p": request.top_p,
    }
    if request.max_tokens is not None:
        params["max_tokens"] = request.max_tokens
    # Pass the thinking-channel override through: clients send
    # chat_template_kwargs.enable_thinking=false so one-shot answers don't
    # burn the token budget on reasoning.
    ctk = body.get("chat_template_kwargs")
    if ctk:
        params["chat_template_kwargs"] = ctk

    job_id, _ = await orch.submit_job(
        JobRequest(
            worker="llm",
            model=model,
            tasks=[{"id": "chat-0", "system": system_msg, "user": user_msg}],
            params=params,
        )
    )

    completed_job = await orch.wait_for_job(job_id)
    if not completed_job.results:
        raise HTTPException(status_code=500, detail="No response generated")

    result = completed_job.results[0]
    output = result.get(
        "output", result.get("choices", [{}])[0].get("message", {}).get("content", "")
    )
    tokens_in = result.get("tokens_in") or 0
    tokens_out = result.get("tokens_out") or 0

    return {
        "id": f"chatcmpl-{job_id}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "total_tokens": tokens_in + tokens_out,
        },
    }


def _advertised_llm_specs() -> list[ModelSpec]:
    """The LLM models an OpenAI client should be offered, in display order.

    Installed is the only filter: if the weights are on disk, the model is
    offered. No audit gate, no staging step, no opinion about how good or how
    aligned a model is — this is a homelab, and a model that is here is a
    model you can pick. The one thing it will not do is advertise a model
    whose GGUF is missing, which is not curation but honesty: five registered
    models had had their weights deleted and were being offered anyway.

    Residents first in reload-priority order, then everything else by name,
    so a client that treats `data[0]` as its default gets the model already
    loaded rather than one that forces an eviction.

    Chat clients get chat models: `/capabilities` enumerates every modality.
    """
    from giq.workers.llm import weights_installed

    specs = [spec for spec in all_specs() if spec.worker == "llm" and weights_installed(spec.model)]
    return sorted(
        specs,
        key=lambda s: (
            (1, 0, s.model) if s.resident_priority is None else (0, s.resident_priority, "")
        ),
    )


@router.get("/models")
async def list_models() -> dict:
    """List available models (OpenAI-compatible endpoint).

    Generated from the registry, for the same reason `/capabilities` is: a
    hand-written list drifts. With a literal here, a model could be
    registered and servable while every OpenAI client was told it did not
    exist, because adding a model meant remembering to edit this list too.
    """
    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {"id": spec.model, "object": "model", "created": now, "owned_by": "giq"}
            for spec in _advertised_llm_specs()
        ],
    }


async def _run_tts_job(orch: Orchestrator, request: "TTSRequest", timeout: float) -> bytes:
    """Submit a TTS job, wait for it, and return decoded audio bytes."""
    if not request.input.strip():
        raise HTTPException(status_code=400, detail="Input text is required")

    tts_model = "kokoro"  # the one TTS model; qwen-tts was tried, judged poor, and removed
    job_id, _ = await orch.submit_job(
        JobRequest(
            worker="tts",
            model=tts_model,
            tasks=[
                {
                    "id": "tts-0",
                    "text": request.input,
                    "voice": request.voice,
                    "language": request.language,
                }
            ],
        )
    )
    logger.info(f"TTS job {job_id}: {len(request.input)} chars, voice={request.voice}")
    completed_job = await orch.wait_for_job(job_id, timeout=timeout)

    if not completed_job.results:
        raise HTTPException(status_code=500, detail="No audio generated")

    result = completed_job.results[0]
    if isinstance(result, dict):
        audio_b64 = result.get("output", "")
        error = result.get("error")
    else:
        audio_b64 = result.output
        error = result.error

    if error:
        raise HTTPException(status_code=500, detail=f"TTS failed: {error}")
    if not audio_b64:
        raise HTTPException(status_code=500, detail="No audio generated")
    return base64.b64decode(audio_b64)


@router.post("/audio/speech")
async def create_speech(
    request: TTSRequest, orch: Orchestrator = Depends(get_orchestrator)
) -> Response:
    """Generate speech from text (OpenAI-compatible endpoint)."""
    audio_bytes = await _run_tts_job(orch, request, timeout=60.0)
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="speech.wav"'},
    )


@router.get("/audio/speech")
async def create_speech_get(
    text: str = Query(..., description="Text to synthesize"),
    voice: str = Query(default="alloy"),
    model: str = Query(default="kokoro", description="TTS model (kokoro)"),
    language: str = Query(default=None),
    orch: Orchestrator = Depends(get_orchestrator),
) -> Response:
    """Generate speech via GET (for ESP32 streaming)."""
    request = TTSRequest(input=text, voice=voice, model=model, language=language)
    return await create_speech(request, orch=orch)


@router.post("/audio/render", response_model=RenderResponse)
async def render_speech(
    request: TTSRequest,
    ttl: int = Query(default=300, ge=60, le=3600, description="Cache TTL in seconds"),
    orch: Orchestrator = Depends(get_orchestrator),
    cache: AudioCache = Depends(get_audio_cache),
) -> RenderResponse:
    """Pre-render TTS and return a streaming URL (for long narrations)."""
    await cache.cleanup()
    # Scale timeout with text length: ~50 chars/sec floor.
    timeout = max(60.0, len(request.input) / 50)
    audio_bytes = await _run_tts_job(orch, request, timeout=timeout)

    file_id = str(uuid.uuid4())[:8]
    cache.set(file_id, audio_bytes, expires_in=ttl)
    logger.info(f"Audio cache: stored {file_id} ({len(audio_bytes)} bytes, expires in {ttl}s)")
    return RenderResponse(
        url=f"/v1/audio/files/{file_id}.wav",
        file_id=file_id,
        size_bytes=len(audio_bytes),
        expires_in=ttl,
    )


@router.get("/audio/files/{file_id}.wav")
async def get_audio_file(file_id: str, cache: AudioCache = Depends(get_audio_cache)) -> Response:
    """Stream pre-rendered audio file (used by ESP32 for long narrations)."""
    info = cache.get(file_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    logger.info(f"Audio cache: serving {file_id} ({len(info['data'])} bytes)")
    return Response(
        content=info["data"],
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'attachment; filename="{file_id}.wav"',
            "Cache-Control": "no-cache",
        },
    )


@router.delete("/audio/files/{file_id}")
async def delete_audio_file(file_id: str, cache: AudioCache = Depends(get_audio_cache)) -> dict:
    """Delete pre-rendered audio file (optional cleanup)."""
    if file_id not in cache:
        raise HTTPException(status_code=404, detail="Audio not found")
    cache.delete(file_id)
    return {"status": "deleted", "file_id": file_id}


# Transcription/embedding jobs can queue behind a multi-minute image batch;
# the sync wait must absorb queue time + model runtime. Stay under 900s, a
# common client-side budget for batch transcription. Live callers time out client-side much
# earlier; their disconnect cancels the pending job (see _wait_cancelling).
AUDIO_WAIT_TIMEOUT_SECONDS = 880.0


async def _wait_cancelling(orch: Orchestrator, job_id: str) -> "Job":
    """wait_for_job, but client disconnect cancels a still-pending job.

    Live audio chunks arrive every ~5s; during an image batch each caller
    gives up in 30-60s. Without cancellation every abandoned chunk stays
    queued and gets pointlessly transcribed after the batch drains.
    """
    try:
        return await orch.wait_for_job(job_id, timeout=AUDIO_WAIT_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        await orch.cancel_job(job_id)
        raise


@router.post("/audio/transcriptions", response_model=None)
async def create_transcription(
    file: UploadFile = File(...),  # noqa: B008 (FastAPI dependency-injection idiom)
    model: str = Form(default="whisper-1"),
    language: str = Form(default=None),
    response_format: str = Form(default="json"),
    diarize: bool = Query(default=True),
    orch: Orchestrator = Depends(get_orchestrator),
) -> Response | dict:
    """Transcribe (+diarize) audio.

    Runs on the resident audio worker (faster-whisper large-v3 + pyannote
    pyannote). response_format: json (default), verbose_json (per-segment
    language + words), text.
    """
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    audio_b64 = base64.b64encode(audio_bytes).decode()
    job_id, _ = await orch.submit_job(
        JobRequest(
            worker="audio",
            model="whisper-large-v3",
            tasks=[
                {
                    "id": "asr-0",
                    "audio_b64": audio_b64,
                    "language": language,
                    "diarize": diarize,
                }
            ],
        )
    )
    logger.info(f"audio job {job_id}: {len(audio_bytes)} bytes (diarize={diarize})")
    completed_job = await _wait_cancelling(orch, job_id)

    if not completed_job.results:
        raise HTTPException(status_code=500, detail="No transcription generated")
    result = completed_job.results[0]
    if result.get("error"):
        raise HTTPException(status_code=500, detail=f"Transcription failed: {result['error']}")

    if response_format == "text":
        return PlainTextResponse(result.get("text", ""))
    if response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": result.get("language"),
            "duration": result.get("duration"),
            "text": result.get("text", ""),
            "speakers": result.get("speakers", []),
            "segments": [
                {
                    "start": s["start"],
                    "end": s["end"],
                    "text": s["text"],
                    "language": result.get("language"),
                    "speaker": s.get("speaker"),
                    "words": s.get("words", []),
                }
                for s in result.get("segments", [])
            ],
        }
    return {
        "text": result.get("text", ""),
        "language": result.get("language"),
        "duration": result.get("duration"),
        "speakers": result.get("speakers", []),
        "segments": [
            {
                "start": s["start"],
                "end": s["end"],
                "text": s["text"],
                "speaker": s.get("speaker"),
            }
            for s in result.get("segments", [])
        ],
    }


@router.post("/audio/embeddings")
async def create_audio_embedding(
    file: UploadFile = File(...),  # noqa: B008 (FastAPI dependency-injection idiom)
    model: str = Form(default="ecapa-tdnn"),
    orch: Orchestrator = Depends(get_orchestrator),
) -> dict:
    """Speaker voiceprint: clip → L2-normalized vector."""
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    audio_b64 = base64.b64encode(audio_bytes).decode()
    job_id, _ = await orch.submit_job(
        JobRequest(
            worker="embed",
            model="ecapa-tdnn",
            tasks=[{"id": "emb-0", "audio_b64": audio_b64}],
        )
    )
    completed_job = await _wait_cancelling(orch, job_id)

    if not completed_job.results:
        raise HTTPException(status_code=500, detail="No embedding generated")
    result = completed_job.results[0]
    if result.get("error"):
        # Undecodable clip is a client error: 400.
        raise HTTPException(status_code=400, detail=result["error"])
    return {
        "embedding": result["embedding"],
        "dim": result["dim"],
        "model": "ecapa-tdnn",
        "normalized": True,
    }

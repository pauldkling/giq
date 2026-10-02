# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI Responses API (`POST /v1/responses`), translated to chat.

giq's engines (llama-server, vllm) speak Chat Completions, not Responses, so
this endpoint is not a proxy: it translates the Responses request shape down to
the chat_request dict the LLM worker already consumes, submits it through the
same Orchestrator as every other job, and translates the result back up —
either as one `response` object (non-streaming) or as the typed `response.*`
SSE event sequence a Responses SDK expects (streaming).

The whole cost of the feature lives here. The queue, residency, eviction,
timeout and accounting are the chat path's, untouched, and so are the
message helpers (`format_messages`, `is_multimodal`) from `openai_compat`.
What the chat path reads off its own request model — structured output, the
reasoning budget, the loop guard — is read here off the Responses body,
because Responses spells most of it differently.

giq is stateless: there is no server-side conversation store, so
`previous_response_id` and `store` cannot be honoured. A request that sets
`previous_response_id` or `store: true` is refused rather than silently
claiming persistence or answering without the history it names. The same
applies to the rest of what Responses assumes a server provides: there is no
file store to resolve a `file_id` against and no server-side tool to run, so
those requests are refused too. A dropped image or a tool that was never
called is worse than a 400 — the answer comes back looking right.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, NamedTuple, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from giq.api.dependencies import get_orchestrator
from giq.api.openai_compat import (
    SSE_KEEPALIVE_SECONDS,
    ChatMessage,
    extract_text_content,
    format_messages,
    is_multimodal,
)
from giq.models import JobRequest, Modality
from giq.registry import get_spec
from giq.services.orchestration import Orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class ResponsesRequest(BaseModel):
    """OpenAI Responses request.

    Only the fields giq can act on are named; `extra="ignore"` drops the rest
    (SDK bookkeeping like `metadata`, `parallel_tool_calls`) rather than
    rejecting a request for carrying them. `reasoning`, `text` and
    `max_output_tokens` are read from the raw body in the handler because their
    nested shapes map onto several engine knobs at once.
    """

    model_config = ConfigDict(extra="ignore")
    model: str = Field(..., description="Model to use")
    # Responses accepts either a bare string or a list of typed input items.
    input: str | list = Field(..., description="Input text or item list")
    instructions: str | None = Field(
        default=None, description="System prompt, folded in ahead of the input"
    )
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.95, ge=0.0, le=1.0)
    stream: bool = Field(default=False)
    tools: list[dict] | None = Field(default=None, description="Tool definitions")
    tool_choice: str | dict | None = Field(default=None)
    store: bool | None = Field(default=None)
    # A conversation giq never stored cannot be continued. Named so the refusal
    # can be specific rather than a generic 422 from a field it ignored.
    previous_response_id: str | None = Field(default=None)


def _tool_to_chat(tool: dict) -> dict:
    """A Responses function tool as Chat Completions spells it.

    Responses flattens the function onto the tool — `{"type":"function",
    "name":..., "parameters":...}` — where Chat nests it under `"function"`.
    The engines only understand the nested form, so a flat tool is reshaped.

    Every other Responses tool type is a tool OpenAI *hosts* (web search, file
    search, code interpreter, MCP, image generation, computer use). giq runs no
    such tool and no engine behind it does either, so a request naming one is
    refused: forwarding it would either fail inside the engine or, worse, come
    back as an answer that quietly never used the tool the caller asked for.
    """
    if tool.get("type") != "function":
        raise HTTPException(
            status_code=400,
            detail=(
                f"tool type {tool.get('type')!r} is not supported: giq executes no "
                "server-side tools. Declare a function tool and call it yourself."
            ),
        )
    if "function" not in tool:
        fn = {k: tool[k] for k in ("name", "description", "parameters", "strict") if k in tool}
        return {"type": "function", "function": fn}
    return tool


# Both APIs spell the modes the same way; anything else is a tool giq cannot run.
_TOOL_CHOICE_MODES = frozenset({"none", "auto", "required"})


def _function_ref_to_chat(ref: dict) -> dict:
    """A Responses function reference (`{"type":"function","name":...}`) nested."""
    if ref.get("type") == "function" and "function" not in ref:
        return {"type": "function", "function": {"name": ref.get("name", "")}}
    return ref


def _tool_choice_to_chat(choice: str | dict) -> str | dict:
    """Translate a Responses tool_choice into the Chat spelling.

    The two APIs agree on the bare modes but not on the objects: Responses puts
    `name` and `mode`/`tools` on the choice itself, Chat nests them one level
    down (under `"function"` and `"allowed_tools"` respectively). An untranslated
    object reaches the engine as a shape it does not know, so each supported
    form is reshaped here and every other one — a hosted or custom tool giq
    cannot run — is refused rather than sent on to fail remotely.
    """
    if isinstance(choice, str):
        if choice not in _TOOL_CHOICE_MODES:
            raise HTTPException(
                status_code=400,
                detail=f"tool_choice must be one of {sorted(_TOOL_CHOICE_MODES)}, not {choice!r}",
            )
        return choice
    ctype = choice.get("type")
    if ctype == "function":
        return _function_ref_to_chat(choice)
    if ctype == "allowed_tools":
        allowed = choice.get("allowed_tools")
        if isinstance(allowed, dict):  # already the Chat shape
            return choice
        tools = choice.get("tools")
        if not isinstance(tools, list):
            raise HTTPException(
                status_code=400, detail="tool_choice allowed_tools needs a tools list"
            )
        return {
            "type": "allowed_tools",
            "allowed_tools": {
                "mode": choice.get("mode", "auto"),
                "tools": [_function_ref_to_chat(t) for t in tools if isinstance(t, dict)],
            },
        }
    raise HTTPException(
        status_code=400,
        detail=(
            f"tool_choice type {ctype!r} is not supported: giq executes no server-side "
            "tools. Use a mode, a function choice, or allowed_tools over your own functions."
        ),
    )


def _content_parts_to_chat(parts: list) -> list | str:
    """Responses content blocks as Chat content.

    `input_text`/`output_text` become `{"type":"text",...}`; `input_image`
    becomes `{"type":"image_url",...}` so the existing multimodal passthrough
    carries it to a vision model. A lone text part collapses to a string, which
    is what the plain path downstream expects. A part that names a stored file
    is refused — see below — because giq has nothing to resolve the ID against.
    """
    out: list = []
    for part in parts:
        if not isinstance(part, dict):
            out.append({"type": "text", "text": str(part)})
            continue
        ptype = part.get("type")
        if ptype in ("input_text", "output_text", "text"):
            out.append({"type": "text", "text": part.get("text", "")})
        elif ptype in ("input_image", "image_url"):
            url = part.get("image_url") or part.get("url")
            if not url and part.get("file_id"):
                # Responses lets an image be named by a file the caller uploaded
                # earlier. giq has no file store to resolve that ID against, and
                # dropping the part would send a vision question to a text-only
                # prompt — the exact silent image loss the vision check exists
                # to prevent — so the request is refused instead.
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "input_image.file_id is not supported: giq keeps no file store. "
                        "Send the image inline as an image_url data URI."
                    ),
                )
            if isinstance(url, dict):
                out.append({"type": "image_url", "image_url": url})
            elif url:
                image_url = {"url": url}
                if part.get("detail") is not None:
                    image_url["detail"] = part["detail"]
                out.append({"type": "image_url", "image_url": image_url})
        elif ptype == "input_file":
            # Same reasoning as input_image.file_id, and no engine behind giq
            # takes a document part either: a dropped attachment would leave the
            # model answering about a file it never saw.
            raise HTTPException(
                status_code=400,
                detail=(
                    "input_file is not supported: giq keeps no file store and the chat "
                    "engines take no document parts. Send the text, or an image part."
                ),
            )
        else:
            # Unknown block: keep its text if it has any, else skip it rather
            # than forward a shape the engine would reject.
            if part.get("text"):
                out.append({"type": "text", "text": part["text"]})
    if len(out) == 1 and out[0]["type"] == "text":
        return out[0]["text"]
    return out


def responses_input_to_messages(
    user_input: str | list, instructions: str | None
) -> list[ChatMessage]:
    """Fold a Responses `input` (+ `instructions`) into a chat message list.

    `instructions` leads as a system message. A bare-string input is one user
    turn. An item list is walked in order, each item mapped to the chat message
    it corresponds to:

    * `message` → a role-tagged message, its content parts translated;
    * `function_call` → an assistant turn carrying a `tool_calls` entry;
    * `function_call_output` → a `tool` turn keyed by `call_id`.

    A loose dict with a `role` is treated as a message so a caller that already
    speaks chat is not forced to wrap it.
    """
    messages: list[ChatMessage] = []
    if instructions:
        messages.append(ChatMessage(role="system", content=instructions))

    if isinstance(user_input, str):
        messages.append(ChatMessage(role="user", content=user_input))
        return messages

    pending_calls: list[dict] = []

    def flush_calls() -> None:
        if pending_calls:
            messages.append(
                ChatMessage(role="assistant", content=None, tool_calls=list(pending_calls))
            )
            pending_calls.clear()

    for item in user_input:
        if not isinstance(item, dict):
            flush_calls()
            messages.append(ChatMessage(role="user", content=str(item)))
            continue
        itype = item.get("type")
        if itype == "function_call":
            pending_calls.append(
                {
                    "id": item.get("call_id") or item.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", ""),
                    },
                }
            )
            continue

        flush_calls()
        if itype == "function_call_output":
            output = item.get("output", "")
            # Responses lets a tool return content parts as well as a string;
            # those translate like a message's, rather than reaching the model
            # as the JSON text of the parts.
            if isinstance(output, list):
                output = _content_parts_to_chat(output)
            elif not isinstance(output, str):
                output = json.dumps(output)
            messages.append(
                ChatMessage(
                    role="tool",
                    content=output,
                    tool_call_id=item.get("call_id") or item.get("id"),
                )
            )
        elif itype == "message" or "role" in item:
            content = item.get("content")
            if isinstance(content, list):
                content = _content_parts_to_chat(content)
            role = item.get("role", "user")
            # Responses clients send their standing instructions as
            # `developer`, a role the chat templates behind llama-server don't
            # know; to them it is the system prompt.
            if role == "developer":
                role = "system"
            messages.append(ChatMessage(role=role, content=content))
        # Items with no role and an unknown type (e.g. a bare reasoning item
        # echoed back) carry nothing the engine needs; skipping them is safe.
    flush_calls()
    return _merge_leading_system(messages)


def _merge_leading_system(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Fold the system messages that open a conversation into one.

    `instructions` plus a `developer` item is two system messages in a row,
    and chat templates commonly accept a system prompt only as the first
    message — a second one is a template error inside the engine. Joined, the
    model reads both, in order.
    """
    lead = 0
    while lead < len(messages) and messages[lead].role == "system":
        lead += 1
    if lead < 2:
        return messages
    text = "\n\n".join(extract_text_content(m.content) for m in messages[:lead])
    return [ChatMessage(role="system", content=text), *messages[lead:]]


def _build_chat_request(request: ResponsesRequest, body: dict) -> tuple[str, dict]:
    """The model name and the chat_request dict a Responses call reduces to.

    Shared by both handlers so streaming and non-streaming send the engine the
    same thing. `max_output_tokens` maps to `max_tokens`; `text.format` and the
    reasoning budget are read from the raw body because their Responses shapes
    nest the value the engine wants.
    """
    model = request.model
    if "/" in model:
        model = model.split("/", 1)[1]

    messages = responses_input_to_messages(request.input, request.instructions)

    if is_multimodal(messages):
        spec = get_spec("llm", model)
        if spec is None or not spec.vision:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{model} has no vision support, and the images in this request would "
                    "be dropped silently. Use a model whose catalog entry says vision."
                ),
            )

    chat: dict = {
        "messages": format_messages(messages),
        "temperature": request.temperature,
        "top_p": request.top_p,
    }
    if request.max_output_tokens is not None:
        chat["max_tokens"] = request.max_output_tokens
    if request.tools:
        chat["tools"] = [_tool_to_chat(t) for t in request.tools]
        if request.tool_choice is not None:
            chat["tool_choice"] = _tool_choice_to_chat(request.tool_choice)

    # response_format via Responses `text.format`, or the chat spelling if a
    # caller sent it directly. {"type":"json_schema","name":...,"schema":...}
    # is the Responses shape; the engines want it nested under "json_schema".
    text = body.get("text")
    if isinstance(text, dict) and isinstance(text.get("format"), dict):
        fmt = text["format"]
        if fmt.get("type") == "json_schema":
            chat["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    k: fmt[k] for k in ("name", "schema", "strict", "description") if k in fmt
                },
            }
        else:
            chat["response_format"] = fmt
    elif isinstance(body.get("response_format"), dict):
        chat["response_format"] = body["response_format"]

    # Thinking on or off. The chat path's own knob is passed through as it is
    # there; Responses' portable spelling is `reasoning.effort`, and of its
    # levels only "turn it off" has an engine equivalent — the chat templates
    # switch thinking, they don't grade it. An explicit enable_thinking wins.
    ctk = body.get("chat_template_kwargs")
    ctk = dict(ctk) if isinstance(ctk, dict) else {}
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort") in ("none", "minimal"):
        ctk.setdefault("enable_thinking", False)
    if ctk:
        chat["chat_template_kwargs"] = ctk
    # The deadline on the thought, under the same top-level names the chat
    # path takes; Responses has no field of its own for it.
    for key in ("reasoning_budget_tokens", "thinking_budget_tokens"):
        if isinstance(body.get(key), int):
            chat["reasoning_budget_tokens"] = body[key]
            break
    # Only the streaming worker knows this key: it pops it before calling the
    # engine. The non-streaming path forwards the body verbatim, so sending it
    # there would hand llama-server a parameter it may reject outright.
    if request.stream and isinstance(body.get("giq_loop_guard"), bool):
        chat["giq_loop_guard"] = body["giq_loop_guard"]

    return model, chat


# --- non-streaming -----------------------------------------------------------


def _message_to_output(message: dict, status: str = "completed") -> list[dict]:
    """A chat assistant message as Responses `output` items.

    Reasoning becomes a `reasoning` item carrying the raw thought as a
    `reasoning_text` part (not a summary, which it isn't — see _TEXT_PART), the
    answer a `message` item with an `output_text` part, and each tool call its
    own `function_call` item — the order a Responses client reads them back in.
    """
    output: list[dict] = []
    reasoning = message.get("reasoning_content")
    if reasoning:
        output.append(
            {
                "type": "reasoning",
                "id": f"rs_{uuid.uuid4().hex[:24]}",
                "summary": [],
                "content": [{"type": "reasoning_text", "text": reasoning}],
                "status": status,
            }
        )
    content = message.get("content")
    if content:
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex[:24]}",
                "status": status,
                "role": "assistant",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        )
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        output.append(
            {
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex[:24]}",
                "call_id": call.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", ""),
                "status": status,
            }
        )
    return output


class _ResponseMeta(NamedTuple):
    """The per-request facts every response object for that request repeats.

    A streamed response is one object reported many times (`response.created`,
    `response.in_progress`, the terminal event), so these are settled once when
    the request is accepted. `created_at` especially: recomputing it per event
    made one response appear to have several creation times.
    """

    id: str
    model: str
    created_at: int
    tools: list[dict]
    tool_choice: str | dict


def _response_meta(response_id: str, request: ResponsesRequest) -> _ResponseMeta:
    return _ResponseMeta(
        id=response_id,
        # Echoed as the caller sent them, not as the engine received them: the
        # client reads this back as its own request. The model keeps any
        # provider prefix it came with, as /v1/chat/completions echoes it.
        model=request.model,
        created_at=int(time.time()),
        tools=request.tools or [],
        tool_choice=request.tool_choice if request.tool_choice is not None else "auto",
    )


def _usage_object(usage: dict) -> dict:
    """Chat's usage block as Responses spells it, detail objects included.

    Responses requires the two detail objects even when the engine reports no
    such breakdown, so a missing count is reported as the zero it is rather
    than omitted — a client reading `output_tokens_details.reasoning_tokens`
    should find a number, not a KeyError.
    """
    tokens_in = usage.get("prompt_tokens") or 0
    tokens_out = usage.get("completion_tokens") or 0
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = completion_details if isinstance(completion_details, dict) else {}
    return {
        "input_tokens": tokens_in,
        "input_tokens_details": {
            "cached_tokens": prompt_details.get("cached_tokens") or 0,
            "cache_write_tokens": prompt_details.get("cache_write_tokens") or 0,
        },
        "output_tokens": tokens_out,
        "output_tokens_details": {
            "reasoning_tokens": completion_details.get("reasoning_tokens") or 0,
        },
        "total_tokens": usage.get("total_tokens") or (tokens_in + tokens_out),
    }


def _response_object(
    meta: _ResponseMeta,
    status: str,
    output: list[dict],
    usage: dict | None = None,
    incomplete_reason: str | None = None,
    error: dict | None = None,
) -> dict:
    """One Responses `response` object with every field the schema requires.

    `tools`, `tool_choice` and `parallel_tool_calls` are not optional in the
    Responses schema, even for a request that used no tools, so a client that
    validates what it receives needs them on every event. `usage` is left out
    while the response is still in progress: the token counts do not exist
    until the engine's final chunk arrives.
    """
    response: dict = {
        "id": meta.id,
        "object": "response",
        "created_at": meta.created_at,
        "status": status,
        "model": meta.model,
        "output": output,
        "tools": meta.tools,
        "tool_choice": meta.tool_choice,
        # A statement of fact rather than an echo: giq never tells the engine
        # to emit one tool call at a time, so reporting `false` back to a
        # caller that asked for it would be a promise nothing keeps.
        "parallel_tool_calls": True,
    }
    if usage is not None:
        response["usage"] = _usage_object(usage)
    if incomplete_reason is not None:
        response["incomplete_details"] = {"reason": incomplete_reason}
    if error is not None:
        response["error"] = error
    return response


# What the workers put in finish_reason when a stream was cut short — the client
# vanished, or the buffer stalled long enough that we stopped generating.
CANCELLED_FINISH_REASON = "cancelled"


def _completion_status(finish_reason: str | None) -> tuple[str, str | None]:
    """Map Chat's terminal reason onto Responses' status vocabulary."""
    if finish_reason == "length":
        return "incomplete", "max_output_tokens"
    if finish_reason == "content_filter":
        return "incomplete", "content_filter"
    return "completed", None


@router.post("/responses", response_model=None)
async def create_response(
    raw_request: Request, orch: Orchestrator = Depends(get_orchestrator)
) -> dict | StreamingResponse:
    """Generate a model response (OpenAI Responses-compatible endpoint)."""
    # Decoding inside the same guard as validation: a truncated body is the
    # caller's mistake, and reading it outside turned that into a 500.
    try:
        body = await raw_request.json()
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        request = ResponsesRequest(**body)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if request.previous_response_id is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "previous_response_id is not supported: giq keeps no server-side "
                "conversation store. Resend the prior turns in `input` instead."
            ),
        )
    if request.store:
        raise HTTPException(
            status_code=400,
            detail="store=true is not supported: giq keeps no server-side conversation store.",
        )

    model, chat = _build_chat_request(request, body)
    meta = _response_meta(f"resp_{uuid.uuid4().hex[:24]}", request)

    if request.stream:
        job_id, _, stream = await orch.submit_streaming_job(
            JobRequest(modality=Modality.llm, model=model, chat_request=chat)
        )
        return StreamingResponse(
            _relay_responses_stream(orch, job_id, stream, meta),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    job_id, _ = await orch.submit_job(
        JobRequest(modality=Modality.llm, model=model, chat_request=chat)
    )
    try:
        completed_job = await orch.wait_for_job(job_id)
    except asyncio.CancelledError:
        # The caller hung up or its proxy timed out. A job nobody can collect
        # would still queue, load a model and evict the resident set, so it
        # goes now while cancelling still costs nothing.
        await orch.cancel_job(job_id)
        raise
    if not completed_job.results:
        raise HTTPException(status_code=500, detail="No response generated")

    result = cast(dict, completed_job.results[0])
    choice = (result.get("choices") or [{}])[0]
    status, incomplete_reason = _completion_status(choice.get("finish_reason"))
    output = _message_to_output(choice.get("message", {}), status)
    return _response_object(meta, status, output, result.get("usage") or {}, incomplete_reason)


# --- streaming ---------------------------------------------------------------


def _event(seq: int, event_type: str, payload: dict) -> str:
    """One Responses SSE event: a named event line plus its JSON data.

    Responses streams are typed — the client dispatches on the `event:` name —
    where Chat Completions streams are a single anonymous `data:` channel. Each
    event also carries its own `type` and a monotonic `sequence_number`.
    """
    data = {"type": event_type, "sequence_number": seq, **payload}
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# The two text-bearing item types differ only in names: reasoning streams its
# raw thought as a `reasoning_text` content part, the answer as `output_text`.
# A summary is a different thing from the thought — OpenAI writes one *about*
# a thought it keeps hidden — so the engine's full reasoning goes out under
# the raw-reasoning names, as vllm's own Responses server sends it.
_TEXT_PART = {"reasoning": "reasoning_text", "message": "output_text"}
_TEXT_EVENT = {"reasoning": "response.reasoning_text", "message": "response.output_text"}


class _OutputItems:
    """The output items of one streamed response, and the events that build them.

    A Responses client assembles its output from the event stream, and OpenAI's
    own streams finish each item before the next one's `output_item.added`. So
    exactly one item is open at a time: opening the next one closes the
    current one first, whatever its type. The engine's chat deltas don't
    promise that order — reasoning can resume after the answer has begun, an
    answer can precede a tool call — and each such switch simply becomes a new
    item, which is also what the Responses model of interleaved output is.

    Every method returns the SSE events it produced; the relay yields them.
    An async generator cannot delegate to a helper generator, so lists it is.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self._seq = 0

    def ev(self, event_type: str, payload: dict) -> str:
        out = _event(self._seq, event_type, payload)
        self._seq += 1
        return out

    @staticmethod
    def item(record: dict[str, Any], status: str | None = None) -> dict:
        """A record as the Responses output item it stands for.

        `status` overrides the record's own: an item still open when the stream
        ends takes the response's ending, the ones closed before it completed.
        """
        status = status or record["status"]
        kind = record["type"]
        if kind == "function_call":
            return {
                "type": "function_call",
                "id": record["id"],
                "call_id": record["call_id"],
                "name": record["name"],
                "arguments": "".join(record["arguments"]),
                "status": status,
            }
        part = _OutputItems.part(record)
        if kind == "reasoning":
            return {
                "type": "reasoning",
                "id": record["id"],
                "summary": [],
                "content": [part],
                "status": status,
            }
        return {
            "type": "message",
            "id": record["id"],
            "status": status,
            "role": "assistant",
            "content": [part],
        }

    @staticmethod
    def part(record: dict[str, Any], text: str | None = None) -> dict:
        part = {
            "type": _TEXT_PART[record["type"]],
            "text": "".join(record["text"]) if text is None else text,
        }
        if record["type"] == "message":
            part["annotations"] = []
        return part

    def output(self, open_status: str) -> list[dict]:
        """Every item so far, the still-open one reported as `open_status`."""
        return [
            self.item(r, None if r["status"] != "in_progress" else open_status)
            for r in self.records
        ]

    def _open(self, record: dict[str, Any]) -> list[str]:
        events = self.close()
        record["output_index"] = len(self.records)
        record["status"] = "in_progress"
        self.records.append(record)
        self.current = record
        # Opened empty: the deltas that follow are what fills it.
        added = self.item(record)
        if record["type"] == "function_call":
            added["arguments"] = ""
        else:
            added["content"] = []
        events.append(
            self.ev(
                "response.output_item.added",
                {"output_index": record["output_index"], "item": added},
            )
        )
        if record["type"] != "function_call":
            events.append(
                self.ev(
                    "response.content_part.added",
                    {
                        "item_id": record["id"],
                        "output_index": record["output_index"],
                        "content_index": 0,
                        "part": self.part(record, text=""),
                    },
                )
            )
        return events

    def close(self, status: str = "completed") -> list[str]:
        """Finish the open item: its text or arguments, its part, then the item."""
        record = self.current
        if record is None:
            return []
        self.current = None
        record["status"] = status
        located = {"item_id": record["id"], "output_index": record["output_index"]}
        item = self.item(record)
        if record["type"] == "function_call":
            events = [
                self.ev(
                    "response.function_call_arguments.done",
                    {**located, "arguments": item["arguments"]},
                )
            ]
        else:
            part = item["content"][0]
            events = [
                self.ev(
                    f"{_TEXT_EVENT[record['type']]}.done",
                    {**located, "content_index": 0, "text": part["text"]},
                ),
                self.ev(
                    "response.content_part.done", {**located, "content_index": 0, "part": part}
                ),
            ]
        events.append(
            self.ev(
                "response.output_item.done", {"output_index": record["output_index"], "item": item}
            )
        )
        return events

    def text(self, kind: str, fragment: str) -> list[str]:
        """A reasoning or answer fragment, into the open item of its kind or a new one."""
        events: list[str] = []
        record: dict[str, Any] | None = self.current
        if record is None or record["type"] != kind:
            record = {
                "type": kind,
                "id": f"{'rs' if kind == 'reasoning' else 'msg'}_{uuid.uuid4().hex[:24]}",
                "text": [],
            }
            events += self._open(record)
        record["text"].append(fragment)
        events.append(
            self.ev(
                f"{_TEXT_EVENT[kind]}.delta",
                {
                    "item_id": record["id"],
                    "output_index": record["output_index"],
                    "content_index": 0,
                    "delta": fragment,
                },
            )
        )
        return events

    def tool_call(self, call: dict) -> list[str]:
        """One chat tool-call fragment, folded into the call at its index.

        A function_call item has no event that backfills `call_id` or `name`,
        so the item is not announced until both exist; argument fragments that
        arrive first wait in `pending` rather than stream into a blank. The
        engines finish one call before starting the next, so a fragment for a
        call that is no longer open is not expected — if one comes anyway it
        still lands in the call's arguments, and the terminal response carries
        them whole even though no delta announced them.
        """
        idx = call.get("index", 0)
        record: dict[str, Any] | None = self.tool_calls.get(idx)
        if record is None:
            record = self.tool_calls[idx] = {
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex[:24]}",
                "call_id": "",
                "name": "",
                "arguments": [],
                "pending": [],
                "output_index": None,
            }
        fn = call.get("function") or {}
        if call.get("id"):
            record["call_id"] = call["id"]
        if fn.get("name"):
            record["name"] = fn["name"]
        if fn.get("arguments"):
            record["arguments"].append(fn["arguments"])
            record["pending"].append(fn["arguments"])

        events: list[str] = []
        if record["output_index"] is None and record["call_id"] and record["name"]:
            events += self._open(record)
        if record is self.current:
            events += [
                self.ev(
                    "response.function_call_arguments.delta",
                    {
                        "item_id": record["id"],
                        "output_index": record["output_index"],
                        "delta": frag,
                    },
                )
                for frag in record["pending"]
            ]
            record["pending"].clear()
        return events

    @property
    def unannounced_calls(self) -> bool:
        return any(r["output_index"] is None for r in self.tool_calls.values())


async def _relay_responses_stream(orch: Orchestrator, job_id: str, stream, meta: _ResponseMeta):
    """Translate a chat job's delta chunks into the Responses event sequence.

    The queue carries llama-server's raw Chat Completions chunks
    (`choices[].delta.{content,reasoning_content,tool_calls}`, a trailing
    usage-only chunk). This consumes them and emits the typed `response.*`
    events a Responses SDK expects:

      response.created / response.in_progress
      → per item, one at a time (see _OutputItems):
          output_item.added,
          content_part.added, reasoning_text / output_text .delta…, .done,
          content_part.done                      (reasoning and message items)
          function_call_arguments.delta…, .done  (function_call items)
        output_item.done
      → response.completed / .incomplete / .failed

    It keeps `_relay_stream`'s discipline: an SSE keepalive while the job is
    cold or queued, and a finally-block that drains and cancels the job the
    moment the client goes away.
    """
    from giq.models import JobStatus

    items = _OutputItems()
    ev = items.ev
    usage: dict | None = None
    finish_reason: str | None = None

    def in_progress() -> dict:
        return {"response": _response_object(meta, "in_progress", [])}

    try:
        yield ev("response.created", in_progress())
        yield ev("response.in_progress", in_progress())

        while True:
            try:
                chunk = await asyncio.wait_for(stream.queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if chunk is None:
                break
            if isinstance(chunk.get("usage"), dict):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                if delta.get("reasoning_content"):
                    for event in items.text("reasoning", delta["reasoning_content"]):
                        yield event
                if delta.get("content"):
                    for event in items.text("message", delta["content"]):
                        yield event
                for call in delta.get("tool_calls") or []:
                    if isinstance(call, dict):
                        for event in items.tool_call(call):
                            yield event

        # The stored result is the authority on how the generation ended: a
        # cancelled one stops without a terminal chunk, so the reason exists
        # only on the job. The run paths set it before they close the stream,
        # so by the time the sentinel arrives it is there to read.
        job = await orch.queue.get(job_id)
        if job is not None and job.results:
            stored = cast(dict, job.results[0])
            choices = stored.get("choices") or [{}]
            finish_reason = choices[0].get("finish_reason") or finish_reason
            if usage is None and isinstance(stored.get("usage"), dict):
                usage = stored["usage"]

        def failure(code: str, message: str) -> str:
            """A terminal response.failed with whatever was produced.

            The open item is reported inside it as incomplete and deliberately
            not closed with output_item.done: it did not finish. Items closed
            before the failure did, and stay completed.
            """
            response = _response_object(
                meta,
                "failed",
                items.output("incomplete"),
                usage or {},
                error={"code": code, "message": message},
            )
            return ev("response.failed", {"response": response})

        # A failure after the first event cannot become an HTTP status, so it
        # rides the stream as response.failed rather than a silent truncation.
        if job is not None and job.status == JobStatus.failed:
            yield failure("giq_job_failed", job.error or "Job failed")
            return

        if finish_reason == CANCELLED_FINISH_REASON or stream.is_cancelled:
            # Generation was cut short — the buffer stalled, or the job was
            # cancelled. Calling that "completed" would hand the caller a
            # truncated answer labelled as the whole one.
            yield failure(
                "giq_stream_cancelled", "Generation was cancelled before the model finished."
            )
            return

        if items.unannounced_calls:
            # Arguments arrived for a call the engine never identified. A
            # function_call item without call_id and name is unusable, so this
            # ends as a failure rather than as a call the client cannot make.
            yield failure(
                "giq_incomplete_tool_call",
                "The engine streamed tool-call arguments without a call id and name.",
            )
            return

        # Only the last item can have been cut off by max_output_tokens; the
        # ones before it finished when the next began.
        status, incomplete_reason = _completion_status(finish_reason)
        for event in items.close(status):
            yield event
        response = _response_object(
            meta, status, items.output(status), usage or {}, incomplete_reason
        )
        yield ev(f"response.{status}", {"response": response})
    finally:
        stream.cancel()
        while True:
            try:
                stream.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await orch.cancel_job(job_id)

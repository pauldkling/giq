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
timeout and accounting are the chat path's, untouched; `format_messages`,
`is_multimodal` and the structured-output threading are reused from
`openai_compat` rather than reimplemented.

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
    format_messages,
    is_multimodal,
)
from giq.models import JobRequest, WorkerType
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
            messages.append(
                ChatMessage(
                    role="tool",
                    content=output if isinstance(output, str) else json.dumps(output),
                    tool_call_id=item.get("call_id") or item.get("id"),
                )
            )
        elif itype == "message" or "role" in item:
            content = item.get("content")
            if isinstance(content, list):
                content = _content_parts_to_chat(content)
            messages.append(ChatMessage(role=item.get("role", "user"), content=content))
        # Items with no role and an unknown type (e.g. a bare reasoning item
        # echoed back) carry nothing the engine needs; skipping them is safe.
    flush_calls()
    return messages


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

    # Reasoning budget: Responses nests it under `reasoning`, giq's chat path
    # takes `reasoning_budget_tokens` at the top level.
    reasoning = body.get("reasoning")
    if isinstance(reasoning, dict):
        budget = reasoning.get("budget_tokens") or reasoning.get("max_tokens")
        if isinstance(budget, int):
            chat["reasoning_budget_tokens"] = budget
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

    Reasoning becomes a `reasoning` item (summary text), the answer a `message`
    item with an `output_text` part, and each tool call its own `function_call`
    item — the order a Responses client reads them back in.
    """
    output: list[dict] = []
    reasoning = message.get("reasoning_content")
    if reasoning:
        output.append(
            {
                "type": "reasoning",
                "id": f"rs_{uuid.uuid4().hex[:24]}",
                "summary": [{"type": "summary_text", "text": reasoning}],
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


def _response_meta(response_id: str, model: str, request: ResponsesRequest) -> _ResponseMeta:
    return _ResponseMeta(
        id=response_id,
        model=model,
        created_at=int(time.time()),
        # Echoed as the caller sent them, not as the engine received them: the
        # client reads this back as its own request.
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
    meta = _response_meta(f"resp_{uuid.uuid4().hex[:24]}", model, request)

    if request.stream:
        job_id, _, stream = await orch.submit_streaming_job(
            JobRequest(worker=WorkerType.llm, model=model, chat_request=chat)
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
        JobRequest(worker=WorkerType.llm, model=model, chat_request=chat)
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


async def _relay_responses_stream(orch: Orchestrator, job_id: str, stream, meta: _ResponseMeta):
    """Translate a chat job's delta chunks into the Responses event sequence.

    The queue carries llama-server's raw Chat Completions chunks
    (`choices[].delta.{content,reasoning_content,tool_calls}`, a trailing
    usage-only chunk). This consumes them and emits the typed `response.*`
    events a Responses SDK expects, opening and closing each output item and
    content part around the deltas:

      response.created / response.in_progress
      → response.output_item.added (reasoning), reasoning_summary_part.added,
        reasoning_summary_text.delta…, .done, reasoning_summary_part.done,
        response.output_item.done
      → response.output_item.added (message), content_part.added,
        output_text.delta…, output_text.done, content_part.done
      → response.output_item.added (function_call),
        function_call_arguments.delta…, .done
      → response.output_item.done per item
      → response.completed  (or response.failed on a job error)

    An item is opened, streamed and closed before the next one opens, and a
    function call is not announced until its `call_id` and name exist — a
    client that builds its objects from the `*.added` events gets something it
    can act on rather than a blank it must wait to see corrected.

    It keeps `_relay_stream`'s discipline: an SSE keepalive while the job is
    cold or queued, and a finally-block that drains and cancels the job the
    moment the client goes away.
    """
    from giq.models import JobStatus

    seq = 0

    def ev(event_type: str, payload: dict) -> str:
        nonlocal seq
        out = _event(seq, event_type, payload)
        seq += 1
        return out

    # Every item reserves its identity and position when opened. Later deltas,
    # done events and the terminal response all refer to this same record.
    items: list[dict] = []
    reasoning_item: dict | None = None
    message_item: dict | None = None
    tool_calls: dict[int, dict[str, Any]] = {}
    usage: dict | None = None
    finish_reason: str | None = None

    def final_output(status: str) -> list[dict]:
        output: list[dict] = []
        for record in items:
            if record["type"] == "reasoning":
                output.append(
                    {
                        "type": "reasoning",
                        "id": record["id"],
                        "summary": [{"type": "summary_text", "text": "".join(record["text"])}],
                    }
                )
            elif record["type"] == "message":
                text = "".join(record["text"])
                output.append(
                    {
                        "type": "message",
                        "id": record["id"],
                        "status": status,
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text, "annotations": []}],
                    }
                )
            else:
                output.append(
                    {
                        "type": "function_call",
                        "id": record["id"],
                        "call_id": record["call_id"],
                        "name": record["name"],
                        "arguments": "".join(record["arguments"]),
                        "status": status,
                    }
                )
        return output

    def close_reasoning() -> list[str]:
        """Shut an open reasoning item: text, then summary part, then the item.

        Responses treats the summary text and the summary *part* that holds it
        as separately completed things, and the part has to be closed before
        the item. Returned as a list because an async generator cannot delegate
        to another generator, and both close sites — a later item opening and
        the end of the stream — need the same three events in the same order.
        """
        if reasoning_item is None or reasoning_item["closed"]:
            return []
        text = "".join(reasoning_item["text"])
        part = {"type": "summary_text", "text": text}
        located = {
            "item_id": reasoning_item["id"],
            "output_index": reasoning_item["output_index"],
            "summary_index": 0,
        }
        reasoning_item["closed"] = True
        return [
            ev("response.reasoning_summary_text.done", {**located, "text": text}),
            ev("response.reasoning_summary_part.done", {**located, "part": part}),
            ev(
                "response.output_item.done",
                {
                    "output_index": reasoning_item["output_index"],
                    "item": {
                        "type": "reasoning",
                        "id": reasoning_item["id"],
                        "summary": [part],
                    },
                },
            ),
        ]

    def in_progress() -> dict:
        return {"response": _response_object(meta, "in_progress", [])}

    def new_tool_call() -> dict[str, Any]:
        """A function call being assembled from the engine's fragments.

        `pending` holds argument fragments that arrived before the call could
        be announced: a Responses function_call item has no event that
        backfills `call_id` or `name`, so the item waits for both and the
        arguments wait for the item rather than streaming into a blank.
        """
        return {
            "type": "function_call",
            "id": f"fc_{uuid.uuid4().hex[:24]}",
            "call_id": "",
            "name": "",
            "arguments": [],
            "pending": [],
            "output_index": None,
        }

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

                rc = delta.get("reasoning_content")
                if rc:
                    if reasoning_item is None:
                        reasoning_item = {
                            "type": "reasoning",
                            "id": f"rs_{uuid.uuid4().hex[:24]}",
                            "output_index": len(items),
                            "text": [],
                            "closed": False,
                        }
                        items.append(reasoning_item)
                        yield ev(
                            "response.output_item.added",
                            {
                                "output_index": reasoning_item["output_index"],
                                "item": {
                                    "type": "reasoning",
                                    "id": reasoning_item["id"],
                                    "summary": [],
                                },
                            },
                        )
                        # The summary part the deltas below belong to. Without
                        # it a client has no part to attach them to: the item
                        # opened with an empty summary.
                        yield ev(
                            "response.reasoning_summary_part.added",
                            {
                                "item_id": reasoning_item["id"],
                                "output_index": reasoning_item["output_index"],
                                "summary_index": 0,
                                "part": {"type": "summary_text", "text": ""},
                            },
                        )
                    reasoning_item["text"].append(rc)
                    yield ev(
                        "response.reasoning_summary_text.delta",
                        {
                            "item_id": reasoning_item["id"],
                            "output_index": reasoning_item["output_index"],
                            "summary_index": 0,
                            "delta": rc,
                        },
                    )

                content = delta.get("content")
                if content:
                    # The thought ends where the answer begins.
                    for event in close_reasoning():
                        yield event
                    if message_item is None:
                        message_item = {
                            "type": "message",
                            "id": f"msg_{uuid.uuid4().hex[:24]}",
                            "output_index": len(items),
                            "text": [],
                        }
                        items.append(message_item)
                        yield ev(
                            "response.output_item.added",
                            {
                                "output_index": message_item["output_index"],
                                "item": {
                                    "type": "message",
                                    "id": message_item["id"],
                                    "status": "in_progress",
                                    "role": "assistant",
                                    "content": [],
                                },
                            },
                        )
                        yield ev(
                            "response.content_part.added",
                            {
                                "item_id": message_item["id"],
                                "output_index": message_item["output_index"],
                                "content_index": 0,
                                "part": {"type": "output_text", "text": "", "annotations": []},
                            },
                        )
                    message_item["text"].append(content)
                    yield ev(
                        "response.output_text.delta",
                        {
                            "item_id": message_item["id"],
                            "output_index": message_item["output_index"],
                            "content_index": 0,
                            "delta": content,
                        },
                    )

                for call in delta.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    idx = call.get("index", 0)
                    record = tool_calls.get(idx)
                    if record is None:
                        record = tool_calls[idx] = new_tool_call()
                    fn = call.get("function") or {}
                    if call.get("id"):
                        record["call_id"] = call["id"]
                    if fn.get("name"):
                        record["name"] = fn["name"]
                    frag = fn.get("arguments")
                    if frag:
                        record["arguments"].append(frag)
                        record["pending"].append(frag)
                    if record["output_index"] is None and record["call_id"] and record["name"]:
                        for event in close_reasoning():
                            yield event
                        record["output_index"] = len(items)
                        items.append(record)
                        yield ev(
                            "response.output_item.added",
                            {
                                "output_index": record["output_index"],
                                "item": {
                                    "type": "function_call",
                                    "id": record["id"],
                                    "call_id": record["call_id"],
                                    "name": record["name"],
                                    "arguments": "",
                                    "status": "in_progress",
                                },
                            },
                        )
                    if record["output_index"] is not None and record["pending"]:
                        for buffered in record["pending"]:
                            yield ev(
                                "response.function_call_arguments.delta",
                                {
                                    "item_id": record["id"],
                                    "output_index": record["output_index"],
                                    "delta": buffered,
                                },
                            )
                        record["pending"].clear()

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

        def failure(code: str, message: str) -> dict:
            """A terminal response.failed payload with whatever was produced."""
            return {
                "response": _response_object(
                    meta,
                    "failed",
                    final_output("incomplete"),
                    usage or {},
                    error={"code": code, "message": message},
                )
            }

        # A failure after the first event cannot become an HTTP status, so it
        # rides the stream as response.failed rather than a silent truncation.
        # Partial items are reported inside that response and deliberately not
        # closed with output_item.done: they did not finish.
        if job is not None and job.status == JobStatus.failed:
            yield ev("response.failed", failure("giq_job_failed", job.error or "Job failed"))
            return

        if finish_reason == CANCELLED_FINISH_REASON or stream.is_cancelled:
            # Generation was cut short — the buffer stalled, or the job was
            # cancelled. Calling that "completed" would hand the caller a
            # truncated answer labelled as the whole one.
            yield ev(
                "response.failed",
                failure(
                    "giq_stream_cancelled",
                    "Generation was cancelled before the model finished.",
                ),
            )
            return

        unannounced = [r for r in tool_calls.values() if r["output_index"] is None]
        if unannounced:
            # Arguments arrived for a call the engine never identified. A
            # function_call item without call_id and name is unusable, so this
            # ends as a failure rather than as a call the client cannot make.
            yield ev(
                "response.failed",
                failure(
                    "giq_incomplete_tool_call",
                    "The engine streamed tool-call arguments without a call id and name.",
                ),
            )
            return

        status, incomplete_reason = _completion_status(finish_reason)
        output = final_output(status)
        for record, item in zip(items, output, strict=True):
            if record["type"] == "reasoning":
                # Reasoning that ran to the end of the stream closes the same
                # way it would have closed had an answer followed it.
                for event in close_reasoning():
                    yield event
                continue
            if record["type"] == "message":
                text = item["content"][0]["text"]
                yield ev(
                    "response.output_text.done",
                    {
                        "item_id": record["id"],
                        "output_index": record["output_index"],
                        "content_index": 0,
                        "text": text,
                    },
                )
                yield ev(
                    "response.content_part.done",
                    {
                        "item_id": record["id"],
                        "output_index": record["output_index"],
                        "content_index": 0,
                        "part": item["content"][0],
                    },
                )
            else:
                yield ev(
                    "response.function_call_arguments.done",
                    {
                        "item_id": record["id"],
                        "output_index": record["output_index"],
                        "arguments": item["arguments"],
                    },
                )
            yield ev(
                "response.output_item.done",
                {"output_index": record["output_index"], "item": item},
            )

        response = _response_object(meta, status, output, usage or {}, incomplete_reason)
        yield ev(f"response.{status}", {"response": response})
    finally:
        stream.cancel()
        while True:
            try:
                stream.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        await orch.cancel_job(job_id)

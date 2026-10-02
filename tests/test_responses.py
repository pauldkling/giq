# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI Responses API: the shape translated down to chat and back up.

giq's engines speak Chat Completions, so `/v1/responses` is a translation, not
a proxy. These tests pin the three joints where the translation can go wrong:
the input adapter (Responses `input`/`instructions` → chat messages), the
non-streaming reshape (a chat result → one `response` object), and the
streaming relay (chat deltas → the typed `response.*` event sequence a
Responses SDK dispatches on). A streaming job stays an ordinary queued job;
only its delivery differs.
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from giq.main import app
from giq.models import JobRequest, JobStatus, Modality
from giq.queue import Job, JobQueue, JobStream
from giq.runner import Runner

# --- helpers -----------------------------------------------------------------


def delta(**kw) -> dict:
    """A llama-server chat.completion.chunk, as it lands on the stream queue."""
    return {"id": "c1", "created": 1, "model": "m", "choices": [{"index": 0, "delta": kw}]}


class FakeQueue:
    def __init__(self, job):
        self._job = job

    async def get(self, job_id):
        return self._job


class FakeOrch:
    def __init__(self, job):
        self.queue = FakeQueue(job)
        self.cancelled = []

    async def cancel_job(self, job_id):
        self.cancelled.append(job_id)
        return True, "Cancelled"


def _job() -> Job:
    return Job(
        job_id="j1",
        request=JobRequest(modality=Modality.llm, model="qwen3.8-27b", chat_request={}),
    )


def meta(**over):
    """The per-request facts the relay repeats on every response object."""
    from giq.api.openai_responses import _ResponseMeta

    fields = {
        "id": "resp_x",
        "model": "qwen3.8-27b",
        "created_at": 1_700_000_000,
        "tools": [],
        "tool_choice": "auto",
    }
    return _ResponseMeta(**{**fields, **over})


async def collect(orch, stream, **over) -> list[str]:
    from giq.api.openai_responses import _relay_responses_stream

    return [part async for part in _relay_responses_stream(orch, "j1", stream, meta(**over))]


def events(parts: list[str]) -> list[dict]:
    """Parse the `data:` JSON out of the relay's typed SSE parts."""
    out = []
    for p in parts:
        for line in p.splitlines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


@pytest.fixture
async def client():
    import giq.queue
    import giq.runner

    giq.queue._queue = JobQueue()
    giq.runner._runner = Runner(giq.queue._queue)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as ac:
        yield ac


# --- the input adapter -------------------------------------------------------


def test_bare_string_input_becomes_one_user_turn():
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages("hello", None)
    assert [(m.role, m.content) for m in msgs] == [("user", "hello")]


def test_instructions_lead_as_a_system_message():
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages("hi", "be terse")
    assert msgs[0].role == "system" and msgs[0].content == "be terse"
    assert msgs[1].role == "user"


def test_item_list_text_parts_collapse_to_a_string():
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages(
        [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "q"}]}],
        None,
    )
    assert msgs[0].role == "user" and msgs[0].content == "q"


def test_function_call_round_trips_through_the_adapter():
    """A prior tool call and its result come back as assistant+tool turns, the
    shape the engine needs to continue the conversation."""
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages(
        [
            {"type": "message", "role": "user", "content": "weather?"},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "get_weather",
                "arguments": '{"city":"Berlin"}',
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "sunny"},
        ],
        None,
    )
    assert msgs[0].role == "user"
    assert msgs[1].role == "assistant"
    assert msgs[1].tool_calls[0]["id"] == "call_1"
    assert msgs[1].tool_calls[0]["function"]["name"] == "get_weather"
    assert msgs[2].role == "tool"
    assert msgs[2].tool_call_id == "call_1"
    assert msgs[2].content == "sunny"


def test_parallel_function_calls_share_one_assistant_turn():
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages(
        [
            {"type": "function_call", "call_id": "c1", "name": "first", "arguments": "{}"},
            {"type": "function_call", "call_id": "c2", "name": "second", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "one"},
            {"type": "function_call_output", "call_id": "c2", "output": "two"},
        ],
        None,
    )
    assert [m.role for m in msgs] == ["assistant", "tool", "tool"]
    assert [call["id"] for call in msgs[0].tool_calls] == ["c1", "c2"]


def test_input_image_detail_is_preserved():
    from giq.api.openai_responses import _content_parts_to_chat

    content = _content_parts_to_chat(
        [{"type": "input_image", "image_url": "data:image/png;base64,eA==", "detail": "high"}]
    )
    assert content == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,eA==", "detail": "high"},
        }
    ]


def test_developer_role_joins_the_system_prompt():
    """Responses clients send standing instructions as `developer`; the chat
    templates know only a system prompt, and only as the first message."""
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages(
        [
            {"type": "message", "role": "developer", "content": "use metric units"},
            {"type": "message", "role": "user", "content": "weather?"},
        ],
        "be brief",
    )
    assert [(m.role, m.content) for m in msgs] == [
        ("system", "be brief\n\nuse metric units"),
        ("user", "weather?"),
    ]


def test_tool_output_parts_reach_the_model_as_text():
    from giq.api.openai_responses import responses_input_to_messages

    msgs = responses_input_to_messages(
        [
            {
                "type": "function_call_output",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": "14 C, overcast"}],
            }
        ],
        None,
    )
    assert msgs[0].role == "tool" and msgs[0].content == "14 C, overcast"


def test_tool_definition_is_renested_for_the_engine():
    """Responses flattens the function onto the tool; the engine wants it under
    `function`."""
    from giq.api.openai_responses import _tool_to_chat

    chat_tool = _tool_to_chat({"type": "function", "name": "f", "parameters": {"type": "object"}})
    assert chat_tool == {
        "type": "function",
        "function": {"name": "f", "parameters": {"type": "object"}},
    }


def test_hosted_tool_types_are_refused():
    """giq runs no tool itself, and a tool silently not used is worse than a 400."""
    from fastapi import HTTPException

    from giq.api.openai_responses import _tool_to_chat

    for tool in ({"type": "web_search"}, {"type": "file_search"}, {"type": "mcp"}):
        with pytest.raises(HTTPException) as exc:
            _tool_to_chat(tool)
        assert exc.value.status_code == 400
        assert tool["type"] in exc.value.detail


def test_allowed_tools_choice_is_renested_for_the_engine():
    """Responses puts mode/tools on the choice; Chat nests them under
    `allowed_tools` and each function reference under `function`."""
    from giq.api.openai_responses import _tool_choice_to_chat

    assert _tool_choice_to_chat(
        {
            "type": "allowed_tools",
            "mode": "required",
            "tools": [{"type": "function", "name": "lookup"}],
        }
    ) == {
        "type": "allowed_tools",
        "allowed_tools": {
            "mode": "required",
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
        },
    }


def test_unsupported_tool_choices_are_refused():
    from fastapi import HTTPException

    from giq.api.openai_responses import _tool_choice_to_chat

    assert _tool_choice_to_chat("required") == "required"
    for choice in ("whenever", {"type": "web_search_preview"}, {"type": "custom", "name": "c"}):
        with pytest.raises(HTTPException) as exc:
            _tool_choice_to_chat(choice)
        assert exc.value.status_code == 400


def test_stored_file_references_are_refused_not_dropped():
    """A file giq cannot resolve would otherwise vanish, leaving the model
    answering a vision or document question it never saw the input for."""
    from fastapi import HTTPException

    from giq.api.openai_responses import _content_parts_to_chat

    with pytest.raises(HTTPException) as image:
        _content_parts_to_chat([{"type": "input_image", "file_id": "file_abc"}])
    assert image.value.status_code == 400 and "file_id" in image.value.detail

    with pytest.raises(HTTPException) as doc:
        _content_parts_to_chat([{"type": "input_file", "file_id": "file_abc"}])
    assert doc.value.status_code == 400 and "input_file" in doc.value.detail


def test_usage_carries_the_detail_objects_responses_requires():
    from giq.api.openai_responses import _usage_object

    assert _usage_object({"prompt_tokens": 7, "completion_tokens": 3}) == {
        "input_tokens": 7,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 3,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 10,
    }
    # What the engine does report is passed through rather than zeroed.
    detailed = _usage_object(
        {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "total_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 5},
            "completion_tokens_details": {"reasoning_tokens": 2},
        }
    )
    assert detailed["input_tokens_details"]["cached_tokens"] == 5
    assert detailed["output_tokens_details"]["reasoning_tokens"] == 2


# --- non-streaming reshape ---------------------------------------------------


def test_message_becomes_an_output_text_item():
    from giq.api.openai_responses import _message_to_output

    output = _message_to_output({"content": "the answer"})
    assert output[0]["type"] == "message"
    assert output[0]["content"][0]["type"] == "output_text"
    assert output[0]["content"][0]["text"] == "the answer"


def test_reasoning_and_tool_calls_become_their_own_items():
    from giq.api.openai_responses import _message_to_output

    output = _message_to_output(
        {
            "content": "done",
            "reasoning_content": "thinking",
            "tool_calls": [
                {"id": "c1", "function": {"name": "f", "arguments": "{}"}},
            ],
        }
    )
    types = [item["type"] for item in output]
    assert types == ["reasoning", "message", "function_call"]
    assert output[0]["content"] == [{"type": "reasoning_text", "text": "thinking"}]
    assert output[0]["summary"] == []
    assert output[2]["call_id"] == "c1" and output[2]["name"] == "f"


@pytest.mark.parametrize(
    ("finish_reason", "status", "incomplete_reason"),
    [
        ("stop", "completed", None),
        ("tool_calls", "completed", None),
        ("length", "incomplete", "max_output_tokens"),
        ("content_filter", "incomplete", "content_filter"),
    ],
)
def test_chat_finish_reason_maps_to_response_status(finish_reason, status, incomplete_reason):
    from giq.api.openai_responses import _completion_status

    assert _completion_status(finish_reason) == (status, incomplete_reason)


# --- the endpoint (non-streaming) --------------------------------------------


@pytest.fixture
def responds(monkeypatch):
    """Capture the JobRequest a /v1/responses call submits; return a canned result."""
    from giq.services.orchestration import Orchestrator

    seen: dict = {"finish_reason": "stop"}

    async def submit(self, request):
        seen["request"] = request
        return "job-xyz", 0

    async def wait(self, job_id, timeout=None):
        job = Job(
            job_id=job_id,
            request=JobRequest(modality=Modality.llm, model="m", chat_request={}),
        )
        job.status = JobStatus.completed
        job.results = [
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "hi there"},
                        "finish_reason": seen["finish_reason"],
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        ]
        return job

    monkeypatch.setattr(Orchestrator, "submit_job", submit)
    monkeypatch.setattr(Orchestrator, "wait_for_job", wait)
    return seen


@pytest.fixture
def streams(monkeypatch):
    """Capture the JobRequest a streaming /v1/responses call submits."""
    from giq.services.orchestration import Orchestrator

    seen: dict = {}

    async def submit(self, request):
        seen["request"] = request
        stream = JobStream()
        stream.queue.put_nowait(
            {"choices": [{"index": 0, "delta": {"content": "{}"}, "finish_reason": "stop"}]}
        )
        await stream.close()
        return "stream-job", 0, stream

    monkeypatch.setattr(Orchestrator, "submit_streaming_job", submit)
    return seen


@pytest.mark.asyncio
async def test_endpoint_returns_a_response_object(client: AsyncClient, responds):
    r = await client.post(
        "/v1/responses",
        json={"model": "qwen3.8-27b", "input": "hello", "instructions": "be nice"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "response"
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "hi there"
    assert body["usage"] == {
        "input_tokens": 3,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 5,
    }
    # Instructions were folded into the chat request as a system message.
    messages = responds["request"].chat_request["messages"]
    assert messages[0]["role"] == "system" and messages[0]["content"] == "be nice"


@pytest.mark.asyncio
async def test_max_output_tokens_maps_to_max_tokens(client: AsyncClient, responds):
    await client.post(
        "/v1/responses",
        json={"model": "m", "input": "hi", "max_output_tokens": 128},
    )
    assert responds["request"].chat_request["max_tokens"] == 128


@pytest.mark.asyncio
async def test_previous_response_id_is_refused(client: AsyncClient, responds):
    """giq keeps no conversation store, so a continuation it cannot honour is
    refused rather than answered without the history it names."""
    r = await client.post(
        "/v1/responses",
        json={"model": "m", "input": "hi", "previous_response_id": "resp_old"},
    )
    assert r.status_code == 400
    assert "previous_response_id" in r.json()["detail"]


@pytest.mark.asyncio
async def test_store_true_is_refused_but_false_is_stateless(client: AsyncClient, responds):
    rejected = await client.post("/v1/responses", json={"model": "m", "input": "hi", "store": True})
    assert rejected.status_code == 400
    assert "store=true" in rejected.json()["detail"]

    accepted = await client.post(
        "/v1/responses", json={"model": "m", "input": "hi", "store": False}
    )
    assert accepted.status_code == 200


@pytest.mark.asyncio
async def test_forced_function_choice_is_renested(client: AsyncClient, responds):
    r = await client.post(
        "/v1/responses",
        json={
            "model": "m",
            "input": "use f",
            "tools": [{"type": "function", "name": "f", "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "f"},
        },
    )
    assert r.status_code == 200, r.text
    assert responds["request"].chat_request["tool_choice"] == {
        "type": "function",
        "function": {"name": "f"},
    }


@pytest.mark.asyncio
async def test_nonstreaming_length_is_incomplete(client: AsyncClient, responds):
    responds["finish_reason"] = "length"
    r = await client.post("/v1/responses", json={"model": "m", "input": "hi"})
    body = r.json()
    assert body["status"] == "incomplete"
    assert body["incomplete_details"] == {"reason": "max_output_tokens"}
    assert body["output"][0]["status"] == "incomplete"


@pytest.mark.asyncio
async def test_text_format_json_schema_reaches_the_engine(client: AsyncClient, responds):
    """Responses carries the schema under text.format; the engine wants it under
    response_format.json_schema."""
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    await client.post(
        "/v1/responses",
        json={
            "model": "m",
            "input": "hi",
            "text": {"format": {"type": "json_schema", "name": "s", "schema": schema}},
        },
    )
    rf = responds["request"].chat_request["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["schema"] == schema


@pytest.mark.asyncio
async def test_reasoning_effort_none_turns_thinking_off(client: AsyncClient, responds):
    await client.post(
        "/v1/responses", json={"model": "m", "input": "hi", "reasoning": {"effort": "none"}}
    )
    assert responds["request"].chat_request["chat_template_kwargs"] == {"enable_thinking": False}

    # An explicit chat_template_kwargs is the caller's last word.
    await client.post(
        "/v1/responses",
        json={
            "model": "m",
            "input": "hi",
            "reasoning": {"effort": "minimal"},
            "chat_template_kwargs": {"enable_thinking": True},
        },
    )
    assert responds["request"].chat_request["chat_template_kwargs"] == {"enable_thinking": True}

    await client.post(
        "/v1/responses", json={"model": "m", "input": "hi", "reasoning": {"effort": "high"}}
    )
    assert "chat_template_kwargs" not in responds["request"].chat_request


@pytest.mark.asyncio
async def test_model_is_echoed_as_the_caller_sent_it(client: AsyncClient, responds):
    r = await client.post("/v1/responses", json={"model": "giq/qwen3.8-27b", "input": "hi"})
    assert r.json()["model"] == "giq/qwen3.8-27b"
    assert responds["request"].model == "qwen3.8-27b"


@pytest.mark.asyncio
async def test_malformed_json_is_a_client_error(client: AsyncClient, responds):
    """A truncated body is the caller's mistake, not a server fault."""
    r = await client.post(
        "/v1/responses",
        content=b'{"model":"m","input":',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400
    r = await client.post(
        "/v1/responses", content=b"[1, 2]", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400
    assert "request" not in responds


@pytest.mark.asyncio
async def test_image_file_id_is_refused_by_the_endpoint(client: AsyncClient, responds):
    r = await client.post(
        "/v1/responses",
        json={
            "model": "m",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_image", "file_id": "file_abc"}],
                }
            ],
        },
    )
    assert r.status_code == 400
    assert "file_id" in r.json()["detail"]
    # Nothing was queued: the image never reached a text-only prompt.
    assert "request" not in responds


@pytest.mark.asyncio
async def test_response_object_carries_the_schema_required_fields(client: AsyncClient, responds):
    """`tools`, `tool_choice` and `parallel_tool_calls` are not optional in the
    Responses schema, and they are echoed in the Responses spelling the caller
    sent — not the Chat shape the engine received."""
    tools = [{"type": "function", "name": "f", "parameters": {"type": "object"}}]
    r = await client.post(
        "/v1/responses",
        json={
            "model": "m",
            "input": "hi",
            "tools": tools,
            "tool_choice": {"type": "function", "name": "f"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tools"] == tools
    assert body["tool_choice"] == {"type": "function", "name": "f"}
    assert body["parallel_tool_calls"] is True
    assert isinstance(body["created_at"], int)


@pytest.mark.asyncio
async def test_loop_guard_only_reaches_the_streaming_worker(client: AsyncClient, responds, streams):
    """Only the streaming worker consumes giq_loop_guard; the non-streaming path
    forwards the body verbatim, so sending it there hands llama-server a key it
    never asked for."""
    await client.post("/v1/responses", json={"model": "m", "input": "hi", "giq_loop_guard": False})
    assert "giq_loop_guard" not in responds["request"].chat_request

    await client.post(
        "/v1/responses",
        json={"model": "m", "input": "hi", "stream": True, "giq_loop_guard": False},
    )
    assert streams["request"].chat_request["giq_loop_guard"] is False


@pytest.mark.asyncio
async def test_streaming_endpoint_submits_the_translated_chat_request(client: AsyncClient, streams):
    seen = streams
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    r = await client.post(
        "/v1/responses",
        json={
            "model": "provider/qwen3.8-27b",
            "input": "hi",
            "stream": True,
            "tools": [{"type": "function", "name": "f", "parameters": {"type": "object"}}],
            "tool_choice": {"type": "function", "name": "f"},
            "text": {"format": {"type": "json_schema", "name": "answer", "schema": schema}},
        },
    )
    assert r.status_code == 200, r.text
    request = seen["request"]
    assert request.model == "qwen3.8-27b"
    assert request.chat_request["messages"] == [{"role": "user", "content": "hi"}]
    assert request.chat_request["tools"][0]["function"]["name"] == "f"
    assert request.chat_request["tool_choice"] == {
        "type": "function",
        "function": {"name": "f"},
    }
    assert request.chat_request["response_format"]["json_schema"]["schema"] == schema
    assert r.headers["content-type"].startswith("text/event-stream")


# --- the streaming relay -----------------------------------------------------


@pytest.mark.asyncio
async def test_stream_opens_and_closes_a_text_item():
    """A plain answer: created/in_progress, an item opened, text deltas, then
    the item closed and response.completed last."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(content="The "))
    stream.queue.put_nowait(delta(content="answer."))
    stream.queue.put_nowait({"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}})
    await stream.close()

    parts = await collect(FakeOrch(job), stream)
    evs = events(parts)
    types = [e["type"] for e in evs]

    assert types[0] == "response.created"
    assert types[1] == "response.in_progress"
    assert "response.output_item.added" in types
    assert "response.output_text.delta" in types
    assert types[-1] == "response.completed"
    assert parts[-1].startswith("event: response.completed\n")
    assert all("[DONE]" not in part for part in parts)

    deltas = [e["delta"] for e in evs if e["type"] == "response.output_text.delta"]
    assert "".join(deltas) == "The answer."
    completed = next(e for e in evs if e["type"] == "response.completed")
    assert completed["response"]["output"][0]["content"][0]["text"] == "The answer."
    assert completed["response"]["usage"]["output_tokens"] == 2


@pytest.mark.asyncio
async def test_stream_separates_reasoning_from_the_answer():
    """Reasoning deltas open a reasoning item and close it before the message
    item opens, so the scratchpad never pastes onto the answer."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="let me "))
    stream.queue.put_nowait(delta(reasoning_content="think"))
    stream.queue.put_nowait(delta(content="42"))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    types = [e["type"] for e in evs]
    assert "response.reasoning_text.delta" in types
    # The reasoning item is done before the message's text starts.
    assert types.index("response.reasoning_text.done") < types.index("response.output_text.delta")
    rdeltas = [e["delta"] for e in evs if e["type"] == "response.reasoning_text.delta"]
    assert "".join(rdeltas) == "let me think"


@pytest.mark.asyncio
async def test_reasoning_part_has_a_full_lifecycle():
    """A Responses client builds each item from the part events, so the part is
    opened before the text flows and closed before the item does — the raw
    thought as a reasoning_text part, the same way the answer is built."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="thinking"))
    stream.queue.put_nowait(delta(content="42"))
    await stream.close()

    types = [e["type"] for e in events(await collect(FakeOrch(job), stream))]
    assert types == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.reasoning_text.delta",
        "response.reasoning_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]


@pytest.mark.asyncio
async def test_reasoning_closes_before_a_tool_call_opens():
    """One item at a time: a thought that precedes a tool call is closed before
    the function_call item is announced."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="which tool?"))
    stream.queue.put_nowait(
        delta(tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "f"}}])
    )
    await stream.close()

    types = [e["type"] for e in events(await collect(FakeOrch(job), stream))]
    closed = types.index("response.output_item.done")
    opened_call = [i for i, t in enumerate(types) if t == "response.output_item.added"][1]
    assert closed < opened_call
    assert types.index("response.content_part.done") < closed


@pytest.mark.asyncio
async def test_reasoning_only_stream_closes_its_item():
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="thinking"))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    types = [e["type"] for e in evs]
    assert "response.reasoning_text.done" in types
    assert "response.output_item.done" in types
    assert types[-1] == "response.completed"


@pytest.mark.asyncio
async def test_answer_closes_before_a_tool_call_opens():
    """One item at a time, whatever the order: text before a tool call is a
    finished message by the time the function_call is announced."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(content="Let me check."))
    stream.queue.put_nowait(
        delta(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "f", "arguments": "{}"}}])
    )
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    shape = [(e["type"], e.get("output_index")) for e in evs]
    assert shape.index(("response.output_item.done", 0)) < shape.index(
        ("response.output_item.added", 1)
    )
    completed = evs[-1]["response"]
    assert [i["status"] for i in completed["output"]] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_reasoning_after_the_answer_is_a_new_item():
    """A thought that resumes after the answer began cannot stream into the
    reasoning item already closed; it opens its own."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="first"))
    stream.queue.put_nowait(delta(content="answer"))
    stream.queue.put_nowait(delta(reasoning_content="second"))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    added = [e["item"]["type"] for e in evs if e["type"] == "response.output_item.added"]
    assert added == ["reasoning", "message", "reasoning"]
    # Every delta lands in an item that is still open.
    open_items: set[int] = set()
    for e in evs:
        if e["type"] == "response.output_item.added":
            open_items.add(e["output_index"])
        elif e["type"] == "response.output_item.done":
            open_items.discard(e["output_index"])
        elif e["type"].endswith(".delta"):
            assert e["output_index"] in open_items, e
    output = evs[-1]["response"]["output"]
    assert [i["content"][0]["text"] for i in output] == ["first", "answer", "second"]


@pytest.mark.asyncio
async def test_only_the_last_item_is_incomplete_on_length():
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(reasoning_content="thinking"))
    stream.queue.put_nowait(delta(content="partial"))
    stream.queue.put_nowait({"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]})
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    assert evs[-1]["type"] == "response.incomplete"
    assert [i["status"] for i in evs[-1]["response"]["output"]] == ["completed", "incomplete"]


@pytest.mark.asyncio
async def test_stream_item_indices_and_ids_stay_stable():
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(content="calling "))
    stream.queue.put_nowait(
        delta(
            tool_calls=[{"index": 0, "id": "call_1", "function": {"name": "f", "arguments": "{}"}}]
        )
    )
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    added = [e for e in evs if e["type"] == "response.output_item.added"]
    assert [e["output_index"] for e in added] == [0, 1]
    ids = {e["output_index"]: e["item"]["id"] for e in added}
    associated = [
        e
        for e in evs
        if e["type"]
        in {
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.added",
            "response.content_part.done",
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }
    ]
    assert all(e["item_id"] == ids[e["output_index"]] for e in associated)
    done = [e for e in evs if e["type"] == "response.output_item.done"]
    assert all(e["item"]["id"] == ids[e["output_index"]] for e in done)
    completed = evs[-1]["response"]
    assert [item["id"] for item in completed["output"]] == [ids[0], ids[1]]


@pytest.mark.asyncio
async def test_stream_accumulates_tool_call_arguments():
    """Tool-call argument fragments stream as function_call_arguments deltas and
    accumulate into the final item."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(
        delta(
            tool_calls=[
                {"index": 0, "id": "call_1", "function": {"name": "f", "arguments": '{"a":'}}
            ]
        )
    )
    stream.queue.put_nowait(delta(tool_calls=[{"index": 0, "function": {"arguments": "1}"}}]))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    types = [e["type"] for e in evs]
    assert "response.function_call_arguments.delta" in types
    assert "response.function_call_arguments.done" in types
    done = next(e for e in evs if e["type"] == "response.function_call_arguments.done")
    assert done["arguments"] == '{"a":1}'
    completed = next(e for e in evs if e["type"] == "response.completed")
    fc = next(i for i in completed["response"]["output"] if i["type"] == "function_call")
    assert fc["call_id"] == "call_1" and fc["name"] == "f" and fc["arguments"] == '{"a":1}'


@pytest.mark.asyncio
async def test_tool_call_waits_for_its_identity_before_being_announced():
    """Chat streams can split a tool call's id, name and arguments across
    chunks. A Responses function_call item has no event that backfills call_id
    or name, so the item waits for both and the buffered arguments follow it."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(tool_calls=[{"index": 0, "function": {"arguments": '{"a":'}}]))
    stream.queue.put_nowait(delta(tool_calls=[{"index": 0, "id": "call_1"}]))
    stream.queue.put_nowait(
        delta(tool_calls=[{"index": 0, "function": {"name": "f", "arguments": "1}"}}])
    )
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    added = [e for e in evs if e["type"] == "response.output_item.added"]
    assert len(added) == 1
    assert added[0]["item"]["call_id"] == "call_1" and added[0]["item"]["name"] == "f"

    types = [e["type"] for e in evs]
    first_delta = types.index("response.function_call_arguments.delta")
    assert types.index("response.output_item.added") < first_delta
    frags = [e["delta"] for e in evs if e["type"] == "response.function_call_arguments.delta"]
    assert frags == ['{"a":', "1}"]
    completed = evs[-1]["response"]
    assert completed["output"][0]["arguments"] == '{"a":1}'


@pytest.mark.asyncio
async def test_tool_call_without_identity_fails_instead_of_emitting_a_blank():
    """Arguments for a call the engine never identified cannot be acted on."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(tool_calls=[{"index": 0, "function": {"arguments": "{}"}}]))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    assert evs[-1]["type"] == "response.failed"
    assert evs[-1]["response"]["error"]["code"] == "giq_incomplete_tool_call"
    assert not any(e["type"] == "response.output_item.added" for e in evs)
    assert not any(e["type"] == "response.completed" for e in evs)


@pytest.mark.asyncio
async def test_cancelled_generation_is_not_reported_as_completed():
    """The worker records `cancelled` on the job even when the stream ended
    without a terminal chunk. Calling that completed would hand the caller a
    truncated answer labelled as the whole one."""
    job = _job()
    job.status = JobStatus.completed
    job.results = [{"choices": [{"message": {"content": "partial"}, "finish_reason": "cancelled"}]}]
    stream = JobStream()
    stream.queue.put_nowait(delta(content="partial"))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    assert evs[-1]["type"] == "response.failed"
    assert evs[-1]["response"]["error"]["code"] == "giq_stream_cancelled"
    assert evs[-1]["response"]["output"][0]["status"] == "incomplete"
    assert not any(e["type"] == "response.completed" for e in evs)


@pytest.mark.asyncio
async def test_cancelled_partial_tool_call_fails_too():
    """The same holds mid-tool-call: half the arguments are not a callable tool."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(
        delta(
            tool_calls=[
                {"index": 0, "id": "call_1", "function": {"name": "f", "arguments": '{"a":'}}
            ]
        )
    )
    stream.cancel()
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    assert evs[-1]["type"] == "response.failed"
    assert evs[-1]["response"]["error"]["code"] == "giq_stream_cancelled"
    partial = evs[-1]["response"]["output"][0]
    assert partial["arguments"] == '{"a":' and partial["status"] == "incomplete"


@pytest.mark.asyncio
async def test_queued_stream_failed_before_it_ran_still_terminates():
    """Pausing giq fails queued jobs and closes their streams; the relay turns
    that into response.failed instead of keeping the client on keepalives."""
    job = _job()
    job.status = JobStatus.failed
    job.error = "giq is paused — job never started"
    stream = JobStream()
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    assert evs[-1]["type"] == "response.failed"
    assert "paused" in evs[-1]["response"]["error"]["message"]


@pytest.mark.asyncio
async def test_every_event_reports_the_same_response_identity():
    """One response, one creation time: the fields are settled when the request
    is accepted, not recomputed per event."""
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(content="hi"))
    await stream.close()

    tools = [{"type": "function", "name": "f", "parameters": {"type": "object"}}]
    evs = events(await collect(FakeOrch(job), stream, tools=tools))
    carried = [e["response"] for e in evs if "response" in e]
    assert len(carried) >= 3
    for response in carried:
        assert response["id"] == "resp_x"
        assert response["created_at"] == 1_700_000_000
        assert response["tools"] == tools
        assert response["tool_choice"] == "auto"
        assert response["parallel_tool_calls"] is True
    # Token counts only exist once the engine's final chunk has arrived.
    assert "usage" not in carried[0]
    assert "usage" in carried[-1]


@pytest.mark.asyncio
async def test_stream_failure_becomes_response_failed():
    """A failure after the first event rides the stream as response.failed, not
    a silent truncation."""
    job = _job()
    job.status = JobStatus.failed
    job.error = "Job timed out after 300s"
    stream = JobStream()
    stream.queue.put_nowait(delta(content="partial"))
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    failed = next(e for e in evs if e["type"] == "response.failed")
    assert "timed out" in failed["response"]["error"]["message"]
    assert failed["response"]["output"][0]["status"] == "incomplete"
    assert not any(e["type"] == "response.output_item.done" for e in evs)
    assert not any(e["type"] == "response.completed" for e in evs)


@pytest.mark.asyncio
async def test_stream_length_becomes_response_incomplete():
    job = _job()
    job.status = JobStatus.completed
    stream = JobStream()
    stream.queue.put_nowait(delta(content="partial"))
    stream.queue.put_nowait({"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]})
    await stream.close()

    evs = events(await collect(FakeOrch(job), stream))
    terminal = evs[-1]
    assert terminal["type"] == "response.incomplete"
    assert terminal["response"]["incomplete_details"] == {"reason": "max_output_tokens"}
    assert terminal["response"]["output"][0]["status"] == "incomplete"


@pytest.mark.asyncio
async def test_stream_cancels_the_job_when_the_client_walks_away():
    from giq.api.openai_responses import _relay_responses_stream

    job = _job()
    job.status = JobStatus.running
    stream = JobStream()
    stream.queue.put_nowait(delta(content="one"))
    orch = FakeOrch(job)

    gen = _relay_responses_stream(orch, "j1", stream, meta())
    await gen.__anext__()
    await gen.aclose()

    assert stream.is_cancelled
    assert orch.cancelled == ["j1"]

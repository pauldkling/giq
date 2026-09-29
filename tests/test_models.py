# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from giq.models import (
    Capabilities,
    ImageEditTask,
    ImageResult,
    JobRequest,
    JobResponse,
    JobResult,
    JobStatus,
    JobStatusResponse,
    LLMResult,
    LLMTask,
    ServiceState,
    ServiceStatus,
    Task,
    Text2ImageTask,
    WorkerCapability,
    WorkerType,
)


def test_worker_type_values():
    """Test WorkerType enum values."""
    assert WorkerType.llm == "llm"
    assert WorkerType.text2image == "text2image"
    assert WorkerType.image_edit == "image_edit"
    assert WorkerType.tts == "tts"
    assert WorkerType.stt == "stt"
    assert WorkerType.depth == "depth"
    assert WorkerType.multiview == "multiview"


def test_job_status_values():
    """Test JobStatus enum values."""
    assert JobStatus.pending == "pending"
    assert JobStatus.running == "running"
    assert JobStatus.completed == "completed"
    assert JobStatus.failed == "failed"


def test_task_minimal():
    """Test Task (LLMTask) with minimal fields."""
    task = Task(id="t1", user="Hello")
    assert task.id == "t1"
    assert task.user == "Hello"
    assert task.system is None
    assert task.params is None


def test_task_full():
    """Test Task (LLMTask) with all fields."""
    task = Task(
        id="t1",
        system="You are helpful.",
        user="Hello",
        params={"temperature": 0.7},
    )
    assert task.system == "You are helpful."
    assert task.params == {"temperature": 0.7}


def test_llm_task():
    """Test LLMTask model."""
    task = LLMTask(id="t1", system="Be helpful", user="Hello")
    assert task.id == "t1"
    assert task.system == "Be helpful"


def test_text2image_task():
    """Test Text2ImageTask model."""
    task = Text2ImageTask(id="img1", prompt="A sunset", negative_prompt="blurry", seed=42)
    assert task.id == "img1"
    assert task.prompt == "A sunset"
    assert task.negative_prompt == "blurry"
    assert task.seed == 42


def test_image_edit_task():
    """Test ImageEditTask model."""
    task = ImageEditTask(
        id="edit1",
        reference_image_b64="base64data",
        instruction="Make it blue",
        negative_prompt="ugly",
    )
    assert task.id == "edit1"
    assert task.reference_image_b64 == "base64data"
    assert task.instruction == "Make it blue"


def test_job_request():
    """Test JobRequest model with dict tasks."""
    request = JobRequest(
        worker=WorkerType.llm,
        model="gemma-3-27b",
        tasks=[{"id": "t1", "user": "Hello"}],
    )
    assert request.worker == WorkerType.llm
    assert request.model == "gemma-3-27b"
    assert len(request.tasks) == 1


def test_job_request_with_params():
    """Test JobRequest with params."""
    request = JobRequest(
        worker=WorkerType.text2image,
        model="zimage",
        model_path="/path/to/model",
        params={"width": 512, "height": 512},
        tasks=[{"id": "img1", "prompt": "A sunset"}],
    )
    assert request.model_path == "/path/to/model"
    assert request.params["width"] == 512


def test_job_request_invalid_worker():
    """Test JobRequest with invalid worker type."""
    with pytest.raises(ValidationError):
        JobRequest(
            worker="invalid",
            model="test",
            tasks=[{"id": "t1", "user": "Hello"}],
        )


def test_job_response():
    """Test JobResponse model."""
    response = JobResponse(job_id="abc123", position=5)
    assert response.job_id == "abc123"
    assert response.position == 5


def test_llm_result():
    """Test LLMResult model."""
    result = LLMResult(id="t1", output="Hello world", tokens=10)
    assert result.id == "t1"
    assert result.output == "Hello world"
    assert result.tokens == 10
    assert result.error is None


def test_llm_result_with_error():
    """Test LLMResult with error."""
    result = LLMResult(id="t1", output="", error="Something went wrong")
    assert result.error == "Something went wrong"


def test_job_result_alias():
    """Test JobResult is alias for LLMResult."""
    result = JobResult(id="t1", output="Hello world", tokens=10)
    assert isinstance(result, LLMResult)


def test_image_result():
    """Test ImageResult model."""
    result = ImageResult(id="img1", image_b64="base64data", seed=12345)
    assert result.id == "img1"
    assert result.image_b64 == "base64data"
    assert result.seed == 12345
    assert result.error is None


def test_image_result_with_error():
    """Test ImageResult with error."""
    result = ImageResult(id="img1", error="GPU OOM")
    assert result.image_b64 is None
    assert result.error == "GPU OOM"


def test_job_status_response():
    """Test JobStatusResponse model."""
    response = JobStatusResponse(
        job_id="abc123",
        status=JobStatus.completed,
        worker=WorkerType.llm,
        model="gemma-3-27b",
        results=[{"id": "t1", "output": "Hello", "tokens": 5, "error": None}],
        duration_ms=1500,
    )
    assert response.status == JobStatus.completed
    assert len(response.results) == 1
    assert response.duration_ms == 1500


def test_service_status():
    """Test ServiceStatus model."""
    status = ServiceStatus(
        state=ServiceState.idle,
        active_worker=WorkerType.llm,
        active_model="gemma-3-27b",
        vram_used_gb=18.5,
        vram_total_gb=32.0,
        vram_free_gb=13.5,
        vram_ok=True,
        queue_depth=3,
        jobs_pending=["job1", "job2", "job3"],
    )
    assert status.active_worker == WorkerType.llm
    assert status.vram_used_gb == 18.5
    assert len(status.jobs_pending) == 3


def test_worker_capability():
    """Test WorkerCapability model."""
    cap = WorkerCapability(
        backend="llama.cpp",
        models=["gemma-3-27b", "qwen-7b"],
        max_batch=32,
    )
    assert cap.backend == "llama.cpp"
    assert len(cap.models) == 2
    assert cap.max_batch == 32
    assert cap.voices is None


def test_worker_capability_tts():
    """Test WorkerCapability for TTS."""
    cap = WorkerCapability(
        backend="kokoro",
        models=["kokoro-82m"],
        voices=["af_heart", "am_adam"],
    )
    assert cap.voices == ["af_heart", "am_adam"]


def test_capabilities():
    """Test Capabilities model."""
    caps = Capabilities(
        workers={
            WorkerType.llm: WorkerCapability(
                backend="llama.cpp",
                models=["gemma-3-27b"],
            ),
        },
        constraints={"max_concurrent_heavy": 1},
    )
    assert WorkerType.llm in caps.workers
    assert caps.constraints["max_concurrent_heavy"] == 1

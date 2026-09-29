# SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for job queue."""

import pytest

from giq.models import JobRequest, JobStatus, WorkerType
from giq.queue import Job, JobQueue


@pytest.fixture
def queue():
    """Create a fresh queue for each test."""
    return JobQueue()


def make_job(job_id: str, worker: WorkerType = WorkerType.llm) -> Job:
    """Helper to create a test job."""
    return Job(
        job_id=job_id,
        request=JobRequest(
            worker=worker,
            model="test-model",
            tasks=[{"id": "t1", "user": "test"}],
        ),
    )


@pytest.mark.asyncio
async def test_add_job(queue: JobQueue):
    """Test adding a job to the queue."""
    job = make_job("job1")
    position = await queue.add(job)
    assert position == 0
    assert len(queue) == 1


@pytest.mark.asyncio
async def test_add_multiple_jobs(queue: JobQueue):
    """Test adding multiple jobs."""
    job1 = make_job("job1")
    job2 = make_job("job2")
    job3 = make_job("job3")

    pos1 = await queue.add(job1)
    pos2 = await queue.add(job2)
    pos3 = await queue.add(job3)

    assert pos1 == 0
    assert pos2 == 1
    assert pos3 == 2
    assert len(queue) == 3


@pytest.mark.asyncio
async def test_get_job(queue: JobQueue):
    """Test getting a job by ID."""
    job = make_job("job1")
    await queue.add(job)

    retrieved = await queue.get("job1")
    assert retrieved is not None
    assert retrieved.job_id == "job1"


@pytest.mark.asyncio
async def test_get_nonexistent_job(queue: JobQueue):
    """Test getting a job that doesn't exist."""
    retrieved = await queue.get("nonexistent")
    assert retrieved is None


@pytest.mark.asyncio
async def test_remove_job(queue: JobQueue):
    """Test removing a job."""
    job = make_job("job1")
    await queue.add(job)
    assert len(queue) == 1

    removed = await queue.remove("job1")
    assert removed is True
    assert len(queue) == 0


@pytest.mark.asyncio
async def test_remove_nonexistent_job(queue: JobQueue):
    """Test removing a job that doesn't exist."""
    removed = await queue.remove("nonexistent")
    assert removed is False


@pytest.mark.asyncio
async def test_get_pending(queue: JobQueue):
    """Test getting pending jobs."""
    job1 = make_job("job1")
    job2 = make_job("job2")
    job3 = make_job("job3")

    await queue.add(job1)
    await queue.add(job2)
    await queue.add(job3)

    # Mark one as running
    job2.status = JobStatus.running

    pending = await queue.get_pending()
    assert len(pending) == 2
    assert all(j.status == JobStatus.pending for j in pending)


@pytest.mark.asyncio
async def test_get_next(queue: JobQueue):
    """Test getting next pending job."""
    job1 = make_job("job1")
    job2 = make_job("job2")

    await queue.add(job1)
    await queue.add(job2)

    next_job = await queue.get_next()
    assert next_job is not None
    assert next_job.job_id == "job1"


@pytest.mark.asyncio
async def test_get_next_empty_queue(queue: JobQueue):
    """Test getting next from empty queue."""
    next_job = await queue.get_next()
    assert next_job is None


@pytest.mark.asyncio
async def test_job_duration(queue: JobQueue):
    """Test job duration calculation."""
    from datetime import datetime, timedelta

    job = make_job("job1")
    job.started_at = datetime.now()
    job.completed_at = job.started_at + timedelta(milliseconds=1500)

    assert job.duration_ms == 1500


def test_job_duration_not_completed():
    """Test duration when job not completed."""
    job = make_job("job1")
    assert job.duration_ms is None

<!--
SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)

SPDX-License-Identifier: Apache-2.0
-->

# ADR-001: GPU Queue Ontology

**Status:** Draft (Revised)  
**Date:** 2026-02-13  
**Authors:** giq maintainers

## Context

We need a GPU worker management service that:
- Manages a single GPU (RTX 5090, 32GB VRAM)
- Serves multiple clients (a document pipeline, a voice UI, future projects)
- Minimizes model swapping (expensive: 10-30s per swap)
- Handles mixed workloads (LLM, image generation, TTS)

**Key design principle:** Keep it simple. Clients own their pipeline logic; this service just runs batches.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Clients (own their pipeline logic)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Document   │  │  Voice UI   │  │   Future    │          │
│  │  pipeline   │  │             │  │  projects   │          │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘          │
└─────────┼────────────────┼────────────────┼─────────────────┘
          │                │                │
          │  POST /run     │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│  gpu-queue (worker management only)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │ VRAM     │  │  Job     │  │  Worker  │                   │
│  │ Gating   │  │  Queue   │  │  Runner  │                   │
│  └──────────┘  └──────────┘  └──────────┘                   │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│  GPU Workers (one heavy worker at a time)                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │   LLM    │  │  Image   │  │   TTS    │                   │
│  │llama.cpp │  │ diffusion│  │  Kokoro  │                   │
│  └──────────┘  └──────────┘  └──────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

## What gpu-queue Does

1. **Worker lifecycle** — Load/unload models on demand
2. **VRAM gating** — Only one GPU-heavy worker at a time
3. **Batch execution** — Run multiple prompts while model is warm
4. **Job tracking** — Status reporting, results storage
5. **Capability reporting** — Tell clients what's available

## What gpu-queue Does NOT Do

- ❌ Pipeline orchestration (client's job)
- ❌ Task dependencies (client's job)
- ❌ Prompt templates (client's job)
- ❌ Domain logic (client's job)

## Core Concepts

### Job

A batch of work submitted by a client. Runs on a single worker with a single model.

```python
# Submit a job
POST /run
{
  "worker": "llm",                     # which worker type
  "model": "gemma-3-27b-it-qat",       # which model to load
  "model_path": "~/.lmstudio/...",     # optional: explicit path
  "params": {                          # worker-specific params
    "temperature": 0.7,
    "max_tokens": 1500
  },
  "tasks": [                           # batch of prompts
    {"id": "t1", "system": "...", "user": "..."},
    {"id": "t2", "system": "...", "user": "..."},
    {"id": "t3", "system": "...", "user": "..."}
  ]
}
→ {"job_id": "abc123", "position": 2}
```

### Worker

Runtime process that executes jobs. Types:

| Worker | Backend | VRAM | Notes |
|--------|---------|------|-------|
| `llm` | llama.cpp | ~15-20GB | Hot-swappable models |
| `image` | diffusion | ~12-18GB | Z-Image, Qwen-Image |
| `tts` | Kokoro | ~1GB | Lightweight, may coexist |
| `stt` | Whisper | ~2-4GB | Future |

**Constraint:** Only one GPU-heavy worker active at a time (LLM or Image, not both).

### Job States

```
pending → running → completed
                 └→ failed
```

Simple. No blocked/ready complexity — that's the client's problem.

## API

### POST /run

Submit a job for execution.

```json
{
  "worker": "llm",
  "model": "gemma-3-27b-it-qat",
  "params": {"temperature": 0.7},
  "tasks": [
    {"id": "a", "system": "You are...", "user": "Summarize..."}
  ]
}
```

Response:
```json
{"job_id": "xyz", "position": 0}
```

### GET /jobs/{id}

Check job status and get results.

```json
{
  "job_id": "xyz",
  "status": "completed",
  "worker": "llm",
  "model": "gemma-3-27b-it-qat",
  "results": [
    {"id": "a", "output": "...", "tokens": 342}
  ],
  "duration_ms": 1523
}
```

### DELETE /jobs/{id}

Cancel a pending job (best-effort).

### GET /status

Service status and current state.

```json
{
  "active_worker": "llm",
  "active_model": "gemma-3-27b-it-qat",
  "vram_used_gb": 18.4,
  "vram_total_gb": 32.0,
  "queue_depth": 3,
  "jobs_pending": ["job1", "job2", "job3"]
}
```

### GET /capabilities

What can this service do? (For client discovery)

```json
{
  "workers": {
    "llm": {
      "backend": "llama.cpp",
      "models": ["gemma-3-27b-it-qat", "qwen-7b", "qwen-coder-30b"],
      "max_batch": 32
    },
    "image": {
      "backend": "diffusion",
      "models": ["zimage-turbo", "qwen-image"],
      "max_batch": 8
    },
    "tts": {
      "backend": "kokoro",
      "models": ["kokoro-82m"],
      "voices": ["af_heart", "am_adam", "af_bella"]
    }
  },
  "constraints": {
    "max_concurrent_heavy": 1,
    "vram_total_gb": 32
  }
}
```

## Execution Flow

```
┌────────────────────────────────────────────────────────────────┐
│  Client (e.g., a document pipeline)                            │
│                                                                │
│  1. Orchestrator decides: "I need to run 3 summaries"          │
│  2. POST /run {worker: llm, model: gemma, tasks: [...]}        │
│  3. Poll GET /jobs/{id} until completed                        │
│  4. Use results, decide next step (maybe image gen)            │
│  5. POST /run {worker: image, model: zimage, tasks: [...]}     │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  gpu-queue                                                     │
│                                                                │
│  1. Receive job, add to queue                                  │
│  2. If model not loaded → unload current, load requested       │
│  3. Execute batch                                              │
│  4. Store results, update status                               │
│  5. If queue empty + timeout → unload model (save VRAM)        │
└────────────────────────────────────────────────────────────────┘
```

## Model Warm Timeout

When a model is loaded but no jobs pending:
- Keep model warm for `WARM_TIMEOUT` seconds (default: 120)
- If new job arrives for same model → instant execution
- If timeout expires → unload model, free VRAM
- If new job arrives for different model → immediate swap

## Decisions

### D1: Clients own pipeline logic

A client keeps its chain configs, orchestrator, and prompt templates. gpu-queue doesn't know what a "summarizer" or "scene_describer" is — it just runs prompts.

### D2: Simple job model

No task dependencies, no blocked states. A job is a batch that runs atomically. Client decides sequencing.

### D3: Single GPU-heavy worker constraint

Only LLM OR Image active, never both. TTS may coexist if VRAM allows.

### D4: Model-based batching is client's responsibility

If client wants to batch multiple summarize requests, it combines them into one job. gpu-queue doesn't merge jobs.

### D5: Capability discovery

`GET /capabilities` lets clients discover what's available without hardcoding.

## File Structure

```
giq/
├── pyproject.toml
├── docs/
│   └── ADR-001-ontology.md
├── src/
│   ├── __init__.py
│   ├── main.py               # FastAPI app
│   ├── models.py             # Job, Worker types
│   ├── queue.py              # Job queue
│   ├── runner.py             # Worker process management
│   ├── vram.py               # nvidia-smi wrapper
│   └── workers/
│       ├── llm.py            # llama.cpp integration
│       ├── image.py          # diffusion integration
│       └── tts.py            # kokoro integration
└── config/
    └── workers.yaml          # model paths, defaults
```

## Open Questions

1. **TTS coexistence** — Can Kokoro stay loaded alongside LLM?
2. **Model paths** — Hardcode in config or pass per-job?
3. **Timeout tuning** — 120s warm timeout? Configurable?
4. **Authentication** — Needed for multi-client? Or trust localhost?

## Name

**giq** — GPU Inference Queue

Short, memorable, 3 letters. Pronounced "geek" or "gee-eye-queue".

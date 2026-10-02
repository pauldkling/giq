// SPDX-FileCopyrightText: 2026 vikworks UG (haftungsbeschränkt)
//
// SPDX-License-Identifier: Apache-2.0

/* Response shapes of every endpoint the dashboard calls, transcribed from
   giq's routers (src/giq/api/*.py) and pydantic models (src/giq/models.py).
   Nullable where the server can send null — nvidia-smi reports [N/A] for
   telemetry a card does not expose, and SQL aggregates over no rows are
   NULL — so the type checker makes views handle the missing reading. */

export type WorkerType =
  | "llm"
  | "text2image"
  | "image_edit"
  | "tts"
  | "stt"
  | "audio"
  | "embed"
  | "ocr"
  | "depth"
  | "multiview";

export const WORKER_TYPES: readonly WorkerType[] = [
  "llm",
  "text2image",
  "image_edit",
  "audio",
  "embed",
  "tts",
  "stt",
  "ocr",
  "depth",
  "multiview",
];

export type JobStatus = "pending" | "running" | "completed" | "failed";
export type ServiceState = "idle" | "ready" | "running" | "blocked" | "paused" | "error";
export type Policy = "pinned" | "auto" | "off";
export type Fit = "loaded" | "fits_now" | "fits_after_eviction" | "wont_fit_now" | "never";

// --- GET /status -------------------------------------------------------------

export interface AccessPosture {
  bound_host: string;
  reachable: string;
  loopback_only: boolean;
  token_set: boolean;
  /** Reachable beyond loopback with no token. */
  exposed: boolean;
}

export interface ActiveSlot {
  /** GPU UUID the sleepy worker sits on. */
  device: string | null;
  worker: string;
  model: string;
  ready: boolean;
}

export interface StatusGpu {
  uuid: string;
  index: number;
  name: string;
  selected: boolean;
  vram_used_gb: number;
  vram_total_gb: number;
  vram_free_gb: number;
  vram_giq_gb: number | null;
  vram_other_gb: number | null;
}

export interface Status {
  state: ServiceState;
  state_message: string | null;
  active_worker: WorkerType | null;
  active_model: string | null;
  active: ActiveSlot[];
  /** The ONE card the vram_* figures below describe (giq's default card). */
  gpu: { uuid: string; index: number; name: string } | null;
  vram_used_gb: number;
  vram_total_gb: number;
  vram_free_gb: number;
  vram_giq_gb: number | null;
  vram_other_gb: number | null;
  /** False while a pending job waits for room on its own card. */
  vram_ok: boolean;
  vram_message: string | null;
  /** The card (a `gpus` uuid) a blocked job is waiting on. */
  vram_blocked_gpu: string | null;
  /** Every card, in the terms of the one-card vram_* fields above. */
  gpus: StatusGpu[];
  queue_depth: number;
  /** Job ids, queue order. */
  jobs_pending: string[];
  jobs_running: string[];
  access: AccessPosture | null;
  paused: boolean;
  /** ISO 8601. */
  paused_since: string | null;
  pause_reason: string | null;
  /** giq's package version. */
  version: string;
  /** Seconds since the process started. */
  uptime_s: number;
}

// --- GET /gpus ---------------------------------------------------------------

export type ThrottleSeverity = "info" | "warning" | "critical";

export interface GpuProcess {
  pid: number;
  /** worker/model, or giq itself. */
  label: string;
  gb: number;
}

export interface Gpu {
  uuid: string;
  index: number;
  name: string;
  vram_total_gb: number;
  vram_used_gb: number;
  vram_free_gb: number;
  temperature_c: number | null;
  power_draw_w: number | null;
  power_limit_w: number | null;
  utilization_pct: number | null;
  fan_pct: number | null;
  throttle: { reason: string; severity: ThrottleSeverity }[];
  /** giq's default card. */
  selected: boolean;
  /** Held by giq's processes; with vram_other_gb sums to vram_used_gb. */
  vram_giq_gb: number;
  /** Everything else on the card (desktop, other CUDA apps). */
  vram_other_gb: number;
  giq: GpuProcess[];
}

export interface GpusResponse {
  selected: string | null;
  gpus: Gpu[];
}

// --- GET /stats/models (the catalog) ------------------------------------------

export interface CatalogModel {
  worker: WorkerType;
  model: string;
  vram_gb: number;
  /** vram_gb plus margin and the card's reserve: what a load is gated on. */
  needed_gb: number;
  measured: boolean;
  backend: string;
  /** Image models: "sd.cpp" (the same as backend); null otherwise. */
  engine: string | null;
  label: string;
  detail: string;
  lanes: number;
  resident: boolean;
  /** Meant to be resident by configuration, whatever the operator did since. */
  resident_default: boolean;
  /** Loaded and serving now. */
  ready: boolean;
  fits: Fit;
  policy: Policy;
  policy_source: "override" | "default";
  policy_reason: string | null;
  /** LLMs: whether giq launches it with thinking on. */
  reasoning: "on" | "off" | "template" | null;
  vision: boolean;
  /** Engine binary that executes it (key into /engines). */
  runtime: string;
  /** Explicit binding (GPU UUID), null when unbound. */
  device: string | null;
  device_source: "override" | "config" | "default";
  /** Card it lands on either way. */
  effective_device: string | null;
  device_index: number | null;
  device_name: string | null;
}

export interface CardBudget {
  uuid: string;
  index: number;
  name: string;
  total_gb: number;
  free_gb: number;
  reserve_gb: number;
  pinned_gb: number;
  pinned_needed_gb: number;
  pinned_fits: boolean;
  /** worker/model keys pinned to this card. */
  pinned: string[];
  default: boolean;
}

export interface Catalog {
  cards: CardBudget[];
  free_gb: number;
  total_gb: number;
  evictable_gb: number;
  pinned_gb: number;
  pinned_needed_gb: number;
  pinned_fits: boolean;
  pinned_device: string | null;
  pinned_by_device: Record<string, string[]>;
  /** Reload priority order. */
  pinned: string[];
  models: CatalogModel[];
}

// --- GET /storage, DELETE /storage/models/{w}/{m} ----------------------------

export interface Disk {
  mount: string;
  total_bytes: number;
  free_bytes: number;
  models_bytes: number;
  other_bytes: number;
}

export interface StorageModel {
  worker: WorkerType;
  model: string;
  size_bytes: number;
  on_disk: boolean;
  /** Other worker/model keys sharing these files. */
  shared_with: string[];
  resident: boolean;
  /** Epoch seconds of the last completed job. */
  last_used: number | null;
  paths: string[];
}

/** An operator recipe file that is serving. */
export interface InstanceFile {
  file: string;
  worker: WorkerType;
  name: string;
  /** Replaces the built-in recipe of the same worker and name. */
  replaces_builtin: boolean;
}

/** An operator recipe file giq left out, and why. */
export interface InstanceLoadError {
  /** Null when the problem is not one file's (two files defining one recipe). */
  file: string | null;
  message: string;
}

/** The operator's recipe files, as the running snapshot read them. */
export interface RecipesInfo {
  dir: string | null;
  builtin_dir: string;
  files: InstanceFile[];
  /** "worker/name" of each built-in an operator file replaces. */
  overrides: string[];
  errors: InstanceLoadError[];
}

export interface StorageResponse {
  disks: Disk[];
  models: StorageModel[];
  /** Absent from a giq older than recipe files. */
  recipes?: RecipesInfo;
}

export interface DeleteWeightsResponse {
  worker: string;
  model: string;
  deleted: string[];
  skipped_shared: { path: string; shared_with: string[] }[];
  missing: string[];
  freed_bytes: number;
}

// --- GET /engines --------------------------------------------------------------

export interface Engine {
  name: string;
  binary: string | null;
  detail?: string;
  present: boolean;
  version: string | null;
  error: string | null;
}

export interface EnginesResponse {
  engines: Engine[];
}

// --- /control -----------------------------------------------------------------

export interface PauseRequest {
  force?: boolean;
  reason?: string | null;
}

export interface PauseResponse {
  paused: boolean;
  since: string | null;
  reason: string | null;
  forced: boolean;
  drained: boolean;
  warnings: string[];
  vram_free_gb: number;
  vram_total_gb: number;
}

export interface ModelPolicyState {
  worker: string;
  model: string;
  policy: Policy;
  source: "override" | "default";
  reason: string | null;
  updated_at: number | null;
  vram_gb: number;
  ready: boolean;
  device: string | null;
  device_source: string;
  effective_device: string | null;
  device_index: number | null;
  device_name: string | null;
}

/** POST /control/models/{w}/{m} {policy, reason?, force?} and …/device {device, force?}. */
export interface ModelPolicyResponse {
  state: ModelPolicyState;
  pinned: string[];
  pinned_vram_gb: number;
  vram_total_gb: number;
  pinned_by_device: Record<string, string[]>;
  warnings: string[];
}

// --- jobs ------------------------------------------------------------------------

export interface JobRequest {
  modality: WorkerType;
  model: string;
  params?: Record<string, unknown>;
  tasks: Record<string, unknown>[];
}

/** POST /run (without wait). */
export interface JobSubmitted {
  job_id: string;
  position: number;
}

/** GET /jobs/{id}, POST /run?wait=true. Results are per worker (image_b64/seed/error, output, …). */
export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  modality: WorkerType;
  model: string;
  results: Record<string, unknown>[] | null;
  duration_ms: number | null;
}

/** DELETE /jobs/{id}: only pending jobs cancel. 404 when unknown. */
export interface CancelResponse {
  cancelled: boolean;
  reason?: string;
}

// --- /stats --------------------------------------------------------------------

/** GET /stats/summary?hours= */
export interface StatsSummary {
  hours: number;
  evictions: number;
  models: {
    worker: WorkerType;
    model: string;
    jobs: number;
    failed: number;
    avg_run_ms: number | null;
    max_run_ms: number | null;
    avg_queue_ms: number | null;
    tasks: number | null;
  }[];
}

/** GET /stats/timeline?hours=&bucket_s= */
export interface StatsTimeline {
  bucket_s: number;
  points: {
    /** Bucket start, epoch seconds. */
    t: number;
    worker: WorkerType;
    jobs: number;
    failed: number;
    avg_run_ms: number | null;
  }[];
}

/** GET /stats/vram?hours= (the default card). */
export interface StatsVram {
  total_gb: number;
  samples: { t: number; used: number; active: string | null; ready: number }[];
}

/** GET /stats/gpus?hours= */
export interface StatsGpus {
  hours: number;
  gpus: {
    uuid: string;
    index: number | null;
    name: string;
    total_gb: number;
    power_limit: number | null;
    samples: {
      t: number;
      used: number;
      temp: number | null;
      power: number | null;
      util: number | null;
    }[];
  }[];
}

/** GET /stats/gpus/eras */
export interface GpuEra {
  uuid: string;
  name: string;
  total_gb: number;
  first_seen: number;
  last_seen: number;
  jobs: number;
  failed: number;
  tokens_in: number | null;
  tokens_out: number | null;
  avg_run_ms: number | null;
  first_job: number | null;
  last_job: number | null;
}

export interface GpuErasResponse {
  eras: GpuEra[];
}

export type UsagePeriod = "day" | "week" | "month" | "all";

/** GET /stats/usage?period=&gpu=&since=&until= */
export interface StatsUsage {
  period: UsagePeriod;
  gpu: string | null;
  since: number;
  until: number | null;
  totals: { jobs: number; failed: number; tokens_in: number; tokens_out: number };
  models: {
    worker: WorkerType;
    model: string;
    jobs: number;
    failed: number;
    tasks: number | null;
    tokens_in: number | null;
    tokens_out: number | null;
    last_ts: number | null;
  }[];
  /** `b` is a local-time bucket key: "YYYY-MM-DD HH:00" (day), "YYYY-MM-DD" (week/month), "YYYY-MM" (all). */
  series: {
    b: string;
    worker: WorkerType;
    model: string;
    jobs: number;
    tokens_in: number | null;
    tokens_out: number | null;
  }[];
}

/** GET /stats/jobs?limit=&gpu= — newest first. */
export interface JobRecord {
  t: number;
  job_id: string;
  worker: WorkerType;
  model: string;
  status: JobStatus | string;
  queue_ms: number | null;
  run_ms: number | null;
  tasks: number | null;
  error: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}

/** GET /stats/events?hours=&limit= */
export interface StatsEvent {
  t: number;
  kind: string;
  detail: string;
}

// --- GET /capabilities -------------------------------------------------------------

export interface Capabilities {
  workers: Partial<
    Record<
      WorkerType,
      { backend: string; models: string[]; max_batch: number | null; voices: string[] | null }
    >
  >;
  constraints: Record<string, unknown>;
}

// --- /v1 (OpenAI-compatible) ---------------------------------------------------------

export interface V1Models {
  object: "list";
  data: { id: string; object: "model"; created: number; owned_by: string }[];
}

export type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } };

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | ChatContentPart[] | null;
  tool_calls?: ToolCall[];
  tool_call_id?: string;
  reasoning_content?: string;
}

export interface ToolCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export interface ChatUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** One SSE chunk of POST /v1/chat/completions with stream: true. */
export interface ChatChunk {
  id?: string;
  model?: string;
  choices?: {
    index: number;
    delta?: { role?: string; content?: string | null; reasoning_content?: string | null };
    finish_reason?: string | null;
  }[];
  usage?: ChatUsage | null;
}

/** Non-streaming POST /v1/chat/completions. */
export interface ChatCompletion {
  id: string;
  model: string;
  choices: {
    index: number;
    message: ChatMessage;
    finish_reason: string | null;
  }[];
  usage?: ChatUsage;
}

/** POST /v1/audio/transcriptions (json / verbose_json). */
export interface Transcription {
  task?: "transcribe";
  text: string;
  language: string | null;
  duration: number | null;
  speakers: string[];
  segments: {
    start: number;
    end: number;
    text: string;
    speaker: string | null;
    language?: string | null;
    words?: unknown[];
  }[];
}

/** POST /v1/audio/embeddings. */
export interface AudioEmbedding {
  embedding: number[];
  dim: number;
  model: string;
  normalized: boolean;
}

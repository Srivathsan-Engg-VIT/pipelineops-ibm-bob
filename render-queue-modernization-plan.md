# Render Queue Modernization Plan

## Overview

`legacy/render_queue.py` is a single-file, synchronous render farm dispatcher written without type safety, structured logging, retry discipline, or any worker abstraction. The goal of this plan is to modernize it in four focused, independently reviewable stages:

1. **Type safety** — replace bare dicts with typed data models so every field is validated and discoverable.
2. **Retry with backoff and alerting** — replace the silent infinite-requeue loop with a capped retry strategy using exponential backoff, and fire an alert when a job exhausts its retries.
3. **Structured logging** — replace `print()` calls and raw file-appends with structured, machine-readable log output.
4. **GPU-aware worker pool** — replace the hardcoded 3-string list with a dynamic pool that discovers workers, tracks GPU availability, and routes jobs accordingly.

The existing file lives at [`legacy/render_queue.py`](legacy/render_queue.py). The refactored code will live at `render_queue/` (a proper package), keeping the legacy file untouched as a reference.

---

## Sub-Task 1 — Introduce Typed Data Models

**Status:** `[x] done`

### Intent
All data in the current code is stored in plain `dict` objects with string keys and no validation. Fields like `shot`, `frames`, `priority`, `status`, and `worker` are accessed by magic strings throughout the code. Introducing typed models (dataclasses or Pydantic) will make fields explicit, enable IDE autocompletion, and catch schema errors at construction time rather than silently at runtime.

### Expected Outcomes
- A `RenderJob` model with fields: `shot: str`, `frames: int`, `priority: int`, `status: JobStatus` (enum), `worker: str | None`, `retry_count: int`, `error: str | None`.
- A `Worker` model with fields: `name: str`, `status: WorkerStatus` (enum), `gpu_memory_mb: int | None`.
- A `JobStatus` enum covering: `QUEUED`, `RUNNING`, `DONE`, `FAILED`.
- A `WorkerStatus` enum covering: `IDLE`, `BUSY`, `OFFLINE`.
- All existing functions that create or mutate jobs/workers updated to use these models.
- The `data/render_status.json` schema aligns with the new models (add `retry_count` and `error` fields).

### Todo List
- [ ] Create `render_queue/models.py` with `JobStatus`, `WorkerStatus` enums and `RenderJob`, `Worker` dataclasses (or Pydantic models).
- [ ] Add `retry_count: int = 0` and `error: str | None = None` to `RenderJob` — these fields are needed by Sub-Task 2 and are already implied by `data/render_status.json`.
- [ ] Rewrite `add_job()` to construct and return a `RenderJob` instance instead of a bare dict.
- [ ] Rewrite `find_idle_worker()` to work over `Worker` objects and check `worker.status == WorkerStatus.IDLE`.
- [ ] Update `dispatch()` to operate on typed objects throughout.
- [ ] Add `requirements.txt` or `pyproject.toml` declaring the new dependencies (pydantic or dataclasses-json if chosen).

### Relevant Context
- [`legacy/render_queue.py:9-12`](legacy/render_queue.py) — `QUEUE`, `WORKERS`, `worker_status` globals are the targets of this change.
- [`legacy/render_queue.py:17-25`](legacy/render_queue.py) — `add_job()` manually builds a dict; this becomes a model constructor call.
- [`data/render_status.json`](data/render_status.json) — already includes `error` and `null` worker fields; the model should match this schema.

---

## Sub-Task 2 — Replace Silent Retry with Capped Backoff and Alerting

**Status:** `[x] done`

### Intent
The current failure path (lines 57–58) silently re-sets `job["status"] = "queued"` with no retry counter, no delay, and no upper bound. A job that always fails will be re-dispatched forever without any operator awareness. This sub-task replaces that with:
- A **max retry limit** (configurable, e.g. `MAX_RETRIES = 3`).
- **Exponential backoff** between attempts (e.g. 1 s, 2 s, 4 s).
- A **`FAILED` terminal state** once retries are exhausted.
- An **alert hook** that is called when a job enters `FAILED` state (initially a log-level CRITICAL emission + pluggable notifier interface so Slack/email can be wired later).

### Expected Outcomes
- `RenderJob.retry_count` is incremented on each failure.
- When `retry_count < MAX_RETRIES`, the job is re-queued after a backoff delay (`2 ** retry_count` seconds, or a configurable base).
- When `retry_count >= MAX_RETRIES`, the job transitions to `JobStatus.FAILED` and is **not** re-queued.
- An `AlertNotifier` interface (or simple callable) is invoked with the failed job's details.
- A default `LogAlertNotifier` implementation emits a `CRITICAL`-level structured log entry.
- `MAX_RETRIES` and `BACKOFF_BASE_SECONDS` are read from configuration, not hardcoded.

### Todo List
- [ ] Add `MAX_RETRIES` and `BACKOFF_BASE_SECONDS` to a `config.py` or environment-variable loader.
- [ ] Define an `AlertNotifier` protocol/interface in `render_queue/alerting.py` with a single `notify(job: RenderJob) -> None` method.
- [ ] Implement `LogAlertNotifier` as the default notifier that logs a `CRITICAL` structured entry.
- [ ] Update `dispatch()`: on failure, increment `job.retry_count`; if under limit re-queue with `time.sleep(backoff)`; if at limit set `FAILED` and call notifier.
- [ ] Ensure the backoff sleep does not block the main thread indefinitely — note this as a known limitation to address in Sub-Task 4 (async/pool dispatch).

### Relevant Context
- [`legacy/render_queue.py:54-58`](legacy/render_queue.py) — the 4-line silent retry block that this sub-task replaces.
- [`data/render_status.json:5`](data/render_status.json) — `"status": "failed"` and `"error": "GPU memory exceeded"` confirm the schema expectation for terminal failure.

---

## Sub-Task 3 — Replace print() and File Appends with Structured Logging

**Status:** `[x] done`

### Intent
The current code has three `print()` calls and a manual `open()/write()/close()` sequence that appends CSV-like lines to `/tmp/render_log.txt`. This approach is:
- Not queryable by log aggregators (Splunk, Datadog, CloudWatch, etc.)
- Not filterable by level or field
- Not safe under concurrent access (no file lock)
- Hardcoded to a path that breaks in production environments

Structured logging emits JSON (or key=value) records with consistent fields so every event is queryable.

### Expected Outcomes
- All `print()` calls replaced with leveled log calls (`logger.info`, `logger.warning`, `logger.error`).
- Every log record includes structured fields: `shot`, `worker`, `status`, `retry_count`, `frames`.
- The log destination and format are controlled by configuration, not hardcoded paths.
- The raw file-append block (lines 60–63) is removed; the log record for a dispatch result replaces it.
- The logging library choice (stdlib `logging` + `python-json-logger`, or `structlog`) is made and documented in `requirements.txt`.

### Todo List
- [ ] Choose and document the logging library (`structlog` preferred for structured output; stdlib `logging` + `python-json-logger` is acceptable if dependencies must be minimal).
- [ ] Create `render_queue/logging_config.py` that configures the chosen logger at import time.
- [ ] Replace `print("added job: " + shot_name)` in `add_job()` with `logger.info("job_added", shot=shot_name, frames=frames, priority=priority)`.
- [ ] Replace `print("no workers free")` in `dispatch()` with `logger.warning("no_idle_workers")`.
- [ ] Replace `print(worker + " picked up " + job.shot)` with `logger.info("job_dispatched", shot=job.shot, worker=worker)`.
- [ ] Replace the `open(JOB_LOG, "a") / f.write()` block with `logger.info("dispatch_result", shot=job.shot, status=job.status, worker=worker, retry_count=job.retry_count)`.
- [ ] Remove the `JOB_LOG` global constant.

### Relevant Context
- [`legacy/render_queue.py:25`](legacy/render_queue.py) — `print("added job: ...")` target.
- [`legacy/render_queue.py:47`](legacy/render_queue.py) — `print("no workers free")` target.
- [`legacy/render_queue.py:52`](legacy/render_queue.py) — `print(worker + " picked up ...")` target.
- [`legacy/render_queue.py:60-63`](legacy/render_queue.py) — `open()/write()/close()` block target.
- [`legacy/render_queue.py:11`](legacy/render_queue.py) — `JOB_LOG = "/tmp/render_log.txt"` to be removed.

---

## Sub-Task 4 — GPU-Aware Dynamic Worker Pool

**Status:** `[x] done`

### Intent
The current worker list is three hardcoded strings (`"farm01"`, `"farm02"`, `"farm03"`) with no GPU information, no dynamic discovery, no capacity tracking, and no concurrency. The `data/render_status.json` already records GPU-related failures (`"error": "GPU memory exceeded"`), confirming the need. This sub-task introduces:
- A **`WorkerPool`** class that holds a collection of `Worker` objects.
- A **GPU metadata field** on each `Worker` (`gpu_memory_mb`, `gpu_model`, or similar) that can be populated at startup via a discovery mechanism (initially from config/env; later extensible to `nvidia-smi` subprocess).
- A **routing strategy** interface so dispatch can prefer GPU workers for frame-heavy jobs or fall back to CPU workers.
- Worker list sourced from **configuration** rather than source code.

### Expected Outcomes
- `WorkerPool` exposes `find_idle_worker(job: RenderJob) -> Worker | None` that applies a routing strategy.
- A `GPUFirstStrategy` routing strategy preferentially assigns GPU-capable workers to jobs above a frame threshold (configurable).
- A `RoundRobinStrategy` as a CPU fallback.
- Workers are defined in a config file (e.g. `workers.yaml` or environment variables), not hardcoded in Python.
- The `WORKERS` and `worker_status` globals in the legacy file are fully replaced by `WorkerPool`.
- The pool is designed to be thread-safe (using a lock or queue) so that Sub-Task 4 paves the way for concurrent dispatch in a future iteration.

### Todo List
- [ ] Create `render_queue/worker_pool.py` with a `WorkerPool` class containing a list of `Worker` instances and a routing strategy.
- [ ] Define a `RoutingStrategy` protocol with a single method `select(workers: list[Worker], job: RenderJob) -> Worker | None`.
- [ ] Implement `GPUFirstStrategy`: prefer workers with `gpu_memory_mb` set and above a threshold.
- [ ] Implement `RoundRobinStrategy`: cycle through idle workers ignoring GPU metadata.
- [ ] Add a `WorkerPool.from_config(path: str) -> WorkerPool` factory that loads workers from YAML/JSON config.
- [ ] Create `config/workers.yaml` with the three existing farm nodes plus a `gpu_memory_mb` field (set to `null` for current CPU-only nodes).
- [ ] Remove the `WORKERS` list and `worker_status` dict globals; replace all call sites with `WorkerPool` calls.
- [ ] Document the `nvidia-smi` discovery path as a future enhancement in a code comment — do not implement it now.

### Relevant Context
- [`legacy/render_queue.py:10`](legacy/render_queue.py) — `WORKERS = ["farm01", "farm02", "farm03"]` — the static list to be replaced.
- [`legacy/render_queue.py:12-15`](legacy/render_queue.py) — `worker_status` dict initialization at module level.
- [`legacy/render_queue.py:35-39`](legacy/render_queue.py) — `find_idle_worker()` to be replaced by `WorkerPool.find_idle_worker()`.
- [`data/render_status.json:5`](data/render_status.json) — `"error": "GPU memory exceeded"` — confirms GPU tracking need.

---

## Dependency Summary

The following new dependencies will be introduced across these sub-tasks:

| Dependency | Purpose | Sub-Task |
|---|---|---|
| `pydantic` or stdlib `dataclasses` | Typed job/worker models | 1 |
| `structlog` or `python-json-logger` | Structured logging | 3 |
| `pyyaml` | Worker pool config loading | 4 |

No dependency is introduced for retry backoff — the backoff logic (`2 ** retry_count`) is simple enough to implement inline without a library. If a richer retry library is desired later, `tenacity` is the recommended choice.

---

## File Layout After Modernization

```
render_queue/
  __init__.py
  models.py          # RenderJob, Worker, JobStatus, WorkerStatus
  alerting.py        # AlertNotifier protocol, LogAlertNotifier
  logging_config.py  # Logger setup
  worker_pool.py     # WorkerPool, RoutingStrategy, GPUFirstStrategy, RoundRobinStrategy
  dispatcher.py      # dispatch(), get_next_job(), run_loop()
  config.py          # MAX_RETRIES, BACKOFF_BASE_SECONDS, config loading
config/
  workers.yaml       # Worker definitions (name, gpu_memory_mb)
legacy/
  render_queue.py    # Untouched original
data/
  render_status.json # Existing sample data
```

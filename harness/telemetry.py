"""Persist real execution intervals and expose only numeric model usage to the UI."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time

from harness.production_audit import save_json


STAGES = {"identify", "research", "teaching", "visual", "assets", "storyboard", "generation",
          "rendering", "narration", "animation", "composition"}
USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens", "reasoning_tokens", "cached_input_tokens")


def now():
    return datetime.now(timezone.utc).isoformat()


def _time(value):
    try:
        result = datetime.fromisoformat(value)
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _status(record):
    return getattr(record.status, "value", record.status)


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _usage(raw):
    """Provider totals already include their details; never add cache/reasoning twice."""
    raw = raw if isinstance(raw, dict) else {}
    inputs = _number(raw.get("prompt_tokens", raw.get("input_tokens")))
    outputs = _number(raw.get("completion_tokens", raw.get("output_tokens")))
    completion = raw.get("completion_tokens_details", {})
    prompt = raw.get("prompt_tokens_details", raw.get("input_tokens_details", {}))
    reasoning = _number(completion.get("reasoning_tokens")) if isinstance(completion, dict) else None
    cached = _number(prompt.get("cached_tokens")) if isinstance(prompt, dict) else None
    if cached is None:
        cached = _number(raw.get("prompt_cache_hit_tokens"))
    return {"input_tokens": inputs, "output_tokens": outputs,
            "total_tokens": inputs + outputs if inputs is not None and outputs is not None else _number(raw.get("total_tokens")),
            "reasoning_tokens": reasoning, "cached_input_tokens": cached}


def _sum_usage(calls):
    values = [_usage(call.get("usage")) for call in calls]
    return {**{key: (sum(value[key] for value in values if value[key] is not None)
                    if any(value[key] is not None for value in values) else None) for key in USAGE_KEYS},
            "calls": len(values),
            "unreported_calls": sum(value["input_tokens"] is None or value["output_tokens"] is None for value in values)}


def _calls(folder):
    raw = _read(folder / "model_calls.json", [])
    unique = {}
    for call in raw if isinstance(raw, list) else []:
        if isinstance(call, dict) and isinstance(call.get("call_id"), str):
            unique[call["call_id"]] = call
    return list(unique.values())


def _stage_id(stage):
    if not isinstance(stage, str):
        return None
    return "visual" if stage in {"director", "director_repair"} else stage


def _elapsed(intervals, at):
    """Measure the union of intervals, including concurrent scene operations once."""
    spans = []
    for item in intervals:
        start, end = _time(item.get("started_at")), _time(item.get("completed_at") or at)
        if start and end:
            spans.append((start.timestamp(), max(start.timestamp(), end.timestamp())))
    if not spans:
        return 0
    spans.sort()
    left, right = spans[0]
    seconds = 0.0
    for start, end in spans[1:]:
        if start > right:
            seconds += right - left
            left, right = start, end
        else:
            right = max(right, end)
    return round((seconds + right - left) * 1000)


def _close_open(state, at, status):
    for item in state.get("runs", []):
        if item.get("completed_at") is None:
            item.update(completed_at=at, status=status)
    for attempts in state.get("stages", {}).values():
        for item in attempts:
            if item.get("completed_at") is None:
                item.update(completed_at=at, status=status)


def snapshot(record, folder, *, state=None, at=None):
    """Read-only projection; old records may have usage but no recoverable timing."""
    folder, at = Path(folder), at or now()
    state = state if state is not None else _read(folder / "telemetry_state.json", {})
    state = state if isinstance(state, dict) and state.get("version") == "1.0" else {}
    calls = _calls(folder)
    status = _status(record)
    heartbeat = _time(state.get("last_seen"))
    current_time = _time(at)
    recent = bool(heartbeat and current_time and (current_time - heartbeat).total_seconds() <= 30)
    running = status == "running" and recent and any(item.get("completed_at") is None for item in state.get("runs", []))
    queued = status == "queued"
    # A restart may requeue a job before the new worker can reconcile its ledger.
    measured_at = at if running else state.get("last_seen", at)
    timings = state.get("stages", {})
    rows = {}
    known_stages = set(timings) | {_stage_id(call.get("stage")) for call in calls}
    for stage in sorted(known_stages & STAGES):
        attempts = timings.get(stage, [])
        stage_calls = [call for call in calls if _stage_id(call.get("stage")) == stage]
        active = any(item.get("completed_at") is None for item in attempts)
        latest_run = max((item.get("run", 0) for item in attempts), default=0)
        latest_units = {item.get("unit", "stage"): item for item in attempts if item.get("run", 0) == latest_run}
        statuses = {item.get("status") for item in latest_units.values()}
        settled = ("failed" if "failed" in statuses else "interrupted" if "interrupted" in statuses else
                   "cached" if statuses == {"cached"} else "completed")
        phase_status = "running" if active and running else ("interrupted" if active else
                       settled if attempts else
                       ("failed" if stage_calls and stage_calls[-1].get("status") == "failed" else "completed"))
        rows[stage] = {"status": phase_status,
                       "started_at": attempts[0].get("started_at") if attempts else None,
                       "completed_at": None if active else max((item["completed_at"] for item in attempts
                                                                 if item.get("completed_at")), default=None),
                       "elapsed_ms": _elapsed(attempts, measured_at) if attempts else None,
                       "attempts": len(attempts), "cached_runs": sum(item.get("status") == "cached" for item in attempts),
                       **_sum_usage(stage_calls)}
    queue_intervals = list(state.get("queues", []))
    if queued:
        queue_intervals.append({"started_at": record.updated_at if record.stage == "resuming" else record.created_at})
    return {"version": "1.0", "as_of": at, "timing_recorded": bool(state), "running": running,
            "queued": queued, "elapsed_ms": _elapsed(state.get("runs", []), measured_at) if state else None,
            "queue_ms": _elapsed(queue_intervals, at) if state or queued else None,
            "usage": _sum_usage(calls), "stages": rows}


def enrich(record, output_dir):
    if record is None:
        return None
    root = Path(output_dir).resolve()
    folder = (root / record.id).resolve()
    if folder.parent != root:
        return record
    return record.model_copy(update={"telemetry": snapshot(record, folder)})


class JobTelemetry:
    """Synchronous thread-safe callback: start/end/fail(stage, unit=scene_id)."""
    def __init__(self, repository, job_id, folder):
        self.repository, self.job_id, self.folder = repository, job_id, Path(folder)
        self.path = self.folder / "telemetry_state.json"
        self.lock = threading.RLock()
        self.state = _read(self.path, {})
        if not isinstance(self.state, dict) or self.state.get("version") != "1.0":
            self.state = {"version": "1.0", "runs": [], "queues": [], "stages": {}}
        self.current_stage = None
        self.closed = False

    def _save(self, at):
        self.state["last_seen"] = at
        # A Windows API reader can briefly prevent atomic replacement in the
        # separate worker. Retry sharing/access races only, never hide failures.
        for attempt in range(6):
            try:
                save_json(self.path, self.state)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in {5, 32} or attempt == 5:
                    raise
                time.sleep(.01)
        record = self.repository.get(self.job_id)
        self.repository.update(self.job_id, telemetry=snapshot(record, self.folder, state=self.state, at=at))

    def start_run(self):
        with self.lock:
            at, record = now(), self.repository.get(self.job_id)
            _close_open(self.state, self.state.get("last_seen", at), "interrupted")
            if _status(record) == "queued":
                self.state["queues"].append({"started_at": record.updated_at if record.stage == "resuming" else record.created_at,
                                             "completed_at": at})
            self.state["runs"].append({"started_at": at, "completed_at": None, "status": "running"})
            self._save(at)

    def heartbeat(self):
        with self.lock:
            if not self.closed:
                self._save(now())

    def finish_run(self, status):
        with self.lock:
            at = now()
            terminal = "completed" if status == "succeeded" else "failed" if status == "failed" else "interrupted"
            _close_open(self.state, at, terminal)
            self.closed = True
            self._save(at)

    def __call__(self, event, stage, *, unit=None, cached=False):
        if stage not in STAGES or event not in {"start", "end", "fail"}:
            raise ValueError("Unsupported execution telemetry event")
        unit = str(unit or "stage")
        if len(unit) > 100:
            raise ValueError("Execution unit identifier is too long")
        with self.lock:
            at = now()
            attempts = self.state["stages"].setdefault(stage, [])
            active = next((item for item in reversed(attempts)
                           if item["unit"] == unit and item["completed_at"] is None), None)
            if event == "start":
                if active is None:
                    attempts.append({"unit": unit, "run": len(self.state["runs"]),
                                     "started_at": at, "completed_at": None, "status": "running"})
            elif active is not None:
                active.update(completed_at=at, status="failed" if event == "fail" else "cached" if cached else "completed")
            self._save(at)

    def transition(self, stage):
        if stage == self.current_stage:
            return
        if self.current_stage:
            self("end", self.current_stage)
        self("start", stage)
        self.current_stage = stage

    @contextmanager
    def span(self, stage, *, unit=None):
        self("start", stage, unit=unit)
        try:
            yield
        except BaseException:
            self("fail", stage, unit=unit)
            raise
        else:
            self("end", stage, unit=unit)

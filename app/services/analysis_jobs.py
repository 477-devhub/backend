"""Bounded, single-process analysis jobs for the development harness."""
import asyncio
import copy
import inspect
import json
from datetime import datetime, timezone
from uuid import uuid4


class AnalysisJobError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now():
    return datetime.now(timezone.utc).isoformat()


class AnalysisJobService:
    def __init__(self, processor, validator, *, queue_size=8, max_jobs=1000,
                 request_ledger=None, state_lock=None):
        if queue_size < 1 or max_jobs < 1:
            raise ValueError("analysis capacities must be positive")
        self.processor = processor
        self.validator = validator
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.max_jobs = max_jobs
        self.jobs = {}
        self.requests = request_ledger if request_ledger is not None else {}
        self.lock = state_lock or asyncio.Lock()
        self.submission_lock = asyncio.Lock()
        self.close_lock = asyncio.Lock()
        self.worker = None
        self.closed = False

    def _replay(self, key, signature):
        if key in self.requests:
            previous, response = self.requests[key]
            if previous != signature:
                raise AnalysisJobError(409, "key already used for another request")
            return copy.deepcopy(response)
        return None

    async def submit(self, body, key):
        if not key or len(key) > 200:
            raise AnalysisJobError(400, "Idempotency-Key required (1..200 chars)")
        payload = body.model_dump(mode="json")
        signature = json.dumps({"scope": "analysis", "payload": payload}, sort_keys=True, ensure_ascii=False)
        async with self.submission_lock:
            async with self.lock:
                replay = self._replay(key, signature)
                if replay is not None:
                    return replay
                if self.closed:
                    raise AnalysisJobError(503, "analysis service stopped")
                if len(self.jobs) >= self.max_jobs or self.queue.full():
                    raise AnalysisJobError(503, "analysis capacity exhausted")
            # Trusted media checks may perform I/O. Never hold the application state lock here.
            checked = self.validator(body)
            if inspect.isawaitable(checked):
                await checked
            async with self.lock:
                replay = self._replay(key, signature)
                if replay is not None:
                    return replay
                if self.closed:
                    raise AnalysisJobError(503, "analysis service stopped")
                if len(self.jobs) >= self.max_jobs or self.queue.full():
                    raise AnalysisJobError(503, "analysis capacity exhausted")
                job_id = "JOB-" + uuid4().hex
                now = _now()
                job = {"job_id": job_id, "state": "queued", "camera_id": body.camera_id,
                       "clip_ref": body.clip_ref, "start_ms": body.start_ms, "end_ms": body.end_ms,
                       "created_at": now, "updated_at": now, "incident_id": None,
                       "suppressed_id": None, "needs_review": None, "stage_trace": [], "error_code": None}
                self.jobs[job_id] = job
                self.queue.put_nowait((job_id, body))
                initial = copy.deepcopy(job)
                self.requests[key] = (signature, initial)
                if self.worker is None:
                    self.worker = asyncio.create_task(self._run(), name="analysis-worker")
                return copy.deepcopy(initial)

    def get(self, job_id):
        if job_id not in self.jobs:
            raise AnalysisJobError(404, "analysis job not found")
        return copy.deepcopy(self.jobs[job_id])

    def metrics(self):
        """Aggregate only recorded terminal traces; absence never means zero usage."""
        states = {name: 0 for name in ("queued", "preparing", "cv", "p1", "p4", "completed", "failed")}
        stages = {}
        for name in ("prepare", "cv", "p1", "p4", "map"):
            stages[name] = {"stage": name, "records": 0, "ok": 0, "failed": 0, "skipped": 0,
                            "attempts": 0, "known_cost_count": 0, "unknown_cost_count": 0,
                            "known_cost_usd": None, "known_latency_count": 0,
                            "unknown_latency_count": 0, "known_latency_total_ms": None,
                            "known_latency_average_ms": None}
        measured_jobs = []
        completed_jobs = 0
        for job in self.jobs.values():
            states[job["state"]] += 1
            if job["state"] not in {"completed", "failed"}:
                continue
            trace = job["stage_trace"]
            if job["state"] == "completed":
                completed_jobs += 1
                if trace and all(record["latency_ms"] is not None for record in trace):
                    measured_jobs.append(sum(record["latency_ms"] for record in trace))
            for record in trace:
                stage = stages[record["stage"]]
                stage["records"] += 1
                stage[record["status"]] += 1
                stage["attempts"] += record["attempts"]
                for source, count_known, count_unknown, total in (
                    ("estimated_cost_usd", "known_cost_count", "unknown_cost_count", "known_cost_usd"),
                    ("latency_ms", "known_latency_count", "unknown_latency_count", "known_latency_total_ms"),
                ):
                    value = record[source]
                    if value is None:
                        stage[count_unknown] += 1
                    else:
                        stage[count_known] += 1
                        stage[total] = (stage[total] if stage[total] is not None else 0) + value
        for stage in stages.values():
            if stage["known_latency_count"]:
                stage["known_latency_average_ms"] = stage["known_latency_total_ms"] / stage["known_latency_count"]
        known_costs = [stage["known_cost_usd"] for stage in stages.values() if stage["known_cost_usd"] is not None]
        return {"job_counts": states, "total_jobs": len(self.jobs), "completed_jobs": completed_jobs,
                "failed_jobs": states["failed"], "stages": list(stages.values()),
                "provider_attempts": sum(stages[name]["attempts"] for name in ("p1", "p4")),
                "known_cost_usd": sum(known_costs) if known_costs else None,
                "unknown_cost_records": sum(stage["unknown_cost_count"] for stage in stages.values()),
                "measured_elapsed_jobs": len(measured_jobs),
                "unknown_elapsed_jobs": completed_jobs - len(measured_jobs),
                "known_elapsed_total_ms": sum(measured_jobs) if measured_jobs else None,
                "known_elapsed_average_ms": sum(measured_jobs) / len(measured_jobs) if measured_jobs else None,
                "measurement_scope": "terminal_job_stage_traces",
                "elapsed_semantics": "sum of recorded stage latency for completed jobs with every stage measured; excludes queue wait",
                "failure_semantics": "unrecorded stages of failed or cancelled jobs have unknown usage and are excluded",
                "cost_semantics": "sum of known estimates only; unknown and skipped estimates remain unknown"}

    def _update(self, job_id, **values):
        self.jobs[job_id].update(values, updated_at=_now())

    async def _run(self):
        while True:
            job_id, body = await self.queue.get()
            try:
                self._update(job_id, state="preparing")

                async def progress(stage, job_id=job_id):
                    if self.closed:
                        raise asyncio.CancelledError
                    if stage not in {"preparing", "cv", "p1", "p4"}:
                        raise ValueError("invalid analysis progress stage")
                    self._update(job_id, state=stage)

                result = await self.processor(job_id, body, progress)
                if self.closed:
                    self._update(job_id, state="failed", error_code="cancelled")
                    return
                # Validate the callback contract before exposing a completed job.
                from app.api.analysis import AnalysisJobResult
                result = AnalysisJobResult.model_validate(result).model_dump(mode="json")
                self._update(job_id, state="completed", **result)
            except asyncio.CancelledError:
                self._update(job_id, state="failed", error_code="cancelled")
                raise
            except Exception:
                # Provider exceptions can include request data, paths, credentials or raw responses.
                self._update(job_id, state="failed", error_code="analysis_failed")
            finally:
                self.queue.task_done()

    async def close(self):
        async with self.close_lock:
            async with self.lock:
                self.closed = True
            if self.worker is not None:
                self.worker.cancel()
                try:
                    await self.worker
                except asyncio.CancelledError:
                    pass
            while not self.queue.empty():
                job_id, _ = self.queue.get_nowait()
                self._update(job_id, state="failed", error_code="cancelled")
                self.queue.task_done()

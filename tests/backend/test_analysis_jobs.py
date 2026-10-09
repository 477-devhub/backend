import asyncio
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.analysis import AnalysisJobBody, router
from app.api.errors import register_errors
from app.services.analysis_jobs import AnalysisJobError, AnalysisJobService


BODY = {"camera_id": "CAM_01", "clip_ref": "neutral-clip", "start_ms": 0, "end_ms": 1000}


def validate(body):
    if body.camera_id != "CAM_01":
        raise AnalysisJobError(404, "camera not found")
    if body.clip_ref != "neutral-clip":
        raise AnalysisJobError(422, "registered MP4 required")


async def complete(job_id, body, progress):
    await progress("cv")
    await progress("p1")
    await progress("p4")
    return {"incident_id": "INC-" + job_id, "needs_review": True,
            "stage_trace": [{"stage": "p4", "status": "ok", "attempts": 1}]}


async def test_nonblocking_single_worker_and_immutable_replay():
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def blocked(job_id, body, progress):
        calls.append(job_id)
        await progress("p4")
        entered.set()
        await release.wait()
        return await complete(job_id, body, progress)

    service = AnalysisJobService(blocked, validate, queue_size=1)
    body = AnalysisJobBody(**BODY)
    first = await asyncio.wait_for(service.submit(body, "one"), .2)
    await entered.wait()
    assert service.get(first["job_id"])["state"] == "p4"
    second = await service.submit(body, "two")
    assert first["job_id"] != second["job_id"]
    assert await service.submit(body, "one") == first
    with pytest.raises(AnalysisJobError) as exhausted:
        await service.submit(body, "three")
    assert exhausted.value.status_code == 503
    assert calls == [first["job_id"]]
    release.set()
    await service.queue.join()
    assert service.get(first["job_id"])["state"] == "completed"
    assert await service.submit(body, "one") == first
    assert len(calls) == 2
    await service.close()


async def test_failed_job_does_not_stop_worker_and_never_exposes_exception():
    async def processor(job_id, body, progress):
        if body.start_ms == 0:
            raise RuntimeError("secret API_TOKEN=xyz D:/private/file.mp4")
        return await complete(job_id, body, progress)

    service = AnalysisJobService(processor, validate)
    first = await service.submit(AnalysisJobBody(**BODY), "one")
    second = await service.submit(AnalysisJobBody(**{**BODY, "start_ms": 1}), "two")
    await service.queue.join()
    failed = service.get(first["job_id"])
    assert failed["state"] == "failed" and failed["error_code"] == "analysis_failed"
    assert "secret" not in str(failed) and "private" not in str(failed)
    assert service.get(second["job_id"])["state"] == "completed"
    await service.close()


async def test_shutdown_cancels_active_and_pending_and_rejects_new():
    entered = asyncio.Event()
    cancelled = []

    async def processor(job_id, body, progress):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(job_id)

    service = AnalysisJobService(processor, validate)
    first = await service.submit(AnalysisJobBody(**BODY), "one")
    await entered.wait()
    second = await service.submit(AnalysisJobBody(**BODY), "two")
    await service.close()
    assert cancelled == [first["job_id"]]
    for job in (first, second):
        assert service.get(job["job_id"])["error_code"] == "cancelled"
    await asyncio.wait_for(service.queue.join(), .2)
    await service.close()
    with pytest.raises(AnalysisJobError) as stopped:
        await service.submit(AnalysisJobBody(**BODY), "three")
    assert stopped.value.status_code == 503


async def test_validation_idempotency_global_keys_and_retained_capacity():
    ledger = {"ack-key": ('other-scope', {"ok": True})}
    service = AnalysisJobService(complete, validate, request_ledger=ledger, max_jobs=1)
    with pytest.raises(AnalysisJobError) as conflict:
        await service.submit(AnalysisJobBody(**BODY), "ack-key")
    assert conflict.value.status_code == 409
    with pytest.raises(AnalysisJobError) as bad_media:
        await service.submit(AnalysisJobBody(**{**BODY, "clip_ref": "https://example.test/x.mp4"}), "media")
    assert bad_media.value.status_code == 422 and not service.jobs
    first = await service.submit(AnalysisJobBody(**BODY), "one")
    with pytest.raises(AnalysisJobError) as reused:
        await service.submit(AnalysisJobBody(**{**BODY, "start_ms": 1}), "one")
    assert reused.value.status_code == 409
    await service.queue.join()
    with pytest.raises(AnalysisJobError) as capacity:
        await service.submit(AnalysisJobBody(**BODY), "two")
    assert capacity.value.status_code == 503
    assert await service.submit(AnalysisJobBody(**BODY), "one") == first
    assert "media" not in ledger
    await service.close()


def test_router_contract_and_development_gate():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        app.state.analysis_jobs = AnalysisJobService(complete, validate)
        yield
        await app.state.analysis_jobs.close()

    app = FastAPI(lifespan=lifespan)
    app.state.settings = SimpleNamespace(mode="development")
    app.include_router(router)
    register_errors(app)
    with TestClient(app) as client:
        empty_stats = client.get("/api/analysis/stats")
        assert empty_stats.status_code == 200
        assert empty_stats.json()["known_cost_usd"] is None
        headers = {"Idempotency-Key": "key"}
        response = client.post("/api/analysis/jobs", json=BODY, headers=headers)
        assert response.status_code == 202
        initial = response.json()
        assert initial["state"] == "queued"
        assert client.post("/api/analysis/jobs", json=BODY, headers=headers).json() == initial
        assert client.get("/api/analysis/jobs/" + initial["job_id"]).status_code == 200
        assert client.get("/api/analysis/jobs/missing").status_code == 404
        assert client.post("/api/analysis/jobs", json=BODY).status_code == 400
        assert client.post("/api/analysis/jobs", json={**BODY, "end_ms": 0}, headers=headers).status_code == 422
        assert client.post("/api/analysis/jobs", json={**BODY, "clip_ref": "C:/file.mp4"},
                           headers={"Idempotency-Key": "path"}).status_code == 422
        assert client.post("/api/analysis/jobs", json={**BODY, "camera_id": "unknown"},
                           headers={"Idempotency-Key": "camera"}).status_code == 404
        app.state.settings.mode = "demo"
        assert client.get("/api/analysis/stats").status_code == 404
        assert client.post("/api/analysis/jobs", json=BODY, headers=headers).status_code == 404
        assert client.get("/api/analysis/jobs/" + initial["job_id"]).status_code == 404


async def test_metrics_count_skips_attempts_and_unknown_estimates_without_zero_imputation():
    async def traced(job_id, body, progress):
        if body.start_ms == 0:
            trace = [{"stage": "prepare", "status": "ok", "latency_ms": 4},
                     {"stage": "p1", "status": "skipped"},
                     {"stage": "p4", "status": "ok", "attempts": 2, "latency_ms": 20,
                      "estimated_cost_usd": .02}]
        else:
            trace = [{"stage": "prepare", "status": "ok", "latency_ms": 6},
                     {"stage": "p1", "status": "failed", "latency_ms": 10, "attempts": 1},
                     {"stage": "p4", "status": "ok", "latency_ms": 30, "attempts": 1,
                      "estimated_cost_usd": .03}]
        return {"incident_id": "INC-" + job_id, "needs_review": True, "stage_trace": trace}

    service = AnalysisJobService(traced, validate)
    assert service.metrics()["known_elapsed_total_ms"] is None
    await service.submit(AnalysisJobBody(**BODY), "one")
    await service.submit(AnalysisJobBody(**{**BODY, "start_ms": 1}), "two")
    await service.queue.join()
    metrics = service.metrics()
    assert metrics["completed_jobs"] == 2 and metrics["provider_attempts"] == 4
    assert metrics["known_cost_usd"] == pytest.approx(.05)
    assert metrics["unknown_cost_records"] == 4
    assert metrics["measured_elapsed_jobs"] == 1 and metrics["unknown_elapsed_jobs"] == 1
    assert metrics["known_elapsed_average_ms"] == metrics["known_elapsed_total_ms"] == 46
    stages = {stage["stage"]: stage for stage in metrics["stages"]}
    assert stages["p1"]["skipped"] == 1 and stages["p1"]["failed"] == 1
    assert stages["p1"]["known_cost_usd"] is None
    assert stages["p4"]["known_latency_average_ms"] == 25
    assert stages["cv"]["records"] == 0 and stages["cv"]["known_latency_total_ms"] is None
    from app.api.analysis import AnalysisStats
    AnalysisStats.model_validate(metrics)
    await service.close()


async def test_close_while_validation_pending_does_not_enqueue():
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_validation(body):
        entered.set()
        await release.wait()

    service = AnalysisJobService(complete, delayed_validation)
    submission = asyncio.create_task(service.submit(AnalysisJobBody(**BODY), "one"))
    await entered.wait()
    await service.close()
    release.set()
    with pytest.raises(AnalysisJobError) as stopped:
        await submission
    assert stopped.value.status_code == 503 and service.jobs == {}


async def test_swallowed_cancellation_cannot_complete_after_shutdown():
    entered = asyncio.Event()

    async def swallowing(job_id, body, progress):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"incident_id": "INC-late", "needs_review": False}

    service = AnalysisJobService(swallowing, validate)
    first = await service.submit(AnalysisJobBody(**BODY), "one")
    await entered.wait()
    await asyncio.gather(service.close(), service.close())
    assert service.get(first["job_id"])["state"] == "failed"
    assert service.get(first["job_id"])["incident_id"] is None
    assert service.metrics()["failed_jobs"] == 1


@pytest.mark.parametrize("result", [
    {"incident_id": "INC-invalid", "needs_review": None},
    {"incident_id": "INC-invalid", "needs_review": "false"},
    {"incident_id": "INC-invalid", "suppressed_id": "SUP-invalid", "needs_review": False},
    {"needs_review": False},
])
async def test_invalid_processor_result_is_failed_without_false_completion(result):
    async def invalid(job_id, body, progress):
        return result

    service = AnalysisJobService(invalid, validate)
    submitted = await service.submit(AnalysisJobBody(**BODY), "one")
    await service.queue.join()
    response = service.get(submitted["job_id"])
    assert response["state"] == "failed" and response["needs_review"] is None
    assert response["incident_id"] is None
    from app.api.analysis import AnalysisJobResponse
    AnalysisJobResponse.model_validate(response)
    await service.close()


def test_completed_response_requires_review_decision():
    from pydantic import ValidationError
    from app.api.analysis import AnalysisJobResponse
    response = {**BODY, "job_id": "job", "state": "completed", "created_at": "now",
                "updated_at": "now", "incident_id": "INC", "needs_review": None}
    with pytest.raises(ValidationError):
        AnalysisJobResponse.model_validate(response)

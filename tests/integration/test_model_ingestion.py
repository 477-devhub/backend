import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.base import ModelAdapter
from app.models.registry import get_adapter
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes


class SyntheticContractAdapter(ModelAdapter):
    """Controlled test output, never registered as a real provider or used in evaluation."""
    name = "synthetic_contract_test"

    def __init__(self, behavior):
        self.behavior = behavior

    async def evaluate(self, mi):
        if self.behavior == "timeout":
            await asyncio.sleep(.1)
        if self.behavior == "provider_error":
            raise RuntimeError("sensitive provider payload")
        normal = self.behavior == "normal"
        axes = RiskAxes(severity=0 if normal else 1, imminence=0 if normal else 1,
                        exposure=0 if normal else 1, persistence=0 if normal else 1)
        result = ModelAssessment(
            event_type="normal" if normal else "collapse", event_confidence=.99,
            risk_axes=axes, evidence_refs=[mi.evidence[0].frame_id],
            ai_opinion="Synthetic contract test output",
            metadata=ModelMetadata(adapter=self.name, model="synthetic-test-only"),
        )
        if self.behavior == "invalid_instance":
            return result.model_copy(update={"event_confidence": 2.0})
        return result


def test_mock_ingestion_push_ack_replay_reconnect(mi, tmp_path):
    with TestClient(create_app(Settings(media_root=tmp_path), adapter=get_adapter("mock_local_cv"))) as client:
        with client.websocket_connect("/ws/attention") as ws:
            initial = ws.receive_json()
            applied = client.portal.call(client.app.state.ingest_model_input, mi)
            snapshot = ws.receive_json()
            assert applied.decision.disposition == "review" and applied.changed
            assert snapshot["revision"] > initial["revision"]
            assert snapshot["active_count"] == 1
            incident_id = applied.record.id
            response = client.get("/api/incidents/" + incident_id).json()
            assert response["risk"] is None and response["level"] == "UNKNOWN"
            assert response["evidence"][0]["frame_id"] == mi.evidence[0].frame_id
            assert response["evidence"][0]["timestamp_ms"] == mi.evidence[0].timestamp_ms
            assert client.get("/api/incidents/" + incident_id + "/clip").json()["available"] is False
            assert client.get("/stream/" + mi.camera.id).status_code == 503
            ack_url = "/api/incidents/" + incident_id + "/ack"
            headers = {"Idempotency-Key": "ingestion-ack"}
            ack = client.post(ack_url, json={"action": "verify"}, headers=headers)
            assert ack.status_code == 200 and ws.receive_json()["active_count"] == 0
            assert client.post(ack_url, json={"action": "verify"}, headers=headers).json() == ack.json()
            revision = client.app.state.store.revision
            replay = client.portal.call(client.app.state.ingest_model_input, mi)
            assert not replay.changed and replay.record.status == "acked"
            assert client.app.state.store.revision == revision
        with client.websocket_connect("/ws/attention") as ws:
            snapshot = ws.receive_json()
            assert snapshot["active_count"] == 0 and snapshot["revision"] == revision
        assert not client.app.state.hub.clients


def test_synthetic_suppression_restore_and_replay(mi, tmp_path):
    with TestClient(create_app(Settings(media_root=tmp_path), adapter=SyntheticContractAdapter("normal"))) as client:
        with client.websocket_connect("/ws/attention") as ws:
            ws.receive_json()
            applied = client.portal.call(client.app.state.ingest_model_input, mi)
            snapshot = ws.receive_json()
            assert applied.decision.disposition == "suppressed"
            assert snapshot["suppressed_count"] == 1 and snapshot["active_count"] == 0
            item = client.get("/api/suppressed").json()[0]
            assert item["stage1_label"] is None and item["resumed_walking"] is None
            url = "/api/suppressed/" + item["id"] + "/restore"
            response = client.post(url, headers={"Idempotency-Key": "restore-ingestion"})
            assert response.status_code == 200
            restored = ws.receive_json()
            assert restored["active_count"] == 1 and restored["suppressed_count"] == 0
            incident = restored["incidents"][0]
            assert incident["risk"] is None and incident["level"] == "UNKNOWN"
            assert incident["needs_human_review"]
            revision = client.app.state.store.revision
            replay = client.portal.call(client.app.state.ingest_model_input, mi)
            assert not replay.changed and replay.record["restored"]
            assert client.app.state.store.revision == revision


@pytest.mark.parametrize("behavior,code", [
    ("timeout", "timeout"), ("provider_error", "provider_error"),
    ("invalid_instance", "schema_or_contract"),
])
def test_failed_ingestion_is_persisted_and_pushed_for_review(mi, tmp_path, behavior, code):
    settings = Settings(media_root=tmp_path, model_timeout_sec=.01)
    with TestClient(create_app(settings, adapter=SyntheticContractAdapter(behavior))) as client:
        with client.websocket_connect("/ws/attention") as ws:
            ws.receive_json()
            applied = client.portal.call(client.app.state.ingest_model_input, mi)
            snapshot = ws.receive_json()
            assert applied.decision.disposition == "review"
            incident = snapshot["incidents"][0]
            assert incident["uncertainty_reason"] == code
            assert incident["risk"] is None and incident["level"] == "UNKNOWN"
            assert incident["needs_human_review"]
            assert "sensitive provider payload" not in str(incident)


def test_default_real_slot_remains_explicitly_unconfigured(mi, client):
    assert client.app.state.model_adapter.name == "local_cv"
    applied = client.portal.call(client.app.state.ingest_model_input, mi)
    assert applied.record.uncertainty_reason == "provider_error"
    assert applied.record.risk is None and applied.record.needs_human_review


def test_synthetic_incidents_are_ranked_from_server_risk(mi, tmp_path):
    with TestClient(create_app(Settings(media_root=tmp_path), adapter=SyntheticContractAdapter("collapse"))) as client:
        applied = client.portal.call(client.app.state.ingest_model_input, mi)
        incident = client.get("/api/incidents/" + applied.record.id).json()
        assert applied.decision.disposition == "incident"
        assert incident["risk"] == 100 and incident["rank"] == 1


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_model_timeout_settings_reject_unbounded_or_invalid_values(timeout):
    with pytest.raises(ValueError, match="positive and finite"):
        Settings(model_timeout_sec=timeout)


class CountedSyntheticAdapter(SyntheticContractAdapter):
    def __init__(self):
        super().__init__("normal")
        self.calls = 0

    async def evaluate(self, mi):
        self.calls += 1
        await asyncio.sleep(.01)
        result = await super().evaluate(mi)
        self.behavior = "invalid_instance"
        return result


async def test_completed_replay_skips_inference_and_new_sample_failure_reviews(mi, tmp_path):
    adapter = CountedSyntheticAdapter()
    app = create_app(Settings(media_root=tmp_path), adapter=adapter)
    first = await app.state.ingest_model_input(mi)
    assert first.decision.disposition == "suppressed" and adapter.calls == 1
    replay = await app.state.ingest_model_input(mi)
    assert not replay.changed and replay.decision == first.decision
    assert adapter.calls == 1
    new_input = mi.model_copy(update={"sample_id": "s_000002"})
    failure = await app.state.ingest_model_input(new_input)
    assert adapter.calls == 2 and failure.decision.disposition == "review"
    assert failure.record.uncertainty_reason == "schema_or_contract"
    assert failure.record.risk is None and failure.record.level == "UNKNOWN"


async def test_simultaneous_same_input_executes_once(mi, tmp_path):
    adapter = CountedSyntheticAdapter()
    app = create_app(Settings(media_root=tmp_path), adapter=adapter)
    results = await asyncio.gather(
        app.state.ingest_model_input(mi), app.state.ingest_model_input(mi),
    )
    assert adapter.calls == 1
    assert [result.changed for result in results] == [True, False]
    assert all(result.decision.disposition == "suppressed" for result in results)
    assert app.state.store.revision == 1


async def test_simultaneous_same_id_different_input_rejects_before_second_inference(mi, tmp_path):
    adapter = CountedSyntheticAdapter()
    app = create_app(Settings(media_root=tmp_path), adapter=adapter)
    changed = mi.model_copy(update={"clip_ref": "different-neutral-ref"})
    results = await asyncio.gather(
        app.state.ingest_model_input(mi), app.state.ingest_model_input(changed),
        return_exceptions=True,
    )
    assert adapter.calls == 1 and results[0].changed
    assert isinstance(results[1], ValueError) and "different input" in str(results[1])


async def test_model_wait_does_not_hold_operator_state_lock(mi, tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    class WaitingSyntheticAdapter(SyntheticContractAdapter):
        async def evaluate(self, model_input):
            started.set()
            await release.wait()
            return await super().evaluate(model_input)

    app = create_app(Settings(media_root=tmp_path), adapter=WaitingSyntheticAdapter("normal"))
    pending = asyncio.create_task(app.state.ingest_model_input(mi))
    try:
        await asyncio.wait_for(started.wait(), .5)
        await asyncio.wait_for(app.state.lock.acquire(), .5)
        app.state.lock.release()
        release.set()
        assert (await pending).changed
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

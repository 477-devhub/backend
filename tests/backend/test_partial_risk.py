"""Synthetic contract checks; partial axes must never become invented totals."""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.base import ModelAdapter
from app.repositories.memory import MemoryStore
from app.schemas.model import (
    SCHEMA_VERSION, CameraContext, EvidenceFrame, ModelAssessment, ModelInput,
    ModelMetadata, RiskAxes, TimeWindow,
)
from app.services.incidents import apply_assessment
from app.services.policy import decide
from app.services.risk import risk_level, risk_score


@pytest.mark.parametrize("missing", ["severity", "imminence", "exposure", "persistence"])
def test_any_missing_axis_has_unknown_total(missing):
    values = dict(severity=.9, imminence=.95, exposure=.8, persistence=.85)
    values[missing] = None
    axes = RiskAxes(**values)
    assert risk_score(axes) is None and risk_level(risk_score(axes)) == "UNKNOWN"
    assert axes.model_dump() == values


@pytest.mark.parametrize("axes", [RiskAxes(severity=.2), RiskAxes()])
def test_partial_and_all_missing_axes_cannot_suppress_normal(axes):
    assessment = synthetic_partial(axes)
    decision = decide(assessment)
    assert decision.disposition == "review" and decision.risk is None
    store = MemoryStore()
    result = apply_assessment(store, synthetic_input(), assessment)
    assert result.record.risk is None and result.record.level == "UNKNOWN"
    assert result.record.needs_human_review
    assert result.record.risk_axes == axes
    assert not store.suppressed


def test_complete_axes_keep_existing_weighted_formula():
    assert risk_score(RiskAxes(severity=.9, imminence=.95, exposure=.8, persistence=.85)) == 89
    assert risk_score(RiskAxes(severity=0, imminence=0, exposure=0, persistence=0)) == 0


def synthetic_input():
    return ModelInput(sample_id="synthetic-partial-risk", camera=CameraContext(id="CAM_01"),
        window=TimeWindow(start_ms=0, end_ms=1000),
        evidence=[EvidenceFrame(frame_id="synthetic-frame", timestamp_ms=500, media_ref="synthetic-ref")])


def synthetic_partial(axes):
    return ModelAssessment(event_type="normal", event_confidence=.99, risk_axes=axes,
        needs_human_review=True, uncertainty_reason="synthetic_partial_measurement",
        evidence_refs=["synthetic-frame"],
        # Leave the mock policy gate off to isolate partial-axis handling.
        metadata=ModelMetadata(adapter="synthetic_partial_test", model="synthetic", is_mock=False))


class SyntheticPartialAdapter(ModelAdapter):
    name = "synthetic_partial_test"

    async def evaluate(self, model_input):
        return synthetic_partial(RiskAxes(severity=.2, exposure=.4))


def test_websocket_partial_axes_serialization_and_reconnect(tmp_path):
    app = create_app(Settings(mode="development", media_root=tmp_path), adapter=SyntheticPartialAdapter())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/attention") as ws:
            initial = ws.receive_json()
            assert initial["schema_version"] == SCHEMA_VERSION == "1.1"
            result = client.portal.call(app.state.ingest_model_input, synthetic_input())
            snapshot = ws.receive_json()
            assert snapshot["revision"] > initial["revision"]
            assert snapshot["schema_version"] == SCHEMA_VERSION
            assert snapshot["active_count"] == 1 and snapshot["suppressed_count"] == 0
            incident = snapshot["incidents"][0]
            assert incident["risk"] is None and incident["level"] == "UNKNOWN"
            assert incident["needs_human_review"]
            assert incident["risk_axes"] == {
                "severity": .2, "imminence": None, "exposure": .4, "persistence": None}
            assert snapshot["level_counts"]["review"] == 1
            assert client.get(f"/api/incidents/{result.record.id}").json()["risk_axes"] == incident["risk_axes"]
        with client.websocket_connect("/ws/attention") as ws:
            assert ws.receive_json() == snapshot

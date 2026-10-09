"""Service contract tests with synthetic assessments; no provider/media evaluation."""
import json
from pathlib import Path

import pytest

from app.repositories.memory import MemoryStore
from app.schemas.incident import AckBody
from app.schemas.model import ModelAssessment, ModelInput, ModelMetadata, RiskAxes
from app.services.incidents import apply_assessment, lookup_assessment


@pytest.fixture
def model_input():
    return ModelInput.model_validate(json.loads(
        (Path(__file__).resolve().parents[2] / "fixtures/model_input.json").read_text()
    ))


def synthetic_assessment(mi, *, event="collapse", axes=.9, confidence=.95, mock=False):
    return ModelAssessment(
        event_type=event, event_confidence=confidence,
        risk_axes=None if axes is None else RiskAxes(
            severity=axes, imminence=axes, exposure=axes, persistence=axes),
        needs_human_review=axes is None,
        evidence_refs=[e.frame_id for e in mi.evidence],
        metadata=ModelMetadata(adapter="synthetic_contract_test", model="synthetic", is_mock=mock),
    )


def test_incident_persists_risk_without_confidence_multiplication(model_input):
    store = MemoryStore()
    result = apply_assessment(store, model_input, synthetic_assessment(model_input))
    assert result.changed and result.decision.disposition == "incident"
    assert result.record.risk == 90 and result.record.confidence == .95
    assert store.get(result.record.id) is result.record
    assert store.revision == 1 and store.snapshot()["active_count"] == 1
    assert [(e.frame_id, e.timestamp_ms) for e in result.record.evidence] == [
        (e.frame_id, e.timestamp_ms) for e in model_input.evidence]


def test_cited_description_is_preserved_and_p1_suppression_has_no_frame_citations(model_input):
    from app.schemas.model import RoutingAssessment
    assessment = synthetic_assessment(model_input)
    cited = model_input.evidence[0].frame_id
    assessment = ModelAssessment.model_validate({**assessment.model_dump(),
        "evidence_descriptions": {cited: "Person remains on the floor"}})
    result = apply_assessment(MemoryStore(), model_input, assessment)
    assert result.record.evidence[0].text == "Person remains on the floor"
    normal = ModelAssessment(event_type="normal", event_confidence=.99,
        risk_axes=RiskAxes(severity=.1, imminence=.1, exposure=.1, persistence=.1),
        metadata=ModelMetadata(adapter="cascade", model="p1"),
        routing=RoutingAssessment(mode="frozen_cascade_v1", selected_stage="p1",
            p_incident=.001, frozen_guard_passed=True, backend_guard_passed=True,
            evidence_scope="window_observations"))
    suppressed_store = MemoryStore()
    suppressed = apply_assessment(suppressed_store, model_input, normal)
    assert suppressed.record["evidence_refs"] == []
    assert suppressed.record["evidence_scope"] == "window_observations"
    assert suppressed.record["routing"]["selected_stage"] == "p1"
    assert suppressed_store.media_context[suppressed.record["id"]] == {
        "clip_ref": model_input.clip_ref, "start_ms": model_input.window.start_ms,
        "end_ms": model_input.window.end_ms}


@pytest.mark.parametrize("axes,confidence,mock", [(None,.95,False), (.9,.5,False), (.0,.99,True)])
def test_unknown_low_confidence_and_mock_stay_visible(model_input, axes, confidence, mock):
    store = MemoryStore()
    result = apply_assessment(store, model_input, synthetic_assessment(
        model_input, axes=axes, confidence=confidence, mock=mock))
    assert result.decision.disposition == "review" and result.record.needs_human_review
    assert store.snapshot()["level_counts"]["review"] == 1
    assert store.snapshot()["suppressed_count"] == 0
    if axes is None:
        assert result.record.risk is None and result.record.level == "UNKNOWN"


@pytest.mark.parametrize("action", ["verify", "dismiss"])
def test_replay_preserves_operator_state(model_input, action):
    store = MemoryStore()
    first = apply_assessment(store, model_input, synthetic_assessment(model_input))
    store.ack(first.record.id, AckBody(action=action))
    revision = store.revision
    replay = apply_assessment(store, model_input, synthetic_assessment(model_input, axes=None))
    assert not replay.changed and replay.decision == first.decision
    assert replay.record.status == ("acked" if action == "verify" else "dismissed")
    assert store.revision == revision and store.snapshot()["active_count"] == 0
    assert len(store.audit) == 1


def test_suppression_replay_keeps_restore_state(model_input):
    store = MemoryStore()
    assessment = synthetic_assessment(model_input, event="normal", axes=.1, confidence=.9)
    first = apply_assessment(store, model_input, assessment)
    assert first.changed and first.decision.disposition == "suppressed"
    assert first.record["risk"] == 10 and first.record["resumed_walking"] is None
    assert store.snapshot()["active_count"] == 0 and store.snapshot()["suppressed_count"] == 1
    first.record["restored"] = True  # Existing restore route owns the operator mutation.
    revision = store.revision
    replay = apply_assessment(store, model_input, assessment)
    assert not replay.changed and replay.record["restored"]
    assert store.revision == revision and len(store.suppressed) == 1


def test_unknown_camera_and_reused_input_rejected_without_mutation(model_input):
    store = MemoryStore()
    unknown = model_input.model_copy(update={"camera": model_input.camera.model_copy(update={"id":"unknown"})})
    with pytest.raises(ValueError, match="unknown camera"):
        apply_assessment(store, unknown, synthetic_assessment(model_input))
    assert not store.assessment_inputs and store.revision == 0
    apply_assessment(store, model_input, synthetic_assessment(model_input))
    changed_input = model_input.model_copy(update={"clip_ref": "different-neutral-ref"})
    with pytest.raises(ValueError, match="sample_id reused"):
        apply_assessment(store, changed_input, synthetic_assessment(model_input))
    assert len(store.incidents) == 1 and store.revision == 1


def test_demo_reset_clears_ingestion_ledger(model_input):
    store = MemoryStore()
    assessment = synthetic_assessment(model_input)
    apply_assessment(store, model_input, assessment)
    store.demo(1)
    assert not store.assessment_inputs and not store.incidents
    assert apply_assessment(store, model_input, assessment).changed


def test_lookup_missing_sample_does_not_mutate(model_input):
    store = MemoryStore()
    before = store.snapshot()
    assert lookup_assessment(store, model_input) is None
    assert store.snapshot() == before
    assert not store.assessment_inputs and not store.audit


@pytest.mark.parametrize("action", ["verify", "dismiss"])
def test_lookup_returns_current_operator_state_without_mutation(model_input, action):
    store = MemoryStore()
    first = apply_assessment(store, model_input, synthetic_assessment(model_input))
    store.ack(first.record.id, AckBody(action=action))
    before = store.snapshot()
    lookup = lookup_assessment(store, model_input)
    assert lookup is not None and not lookup.changed
    assert lookup.decision == first.decision
    assert lookup.record is store.get(first.record.id)
    assert lookup.record.status == ("acked" if action == "verify" else "dismissed")
    assert store.snapshot() == before and len(store.audit) == 1


def test_lookup_restored_suppression_preserves_state(model_input):
    store = MemoryStore()
    first = apply_assessment(store, model_input, synthetic_assessment(
        model_input, event="normal", axes=.1, confidence=.9))
    first.record["restored"] = True
    before = store.snapshot()
    lookup = lookup_assessment(store, model_input)
    assert lookup is not None and not lookup.changed
    assert lookup.record is first.record and lookup.record["restored"]
    assert lookup.decision.disposition == "suppressed"
    assert store.snapshot() == before


def test_lookup_rejects_unknown_camera_and_changed_complete_input(model_input):
    store = MemoryStore()
    unknown = model_input.model_copy(update={
        "camera": model_input.camera.model_copy(update={"id":"unknown"})})
    with pytest.raises(ValueError, match="unknown camera"):
        lookup_assessment(store, unknown)
    assert not store.assessment_inputs and store.revision == 0
    apply_assessment(store, model_input, synthetic_assessment(model_input))
    before = store.snapshot()
    changed_input = model_input.model_copy(update={"clip_ref": "different-neutral-ref"})
    with pytest.raises(ValueError, match="sample_id reused with different input"):
        lookup_assessment(store, changed_input)
    assert store.snapshot() == before

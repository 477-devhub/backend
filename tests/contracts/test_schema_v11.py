import pytest
from pydantic import ValidationError

from app.models.execution import execute
from app.schemas.model import ModelAssessment, ModelInput, ModelMetadata, RiskAxes
from tests.contracts.test_execution_validation import ReturnedAssessmentAdapter


def assessment(mi, **updates):
    payload = dict(
        event_type="normal", event_confidence=.99,
        risk_axes={"severity": .2, "imminence": None, "exposure": .4},
        needs_human_review=True, evidence_refs=[mi.evidence[0].frame_id],
        metadata=ModelMetadata(adapter="contract_probe", model="test"),
    )
    payload.update(updates)
    return ModelAssessment(**payload)


def test_partial_axes_roundtrip_preserves_measured_values(mi):
    result = assessment(mi)
    restored = ModelAssessment.model_validate_json(result.model_dump_json())
    assert restored.schema_version == "1.1"
    assert restored.risk_axes.model_dump() == dict(
        severity=.2, imminence=None, exposure=.4, persistence=None)
    assert not restored.risk_axes.is_complete


def test_legacy_complete_output_and_input_remain_readable(mi):
    result = assessment(mi, schema_version="1.0", risk_axes=RiskAxes(
        severity=0, imminence=0, exposure=0, persistence=0), needs_human_review=False)
    assert result.schema_version == "1.0"
    payload = mi.model_dump()
    payload["schema_version"] = "1.0"
    assert ModelInput.model_validate(payload).schema_version == "1.0"
    with pytest.raises(ValidationError, match="partial risk axes"):
        assessment(mi, schema_version="1.0")


async def test_forged_partial_assessment_without_review_is_rejected(mi):
    forged = assessment(mi).model_copy(update={"needs_human_review": False})
    result = await execute(ReturnedAssessmentAdapter(forged), mi)
    assert result.metadata.error_code == "schema_or_contract"
    assert result.risk_axes is None and result.needs_human_review


@pytest.mark.parametrize("key", ["annotations", "caption", "answer", "obj_bbox", "frame_id"])
def test_annotation_envelope_cannot_be_model_input(mi, key):
    payload = mi.model_dump()
    payload[key] = {"evaluation_only": True}
    with pytest.raises(ValidationError, match="Extra inputs"):
        ModelInput.model_validate(payload)

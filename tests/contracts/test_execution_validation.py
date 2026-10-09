import pytest

from app.models.base import ModelAdapter
from app.models.execution import execute
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes
from app.services.incidents import make_incident
from app.services.policy import decide


class ReturnedAssessmentAdapter(ModelAdapter):
    name = "contract_probe"

    def __init__(self, result):
        self.result = result

    async def evaluate(self, model_input):
        return self.result


@pytest.mark.parametrize("invalid", [
    "confidence_high", "confidence_negative", "confidence_nan", "confidence_inf",
    "event_type", "axis_high", "axis_nan", "negative_cost",
])
@pytest.mark.parametrize("as_dict", [False, True])
async def test_invalid_returned_instances_require_review(mi, invalid, as_dict):
    axes = RiskAxes(severity=0, imminence=0, exposure=0, persistence=0)
    metadata = ModelMetadata(adapter="contract_probe", model="test")
    assessment = ModelAssessment(
        event_type="normal", event_confidence=.99, risk_axes=axes,
        evidence_refs=[mi.evidence[0].frame_id], metadata=metadata,
    )
    updates = {
        "confidence_high": {"event_confidence": 2.0},
        "confidence_negative": {"event_confidence": -1.0},
        "confidence_nan": {"event_confidence": float("nan")},
        "confidence_inf": {"event_confidence": float("inf")},
        "event_type": {"event_type": "invented"},
        "axis_high": {"risk_axes": axes.model_copy(update={"severity": 2.0})},
        "axis_nan": {"risk_axes": axes.model_copy(update={"severity": float("nan")})},
        "negative_cost": {"metadata": metadata.model_copy(update={"estimated_cost_usd": -1.0})},
    }
    raw = assessment.model_copy(update=updates[invalid])
    if as_dict:
        # A dict can still contain unvalidated nested Pydantic instances.
        raw = {field: getattr(raw, field) for field in type(raw).model_fields}
    before = mi.model_dump()
    result = await execute(ReturnedAssessmentAdapter(raw), mi)

    assert result.metadata.error_code == "schema_or_contract"
    assert result.risk_axes is None and result.needs_human_review
    assert decide(result).disposition == "review"
    incident = make_incident(mi, result)
    assert incident.risk is None and incident.level == "UNKNOWN"
    assert mi.model_dump() == before

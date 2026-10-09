import pytest

from app.models.execution import failure_assessment
from app.services.incidents import make_incident
from app.services.policy import decide


def test_preprocessing_failure_has_no_claimed_evidence_or_risk(mi):
    result = failure_assessment("local_cv", mi, "preprocessing_error")
    assert result.evidence_refs == []
    assert result.event_type == "uncertain" and result.needs_human_review
    assert result.risk_axes is None and result.metadata.latency_ms is None
    assert result.metadata.estimated_cost_usd is None and not result.metadata.is_mock
    assert decide(result).disposition == "review"
    assert make_incident(mi, result).risk is None


def test_public_failure_helper_rejects_raw_exception_message(mi):
    with pytest.raises(ValueError, match="unsupported failure code"):
        failure_assessment("local_cv", mi, "private provider exception payload")

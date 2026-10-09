from dataclasses import dataclass
from app.schemas.model import ModelAssessment
from app.services.risk import risk_score

@dataclass(frozen=True)
class Decision:
    disposition: str
    risk: int | None
    reason: str

def decide(a: ModelAssessment) -> Decision:
    score = risk_score(a.risk_axes) if a.risk_axes else None
    if a.metadata.error_code or a.metadata.is_mock or a.event_type == "uncertain" or score is None:
        return Decision("review", score, "unmeasured_or_failed")
    if a.needs_human_review or a.event_confidence < .70:
        return Decision("review", score, "uncertainty")
    # Only explicit normal, strong confidence and low measured risk may suppress.
    if a.event_type == "normal" and a.event_confidence >= .90 and score < 20:
        return Decision("suppressed", score, "normal_with_evidence")
    return Decision("incident", score, "risk_or_event")

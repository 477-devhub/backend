from datetime import datetime
from typing import Literal
from pydantic import Field
from app.schemas.model import ContractModel, RiskAxes

class Evidence(ContractModel):
    frame_id: str
    timestamp_ms: int = Field(ge=0)
    t: str
    text: str
    frame_url: str | None = None

class TimelineItem(ContractModel):
    t: str
    label: str
    frame_id: str | None = None
    frame_url: str | None = None

class RelatedView(ContractModel):
    cam_id: str
    role: Literal["best", "secondary"]
    snapshot_url: str | None = None
    match_confidence: float = Field(ge=0, le=1)

class Incident(ContractModel):
    id: str
    sample_id: str
    type: str
    title: str
    primary_cam: str
    related_cams: list[str] = Field(default_factory=list)
    location: str | None = None
    risk: int | None = Field(default=None, ge=0, le=100)
    level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
    risk_axes: RiskAxes | None
    confidence: float = Field(ge=0, le=1)
    needs_human_review: bool
    uncertainty_reason: str | None = None
    rank: int | None = None
    rank_reason: str | None = None
    timeline: list[TimelineItem] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    related_views: list[RelatedView] = Field(default_factory=list)
    ai_opinion: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    next_incident_id: str | None = None
    created_at: datetime
    status: Literal["open", "acked", "dismissed"] = "open"
    dispatch_requested: bool = False
    assigned_operator: str | None = None
    revision: int = Field(default=1, ge=1)

AckAction = Literal["verify", "request_dispatch", "dismiss", "needs_review", "confirm_review", "handover"]
class AckBody(ContractModel):
    action: AckAction
    note: str | None = Field(default=None, max_length=2000)
    to_operator: str | None = Field(default=None, max_length=100)

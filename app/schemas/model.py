from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

EventType = Literal["normal", "collapse", "conflict", "intrusion", "loitering", "uncertain"]
SCHEMA_VERSION = "1.1"
class ContractModel(BaseModel):
    # model_copy/model_construct can bypass validation, including nested values.
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, revalidate_instances="always")

class CameraContext(ContractModel):
    id: str = Field(min_length=1)
    location: str | None = None
    zone_type: str | None = None

class TimeWindow(ContractModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be after start_ms")
        return self

class EvidenceFrame(ContractModel):
    frame_id: str = Field(min_length=1)
    timestamp_ms: int = Field(ge=0)
    # Opaque reference. Only the trusted media resolver may map this to local bytes.
    media_ref: str = Field(min_length=1)

class TemporalState(ContractModel):
    # Feature structures must contain inference-derived observations, never labels.
    person_count: int | None = Field(default=None, ge=0)
    vehicle_count: int | None = Field(default=None, ge=0)
    tracks: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    quality: dict[str, float] = Field(default_factory=dict)
    feature_version: str | None = None

class ModelInput(ContractModel):
    schema_version: Literal["1.0", "1.1"] = SCHEMA_VERSION
    sample_id: str = Field(min_length=1)
    camera: CameraContext
    window: TimeWindow
    clip_ref: str | None = None
    temporal_state: TemporalState = Field(default_factory=TemporalState)
    evidence: list[EvidenceFrame] = Field(default_factory=list)
    @model_validator(mode="after")
    def evidence_valid(self):
        ids = [e.frame_id for e in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate frame_id")
        if any(not self.window.start_ms <= e.timestamp_ms <= self.window.end_ms for e in self.evidence):
            raise ValueError("evidence timestamp outside window")
        return self

class RiskAxes(ContractModel):
    severity: float | None = Field(default=None, ge=0, le=1)
    imminence: float | None = Field(default=None, ge=0, le=1)
    exposure: float | None = Field(default=None, ge=0, le=1)
    persistence: float | None = Field(default=None, ge=0, le=1)

    @property
    def is_complete(self) -> bool:
        return all(value is not None for value in self.model_dump().values())

class ModelMetadata(ContractModel):
    adapter: str
    model: str
    is_mock: bool = False
    latency_ms: float | None = Field(default=None, ge=0)
    input_units: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    prompt_version: str | None = None
    stage_trace: list["StageRecord"] = Field(default_factory=list, max_length=16)

class StageRecord(ContractModel):
    stage: Literal["prepare", "cv", "p1", "p4", "map"]
    status: Literal["ok", "failed", "skipped"]
    latency_ms: float | None = Field(default=None, ge=0)
    attempts: int = Field(default=0, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    request_id: str | None = None

class RoutingAssessment(ContractModel):
    mode: Literal["shadow", "frozen_cascade_v1"]
    policy_version: Literal["conservative_normal_then_p4-v1"] = "conservative_normal_then_p4-v1"
    selected_stage: Literal["p1", "p4", "fallback"]
    p_incident: float | None = Field(default=None, ge=0, le=1)
    frozen_guard_passed: bool = False
    backend_guard_passed: bool = False
    evidence_scope: Literal["window_observations", "cited_frames", "none"] = "none"

    @model_validator(mode="after")
    def guarded_p1(self):
        if self.selected_stage == "p1" and not (
            self.mode == "frozen_cascade_v1" and self.frozen_guard_passed
            and self.backend_guard_passed and self.p_incident is not None
            and self.p_incident <= .01 and self.evidence_scope == "window_observations"
        ):
            raise ValueError("P1 suppression requires both guards")
        return self

class ModelAssessment(ContractModel):
    schema_version: Literal["1.0", "1.1"] = SCHEMA_VERSION
    event_type: EventType
    event_confidence: float = Field(ge=0, le=1)
    # null = unmeasured; do not fabricate axes for provider/schema failures.
    risk_axes: RiskAxes | None
    needs_human_review: bool = False
    uncertainty_reason: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    ai_opinion: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    metadata: ModelMetadata
    routing: RoutingAssessment | None = None
    evidence_descriptions: dict[str, str] = Field(default_factory=dict)
    @model_validator(mode="after")
    def unknown_goes_to_review(self):
        incomplete = self.risk_axes is not None and not self.risk_axes.is_complete
        if self.schema_version == "1.0" and incomplete:
            raise ValueError("partial risk axes require schema_version 1.1")
        if (self.risk_axes is None or incomplete or self.event_type == "uncertain" or self.metadata.error_code) and not self.needs_human_review:
            raise ValueError("unknown/error assessment requires human review")
        if self.routing and self.routing.selected_stage == "p1":
            axes = self.risk_axes
            score = round(100 * (.35*axes.severity + .30*axes.imminence + .20*axes.exposure + .15*axes.persistence)) if axes and axes.is_complete else None
            if self.event_type != "normal" or self.event_confidence < .90 or self.needs_human_review or score is None or score >= 20 or self.metadata.error_code or self.metadata.is_mock or self.evidence_refs or self.evidence_descriptions:
                raise ValueError("invalid P1 window-level normal assessment")
        return self

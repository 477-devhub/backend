"""HACKATHON-DAY: additive frontend API contracts, independent of model schema."""
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.model import ContractModel

API_CONTRACT_VERSION = "1.2"

class BoxOverlay(ContractModel):
    frame_id: str
    timestamp_ms: int = Field(ge=0)
    xywh: tuple[float, float, float, float]
    coordinate_space: Literal["normalized_xywh"] = "normalized_xywh"
    detection_confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def valid_rect(self):
        x,y,w,h=self.xywh
        if any(v < 0 or v > 1 for v in self.xywh) or x+w > 1 or y+h > 1:
            raise ValueError("normalized rectangle must fit within image")
        return self

class CameraState(ContractModel):
    id: str
    name: str
    location: str | None
    stream_url: str
    status: str
    bbox: list[BoxOverlay] = Field(default_factory=list)
    level: str | None = None
    suppressed: bool = False
    analysis_status: Literal["demo", "not_analyzed", "analyzed"]
    media_available: bool
    video_source: Literal["local_file", "not_configured"]
    is_demo: bool

class ServerStatus(ContractModel):
    ok: bool
    mode: str
    system_status: str
    timestamp: str
    active_count: int
    total_cameras: int
    configured_cameras: int
    revision: int
    target_camera_capacity: int
    observed_cameras: int
    server_instance_id: str
    api_contract_version: str
    is_demo: bool


from app.schemas.incident import Incident

class SnapshotEnvelope(ContractModel):
    event_type: Literal["snapshot"]
    schema_version: str
    api_contract_version: str
    server_instance_id: str
    revision: int
    active_count: int
    total_cameras: int
    target_camera_capacity: int
    configured_cameras: int
    observed_cameras: int
    suppressed_count: int
    level_counts: dict[str,int]
    incidents: list[Incident]
    cameras: list[CameraState]
    is_demo: bool

class ClipMetadata(ContractModel):
    clip_url: str
    start: float | None
    end: float | None
    bbox_track: list[BoxOverlay]
    available: bool
    is_demo: bool
    duration_sec: float | None
    range_valid: bool | None
    duration_status: Literal["measured","unmeasured"]
    time_unit: Literal["seconds"]
    time_reference: Literal["source_video_start"]
    delivery: Literal["full_file"]
    crop_available: bool
    range_source: Literal["model_input_window","synthetic_demo","unavailable"]
    bbox_coordinate_space: Literal["normalized_xywh"]
    bbox_available: bool
    source: Literal["incident_source","camera_file"]

class PipelineStats(ContractModel):
    total: int
    configured_cameras: int
    candidates: int
    reasoned: int
    incidents: int
    suppressed: int
    needs_review: int
    avg_latency_sec: float | None
    total_latency_sec: float | None
    stage_trace: list[dict]
    today_summary: dict
    measurement_scope: str
    counter_semantics: str
    target_camera_capacity: int
    observed_cameras: int
    accepted_inputs: int
    latency_measurement_status: str
    today_summary_scope: str
    server_instance_id: str
    api_contract_version: str

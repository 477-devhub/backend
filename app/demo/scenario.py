"""HACKATHON-DAY: explicit scripted demo configuration, never model output."""
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.model import RiskAxes
from app.schemas.incident import Incident
from app.services.risk import risk_score, risk_level

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class DemoCamera(Strict):
    id: str
    region: str
    sync_group: str | None = None
    offset_sec: float = Field(default=0, ge=0, allow_inf_nan=False)
    role: Literal["same_event", "unassigned"]
    video_file: str

class DemoEvent(Strict):
    id: str
    title: str
    type: str
    members: list[str]
    primary_cam: str
    min_step: int = Field(ge=1, le=6)
    enabled: bool = True
    risk_axes: RiskAxes | None
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    needs_human_review: bool

class DemoScenario(Strict):
    schema_version: Literal["demo-scenario-1"]
    decision_source: Literal["scripted_not_ai"]
    cameras: list[DemoCamera]
    incidents: list[DemoEvent]

    @model_validator(mode="after")
    def references(self):
        ids=[c.id for c in self.cameras]
        if set(ids)!={f"CAM_{n:02d}" for n in range(1,10)} or len(ids)!=9:
            raise ValueError("scenario requires nine unique camera IDs")
        for c in self.cameras:
            if c.video_file!=c.id+".mp4":
                raise ValueError("video filenames must use registered camera IDs")
        if len({e.id for e in self.incidents})!=len(self.incidents):
            raise ValueError("duplicate incident ID")
        active=set()
        for e in self.incidents:
            if not e.members or len(set(e.members))!=len(e.members) or e.primary_cam not in e.members or not set(e.members)<=set(ids):
                raise ValueError("invalid event camera references")
            if e.enabled:
                if active & set(e.members):
                    raise ValueError("a camera cannot belong to two scripted events")
                active.update(e.members)
            if (e.risk_axes is None or not e.risk_axes.is_complete) and not e.needs_human_review:
                raise ValueError("unknown risk must require review")
        return self

    def records(self, step, now):
        for e in self.incidents:
            if not e.enabled or step<e.min_step:
                continue
            score=risk_score(e.risk_axes) if e.risk_axes else None
            yield Incident(id=e.id,sample_id="scripted-"+e.id,type=e.type,title=e.title,
                primary_cam=e.primary_cam,related_cams=[c for c in e.members if c!=e.primary_cam],
                risk=score,level=risk_level(score) if score is not None else "UNKNOWN",
                risk_axes=e.risk_axes,confidence=e.confidence,needs_human_review=e.needs_human_review,
                uncertainty_reason="scripted_review_candidate" if e.needs_human_review else None,
                ai_opinion="시나리오로 지정된 판단입니다. AI 분석 결과가 아닙니다.",
                created_at=now)

def load_scenario(path: Path | None):
    return DemoScenario.model_validate_json(path.read_text(encoding="utf-8")) if path else None

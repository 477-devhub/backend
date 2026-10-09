import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from pydantic import Field
from app.schemas.model import ContractModel, ModelInput, TimeWindow, EventType, RiskAxes

class ManifestRow(ContractModel):
    sample_id: str = Field(pattern=r"^s_[a-z0-9]{6,64}$")
    split: Literal["train", "validation", "test"]
    scenario_group: str
    source_video_id: str
    video_path: str
    media_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_path: str
    camera_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    event_type: EventType
    critical: bool | None = None
    needs_human_review: bool | None = None
    risk_axes: RiskAxes | None = None
    @property
    def window(self): return TimeWindow(start_ms=self.start_ms,end_ms=self.end_ms)

def safe_path(root: Path, relative: str) -> Path:
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError("path escapes dataset root")
    return path

def validate_manifest(path: Path) -> list[ManifestRow]:
    rows=[ManifestRow.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows: raise ValueError("empty manifest")
    ids=set();ownership={};root=path.parent
    for row in rows:
        _=row.window
        if row.sample_id in ids: raise ValueError("duplicate sample_id")
        ids.add(row.sample_id)
        for kind,value in [("scenario",row.scenario_group),("source",row.source_video_id),("content",row.media_sha256)]:
            key=(kind,value)
            if key in ownership and ownership[key]!=row.split: raise ValueError("cross-split leakage: "+kind)
            ownership[key]=row.split
        media=safe_path(root,row.video_path)
        h=hashlib.sha256()
        with media.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=row.media_sha256: raise ValueError("media hash mismatch")
        load_input(row,root)
    return rows

FORBIDDEN_KEYS={
    "event_type","ground_truth","label","labels","split","critical",
    "needs_human_review","risk_axes","scenario_group","source_video_id","video_path",
    "annotations","caption","caption_text","cot","answer","question","event_class",
    "evidence_text","obj_bbox","obj_id","obj_label",
}
def check_observations(value):
    if isinstance(value,dict):
        if set(value)&FORBIDDEN_KEYS: raise ValueError("label-like key in inference observations")
        for v in value.values():check_observations(v)
    elif isinstance(value,list):
        for v in value:check_observations(v)

def load_input(row: ManifestRow, root: Path) -> ModelInput:
    # Observations are produced by trusted ingestion, never annotation conversion.
    mi=ModelInput.model_validate_json(safe_path(root,row.input_path).read_text(encoding="utf-8"))
    if (mi.sample_id,mi.camera.id,mi.window.start_ms,mi.window.end_ms)!=(row.sample_id,row.camera_id,row.start_ms,row.end_ms):
        raise ValueError("manifest/input identity mismatch")
    check_observations(mi.temporal_state.model_dump(mode="json"))
    state=mi.temporal_state
    has_observations=(state.person_count is not None or state.vehicle_count is not None
        or bool(state.tracks or state.events or state.relations or state.quality))
    if has_observations and not (state.feature_version and state.feature_version.strip()):
        raise ValueError("feature_version required for observations")
    if mi.clip_ref and not re.fullmatch(r"clip_[a-z0-9_]+",mi.clip_ref):raise ValueError("clip_ref must be an opaque token")
    for e in mi.evidence:
        if not re.fullmatch(r"(?:frame_[a-z0-9_]+|media_[a-f0-9]{64})",e.media_ref):
            raise ValueError("media_ref must be an opaque frame token")
    return mi

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from app.repositories.memory import MemoryStore
from app.schemas.model import ModelInput, ModelAssessment
from app.schemas.incident import Incident, Evidence
from app.services.policy import Decision, decide
from app.services.risk import risk_level

def make_incident(mi: ModelInput, a: ModelAssessment) -> Incident:
    d = decide(a)
    if d.disposition == "suppressed":
        raise ValueError("suppressed assessment is not an active incident")
    incident_id = "INC-" + hashlib.sha256(mi.sample_id.encode()).hexdigest()[:16]
    refs = set(a.evidence_refs)
    return Incident(id=incident_id, sample_id=mi.sample_id, type=a.event_type,
        title=a.ai_opinion or ("판단 불가 · 사람 검토" if d.disposition == "review" else a.event_type),
        primary_cam=mi.camera.id, location=mi.camera.location,
        risk=d.risk, risk_axes=a.risk_axes, level=risk_level(d.risk), confidence=a.event_confidence,
        needs_human_review=d.disposition == "review", uncertainty_reason=a.uncertainty_reason,
        evidence=[Evidence(frame_id=e.frame_id, timestamp_ms=e.timestamp_ms,
            t=f"{e.timestamp_ms//60000:02d}:{e.timestamp_ms//1000%60:02d}", text=a.evidence_descriptions.get(e.frame_id, "Referenced observation"))
            for e in mi.evidence if e.frame_id in refs],
        ai_opinion=a.ai_opinion, recommended_actions=a.recommended_actions,
        created_at=datetime.now(timezone.utc))


@dataclass(frozen=True)
class AppliedAssessment:
    decision: Decision
    record: Incident | dict
    changed: bool


def _input_fingerprint(mi: ModelInput) -> str:
    return hashlib.sha256(json.dumps(
        mi.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def lookup_assessment(store: MemoryStore, mi: ModelInput) -> AppliedAssessment | None:
    """Read a prior accepted decision under the caller's mutation lock.

    Call before execute while holding a separate per-sample execution lock, so a
    replay never starts another inference. This helper does not mutate the store.
    """
    if mi.camera.id not in {camera["id"] for camera in store.cameras}:
        raise ValueError("unknown camera")
    previous = store.assessment_inputs.get(mi.sample_id)
    if previous is not None:
        if previous["fingerprint"] != _input_fingerprint(mi):
            raise ValueError("sample_id reused with different input")
        records = store.suppressed if previous["kind"] == "suppressed" else store.incidents
        return AppliedAssessment(previous["decision"], records[previous["id"]], False)
    return None


def apply_assessment(store: MemoryStore, mi: ModelInput, a: ModelAssessment) -> AppliedAssessment:
    """Persist an assessment already validated by execute, under the caller's lock.

    sample_id identifies one immutable input, rather than one provider attempt.
    Replays retain the first decision and current operator state. A new observation
    needs a new sample_id. This in-memory ledger is cleared by demo resets/restarts.
    """
    previous = lookup_assessment(store, mi)
    if previous is not None:
        return previous

    decision = decide(a)
    if decision.disposition == "suppressed":
        record_id = "SUP-" + hashlib.sha256(mi.sample_id.encode()).hexdigest()[:16]
        record = {
            "id": record_id, "sample_id": mi.sample_id, "cam_id": mi.camera.id,
            "stage1_label": None, "ai_verdict": a.event_type,
            "reason": decision.reason, "risk": decision.risk,
            "resumed_walking": None, "restored": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "evidence_refs": list(a.evidence_refs),
            "metadata": a.metadata.model_dump(mode="json"),
            "routing": a.routing.model_dump(mode="json") if a.routing else None,
            "evidence_scope": a.routing.evidence_scope if a.routing else ("cited_frames" if a.evidence_refs else "none"),
        }
        records = store.suppressed
    else:
        record = make_incident(mi, a)
        record_id = record.id
        records = store.incidents
    if record_id in records:
        raise ValueError("assessment record already exists")
    records[record_id] = record
    store.assessment_inputs[mi.sample_id] = {
        "fingerprint": _input_fingerprint(mi), "decision": decision,
        "camera_id":mi.camera.id, "metadata":a.metadata.model_dump(mode="json"),
        "kind": "suppressed" if decision.disposition == "suppressed" else "incident",
        "id": record_id,
    }
    # Window observations still have a source clip, even without cited frames.
    store.media_context[record_id] = {"start_ms":mi.window.start_ms,"end_ms":mi.window.end_ms,"clip_ref":mi.clip_ref}
    store.revision += 1
    return AppliedAssessment(decision, record, True)

"""Frozen benchmark contracts; labels are deliberately separate from inputs."""
import hashlib
import json
import math
from pathlib import Path

LABELS = ["normal", "fall_ground_posture", "boundary_crossing",
          "gate_entry_authorization_unknown", "physical_conflict", "loitering", "uncertain"]
SYNONYMS = {"collapse": "fall_ground_posture", "fall": "fall_ground_posture",
            "ground posture": "fall_ground_posture", "fight": "physical_conflict",
            "conflict": "physical_conflict", "boundary crossing": "boundary_crossing",
            "gate entry": "gate_entry_authorization_unknown"}
CLASSES = ["person", "bicycle", "car", "motorcycle", "bus", "truck"]
COLUMNS = ["item_id", "sources", "models", "ground_truth", "stage_inputs", "stage_outputs",
           "metrics", "latency_ms", "cost_usd", "status", "errors"]
COMBINATIONS = [[i] for i in range(1, 7)] + [[1, 2], [5, 6], [1, 3, 5],
                                          [1, 2, 3, 4], [1, 2, 3, 4, 5], list(range(1, 7))]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def allocations(count):
    if not 1 <= count <= 6:
        raise ValueError("source count must be 1..6")
    q, r = divmod(64, count)
    return [q + (i < r) for i in range(count)]

def indices(frame_count, count):
    if frame_count < count or count < 2:
        raise ValueError("insufficient unique frames")
    return [int(math.floor(j * (frame_count - 1) / (count - 1) + .5)) for j in range(count)]

def validate_input(data, verify_pixels=True):
    sources = data["sources"]
    if len(sources) != len(set(sources)) or not 1 <= len(sources) <= 6:
        raise ValueError("invalid sources")
    frames = data["frames"]
    if len(frames) != 64 or len({f["frame_id"] for f in frames}) != 64:
        raise ValueError("64 unique frames required")
    if any(k in data for k in ("ground_truth", "annotations", "reference_label")):
        raise ValueError("label leakage")
    for source, expected in zip(sources, allocations(len(sources))):
        rows = [f for f in frames if f["source_id"] == source]
        if len(rows) != expected:
            raise ValueError("wrong allocation")
        numbers = [f["frame_number"] for f in rows]
        times = [f["timestamp_sec"] for f in rows]
        if numbers != sorted(set(numbers)) or times != sorted(set(times)):
            raise ValueError("source order/mapping")
        for f in rows:
            if type(f["frame_number"]) is not int or f["frame_number"] < 0:
                raise ValueError("invalid frame number")
            if not math.isfinite(f["timestamp_sec"]) or f["timestamp_sec"] < 0:
                raise ValueError("invalid timestamp")
            if verify_pixels and digest(f["image_path"]) != f["sha256"]:
                raise ValueError("pixel digest mismatch")
    if set(f["source_id"] for f in frames) != set(sources):
        raise ValueError("unknown source")
    if not set(data.get("active_sources", sources)) <= set(sources):
        raise ValueError("unknown active source")
    return True

def output_schema():
    axis = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
    assessment = {"type": "object", "additionalProperties": False,
        "required": ["source_id", "event_type", "event_confidence", "risk_axes", "evidence_refs",
                     "needs_human_review", "uncertainty_reason"],
        "properties": {"source_id": {"type": "string", "pattern": "^SRC0[1-6]$"},
            "event_type": {"type": "string", "enum": LABELS},
            "event_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "risk_axes": {"type": "object", "additionalProperties": False,
                "required": ["severity", "imminence", "exposure", "persistence"],
                "properties": {k: axis for k in ["severity", "imminence", "exposure", "persistence"]}},
            "evidence_refs": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
            "needs_human_review": {"type": "boolean"},
            "uncertainty_reason": {"type": ["string", "null"]}}}
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "additionalProperties": False, "required": ["assessments"],
            "properties": {"assessments": {"type": "array", "items": assessment}}}

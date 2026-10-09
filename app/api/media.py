"""HACKATHON-DAY: serve only registered incident evidence and trusted local video."""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response

MAX_FRAME_BYTES = 8 * 1024 * 1024

def local_camera_path(s, camera):
    if camera not in {c["id"] for c in s.store.cameras}:
        raise HTTPException(404, "camera not found")
    root = s.settings.media_root.resolve()
    path = (root / (camera + ".mp4")).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(400, "invalid media path")
    return path

def source_path(s, incident):
    context = s.store.media_context.get(incident.id, {})
    ref = context.get("clip_ref")
    resolver = s.store.incident_resolvers.get(incident.id, s.media_resolver)
    if ref and resolver and ref in resolver.mapping:
        root = resolver.root.resolve()
        path = (root / resolver.mapping[ref]).resolve()
        if path.is_relative_to(root) and path.suffix.lower() == ".mp4" and path.is_file():
            return path, "incident_source"
    return local_camera_path(s, incident.primary_cam), "camera_file"

def frame_asset(s, incident, frame_index):
    if frame_index < 0 or frame_index >= len(incident.evidence):
        raise HTTPException(404, "evidence frame not found")
    frame = incident.evidence[frame_index]
    binding = s.store.frame_bindings.get((incident.id, frame.frame_id))
    if binding is None:
        raise HTTPException(503, "evidence image not configured")
    resolver, ref = binding
    try:
        value = resolver.read(ref, max_bytes=MAX_FRAME_BYTES)
    except ValueError as exc:
        if "exceeds byte budget" in str(exc):
            raise HTTPException(413, "evidence image exceeds allowed size")
        raise HTTPException(503, "evidence image unavailable")
    except (KeyError, OSError):
        raise HTTPException(503, "evidence image unavailable")
    if value.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif value.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif value[:4] == b"RIFF" and value[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise HTTPException(503, "evidence image format unsupported")
    return value, mime

def present_incident(s, incident_id):
    result = s.store.present(incident_id).model_dump(mode="json")
    incident = s.store.get(incident_id)
    for index, evidence in enumerate(result["evidence"]):
        try:
            frame_asset(s, incident, index)
        except HTTPException:
            evidence["frame_url"] = None
        else:
            evidence["frame_url"] = f"/api/incidents/{incident_id}/frames/{index}"
    return result

def _duration(path):
    executable = shutil.which("ffprobe")
    if not executable or not path.is_file():
        return None
    try:
        completed = subprocess.run([executable, "-v", "error", "-show_entries",
            "format=duration", "-of", "json", str(path)], capture_output=True, timeout=3, check=True)
        value = float(json.loads(completed.stdout)["format"]["duration"])
        import math
        return value if math.isfinite(value) and value > 0 else None
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None

async def clip_metadata(s, incident):
    path, source = source_path(s, incident)
    duration = await asyncio.to_thread(_duration, path)
    context = s.store.media_context.get(incident.id)
    is_demo = incident.sample_id.startswith(("demo-", "restore-"))
    start = context["start_ms"] / 1000 if context else (0 if is_demo else None)
    end = context["end_ms"] / 1000 if context else (10 if is_demo else None)
    valid_range = None if duration is None or start is None or end is None else 0 <= start < end <= duration
    return {"clip_url":f"/api/incidents/{incident.id}/video" if source == "incident_source" else f"/stream/{incident.primary_cam}",
        "start":start, "end":end, "bbox_track":[], "available":path.is_file(),
        "is_demo":is_demo, "duration_sec":duration, "range_valid":valid_range,
        "duration_status":"measured" if duration is not None else "unmeasured",
        "time_unit":"seconds", "time_reference":"source_video_start",
        "delivery":"full_file", "crop_available":False,
        "range_source":"model_input_window" if context else ("synthetic_demo" if is_demo else "unavailable"),
        "bbox_coordinate_space":"normalized_xywh", "bbox_available":False,
        "source":source}

def video_response(s, incident):
    path, _ = source_path(s, incident)
    if not path.is_file():
        raise HTTPException(503, "incident video not configured")
    return FileResponse(path, media_type="video/mp4")

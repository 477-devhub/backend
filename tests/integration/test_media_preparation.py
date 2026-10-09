"""Synthetic encoded bytes verify the preprocessing/incident seam, never model accuracy."""
import shutil
import subprocess

import pytest

from app.config import Settings
from app.main import create_app
from app.models.media import MediaResolver
from app.models.registry import get_adapter
from app.schemas.model import TimeWindow, TemporalState


async def test_synthetic_video_to_actual_frame_refs_and_mock_review(mi, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("external FFmpeg executable is required for the synthetic decode test")
    encoded = subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "testsrc=size=64x48:rate=3:duration=2", "-threads", "1",
        "-c:v", "ffv1", "-f", "matroska", "pipe:1",
    ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10).stdout
    resolver = MediaResolver(tmp_path, {}, assets={"clip_000001": encoded})
    app = create_app(Settings(media_root=tmp_path), adapter=get_adapter("mock_local_cv"), media_resolver=resolver)
    raw = mi.model_copy(update={
        "clip_ref": "clip_000001", "window": TimeWindow(start_ms=0, end_ms=1700),
        "evidence": [], "temporal_state": TemporalState(events=[{"description": "discard supplied observation"}]),
    })
    prepared = await app.state.prepare_model_input(raw)
    assert prepared.model_input.temporal_state == TemporalState()
    assert prepared.profile["frame_count"] == 4 and prepared.profile["actual_frame_count"] == 4
    assert prepared.preprocessing_ms >= 0 and prepared.ffmpeg_version
    assert len(prepared.model_input.evidence) == 4
    assert all(prepared.resolver.read(frame.media_ref).startswith(b"\xff\xd8")
               for frame in prepared.model_input.evidence)
    assert prepared.resolver.read("clip_000001") == encoded
    applied = await app.state.ingest_model_input(prepared.model_input)
    assert applied.decision.disposition == "review"
    assert applied.record.risk is None and applied.record.level == "UNKNOWN"
    assert [(frame.frame_id, frame.timestamp_ms) for frame in applied.record.evidence] == [
        (frame.frame_id, frame.timestamp_ms) for frame in prepared.model_input.evidence
    ]

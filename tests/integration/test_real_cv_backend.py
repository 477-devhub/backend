"""Real CPU HOG execution on SYNTHETIC media; no CCTV classification claim."""
import asyncio
import json
import shutil
import subprocess

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.adapters.ingestion import MediaIngestion
from app.models.adapters.local_cv import LocalCVAdapter
from app.models.media import MediaResolver
from app.schemas.model import TemporalState, TimeWindow


def test_real_cv_to_repository_ws_ack_and_reconnect(mi, tmp_path, monkeypatch):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None, "FFmpeg is required for real CV integration validation"
    encoded = subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=black:size=640x360:rate=4:duration=2", "-threads", "1",
        "-c:v", "mpeg4", "-f", "mp4", "-movflags", "frag_keyframe+empty_moov", "pipe:1",
    ], check=True, capture_output=True, timeout=10).stdout
    resolver = MediaResolver(tmp_path, {}, assets={"clip_000001": encoded})
    raw = mi.model_copy(update={"sample_id": "s_000001", "clip_ref": "clip_000001",
        "window": TimeWindow(start_ms=0, end_ms=2000), "evidence": [],
        "temporal_state": TemporalState()})
    prepared = asyncio.run(MediaIngestion(resolver).prepare(raw))
    app = create_app(Settings(media_root=tmp_path, model_timeout_sec=10),
                     media_resolver=prepared.resolver)
    assert isinstance(app.state.model_adapter, LocalCVAdapter)
    captured = []
    original_evaluate = app.state.model_adapter.evaluate
    async def capture_actual_result(model_input):
        result = await original_evaluate(model_input)
        captured.append(result)
        return result
    monkeypatch.setattr(app.state.model_adapter, "evaluate", capture_actual_result)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/attention") as ws:
            assert ws.receive_json()["schema_version"] == "1.1"
            applied = client.portal.call(app.state.ingest_model_input, prepared.model_input)
            snapshot = ws.receive_json()
            incident = applied.record
            assert applied.decision.disposition == "review" and snapshot["active_count"] == 1
            assert incident.risk is None and incident.level == "UNKNOWN"
            detail = client.get("/api/incidents/" + incident.id).json()
            assert len(captured) == 1
            assert captured[0].metadata.adapter == "local_cv"
            assert captured[0].metadata.is_mock is False and captured[0].metadata.error_code is None
            assert detail["type"] == "uncertain"
            assert all(v is None for v in detail["risk_axes"].values())
            assert [e["frame_id"] for e in detail["evidence"]] == [e.frame_id for e in prepared.model_input.evidence]
            observation = app.state.model_adapter.last_observation
            assert observation.clip_sha256 == prepared.clip_sha256
            assert observation.temporal_state.feature_version == "opencv-hog-iou-v1"
            headers = {"Idempotency-Key": "real-cv-synthetic-ack"}
            url = "/api/incidents/" + incident.id + "/ack"
            response = client.post(url, json={"action": "verify"}, headers=headers)
            assert response.status_code == 200 and ws.receive_json()["active_count"] == 0
            assert client.post(url, json={"action": "verify"}, headers=headers).json() == response.json()
            async def forbidden_reexecution(_):
                raise AssertionError("completed sample must not execute again")
            monkeypatch.setattr(app.state.model_adapter, "evaluate", forbidden_reexecution)
            replay = client.portal.call(app.state.ingest_model_input, prepared.model_input)
            assert not replay.changed and replay.record.status == "acked"
            revision = app.state.store.revision
        with client.websocket_connect("/ws/attention") as ws:
            restored = ws.receive_json()
            assert restored["active_count"] == 0 and restored["revision"] == revision
        assert not app.state.hub.clients


def test_settings_asset_map_reaches_real_adapter_and_missing_media_reviews(mi, tmp_path):
    asset_map = tmp_path / "asset-map.json"
    asset_map.write_text(json.dumps({"clip_000001": "absent.mp4"}), encoding="utf-8")
    app = create_app(Settings(media_root=tmp_path, asset_map_path=asset_map))
    assert isinstance(app.state.model_adapter, LocalCVAdapter)
    with TestClient(app) as client:
        invalid = mi.model_copy(update={"clip_ref": "clip_000001"})
        with client.websocket_connect("/ws/attention") as ws:
            ws.receive_json()
            result = client.portal.call(app.state.ingest_model_input, invalid)
            assert result.decision.disposition == "review" and result.record.risk is None
            assert ws.receive_json()["active_count"] == 1
            assert result.record.uncertainty_reason == "provider_error"

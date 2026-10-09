"""HACKATHON-DAY frontend preparation tests; synthetic inputs, no provider calls."""
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.models.base import ModelAdapter
from app.models.media import MediaResolver
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes
from app.schemas.incident import Incident
from app.api.contracts import BoxOverlay

def post(client, path, body, key):
    return client.post(path, json=body, headers={"Idempotency-Key":key})

def test_http_snapshot_matches_ws_and_epoch(client):
    with client.websocket_connect("/ws/attention") as ws:
        first=ws.receive_json()
        assert first == client.get("/api/snapshot").json()
        assert first["api_contract_version"]=="1.2"
        epoch=first["server_instance_id"]
        post(client,"/api/demo/step",{"step":5},"new")
        changed=ws.receive_json()
        assert changed["server_instance_id"]==epoch and changed["revision"]>first["revision"]
    with TestClient(create_app()) as another:
        assert another.get("/api/snapshot").json()["server_instance_id"]!=epoch

def test_counts_and_unobserved_state(tmp_path):
    with TestClient(create_app(Settings(mode="development",media_root=tmp_path))) as c:
        status=c.get("/api/status").json()
        assert status["configured_cameras"]==9 and status["target_camera_capacity"]==477
        assert status["observed_cameras"]==0
        cam=c.get("/api/cameras").json()[0]
        assert cam["status"]=="unobserved" and cam["analysis_status"]=="not_analyzed"
        assert not cam["media_available"] and not cam["is_demo"]
        stats=c.get("/api/pipeline/stats").json()
        assert stats["accepted_inputs"]==0 and stats["avg_latency_sec"] is None
        assert stats["today_summary_scope"]=="current_snapshot_not_daily"

def test_ack_rank_cleared_and_replay_stable(client):
    post(client,"/api/demo/step",{"step":5},"demo")
    body=post(client,"/api/incidents/INC-032/ack",{"action":"verify"},"verify").json()
    assert body["incident"]["rank"] is None and body["incident"]["next_incident_id"] is None
    assert body["server_instance_id"]==client.get("/api/status").json()["server_instance_id"]
    assert post(client,"/api/incidents/INC-032/ack",{"action":"verify"},"verify").json()==body
    assert client.get("/api/incidents/INC-033").json()["rank"]==1

@pytest.mark.parametrize("path",["/api/incidents/missing","/stream/missing","/api/incidents/missing/frames/0","/unknown"])
def test_error_format(client,path):
    result=client.get(path)
    assert result.status_code==404
    assert result.json()["error"]["code"]=="not_found"
    assert "detail" in result.json()

def test_validation_does_not_echo_input(client):
    result=client.post("/api/demo/step",json={"step":"SECRET_TOKEN"},headers={"Idempotency-Key":"x"})
    assert result.status_code==422
    assert result.json()["error"]["code"]=="validation_error"
    assert "SECRET_TOKEN" not in result.text

def test_clip_range_and_unmeasured_duration(client,monkeypatch):
    post(client,"/api/demo/step",{"step":3},"demo")
    meta=client.get("/api/incidents/INC-032/clip").json()
    assert meta["start"]==0 and meta["end"]==10
    assert meta["duration_sec"] is None and meta["range_valid"] is None
    assert meta["time_reference"]=="source_video_start" and not meta["crop_available"]
    (client.app.state.settings.media_root/"CAM_08.mp4").write_bytes(b"synthetic_video")
    monkeypatch.setattr("app.api.media._duration",lambda p:12.5)
    meta=client.get("/api/incidents/INC-032/clip").json()
    assert meta["duration_sec"]==12.5 and meta["range_valid"] is True

class FixedAdapter(ModelAdapter):
    name="synthetic_frontend_contract"
    async def evaluate(self,mi):
        return ModelAssessment(event_type="collapse",event_confidence=.99,
            risk_axes=RiskAxes(severity=1,imminence=1,exposure=1,persistence=1),
            evidence_refs=[mi.evidence[0].frame_id],
            metadata=ModelMetadata(adapter=self.name,model="synthetic-only"))

def test_registered_evidence_and_actual_window(mi,tmp_path):
    ref=mi.evidence[0].media_ref
    pixels=b"\x89PNG\r\n\x1a\nsynthetic_test"
    resolver=MediaResolver(tmp_path,{},assets={ref:pixels})
    with TestClient(create_app(Settings(mode="development",media_root=tmp_path),
                              adapter=FixedAdapter(),media_resolver=resolver)) as c:
        applied=c.portal.call(c.app.state.ingest_model_input,mi)
        iid=applied.record.id
        detail=c.get("/api/incidents/"+iid).json()
        frame=detail["evidence"][0]
        assert frame["frame_url"]==f"/api/incidents/{iid}/frames/0"
        result=c.get(frame["frame_url"])
        assert result.status_code==200 and result.content==pixels
        assert result.headers["content-type"]=="image/png"
        assert c.get(f"/api/incidents/{iid}/frames/1").status_code==404
        meta=c.get(f"/api/incidents/{iid}/clip").json()
        assert meta["start"]==mi.window.start_ms/1000 and meta["end"]==mi.window.end_ms/1000
        assert meta["range_source"]=="model_input_window" and not meta["is_demo"]
        assert next(cam for cam in c.get("/api/cameras").json() if cam["id"]==mi.camera.id)["analysis_status"]=="analyzed"

def test_missing_frame_returns_null_and_safe_error(client):
    post(client,"/api/demo/step",{"step":3},"demo")
    assert client.get("/api/incidents/INC-032/frames/0").status_code==404

def test_symlink_source_not_served(mi,tmp_path):
    # Trusted resolver still rejects an escaping path; no arbitrary source-file endpoint.
    outside=tmp_path.parent/"private.mp4"
    outside.write_bytes(b"private")
    resolver=MediaResolver(tmp_path,{mi.clip_ref:"../private.mp4"} if mi.clip_ref else {})
    with TestClient(create_app(Settings(media_root=tmp_path),adapter=FixedAdapter(),media_resolver=resolver)) as c:
        applied=c.portal.call(c.app.state.ingest_model_input,mi)
        assert c.get("/api/incidents/"+applied.record.id+"/video").status_code==503

def test_cors_idempotency_preflight(client):
    response=client.options("/api/demo/step",headers={"Origin":"http://localhost:5173",
        "Access-Control-Request-Method":"POST","Access-Control-Request-Headers":"Idempotency-Key"})
    assert response.status_code==200
    assert response.headers["access-control-allow-origin"]=="http://localhost:5173"

def test_box_coordinate_contract():
    box=BoxOverlay(frame_id="f",timestamp_ms=0,xywh=(.1,.2,.3,.4))
    assert box.coordinate_space=="normalized_xywh"
    with pytest.raises(ValueError):
        BoxOverlay(frame_id="f",timestamp_ms=0,xywh=(.8,0,.4,.3))

def test_configured_count_uses_registered_cameras(client):
    client.app.state.store.cameras=client.app.state.store.cameras[:2]
    assert client.get("/api/status").json()["configured_cameras"]==2
    assert client.get("/api/pipeline/stats").json()["configured_cameras"]==2
    assert client.get("/api/snapshot").json()["configured_cameras"]==2
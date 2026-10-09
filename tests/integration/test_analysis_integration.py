"""Controlled provider fixtures exercise the real job -> incident -> media seam."""
import asyncio
import io
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models.base import ModelAdapter
from app.models.media import MediaResolver
from app.models.adapters.ingestion import PreparedMedia
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes, EvidenceFrame


class FixtureCascade(ModelAdapter):
    # Explicit dependency injection only; never registered as a real provider.
    name = "cascade_v1"
    def __init__(self, resolver, *, fail=False):
        self.resolver = resolver
        self.progress = None
        self.fail = fail
    def with_resolver(self, resolver):
        clone = type(self)(resolver, fail=self.fail)
        clone.progress = self.progress
        return clone
    async def evaluate(self, mi):
        if self.progress:
            await self.progress("p4")
        await asyncio.sleep(.01)
        if self.fail:
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        assert self.resolver.read(mi.evidence[0].media_ref).startswith(b"RIFF")
        return ModelAssessment(event_type="collapse", event_confidence=.95,
            risk_axes=RiskAxes(severity=.8, imminence=.9, exposure=.5, persistence=.7),
            evidence_refs=["F001"], evidence_descriptions={"F001":"Fixture observation"},
            metadata=ModelMetadata(adapter=self.name, model="fixture-only", is_mock=True))


def make_app(tmp_path, *, prepare_fail=False, model_fail=False):
    (tmp_path / "source.mp4").write_bytes(b"\x00\x00\x00\x18ftypisom")
    resolver = MediaResolver(tmp_path, {"ASSET_0001":"source.mp4"})
    app = create_app(Settings(mode="development", media_root=tmp_path),
        adapter=FixtureCascade(resolver, fail=model_fail), media_resolver=resolver)
    async def prepare(mi):
        if prepare_fail:
            raise ValueError("PRIVATE_PATH_AND_DECODER_STDERR")
        image = io.BytesIO()
        Image.new("RGB", (8,8), "black").save(image, "WEBP", lossless=True)
        prepared_mi = mi.model_copy(update={"evidence":[EvidenceFrame(frame_id="F001",timestamp_ms=0,media_ref="FRAME_0001")]})
        return PreparedMedia(prepared_mi,resolver.with_assets({"FRAME_0001":image.getvalue()}),
            "cliphash",{"F001":"framehash"},"fixture-only","fixture-only",{},1.0)
    app.state.analysis_preparer = prepare
    return app


def terminal(client, job_id):
    async def wait():
        for _ in range(100):
            result = client.app.state.analysis_jobs.get(job_id)
            if result["state"] in {"completed","failed"}:
                return result
            await asyncio.sleep(.01)
        raise AssertionError("job did not terminate")
    return client.portal.call(wait)


def test_http_job_stores_cited_image_and_keeps_ack_on_replay(tmp_path):
    app = make_app(tmp_path)
    body={"camera_id":"CAM_02","clip_ref":"ASSET_0001","start_ms":0,"end_ms":3000}
    with TestClient(app) as client:
        with client.websocket_connect("/ws/attention") as ws:
            ws.receive_json()
            accepted=client.post("/api/analysis/jobs",json=body,headers={"Idempotency-Key":"analysis1"})
            assert accepted.status_code==202 and accepted.json()["state"]=="queued"
            result=terminal(client,accepted.json()["job_id"])
            assert result["state"]=="completed" and result["needs_review"]
            assert ws.receive_json()["active_count"]==1
        incident=result["incident_id"]
        detail=client.get(f"/api/incidents/{incident}").json()
        assert detail["evidence"][0]["text"]=="Fixture observation"
        assert client.get(detail["evidence"][0]["frame_url"]).content.startswith(b"RIFF")
        assert client.get(f"/api/incidents/{incident}/clip").json()["end"]==3
        source_url = client.get(f"/api/incidents/{incident}/clip").json()["clip_url"]
        assert source_url==f"/api/incidents/{incident}/video"
        assert client.get(source_url).content==(tmp_path/"source.mp4").read_bytes()
        assert client.post(f"/api/incidents/{incident}/ack",json={"action":"verify"},headers={"Idempotency-Key":"ack1"}).status_code==200
        replay=client.post("/api/analysis/jobs",json=body,headers={"Idempotency-Key":"analysis1"})
        assert replay.json()==accepted.json()
        assert client.get(f"/api/incidents/{incident}").json()["status"]=="acked"
        assert len(app.state.store.assessment_inputs)==1


def test_preparation_failure_is_review_not_lost_job(tmp_path):
    with TestClient(make_app(tmp_path,prepare_fail=True)) as client:
        accepted=client.post("/api/analysis/jobs",json={"camera_id":"CAM_02","clip_ref":"ASSET_0001","start_ms":0,"end_ms":3000},headers={"Idempotency-Key":"preparefailure"})
        result=terminal(client,accepted.json()["job_id"])
        assert result["state"]=="completed" and result["needs_review"]
        detail=client.get("/api/incidents/"+result["incident_id"])
        assert detail.json()["risk"] is None and detail.json()["evidence"]==[]
        assert "PRIVATE" not in detail.text
        assert result["stage_trace"][0]["status"]=="failed"


def test_provider_failure_and_asset_validation(tmp_path):
    with TestClient(make_app(tmp_path,model_fail=True)) as client:
        body={"camera_id":"CAM_02","clip_ref":"ASSET_0001","start_ms":0,"end_ms":3000}
        assert client.post("/api/analysis/jobs",json=body).status_code==400
        assert client.post("/api/analysis/jobs",json={**body,"clip_ref":"../secret.mp4"},headers={"Idempotency-Key":"path"}).status_code==422
        result=terminal(client,client.post("/api/analysis/jobs",json=body,headers={"Idempotency-Key":"modelfailure"}).json()["job_id"])
        detail=client.get("/api/incidents/"+result["incident_id"])
        assert result["state"]=="completed" and detail.json()["risk"] is None
        assert "PRIVATE" not in detail.text

"""HACKATHON-DAY: deterministic scenario contract, no AI calls."""
from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.demo.scenario import DemoScenario
ROOT=Path(__file__).resolve().parents[2]
CONFIG=ROOT/"config/demo-scenario.json"

def test_group_one_event_only_representative_highlighted(tmp_path):
    with TestClient(create_app(Settings(demo_scenario_path=CONFIG,media_root=tmp_path))) as c:
        assert c.get("/api/demo/scenario").json()["scenario"]["decision_source"]=="scripted_not_ai"
        c.post("/api/demo/step",json={"step":3},headers={"Idempotency-Key":"step3"})
        s=c.get("/api/snapshot").json()
        assert s["active_count"]==1
        i=s["incidents"][0]
        assert i["primary_cam"]=="CAM_02" and i["related_cams"]==["CAM_01","CAM_03"]
        cameras={x["id"]:x for x in s["cameras"]}
        assert cameras["CAM_02"]["status"]=="incident"
        assert cameras["CAM_01"]["status"]==cameras["CAM_03"]["status"]=="unobserved"
        c.post("/api/incidents/SCENE-A/ack",json={"action":"verify"},headers={"Idempotency-Key":"verify"})
        s=c.get("/api/snapshot").json()
        assert s["active_count"]==0
        assert all(x["status"]!="incident" for x in s["cameras"])

def test_independent_candidate_and_candidate_disabled(tmp_path):
    config=json.loads(CONFIG.read_text(encoding="utf-8"))
    for enabled in [True,False]:
        config["incidents"][1]["enabled"]=enabled
        path=tmp_path/"scenario.json";path.write_text(json.dumps(config))
        with TestClient(create_app(Settings(demo_scenario_path=path,media_root=tmp_path))) as c:
            c.post("/api/demo/step",json={"step":5},headers={"Idempotency-Key":"step"})
            s=c.get("/api/snapshot").json()
            assert s["active_count"]==(2 if enabled else 1)
            cam=next(x for x in s["cameras"] if x["id"]=="CAM_06")
            assert cam["status"]==("incident" if enabled else "unobserved")
            assert cam["level"]==("HIGH" if enabled else None)

def test_invalid_members_and_traversal_rejected():
    data=json.loads(CONFIG.read_text(encoding="utf-8"))
    data["incidents"][0]["primary_cam"]="CAM_09"
    with pytest.raises(ValueError):DemoScenario.model_validate(data)
    data=json.loads(CONFIG.read_text(encoding="utf-8"));data["cameras"][0]["video_file"]="../secret.mp4"
    with pytest.raises(ValueError):DemoScenario.model_validate(data)

def test_development_does_not_enable_scripted_decisions(tmp_path):
    with TestClient(create_app(Settings(mode="development",demo_scenario_path=CONFIG,media_root=tmp_path))) as c:
        assert c.get("/api/demo/scenario").status_code==404
        assert c.post("/api/demo/step",json={"step":5},headers={"Idempotency-Key":"step"}).status_code==404
        assert c.get("/api/snapshot").json()["active_count"]==0

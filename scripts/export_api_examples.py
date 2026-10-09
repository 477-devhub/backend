"""HACKATHON-DAY: local synthetic response examples; no provider requests."""
import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    with TestClient(create_app(Settings(media_root=Path(folder)))) as client:
        examples={"scope":"HACKATHON-DAY","synthetic":True,"api_contract_version":"1.2",
                  "status_initial":client.get("/api/status").json(),
                  "cameras_initial":client.get("/api/cameras").json(),
                  "snapshot_initial":client.get("/api/snapshot").json()}
        client.post("/api/demo/step",json={"step":5},headers={"Idempotency-Key":"example-demo"})
        examples.update(snapshot_demo=client.get("/api/snapshot").json(),
            incident_demo=client.get("/api/incidents/INC-032").json(),
            clip_without_media=client.get("/api/incidents/INC-032/clip").json(),
            stats_demo=client.get("/api/pipeline/stats").json(),
            ack_verified=client.post("/api/incidents/INC-032/ack",json={"action":"verify"},
                headers={"Idempotency-Key":"example-ack"}).json(),
            error_404=client.get("/api/incidents/missing").json(),
            error_422=client.post("/api/demo/step",json={"step":9},
                headers={"Idempotency-Key":"example-invalid"}).json())
(root/"docs/api-examples-v1.2.json").write_text(json.dumps(examples,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Synthetic API examples written.")

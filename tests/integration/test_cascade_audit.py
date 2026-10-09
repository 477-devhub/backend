"""Accounting and frozen artifact regressions, without external model requests."""
import asyncio
import hashlib
import json
from pathlib import Path
from app.models.adapters.cascade_v1 import CascadeV1Adapter
from app.models.adapters.cascade_media import run_worker
from app.schemas.model import StageRecord


async def test_provider_failure_retains_charged_usage_and_retries(tmp_path):
    async def runner(*args, **kwargs):
        return {"status":"FAILED", "retry_count":2,
            "usage":{"input_tokens":100, "output_tokens":30}, "request_id":"test-request"}
    adapter=CascadeV1Adapter(stage_runner=runner)
    trace=[]
    try:
        await adapter._stage("p4",{},trace)
    except ValueError:
        pass
    assert trace[0].status=="failed" and trace[0].attempts==3
    assert trace[0].request_id=="test-request" and trace[0].estimated_cost_usd>0


async def test_worker_rejects_unpinned_weights_before_loading_cv(tmp_path):
    wrong=tmp_path/"wrong.pt"
    wrong.write_bytes(b"not-a-model")
    # CV imports require the verified existing CV environment; keep this check offline.
    python=Path("D:/projects/477/experiments/p0_cv_only/.venv/Scripts/python.exe")
    if not python.is_file():
        import pytest
        pytest.skip("verified CV runtime not configured on this host")
    record=await run_worker("cv",{"weights_path":str(wrong)},python_executable=python,timeout_sec=60)
    assert record["status"]=="failed" and record["error_type"]=="ValueError"


def test_ported_artifact_manifest_matches_every_declared_file():
    root=Path("app/models/adapters/frozen_v1")
    manifest=json.loads((root/"provenance.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        assert hashlib.sha256((root/record["ported"]).read_bytes()).hexdigest()==record["ported_sha256"]

"""Offline injected fixtures verify diagnostic data flow before paid calls."""
import importlib.util
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "new_477_piprline"
sys.path.insert(0, str(PACKAGE))
spec = importlib.util.spec_from_file_location("review_experiment_tested", PACKAGE / "run_review_experiment.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.asyncio
@pytest.mark.parametrize("route,cv_failure", [(True, False), (False, False), (True, True)])
async def test_real_boundary_no_truth_leak_and_skipped_denominators(tmp_path, monkeypatch, route, cv_failure):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts/pipeline_v2_review.txt").write_text("Generic event definitions, not source truth.")
    monkeypatch.setattr(runner, "HERE", tmp_path)
    frames = [{"frame_id": f"SRC01-F{i:06d}", "source_id": "SRC01", "frame_number": i,
               "timestamp_sec": i / 30, "width": 100, "height": 100,
               "image_path": str(tmp_path / f"{i}.png"), "sha256": "0" * 64} for i in range(64)]
    data = {"sources": ["SRC01"], "frames": frames, "active_sources": ["SRC01"],
            "prompt": "original", "output_schema": {"type": "object"}}
    monkeypatch.setattr(runner, "load_input", lambda item: data.copy())
    truth = {"SRC01": {"yolo": {"frames": [{"frame_number": 0, "complete": True, "objects": []}]},
                       "clef": {"invoke_vlm": True, "reviewed": True, "rationale": "Explicit synthetic test routing fixture"},
                       "vlm": {"label": "physical_conflict", "reviewed": True}}}
    observed = []

    class FixtureAdapter:
        def __init__(self, name):
            self.name = name

        async def run(self, model_input, context):
            observed.append((self.name, model_input))
            assert not any(k in model_input for k in ("annotations", "ground_truth", "reference_label"))
            assert len(model_input["frames"]) == 64
            assert model_input["prompt"] == "Generic event definitions, not source truth."
            record = {"status": "ok", "executed": True, "errors": [],
                      "cost_usd": {"value": 0, "basis": "explicit_offline_fixture"}}
            if self.name == "yolo":
                if cv_failure:
                    return {**record, "status": "error", "output": None, "errors": [{"category": "execution", "code": "fixture_failure"}]}
                record["output"] = {"frames": [{**f, "detections": []} for f in model_input["frames"]]}
            elif self.name == "clef":
                record["output"] = {"sources": [{"source_id": "SRC01", "invoke_vlm": route}]}
            else:
                record["output"] = {"assessments": [{"source_id": "SRC01", "event_type": "physical_conflict",
                    "event_confidence": .9, "risk_axes": {k: None for k in ("severity", "imminence", "exposure", "persistence")},
                    "evidence_refs": [frames[0]["frame_id"]], "needs_human_review": True,
                    "uncertainty_reason": "Synthetic fixture: unmeasured risk."}]}
            return record

    monkeypatch.setattr(runner, "plugin", lambda config: FixtureAdapter(config["model"]))
    config = {name: {"model": name} for name in ("yolo", "clef", "vlm")}
    config.update(timeout_sec=10, fallback="invoke_vlm")
    output = tmp_path / "results"
    output.mkdir()
    row = await runner.run_item({"item_id": "P001", "sources": [{"source_id": "SRC01", "frame_count": 64}]}, config, truth, None, output)
    if cv_failure:
        assert [x[0] for x in observed] == ["yolo", "vlm"]
        import json
        record = json.loads((output / "P001/vlm.normalized.json").read_text())
        assert record["fallback"]["from_stage"] == "clef"
        assert row["status"] == "stage_failure"
    elif not route:
        assert [x[0] for x in observed] == ["yolo", "clef"]
        assert row["stage_outputs"]["vlm"]["status"] == "skipped"
        assert row["stage_outputs"]["vlm"]["executed"] is False
        assert row["metrics"]["vlm"]["omitted_reviewed_source_count"] == 1
        assert row["metrics"]["pipeline"]["event_accuracy"] == 0
    else:
        assert [x[0] for x in observed] == ["yolo", "clef", "vlm"]
        assert row["metrics"]["pipeline"]["event_accuracy"] == 1
    assert data["prompt"] == "original"
    assert all("ground_truth" not in model_input for _, model_input in observed)

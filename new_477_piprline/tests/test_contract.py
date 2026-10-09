import importlib.util
from pathlib import Path

import pytest

from pipeline477.contract import COMBINATIONS, allocations, indices, validate_input
from pipeline477.execution import execute_pipeline_stage

def test_representative_matrix_and_exact_allocation():
    assert len(COMBINATIONS) == 12
    assert {len(c) for c in COMBINATIONS} == set(range(1, 7))
    assert allocations(3) == [22, 21, 21]
    assert allocations(5) == [13, 13, 13, 13, 12]
    assert allocations(6) == [11, 11, 11, 11, 10, 10]
    assert all(sum(allocations(n)) == 64 for n in range(1, 7))

def test_round_half_up_original_frame_bounds():
    values = indices(1050, 64)
    assert values[0] == 0 and values[-1] == 1049 and len(set(values)) == 64
    assert indices(4, 3) == [0, 2, 3]
    with pytest.raises(ValueError):
        indices(10, 64)

def test_shipped_truth_schema_and_pending_reference_are_valid():
    import json
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/ground_truth.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    truth = json.loads((root / "ground_truth/sources.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(truth)

def test_input_duplicate_leak_and_wrong_source_order():
    data = {"sources": ["SRC01"], "frames": [
        {"frame_id": f"SRC01-F{i}", "source_id": "SRC01", "frame_number": i, "timestamp_sec": float(i)} for i in range(64)]}
    assert validate_input(data, False)
    data["annotations"] = {}
    with pytest.raises(ValueError, match="leakage"):
        validate_input(data, False)
    del data["annotations"]
    data["frames"][0]["frame_number"] = 1
    with pytest.raises(ValueError):
        validate_input(data, False)

def test_execution_no_fabricated_prediction_and_no_exception_secrets():
    import asyncio
    class Fail:
        async def run(self, data, context):
            raise RuntimeError("SECRET_SENTINEL")
    result = asyncio.run(execute_pipeline_stage(Fail(), {}, {}))
    assert result["output"] is None and result["status"] == "error"
    assert "SECRET_SENTINEL" not in str(result)

def test_execution_detects_mutation():
    import asyncio
    class Mutate:
        async def run(self, data, context):
            data["frames"].append("bad")
            return {"status": "ok", "output": {}}
    original = {"frames": []}
    result = asyncio.run(execute_pipeline_stage(Mutate(), original, {}))
    assert original == {"frames": []}
    assert result["status"] == "error" and result["output"] is None

def test_portable_runner_scorer_self_check():
    path = Path(__file__).resolve().parents[1] / "run.py"
    spec = importlib.util.spec_from_file_location("portable_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.evaluation_selfcheck()["exact_vs_wrong"]

def test_route_gate_requires_real_bool_not_string_or_missing_key():
    path = Path(__file__).resolve().parents[1] / "run.py"
    spec = importlib.util.spec_from_file_location("portable_routes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.valid_routes({"sources": [{"source_id": "SRC01", "invoke_vlm": False}]}, ["SRC01"])
    assert not module.valid_routes({"sources": [{"source_id": "SRC01", "invoke_vlm": "false"}]}, ["SRC01"])
    assert not module.valid_routes({"sources": [{"source_id": "SRC01"}]}, ["SRC01"])
    assert not module.valid_routes({"sources": [{"source_id": "SRC01", "invoke_vlm": False}] * 2}, ["SRC01", "SRC02"])

def test_detection_gate_rejects_missing_and_cross_source_frames_and_bad_boxes():
    path = Path(__file__).resolve().parents[1] / "run.py"
    spec = importlib.util.spec_from_file_location("portable_detection_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    frame = {"frame_id": "F1", "source_id": "SRC01", "width": 100, "height": 100}
    row = {"frame_id": "F1", "source_id": "SRC01", "detections": []}
    assert module.valid_detections({"frames": [row]}, [frame])
    assert not module.valid_detections({"frames": []}, [frame])
    row["source_id"] = "SRC02"
    assert not module.valid_detections({"frames": [row]}, [frame])
    row["frame_id"] = []
    assert not module.valid_detections({"frames": [row]}, [frame])
    row["source_id"] = "SRC01"
    row["detections"] = [{"class_name": "person", "bbox": [0, 0, 101, 90], "confidence": .9}]
    assert not module.valid_detections({"frames": [row]}, [frame])

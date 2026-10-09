"""Offline CSV representation tests, not model evaluations."""
from copy import deepcopy

from compact_csv import compact_row


def record():
    return {"metrics": {"semantic_accuracy": None}, "errors": [{"code": "policy_invalid"}],
        "models": {"vlm": {"model": "fixture_only", "actual_runtime_metadata": {"images": [1]}}},
        "stage_outputs": {
            "yolo": {"status": "ok", "executed": True, "normalized_path": "P001/yolo.normalized.json",
                "metadata": {}, "output": {"frames": [{"source_id": "SRC01", "detections": [
                    {"class_name": "person", "bbox": [1, 2, 3, 4]}]}], "tracks": [1]}},
            "vlm": {"status": "error", "executed": True, "normalized_path": "P001/vlm.normalized.json",
                "metadata": {"images": [{"frame_id": "SRC01-F000000", "sent_jpeg_sha256": "fixture"}]},
                "invalid_output": {"assessments": [{"source_id": "SRC01", "event_type": "normal"}]}}}}


def test_csv_compaction_never_changes_actual_source_record():
    original = record()
    saved = deepcopy(original)
    compact_row(original)
    assert original == saved


def test_csv_compaction_preserves_metrics_errors_and_vlm_invalid_output():
    original = record()
    short = compact_row(original)
    assert short["metrics"] == original["metrics"]
    assert short["errors"] == original["errors"]
    assert short["stage_outputs"]["vlm"]["invalid_output"] == original["stage_outputs"]["vlm"]["invalid_output"]
    assert short["stage_outputs"]["vlm"]["executed"] is True


def test_csv_compaction_counts_actual_detections_and_links_full_records():
    short = compact_row(record())
    yolo = short["stage_outputs"]["yolo"]
    assert "output" not in yolo
    assert yolo["output_summary"]["sources"]["SRC01"] == {"frames": 1, "detections_by_class": {"person": 1}}
    assert yolo["output_summary"]["full_output_ref"]["json_pointer"] == "/output"
    assert short["stage_outputs"]["vlm"]["metadata"]["image_metadata_ref"]["image_count"] == 1
    assert "images" not in short["models"]["vlm"]["actual_runtime_metadata"]
    assert short["models"]["vlm"]["model"] == "fixture_only"

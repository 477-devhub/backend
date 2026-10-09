"""Synthetic scorer tests only; these fixtures are not model inference."""
import copy
import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.eval.team_benchmark import (
    SUBMISSION_COLUMNS, existing_results_submission, score_submission, template_rows,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(root):
    files = ["items.json", "data/sources.json", "prompts/pipeline_v1.txt", "schemas/vlm_output.schema.json"]
    files += [p.relative_to(root).as_posix() for p in (root / "data/frames").rglob("*") if p.is_file()]
    write(root / "benchmark.lock.json", {p: digest(root / p) for p in files})


@pytest.fixture
def suite(tmp_path):
    """A tiny locked synthetic suite exercising the same 64-frame contract."""
    root = tmp_path
    items, registry, gt = [], {}, {}
    for n in range(1, 3):
        source = f"SRC0{n}"
        registry[source] = {"width": 100, "height": 100, "frame_count": 64, "fps_num": 30, "fps_den": 1}
        gt[source] = {"reviewer": "synthetic test fixture", "reviewed_at": "2026-10-09",
                      "yolo": {"class_scope": ["person"], "frames": [
                          {"frame_number": 0, "complete": True, "objects": [
                              {"class_name": "person", "bbox": [1, 2, 20, 30]}]}]},
                      "clef": {"reviewed": True, "invoke_vlm": True, "rationale": "synthetic visible abnormality"},
                      "vlm": {"reviewed": True, "label": "physical_conflict", "support_frame_interval": [0, 40]}}
    combinations = [["SRC01"], ["SRC02"], ["SRC01", "SRC02"]]
    for n, sources in enumerate(combinations, 1):
        identifier = f"P{n:03d}"
        item = {"item_id": identifier, "sources": [{"source_id": s, "frame_count": 64 // len(sources)} for s in sources]}
        items.append(item)
        frames = []
        for s in sources:
            count = 64 // len(sources)
            for i in range(count):
                number = int(i * 63 / (count - 1) + .5)
                relative = f"data/frames/{identifier}/{s}/{i:03d}.png"
                image = root / relative
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(f"synthetic fixture {s} {number}".encode())
                frames.append({"frame_id": f"{s}-F{number:06d}", "source_id": s,
                               "frame_number": number, "timestamp_sec": number / 30,
                               "image_path": relative, "sha256": digest(image), "width": 100, "height": 100})
        write(root / f"data/frames/{identifier}/manifest.json", {"item_id": identifier, "sources": sources, "frames": frames})
    write(root / "items.json", {"item_count": 3, "items": items})
    write(root / "data/sources.json", registry)
    (root / "prompts").mkdir()
    (root / "prompts/pipeline_v1.txt").write_text("Synthetic fixture prompt", encoding="utf-8")
    write(root / "schemas/vlm_output.schema.json", {})
    write(root / "ground_truth/sources.json", gt)
    freeze(root)
    return root, root / "ground_truth/sources.json"


def perfect(root):
    rows = template_rows(root)
    for row in rows:
        manifest = json.loads((root / row["stage_inputs"]["yolo"]["frame_manifest"]).read_text())
        row["status"] = "completed"
        row["models"] = {s: {"model": "synthetic_unit_fixture"} for s in ("yolo", "clef", "vlm")}
        frames = [{"frame_id": f["frame_id"], "source_id": f["source_id"], "detections": [
            {"class_name": "person", "bbox": [1, 2, 20, 30], "confidence": .99}] if f["frame_number"] == 0 else []}
            for f in manifest["frames"]]
        assessments = [{"source_id": s, "event_type": "physical_conflict", "event_confidence": .95,
                        "risk_axes": {k: None for k in ("severity", "imminence", "exposure", "persistence")},
                        "evidence_refs": [next(f["frame_id"] for f in manifest["frames"] if f["source_id"] == s)],
                        "needs_human_review": True, "uncertainty_reason": "Synthetic unmeasured axes"}
                       for s in manifest["sources"]]
        outputs = {"yolo": {"frames": frames}, "clef": {"sources": [{"source_id": s, "invoke_vlm": True} for s in manifest["sources"]]},
                   "vlm": {"assessments": assessments}}
        row["stage_outputs"] = {s: {"status": "ok", "executed": True, "model": "synthetic_unit_fixture",
                                   "output": output, "errors": []} for s, output in outputs.items()}
        row["stage_outputs"]["vlm"]["active_sources"] = manifest["sources"]
    return rows


def submit(root, rows, extra=None):
    path = root / "submission.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUBMISSION_COLUMNS + (list(extra) if extra else []))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) if k in {"item_id", "status"} else json.dumps(row.get(k))
                             for k in writer.fieldnames})
    return path


def score(suite, rows, extra=None):
    root, gt = suite
    return score_submission(submit(root, rows, extra), root, gt)


def test_perfect_scoring_separates_detection_routing_semantics(suite):
    rows, summary = score(suite, perfect(suite[0]))
    assert summary["primary_score_100"] == 100
    assert summary["reviewed_source_occurrences"] == 4
    assert summary["whole_item_accuracy"] == summary["single_source_accuracy"] == 1
    assert len(rows) == 3
    assert all(r["metrics"]["yolo"]["map50"] == 1 for r in rows)
    assert all(r["metrics"]["clef"]["accuracy_including_unavailable"] == 1 for r in rows)
    assert all(r["status"] == "completed" for r in rows)
    assert rows[0]["metrics"]["vlm"]["per_source"]["SRC01"]["coarse_support_interval_fraction"] == 1
    assert summary["invoice_cost_usd"] is None
    assert rows[0]["cost_usd"]["total"]["value"] is None


def test_wrong_event_and_empty_detection_are_separate(suite):
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["vlm"]["output"]["assessments"][0]["event_type"] = "normal"
    for f in submission[0]["stage_outputs"]["yolo"]["output"]["frames"]:
        f["detections"] = []
    rows, summary = score(suite, submission)
    assert summary["primary_score_100"] == 75
    assert rows[0]["metrics"]["yolo"]["recall"] == 0
    assert rows[0]["metrics"]["yolo"]["precision"] is None
    assert rows[0]["metrics"]["yolo"]["map50"] == 0
    assert rows[0]["status"] == "model_error"


def test_route_skip_is_omission_without_vlm_blame(suite):
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["clef"]["output"]["sources"][0]["invoke_vlm"] = False
    submission[0]["stage_outputs"]["vlm"] = {"status": "skipped", "executed": False, "output": None, "active_sources": [], "errors": []}
    rows, summary = score(suite, submission)
    m = rows[0]["metrics"]
    assert summary["primary_score_100"] == 75
    assert m["clef"]["false_negative_calls"] == 1
    assert m["vlm"]["per_source"]["SRC01"]["omission_cause"] == "routing_false_negative"
    assert m["vlm"]["conditional_attempted_event_accuracy"] is None
    assert not any(e.get("code") == "event_mismatch" for e in rows[0]["errors"])


def test_missing_problem_kept_in_denominator(suite):
    rows, summary = score(suite, perfect(suite[0])[1:])
    assert len(rows) == 3
    assert summary["missing_item_count"] == 1
    assert summary["primary_score_100"] == 75
    assert rows[0]["status"] == "benchmark_error"


def test_no_clef_pipeline_has_na_route_score(suite):
    submission = perfect(suite[0])
    for r in submission:
        r["models"]["clef"] = None
        r["stage_outputs"]["clef"] = {"status": "skipped", "executed": False, "output": None, "errors": []}
    rows, summary = score(suite, submission)
    assert summary["primary_score_100"] == 100
    assert rows[0]["metrics"]["clef"]["used"] is False
    assert rows[0]["metrics"]["clef"]["accuracy_including_unavailable"] is None


@pytest.mark.parametrize("change", ["duplicate", "unknown"])
def test_bad_item_ids_rejected(suite, change):
    submission = perfect(suite[0])
    if change == "duplicate":
        submission.append(copy.deepcopy(submission[0]))
    else:
        submission[0]["item_id"] = "P999"
    with pytest.raises(ValueError, match="unknown/duplicate"):
        score(suite, submission)


@pytest.mark.parametrize("path", ["../escape.json", "https://provider/test", "C:\\secret.json"])
def test_record_escape_rejected_without_credit(suite, path):
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["vlm"] = {"record_path": path}
    rows, summary = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"
    assert summary["primary_score_100"] == 75


def test_symlink_escape_rejected(suite, tmp_path):
    root, _ = suite
    outside = root.parent / (root.name + "_outside.json")
    write(outside, {})
    link = root / "escape.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    submission = perfect(root)
    submission[0]["stage_outputs"]["vlm"] = {"record_path": "escape.json"}
    rows, _ = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"


@pytest.mark.parametrize("tamper", ["pixel", "frame_count", "timestamp", "source_block"])
def test_public_mapping_and_pixels_validated_before_scoring(suite, tamper):
    root, gt = suite
    submission = perfect(root)
    path = root / "data/frames/P003/manifest.json"
    manifest = json.loads(path.read_text())
    if tamper == "pixel":
        (root / manifest["frames"][0]["image_path"]).write_bytes(b"changed fixture")
    elif tamper == "frame_count":
        manifest["frames"].pop()
        write(path, manifest)
    elif tamper == "timestamp":
        manifest["frames"][0]["timestamp_sec"] = 1
        write(path, manifest)
    else:
        manifest["frames"].reverse()
        write(path, manifest)
    with pytest.raises(ValueError):
        score_submission(submit(root, submission), root, gt)


def test_forged_submitted_manifest_rejected(suite):
    root, _ = suite
    submission = perfect(root)
    manifest = json.loads((root / "data/frames/P001/manifest.json").read_text())
    manifest["frames"][0]["sha256"] = "forged"
    write(root / "submissions/forged.json", manifest)
    submission[0]["stage_inputs"]["yolo"]["frame_manifest"] = "submissions/forged.json"
    rows, _ = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"


def test_invalid_truth_rejected_and_pending_stays_null(suite):
    root, path = suite
    submission = perfect(root)
    gt = json.loads(path.read_text())
    gt["SRC01"]["vlm"] = {"reviewed": False, "label": None}
    write(path, gt)
    rows, summary = score(suite, submission)
    assert rows[0]["metrics"]["vlm"]["pipeline_event_accuracy_including_omissions"] is None
    assert summary["reviewed_source_occurrences"] == 2
    assert rows[0]["status"] == "evaluation_unavailable"
    gt["SRC02"]["yolo"]["frames"][0]["objects"][0]["bbox"] = [0, 0, 101, 10]
    write(path, gt)
    with pytest.raises(ValueError, match="invalid ground truth"):
        score(suite, submission)


def test_production_gt_lock_required_and_checked(suite):
    root, path = suite
    submission = perfect(root)
    gt = json.loads(path.read_text())
    reviewed = root / "ground_truth/ai_review_v1/sources.json"
    write(reviewed, gt)
    csv_path = submit(root, submission)
    with pytest.raises(ValueError, match="lock missing"):
        score_submission(csv_path, root, reviewed)
    lock = reviewed.parent / "ground_truth.lock.json"
    write(lock, {reviewed.relative_to(root).as_posix(): digest(reviewed)})
    assert score_submission(csv_path, root, reviewed)[1]["primary_score_100"] == 100
    gt["SRC01"]["vlm"]["label"] = "normal"
    write(reviewed, gt)
    with pytest.raises(ValueError, match="lock mismatch"):
        score_submission(csv_path, root, reviewed)


def test_invalid_output_scored_semantically_but_review_error_preserved(suite):
    submission = perfect(suite[0])
    record = submission[0]["stage_outputs"]["vlm"]
    invalid = record.pop("output")
    invalid["assessments"][0]["needs_human_review"] = False
    record.update(status="error", output=None, invalid_output=invalid,
                  errors=[{"category": "model", "code": "review_policy"}])
    rows, summary = score(suite, submission)
    assert summary["primary_score_100"] == 100
    assert rows[0]["metrics"]["vlm"]["per_source"]["SRC01"]["safety_policy_valid"] is False
    assert rows[0]["stage_outputs"]["vlm"]["output"] is None
    assert rows[0]["stage_outputs"]["vlm"]["invalid_output"] == invalid
    assert rows[0]["status"] == "model_error"


@pytest.mark.parametrize("problem", ["fabricated_skip", "mock", "bad_source", "bad_models", "missing_output"])
def test_invalid_outputs_not_successful(suite, problem):
    submission = perfect(suite[0])
    r = submission[0]
    if problem == "fabricated_skip":
        r["stage_outputs"]["vlm"].update(status="skipped", executed=False)
    elif problem == "mock":
        r["stage_outputs"]["vlm"]["model"] = "mock_test"
    elif problem == "bad_source":
        r["stage_outputs"]["vlm"]["active_sources"] = ["SRC99"]
    elif problem == "bad_models":
        r["models"] = []
    else:
        r["stage_outputs"]["vlm"]["output"] = None
    rows, summary = score(suite, submission)
    assert rows[0]["status"] in {"benchmark_error", "model_error"}
    assert summary["primary_score_100"] == 75


def test_submitted_metrics_are_ignored(suite):
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["vlm"]["output"]["assessments"][0]["event_type"] = "normal"
    for row in submission:
        row["metrics"] = {"score": 100}
    _, summary = score(suite, submission, {"metrics": True})
    assert summary["primary_score_100"] == 75


def test_original_records_by_path_and_converter(suite):
    root, _ = suite
    submission = perfect(root)
    historic = []
    for row in submission:
        r = copy.deepcopy(row)
        for stage, record in row["stage_outputs"].items():
            path = f"results/{row['item_id']}/{stage}.normalized.json"
            write(root / path, record)
            r["stage_outputs"][stage]["normalized_path"] = path
        historic.append(r)
    converted = existing_results_submission(submit(root, historic))
    rows, summary = score(suite, converted)
    assert summary["primary_score_100"] == 100
    assert rows[0]["stage_outputs"]["vlm"]["executed"] is True


def test_unknown_cost_cannot_be_zero_and_partial_yolo_is_not_valid(suite):
    submission = perfect(suite[0])
    submission[0]["cost_usd"]["vlm"] = {"value": 0, "basis": "unknown"}
    rows, _ = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["yolo"]["output"]["frames"].pop()
    rows, _ = score(suite, submission)
    assert rows[0]["metrics"]["yolo"]["output_mapping_valid"] is False
    assert rows[0]["status"] == "model_error"


def test_failed_upstream_fallback_must_be_recorded(suite):
    submission = perfect(suite[0])
    submission[0]["stage_outputs"]["clef"] = {"status": "error", "executed": True,
                                              "output": None, "errors": [{"category": "execution", "code": "timeout"}]}
    rows, summary = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"
    assert summary["primary_score_100"] == 75
    submission[0]["stage_outputs"]["vlm"]["fallback"] = {"from_stage": "clef", "path": "invoke_all"}
    rows, summary = score(suite, submission)
    assert rows[0]["status"] == "execution_error"
    assert rows[0]["metrics"]["pipeline"]["fallback_recorded"] is True
    assert summary["primary_score_100"] == 100


def test_optional_vlm_only_and_relative_truth_path(suite):
    root, _ = suite
    submission = perfect(root)
    for r in submission:
        for stage in ("yolo", "clef"):
            r["models"][stage] = None
            r["stage_outputs"][stage] = {"status": "skipped", "executed": False, "output": None, "errors": []}
    rows, summary = score_submission(submit(root, submission), root, "ground_truth/sources.json")
    assert summary["primary_score_100"] == 100
    assert rows[0]["metrics"]["yolo"]["used"] is False
    assert rows[0]["metrics"]["yolo"]["recall"] is None


def test_annotation_fields_cannot_be_added_to_stage_frames(suite):
    root, _ = suite
    submission = perfect(root)
    manifest = json.loads((root / "data/frames/P001/manifest.json").read_text())
    manifest["frames"][0]["annotations"] = {"answer": "physical_conflict"}
    write(root / "submissions/leaking.json", manifest)
    submission[0]["stage_inputs"]["vlm"]["frame_manifest"] = "submissions/leaking.json"
    rows, _ = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"


def test_prompt_copy_allows_only_platform_newlines(suite):
    root, _ = suite
    frozen = root / "prompts/pipeline_v1.txt"
    frozen.write_bytes(b"Synthetic fixture\nFixed prompt\n")
    freeze(root)
    submission = perfect(root)
    copied = root / "submissions/prompt.txt"
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_bytes(b"Synthetic fixture\r\nFixed prompt\r\n")
    submission[0]["stage_inputs"]["vlm"]["prompt_path"] = "submissions/prompt.txt"
    rows, summary = score(suite, submission)
    assert summary["primary_score_100"] == 100
    copied.write_bytes(b"Synthetic fixture\r\nChanged prompt\r\n")
    rows, summary = score(suite, submission)
    assert rows[0]["status"] == "benchmark_error"
    assert summary["primary_score_100"] == 75

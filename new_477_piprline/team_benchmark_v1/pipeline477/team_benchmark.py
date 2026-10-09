"""Model-agnostic, offline scoring of fixed 64-frame team submissions.

No inference occurs here. Returned rows are data; MAIN owns artifact writing.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
from pathlib import Path

try:
    from pipeline477.metrics import evaluate_item, validate_ground_truth
except ModuleNotFoundError as exc:
    if exc.name not in {"pipeline477", "pipeline477.metrics"}:
        raise
    from app.eval.new_pipeline_metrics import evaluate_item, validate_ground_truth

SUBMISSION_COLUMNS = ["item_id", "sources", "models", "stage_inputs", "stage_outputs",
                      "latency_ms", "cost_usd", "status", "errors"]
SCORE_COLUMNS = SUBMISSION_COLUMNS + ["ground_truth", "metrics"]
STAGES = ("yolo", "clef", "vlm")
PROMPT = "prompts/pipeline_v1.txt"
SCHEMA = "schemas/vlm_output.schema.json"


def _json(path):
    def invalid(value):
        raise ValueError("non-finite JSON number: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid)


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _path(root, value):
    if not isinstance(value, str) or not value or ":" in value or "\\" in value:
        raise ValueError("artifact path must be a root-relative POSIX path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("artifact path escapes benchmark root")
    resolved = (root / candidate).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("artifact path escapes root or is not a file")
    return resolved


def _indices(total, count):
    if type(total) is not int or total < count or count < 2:
        raise ValueError("invalid source frame count")
    return [int(math.floor(i * (total - 1) / (count - 1) + .5)) for i in range(count)]


def _public_inputs(root):
    lock = _json(_path(root, "benchmark.lock.json"))
    required = {"items.json", "data/sources.json", PROMPT, SCHEMA}
    package = _json(_path(root, "items.json"))
    registry = _json(_path(root, "data/sources.json"))
    items = package["items"]
    if (not isinstance(items, list) or not items or package.get("item_count") != len(items)
            or len({i["item_id"] for i in items}) != len(items)):
        raise ValueError("invalid fixed item list")
    data = {}
    for item in items:
        identifier = item["item_id"]
        if not isinstance(identifier, str) or not identifier.isalnum():
            raise ValueError("invalid fixed item identifier")
        manifest_path = f"data/frames/{identifier}/manifest.json"
        required.add(manifest_path)
        manifest = _json(_path(root, manifest_path))
        sources = [s["source_id"] for s in item["sources"]]
        if (not 1 <= len(sources) <= 6 or len(set(sources)) != len(sources)
                or not set(sources) <= set(registry) or manifest.get("sources") != sources
                or manifest.get("item_id") != identifier):
            raise ValueError("invalid fixed source mapping")
        frames = manifest.get("frames")
        if not isinstance(frames, list) or len(frames) != 64:
            raise ValueError("fixed input must contain 64 frames")
        if len({f["frame_id"] for f in frames}) != 64:
            raise ValueError("duplicate fixed frame IDs")
        q, r = divmod(64, len(sources))
        expected_order = []
        for position, allocation in enumerate(item["sources"]):
            source = allocation["source_id"]
            count = q + (position < r)
            meta = registry[source]
            selected = [f for f in frames if f["source_id"] == source]
            numbers = _indices(meta["frame_count"], count)
            if allocation["frame_count"] != count or [f["frame_number"] for f in selected] != numbers:
                raise ValueError("fixed frame allocation/order mismatch")
            for f in selected:
                if (f["frame_id"] != f"{source}-F{f['frame_number']:06d}"
                        or type(f["frame_number"]) is not int
                        or f["timestamp_sec"] != f["frame_number"] * meta["fps_den"] / meta["fps_num"]
                        or f["width"] != meta["width"] or f["height"] != meta["height"]):
                    raise ValueError("fixed source/frame/timestamp mapping mismatch")
                image = _path(root, f["image_path"])
                required.add(f["image_path"])
                if _digest(image) != f["sha256"]:
                    raise ValueError("fixed frame pixel hash mismatch")
                expected_order.append(f["frame_id"])
        if [f["frame_id"] for f in frames] != expected_order:
            raise ValueError("fixed source block order mismatch")
        data[identifier] = {**manifest, "output_schema": _json(_path(root, SCHEMA))}
    for filename in required:
        if filename not in lock or _digest(_path(root, filename)) != lock[filename]:
            raise ValueError("fixed public input lock mismatch: " + filename)
    return items, registry, data


def _truth(root, truth_path, registry):
    path = Path(truth_path)
    path = (path if path.is_absolute() else root / path).resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("ground truth must remain inside evaluator root")
    lock_path = path.parent / "ground_truth.lock.json"
    if "ai_review_v1" in path.parts and not lock_path.exists():
        raise ValueError("reviewed ground-truth lock missing")
    if lock_path.exists():
        lock = _json(lock_path)
        filename = path.relative_to(root).as_posix()
        if filename not in lock:
            raise ValueError("ground truth absent from its lock")
        for name, expected in lock.items():
            if _digest(_path(root, name)) != expected:
                raise ValueError("ground-truth lock mismatch: " + name)
    truth = _json(path)
    validation = validate_ground_truth(truth, registry)
    if not validation["valid"]:
        raise ValueError("invalid ground truth: " + "; ".join(validation["errors"]))
    for value in truth.values():
        if any(value.get(s, {}).get("reviewed") is True for s in ("clef", "vlm")):
            if not value.get("reviewer") or not value.get("reviewed_at"):
                raise ValueError("reviewed ground truth requires reviewer and date")
    return truth


def _absent(reason):
    return {"status": "blocked", "executed": False, "model": None, "output": None,
            "errors": [{"category": "benchmark", "code": reason, "detail": reason}],
            "active_sources": []}


def template_rows(benchmark_root):
    """Return editable empty rows without exposing evaluation labels."""
    root = Path(benchmark_root).resolve(strict=True)
    items, _, _ = _public_inputs(root)
    return [{"item_id": item["item_id"], "sources": {"videos": item["sources"]},
             "models": {s: None for s in STAGES},
             "stage_inputs": {s: {"frame_manifest": f"data/frames/{item['item_id']}/manifest.json",
                                   "prompt_path": PROMPT} for s in STAGES},
             "stage_outputs": {s: _absent("not_submitted") for s in STAGES},
             "latency_ms": {s: None for s in (*STAGES, "total")},
             "cost_usd": {s: {"value": None, "basis": "unknown"} for s in (*STAGES, "total")},
             "status": "not_submitted", "errors": []} for item in items]


def _check_stage_inputs(root, submitted, canonical):
    if not isinstance(submitted, dict):
        raise ValueError("stage_inputs must be an object")
    for stage in STAGES:
        entry = submitted.get(stage)
        if not isinstance(entry, dict):
            raise ValueError("missing stage input record: " + stage)
        manifest = _json(_path(root, entry.get("frame_manifest")))
        if isinstance(manifest, dict) and any(k in manifest for k in ("ground_truth", "annotations", "reference_label")):
            raise ValueError("ground-truth leakage in stage manifest")
        if isinstance(manifest, list):
            frames = manifest
        elif isinstance(manifest, dict):
            frames = manifest.get("frames")
            if manifest.get("sources", canonical["sources"]) != canonical["sources"]:
                raise ValueError("stale stage source manifest")
        else:
            raise ValueError("invalid stage manifest")
        if not isinstance(frames, list) or len(frames) != 64:
            raise ValueError("stage manifest requires the fixed 64 frames")
        fields = ("frame_id", "source_id", "frame_number", "timestamp_sec", "width", "height", "sha256")
        for actual, expected in zip(frames, canonical["frames"]):
            if not isinstance(actual, dict) or set(actual) != set(expected) or any(actual.get(k) != expected[k] for k in fields):
                raise ValueError("stale/forged stage frame mapping")
            image = actual.get("image_path")
            # Historical runner manifests contain absolute local image paths.
            if isinstance(image, str) and Path(image).is_absolute():
                resolved = Path(image).resolve(strict=True)
                if not resolved.is_relative_to(root):
                    raise ValueError("stage image path escapes root")
            else:
                resolved = _path(root, image)
            if resolved != _path(root, expected["image_path"]):
                raise ValueError("stage image path does not match fixed input")
        # Windows copies can encode LF as CRLF; accept only newline normalization.
        if (_path(root, entry.get("prompt_path")).read_text(encoding="utf-8")
                != _path(root, PROMPT).read_text(encoding="utf-8")):
            raise ValueError("stage prompt does not match frozen prompt")
        for key in ("request_path", "response_path", "output_schema_path"):
            if entry.get(key) is not None:
                path = _path(root, entry[key])
                if key == "output_schema_path" and _digest(path) != _digest(_path(root, SCHEMA)):
                    raise ValueError("stage schema mismatch")


def _records(root, row, sources):
    result = {}
    outputs = row["stage_outputs"]
    if not isinstance(outputs, dict) or set(outputs) != set(STAGES):
        raise ValueError("stage_outputs must contain all three stages")
    for stage in STAGES:
        record = outputs[stage]
        if isinstance(record, dict) and "record_path" in record:
            if set(record) != {"record_path"}:
                raise ValueError("record_path cannot be mixed with inline output")
            record = _json(_path(root, record["record_path"]))
        if not isinstance(record, dict) or record.get("status") not in {"ok", "error", "blocked", "skipped"}:
            raise ValueError("invalid stage record status")
        record = copy.deepcopy(record)
        executed, status = record.get("executed"), record["status"]
        if executed is not None and type(executed) is not bool:
            raise ValueError("executed must be boolean or unknown for an error")
        if status == "ok" and executed is not True:
            raise ValueError("successful stage was not executed")
        if status in {"skipped", "blocked"} and executed is not False:
            raise ValueError("skipped/blocked stage cannot have executed")
        if status != "error" and executed is None:
            raise ValueError("unknown execution only valid for an error")
        if executed is not True and (record.get("output") is not None or record.get("invalid_output") is not None):
            raise ValueError("unexecuted stage contains fabricated output")
        if status in {"skipped", "blocked"} and record.get("active_sources"):
            raise ValueError("unexecuted stage declares active sources")
        if record.get("mock") or str(record.get("model", "")).startswith("mock_"):
            raise ValueError("mocks forbidden in real evaluation")
        spec = row["models"].get(stage)
        if str(spec).startswith("mock_") or (isinstance(spec, dict) and any(str(spec.get(k, "")).startswith("mock_") for k in ("model", "model_id", "name"))):
            raise ValueError("mock model configuration forbidden")
        if not isinstance(record.get("errors", []), list):
            raise ValueError("stage errors must be a list")
        if stage == "vlm":
            active = record.get("active_sources", sources if executed is True else [])
            if not isinstance(active, list) or any(not isinstance(s, str) for s in active) or len(active) != len(set(active)) or not set(active) <= set(sources):
                raise ValueError("unknown/duplicate VLM active source")
            record["active_sources"] = active
        result[stage] = record
    if row["models"].get("clef") is None and result["clef"]["status"] != "skipped":
        # An untouched empty template is a genuine omission, not a no-Clef design.
        if row["status"] != "not_submitted":
            raise ValueError("Clef absent requires a skipped record")
    clef, vlm = result["clef"], result["vlm"]
    if row["models"].get("clef") is not None and vlm.get("executed") is True:
        if clef["status"] != "ok" and not vlm.get("fallback"):
            raise ValueError("VLM execution after Clef failure requires a recorded fallback")
        output = clef.get("output")
        routes = output.get("sources") if isinstance(output, dict) else None
        if clef["status"] == "ok" and isinstance(routes, list):
            denied = {r.get("source_id") for r in routes if isinstance(r, dict) and r.get("invoke_vlm") is False}
            if denied.intersection(vlm["active_sources"]) and not vlm.get("fallback"):
                raise ValueError("VLM execution on a Clef-denied source requires a recorded override")
    return result


def _optional_clef(metrics):
    clef = metrics["clef"]
    for key in ("reviewed_source_count", "available_decision_count", "unavailable_decision_count",
                "accuracy_including_unavailable", "conditional_decision_accuracy", "false_negative_calls",
                "false_positive_calls", "missing_required_calls", "output_format_valid"):
        clef[key] = None
    clef["used"] = False
    clef["reason"] = "Clef not part of submitted pipeline; routing score N/A"
    for entry in clef["per_source"].values():
        entry["correct"] = None


def _numeric_cell(value):
    if value is None:
        return
    if type(value) in (int, float):
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid negative/non-finite latency or cost")
    elif isinstance(value, dict):
        for key, child in value.items():
            if key in {"value", "invoice_usd"} or (isinstance(child, (dict, int, float)) and type(child) is not bool):
                _numeric_cell(child)
    elif not isinstance(value, str):
        raise ValueError("invalid latency/cost value")


def _cost_cell(value):
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError("cost_usd must be an object or null")
    for entry in value.values():
        if entry is None:
            continue
        if not isinstance(entry, dict) or "value" not in entry or "basis" not in entry:
            raise ValueError("stage cost requires value and basis")
        amount = entry["value"]
        if amount is not None and (type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0):
            raise ValueError("invalid cost amount")
        if amount is not None and entry["basis"] in {None, "unknown", "unavailable"}:
            raise ValueError("unknown cost must be null")


def _diagnostics(metrics, records, truth):
    errors = []
    for stage, record in records.items():
        for error in record.get("errors", []):
            errors.append({"stage": stage, **error} if isinstance(error, dict) else
                          {"stage": stage, "category": "execution", "code": "stage_error", "detail": str(error)})
        if record["status"] in {"error", "blocked"} and not record.get("errors"):
            errors.append({"stage": stage, "category": "execution", "code": "stage_unavailable"})
    for stage in STAGES:
        for detail in metrics[stage].get("output_errors", []):
            errors.append({"stage": stage, "category": "model", "code": "normalized_output_invalid", "detail": detail})
    for source, result in metrics["vlm"]["per_source"].items():
        for field, code in (("semantic_correct", "event_mismatch"), ("input_reference_valid", "invalid_evidence_reference"),
                            ("safety_policy_valid", "human_review_policy_invalid")):
            if result[field] is False:
                errors.append({"stage": "vlm", "source_id": source, "category": "model", "code": code})
        if result["omission_cause"] == "routing_false_negative":
            errors.append({"stage": "clef", "source_id": source, "category": "model", "code": "routing_false_negative"})
    if metrics["ground_truth_validation"]["review_required"]:
        errors.append({"stage": "evaluation", "category": "evaluation_unavailable", "code": "ground_truth_pending",
                       "detail": metrics["ground_truth_validation"]["review_required"]})
    return errors


def _support(metrics, model_input, truth, scoring):
    frames = {f["frame_id"]: f for f in model_input["frames"]}
    output = scoring["vlm"].get("output")
    entries = output.get("assessments", []) if isinstance(output, dict) else []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("source_id") not in metrics["vlm"]["per_source"]:
            continue
        source = entry["source_id"]
        interval = truth.get(source, {}).get("vlm", {}).get("support_frame_interval")
        refs = entry.get("evidence_refs")
        valid = isinstance(refs, list) and refs and all(isinstance(r, str) and r in frames and frames[r]["source_id"] == source for r in refs)
        fraction = None
        if valid and isinstance(interval, list) and len(interval) == 2:
            fraction = sum(interval[0] <= frames[r]["frame_number"] <= interval[1] for r in refs) / len(refs)
        metrics["vlm"]["per_source"][source]["coarse_support_interval_fraction"] = fraction
    metrics["vlm"]["coarse_support_note"] = "Temporal overlap only; not expert semantic explanation accuracy"


def score_submission(csv_path, benchmark_root, ground_truth_path):
    """Validate artifacts then return one scored row per fixed problem and summary.

    Global lock/GT/duplicate/unknown-item failures raise ValueError. Invalid
    individual submissions receive benchmark errors and remain in denominators.
    """
    root = Path(benchmark_root).resolve(strict=True)
    items, registry, inputs = _public_inputs(root)
    truth = _truth(root, ground_truth_path, registry)
    csv.field_size_limit(32 * 1024 * 1024)
    submitted = {}
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(SUBMISSION_COLUMNS) <= set(reader.fieldnames) or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("submission CSV missing/duplicate required columns")
        for raw in reader:
            identifier = raw["item_id"]
            if identifier not in inputs or identifier in submitted:
                raise ValueError("unknown/duplicate submitted item: " + str(identifier))
            submitted[identifier] = raw
    rows = []
    for item in items:
        identifier = item["item_id"]
        data = inputs[identifier]
        gt = {s: truth[s] for s in data["sources"] if s in truth}
        raw = submitted.get(identifier)
        errors, records = [], {s: _absent("missing_submission") for s in STAGES}
        row = {"item_id": identifier, "sources": {"videos": item["sources"]},
               "models": {s: None for s in STAGES}, "stage_inputs": {}, "stage_outputs": records,
               "latency_ms": None, "cost_usd": None, "status": "benchmark_error", "errors": []}
        if raw is not None:
            try:
                for key in SUBMISSION_COLUMNS:
                    row[key] = raw[key] if key in {"item_id", "status"} else json.loads(raw[key], parse_constant=lambda v: (_ for _ in ()).throw(ValueError("non-finite JSON")))
                if not isinstance(row["models"], dict) or not isinstance(row["errors"], list):
                    raise ValueError("models/errors have invalid types")
                supplied_sources = row["sources"].get("videos") if isinstance(row["sources"], dict) else row["sources"]
                if supplied_sources != item["sources"]:
                    raise ValueError("submitted source allocation differs from fixed item")
                _check_stage_inputs(root, row["stage_inputs"], data)
                records = _records(root, row, data["sources"])
                _numeric_cell(row["latency_ms"])
                _numeric_cell(row["cost_usd"])
                _cost_cell(row["cost_usd"])
                row["stage_outputs"] = records
            except (ValueError, TypeError, KeyError, OSError) as exc:
                records = {s: _absent("invalid_submission") for s in STAGES}
                errors.append({"stage": "benchmark", "category": "benchmark", "code": "invalid_submission", "detail": str(exc)})
        else:
            errors.append({"stage": "benchmark", "category": "benchmark", "code": "missing_submission"})
        scoring = copy.deepcopy(records)
        vlm = scoring["vlm"]
        if vlm.get("executed") is True and vlm.get("output") is None and vlm.get("invalid_output") is not None:
            vlm["output"] = vlm["invalid_output"]
        try:
            metrics = evaluate_item(data, gt, scoring)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({"stage": "benchmark", "category": "benchmark", "code": "invalid_stage_mapping", "detail": str(exc)})
            scoring = {s: _absent("invalid_stage_mapping") for s in STAGES}
            metrics = evaluate_item(data, gt, scoring)
        if not isinstance(row.get("models"), dict):
            row["models"] = {s: None for s in STAGES}
        if row["models"].get("clef") is None and records["clef"]["status"] == "skipped" and not errors:
            _optional_clef(metrics)
        else:
            metrics["clef"]["used"] = True
        if row["models"].get("yolo") is None and records["yolo"]["status"] == "skipped" and not errors:
            for key in ("true_positives", "false_positives", "false_negatives", "precision", "recall", "map50"):
                metrics["yolo"][key] = None
            metrics["yolo"]["per_class"] = {}
            metrics["yolo"]["used"] = False
        else:
            metrics["yolo"]["used"] = True
        yolo_output = scoring["yolo"].get("output")
        if scoring["yolo"]["status"] == "ok" and isinstance(yolo_output, dict):
            out_frames = yolo_output.get("frames")
            expected_ids = {f["frame_id"] for f in data["frames"]}
            supplied_ids = {f.get("frame_id") for f in out_frames if isinstance(f, dict) and isinstance(f.get("frame_id"), str)} if isinstance(out_frames, list) else set()
            if not isinstance(out_frames, list) or len(out_frames) != 64 or supplied_ids != expected_ids:
                metrics["yolo"]["output_mapping_valid"] = False
                metrics["yolo"]["output_errors"].append("executed YOLO must report all fixed 64 frames including empty detections")
        _support(metrics, data, gt, scoring)
        metrics["pipeline"]["whole_item_semantic_correct"] = (
            all(s["semantic_correct"] is True for s in metrics["vlm"]["per_source"].values())
            if metrics["vlm"]["reviewed_source_count"] == len(data["sources"]) else None)
        errors.extend(_diagnostics(metrics, records, gt))
        row["errors"] = row.get("errors", []) + errors if isinstance(row.get("errors"), list) else errors
        categories = {e.get("category") for e in row["errors"] if isinstance(e, dict)}
        row["status"] = next((name for category, name in [("benchmark", "benchmark_error"), ("execution", "execution_error"),
                             ("model", "model_error"), ("evaluation_unavailable", "evaluation_unavailable")]
                              if category in categories), "completed")
        row.update(ground_truth=gt, metrics=metrics)
        rows.append(row)
    known = [s for row in rows for s in row["metrics"]["vlm"]["per_source"].values() if s["expected_event_type"] is not None]
    solo = [s for row in rows if len(inputs[row["item_id"]]["sources"]) == 1
            for s in row["metrics"]["vlm"]["per_source"].values() if s["expected_event_type"] is not None]
    complete = [row["metrics"]["pipeline"]["whole_item_semantic_correct"] for row in rows
                if row["metrics"]["pipeline"]["whole_item_semantic_correct"] is not None]
    accuracy = sum(s["semantic_correct"] is True for s in known) / len(known) if known else None
    summary = {"item_count": len(rows), "submitted_item_count": len(submitted),
               "missing_item_count": len(rows) - len(submitted), "reviewed_source_occurrences": len(known),
               "source_event_accuracy": accuracy, "primary_score_100": accuracy * 100 if accuracy is not None else None,
               "whole_item_accuracy": sum(complete) / len(complete) if complete else None,
               "single_source_accuracy": sum(s["semantic_correct"] is True for s in solo) / len(solo) if solo else None,
               "omitted_reviewed_sources": sum(s["omitted_reviewed_source"] for s in known),
               "ground_truth_sha256": _digest(Path(ground_truth_path) if Path(ground_truth_path).is_absolute() else root / ground_truth_path),
               "output_format_valid_items": sum(r["metrics"]["vlm"]["output_format_valid"] is True for r in rows),
               "note": "AI-reviewed demo references; repeated source combinations are not independent CCTV samples. No weighted composite/pass threshold.",
               "invoice_cost_usd": None}
    return rows, summary


def existing_results_submission(csv_path):
    """Read historic results as submission rows using actual normalized records.

    This is a data conversion only. MAIN writes the returned rows; old results
    and their pending-truth evaluation remain untouched.
    """
    csv.field_size_limit(32 * 1024 * 1024)
    result = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
            row = {k: raw[k] if k in {"item_id", "status"} else json.loads(raw[k]) for k in SUBMISSION_COLUMNS}
            row["stage_outputs"] = {s: {"record_path": value["normalized_path"]}
                                    for s, value in row["stage_outputs"].items()}
            result.append(row)
    return result

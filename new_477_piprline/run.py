"""One item, one CSV row, with auditable stage artifacts and first-class skipped stages."""
import argparse
import asyncio
import csv
from datetime import datetime, timezone
import importlib
import json
import math
from pathlib import Path
import sys
import time

from pipeline477.budget import Budget
from pipeline477.contract import CLASSES, COLUMNS, digest, indices, validate_input
from pipeline477.execution import execute_pipeline_stage
from pipeline477.io import load_env, load_json, scrub, write_json
from pipeline477.metrics import evaluate_item, validate_ground_truth

HERE = Path(__file__).resolve().parent

def plugin(spec):
    module, name = spec["plugin"].split(":", 1)
    return getattr(importlib.import_module(module), name)(spec)

def absent(status, reason):
    return {"status": status, "executed": False, "output": None, "latency_ms": None,
            "cost_usd": {"value": 0, "basis": "not_called", "invoice_usd": 0},
            "errors": [{"category": "execution", "code": reason, "detail": reason}]}

def valid_routes(output, sources):
    if not isinstance(output, dict) or not isinstance(output.get("sources"), list):
        return False
    entries = output["sources"]
    return (len(entries) == len(sources)
            and all(isinstance(d, dict) and isinstance(d.get("source_id"), str)
                    and type(d.get("invoke_vlm")) is bool for d in entries)
            and {d["source_id"] for d in entries} == set(sources))

def valid_detections(output, frames):
    if not isinstance(output, dict) or not isinstance(output.get("frames"), list):
        return False
    expected = {f["frame_id"]: f for f in frames}
    seen = set()
    for row in output["frames"]:
        if (not isinstance(row, dict) or not isinstance(row.get("frame_id"), str)
                or row["frame_id"] not in expected or row["frame_id"] in seen):
            return False
        seen.add(row["frame_id"])
        frame = expected[row["frame_id"]]
        if row.get("source_id") != frame["source_id"] or not isinstance(row.get("detections"), list):
            return False
        for detection in row["detections"]:
            if (not isinstance(detection, dict) or not isinstance(detection.get("class_name"), str)
                    or detection["class_name"] not in CLASSES):
                return False
            box, confidence = detection.get("bbox"), detection.get("confidence")
            if (not isinstance(box, list) or len(box) != 4 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
                    not (0 <= box[0] < box[2] <= frame["width"] and 0 <= box[1] < box[3] <= frame["height"]) or
                    type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                return False
    return seen == set(expected)

def relative(path):
    return Path(path).relative_to(HERE).as_posix()

def check_lock():
    lock = load_json(HERE / "benchmark.lock.json")
    for filename, expected in lock.items():
        if digest(HERE / filename) != expected:
            raise ValueError("frozen input changed: " + filename)
    evaluation_lock = HERE / "evaluation.lock.json"
    if evaluation_lock.exists():
        for filename, expected in load_json(evaluation_lock).items():
            if digest(HERE / filename) != expected:
                raise ValueError("frozen evaluator changed: " + filename)

def load_input(item):
    data = load_json(HERE / "data/frames" / item["item_id"] / "manifest.json")
    for row in data["frames"]:
        row["image_path"] = str(HERE / row["image_path"])
    data["prompt"] = (HERE / "prompts/pipeline_v1.txt").read_text(encoding="utf-8")
    data["output_schema"] = load_json(HERE / "schemas/vlm_output.schema.json")
    data["active_sources"] = data["sources"][:]
    validate_input(data)
    return data

def evaluation_selfcheck():
    """Before paid calls exercise exact/wrong outputs through the real scorer."""
    frames = [{"frame_id": f"SRC01-F{i:06d}", "source_id": "SRC01", "frame_number": i,
               "timestamp_sec": i / 30, "width": 100, "height": 100} for i in range(64)]
    data = {"sources": ["SRC01"], "frames": frames}
    gt = {"SRC01": {"yolo": {"frames": [{"frame_number": 0, "complete": True,
                       "objects": [{"class_name": "person", "bbox": [0, 0, 10, 10]}]}]},
                     "clef": {"reviewed": True, "invoke_vlm": True, "rationale": "Synthetic scorer fixture requires visual review."},
                     "vlm": {"reviewed": True, "label": "physical_conflict"}}}
    prediction = {"source_id": "SRC01", "event_type": "physical_conflict", "event_confidence": .9,
                  "risk_axes": {k: None for k in ("severity", "imminence", "exposure", "persistence")},
                  "evidence_refs": [frames[0]["frame_id"]], "needs_human_review": True,
                  "uncertainty_reason": "Unmeasured risk axes"}
    from pipeline477.contract import output_schema
    data["output_schema"] = output_schema()
    stages = {"yolo": {"status": "ok", "output": {"frames": [{"frame_id": frames[0]["frame_id"],
                    "source_id": "SRC01", "detections": [{"class_name": "person", "bbox": [0, 0, 10, 10], "confidence": .9}]}]}},
              "clef": {"status": "ok", "output": {"sources": [{"source_id": "SRC01", "invoke_vlm": True}]}},
              "vlm": {"status": "ok", "output": {"assessments": [prediction]}}}
    exact = evaluate_item(data, gt, stages)
    stages["vlm"]["output"]["assessments"][0]["event_type"] = "normal"
    wrong = evaluate_item(data, gt, stages)
    if exact == wrong:
        raise ValueError("scorer did not distinguish deliberate semantic mismatch")
    stages["vlm"] = {"status": "skipped", "output": None}
    skipped = evaluate_item(data, gt, stages)
    if skipped == exact:
        raise ValueError("skipped model counted as correct")
    return {"exact_vs_wrong": True, "skipped_vs_exact": True,
            "scope": "synthetic scorer checks, not model execution"}

def preflight(items, registry, gt):
    check_lock()
    from jsonschema import Draft202012Validator
    Draft202012Validator(load_json(HERE / "schemas/ground_truth.schema.json")).validate(gt)
    truth_check = validate_ground_truth(gt, registry)
    if isinstance(truth_check, dict) and not truth_check.get("valid", False):
        raise ValueError("invalid ground truth format")
    for truth in gt.values():
        if any(truth[s].get("reviewed") for s in ("clef", "vlm")):
            if not truth.get("reviewer") or not truth.get("reviewed_at"):
                raise ValueError("reviewed truth needs reviewer and review date")
    for item in items:
        data = load_input(item)
        for allocation in item["sources"]:
            s = allocation["source_id"]
            rows = [f for f in data["frames"] if f["source_id"] == s]
            source = registry[s]
            if [f["frame_number"] for f in rows] != indices(source["frame_count"], allocation["frame_count"]):
                raise ValueError("original frame allocation mismatch")
            if any(f["timestamp_sec"] != f["frame_number"] * source["fps_den"] / source["fps_num"] for f in rows):
                raise ValueError("frame timestamp mapping mismatch")
    return evaluation_selfcheck()

async def run_item(item, gt, models, budget, output, allow_paid):
    start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    data = load_input(item)
    directory = output / item["item_id"]
    directory.mkdir(parents=True, exist_ok=True)
    frame_listing = [{**f, "image_path": relative(f["image_path"])} for f in data["frames"]]
    write_json(directory / "input_frames.json", frame_listing)
    (directory / "prompt.txt").write_text(data["prompt"], encoding="utf-8")
    write_json(directory / "output_schema.json", data["output_schema"])
    context = {"artifact_dir": directory, "package_root": HERE, "budget": budget,
               "allow_paid": allow_paid, "write_json": write_json}
    records, stage_inputs = {}, {}
    public_data = {k: v for k, v in data.items() if k not in ("preparation_decode_ms", "first_decode", "item_id")}
    records["yolo"] = await execute_pipeline_stage(plugin(models["yolo"]), public_data, context,
                                                   models["timeout_sec"])
    records["yolo"].setdefault("executed", True if records["yolo"]["status"] == "ok" else None)
    if records["yolo"]["status"] == "ok" and not valid_detections(records["yolo"].get("output"), data["frames"]):
        records["yolo"].update(status="error", invalid_output=records["yolo"].get("output"), output=None)
        records["yolo"].setdefault("errors", []).append({"category": "evaluation_unavailable",
            "code": "invalid_yolo_stage_output", "detail": "Malformed normalized detection/map; adapter vs model cause needs review."})
    if records["yolo"]["status"] == "ok":
        clef_input = {"sources": data["sources"], "frames": data["frames"],
                      "cv_output": records["yolo"]["output"], "prompt": data["prompt"]}
        records["clef"] = await execute_pipeline_stage(plugin(models["clef"]), clef_input, context,
                                                       models["timeout_sec"])
    else:
        records["clef"] = absent("skipped", "upstream_yolo_failure")
    active, fallback = [], None
    if records["clef"]["status"] == "ok":
        if not valid_routes(records["clef"].get("output"), data["sources"]):
            records["clef"]["status"] = "error"
            records["clef"]["invalid_output"] = records["clef"].get("output")
            records["clef"]["output"] = None
            records["clef"].setdefault("errors", []).append({"category": "model", "code": "route_source_mapping", "detail": "Missing/duplicate source or non-boolean decision"})
        else:
            decisions = records["clef"]["output"]["sources"]
            active = [d["source_id"] for d in decisions if d["invoke_vlm"]]
    if records["clef"]["status"] != "ok" and models.get("fallback") == "invoke_vlm":
        active = data["sources"][:]
        fallback = {"from_stage": "clef", "reason": records["clef"]["status"], "path": "invoke_vlm_all_sources"}
    if active:
        vlm_input = {**public_data, "active_sources": active}
        records["vlm"] = await execute_pipeline_stage(plugin(models["vlm"]), vlm_input, context,
                                                      models["timeout_sec"])
    else:
        records["vlm"] = absent("skipped", "clef_no_action" if records["clef"]["status"] == "ok" else "upstream_clef_unavailable")
    records["vlm"]["source_execution"] = {s: records["vlm"]["status"] if s in active else "skipped" for s in data["sources"]}
    records["vlm"]["active_sources"] = active
    records["vlm"]["fallback"] = fallback
    for stage, record in records.items():
        record.setdefault("errors", [])
        record.setdefault("cost_usd", {"value": None, "basis": "unknown", "invoice_usd": None})
        record.setdefault("executed", None if record["status"] == "error" else False)
        write_json(directory / f"{stage}.normalized.json", record)
        request = directory / f"{stage}.request.json"
        response = directory / f"{stage}.response.json"
        stage_inputs[stage] = {"frame_manifest": relative(directory / "input_frames.json"),
            "request_path": relative(request) if request.exists() else None,
            "prompt_path": relative(directory / "prompt.txt"),
            "candidate_frame_count": 64 if stage != "clef" else 0,
            "frame_count": (64 if stage != "clef" else 0) if record["executed"] is True else 0 if record["executed"] is False else None,
            "feature_frames": 64 if stage == "clef" and record["executed"] is True else 0 if record["executed"] is False else None,
            "request_file_is_planned_not_sent": record["executed"] is not True,
            "active_sources": active if stage == "vlm" else data["sources"],
            "response_path": relative(response) if response.exists() else None,
            "actually_executed": record["executed"]}
        if (HERE / "inspection/quality.json").exists():
            stage_inputs[stage]["sample_quality_inspection"] = "inspection/quality.json"
    metrics = evaluate_item(data, {s: gt[s] for s in data["sources"]}, records)
    errors = [{"stage": stage, **e} for stage, record in records.items() for e in record["errors"]]
    for stage in ("yolo", "clef"):
        for detail in metrics[stage].get("output_errors", []):
            errors.append({"stage": stage, "category": "evaluation_unavailable", "code": "normalized_output_invalid",
                           "detail": detail + "; inspect raw output to distinguish model and conversion errors."})
    if metrics["vlm"].get("output_format_valid") is False:
        errors.append({"stage": "vlm", "category": "model", "code": "output_schema_invalid",
                       "detail": "Valid input yielded a schema-invalid model output; raw response preserved."})
    if metrics["vlm"].get("input_reference_valid") is False:
        errors.append({"stage": "vlm", "category": "model", "code": "evidence_reference_invalid",
                       "detail": "Evidence refers to an absent frame or another source."})
    for source, scored in metrics["vlm"].get("per_source", {}).items():
        if scored.get("safety_policy_valid") is False:
            errors.append({"stage": "vlm", "category": "model", "code": "human_review_policy_invalid",
                           "source_id": source, "detail": "Uncertain/unmeasured/low-confidence result did not request human review."})
        if scored.get("semantic_correct") is False:
            errors.append({"stage": "vlm", "category": "model", "code": "event_mismatch",
                           "source_id": source, "detail": "Prediction differs from reviewed event truth."})
    returned = records["vlm"].get("output")
    assessments = returned.get("assessments", []) if isinstance(returned, dict) else []
    for assessment in assessments if isinstance(assessments, list) else []:
        if isinstance(assessment, dict) and assessment.get("needs_human_review") is False and not assessment.get("evidence_refs"):
            errors.append({"stage": "vlm", "category": "model", "code": "missing_evidence_requires_review",
                           "source_id": assessment.get("source_id"), "detail": "No usable evidence supports automatic assessment."})
    if any(not gt[s]["yolo"]["frames"] or not gt[s]["clef"]["reviewed"] or not gt[s]["vlm"]["reviewed"] for s in data["sources"]):
        errors.append({"stage": "evaluation", "category": "evaluation_unavailable", "code": "ground_truth_review_pending",
                       "detail": "Object boxes, routing truth and/or event labels are unreviewed."})
    categories = {e["category"] for e in errors}
    status = next((name for category, name in [("benchmark", "benchmark_error"), ("execution", "execution_blocked_or_error"),
                  ("model", "model_error"), ("evaluation_unavailable", "evaluation_unavailable")] if category in categories), "completed")
    costs = {s: r["cost_usd"] for s, r in records.items()}
    values = [v["value"] for v in costs.values()]
    costs["total"] = {"value": sum(values) if all(v is not None for v in values) else None,
                      "basis": "sum_usage_based_estimates_or_not_called", "invoice_usd": None}
    row = {"item_id": item["item_id"], "sources": {"videos": item["sources"],
           "same_incident_groups": item["same_incident_groups"], "scenario_semantics": item["scenario_semantics"],
           "synchronization": item["synchronization"]},
           "models": {s: {k: v for k, v in spec.items() if k != "plugin"} for s, spec in models.items() if isinstance(spec, dict)},
           "ground_truth": {s: gt[s] for s in data["sources"]}, "stage_inputs": stage_inputs,
           "stage_outputs": {s: {"status": r["status"], "executed": r["executed"], "output": r.get("output"),
                        "normalized_path": relative(directory / f"{s}.normalized.json"),
                        "metadata": r.get("metadata"), "source_execution": r.get("source_execution"), "fallback": r.get("fallback")}
                             for s, r in records.items()},
           "metrics": metrics, "latency_ms": {s: r.get("latency_ms") for s, r in records.items()},
           "cost_usd": costs, "status": status, "errors": errors}
    # Preparation occurred once before this run; it is included in cold first-use total.
    row["latency_ms"].update(preparation_decode=data["preparation_decode_ms"],
                             current_run_wall=(time.perf_counter() - start) * 1000)
    row["latency_ms"]["total_first_use"] = row["latency_ms"]["current_run_wall"] + data["preparation_decode_ms"]
    row["models"]["execution"] = {"repeats": 1, "yolo_worker_cold_start": True,
        "started_at_utc": started_at,
        "fallback_policy": models.get("fallback", "stop"),
        "api_first_call": None, "benchmark_lock_sha256": digest(HERE / "benchmark.lock.json"),
        "ground_truth_sha256": digest(HERE / "ground_truth/sources.json")}
    row["models"]["execution"]["paid_authorization_sha256"] = digest(HERE / "paid_authorization.json") if (HERE / "paid_authorization.json").exists() else None
    row["models"]["execution"]["evaluation_lock_sha256"] = digest(HERE / "evaluation.lock.json") if (HERE / "evaluation.lock.json").exists() else None
    for stage, record in records.items():
        row["models"][stage]["actual_runtime_metadata"] = record.get("metadata")
    write_json(directory / "result.json", row)
    return scrub(row)

async def main_async(args):
    suite_started = time.perf_counter()
    load_env(args.env_file)
    package = load_json(HERE / "items.json")
    registry, gt = load_json(HERE / "data/sources.json"), load_json(HERE / "ground_truth/sources.json")
    models = load_json(args.config)
    check = preflight(package["items"], registry, gt)
    preflight_ms = (time.perf_counter() - suite_started) * 1000
    budget = Budget(HERE / "budget_ledger.json")
    upper = len(package["items"]) * (models["clef"]["reservation_upper_usd"] + models["vlm"]["reservation_upper_usd"])
    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory is not empty; preserve earlier results")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "execution_config.json", models)
    write_json(output / "preflight.json", {"checks": check, "item_count": package["item_count"],
        "paid_enabled": args.allow_paid, "preflight_ms": preflight_ms, "forecast_reservation_upper_usd": upper,
        "inherited_remaining_usd": budget.remaining, "explicit_uncapped_authorization": budget.uncapped,
        "ground_truth_review_pending": True,
        "invoice_cost_usd": None})
    if args.check_only:
        print(json.dumps({"preflight": "pass", "items": package["item_count"], "paid_calls": 0,
                          "reservation_forecast_usd": upper, "remaining_usd": budget.remaining}))
        return
    rows = []
    # Sequential items and sequential stages. No competing budget writers permitted.
    for item in package["items"]:
        row = await run_item(item, gt, models, budget, output, args.allow_paid)
        rows.append(row)
        with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            for saved in rows:
                writer.writerow({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (list, dict)) else v for k, v in saved.items()})
        print(json.dumps({"item_id": item["item_id"], "status": row["status"],
                          "yolo": row["stage_outputs"]["yolo"]["status"], "rows": len(rows)}), flush=True)
    scored_sources = [s for r in rows for s in r["metrics"]["vlm"]["per_source"].values()
                      if s["expected_event_type"] is not None]
    write_json(output / "summary.json", {"problem_count": len(rows), "repeats": 1,
        "preflight_ms": preflight_ms, "suite_wall_ms": (time.perf_counter() - suite_started) * 1000,
        "yolo_successes": sum(r["stage_outputs"]["yolo"]["status"] == "ok" for r in rows),
        "whole_pipeline_stage_completions": sum(all(s["status"] == "ok" for s in r["stage_outputs"].values()) for r in rows),
        "format_and_reference_valid_items": sum(r["metrics"]["vlm"]["output_format_valid"] is True
                                               and r["metrics"]["vlm"]["input_reference_valid"] is True for r in rows),
        "semantic_accuracy": sum(s["semantic_correct"] is True for s in scored_sources) / len(scored_sources) if scored_sources else None,
        "reviewed_source_occurrences": len(scored_sources),
        "reason": "Source occurrences repeat across items; this is a small demo, not independent CCTV generalization.",
        "budget_remaining_usd": budget.remaining})

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config/models.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except Exception as error:
        # Preserve stable class only, never arbitrary provider messages/credentials.
        print(json.dumps({"status": "benchmark_error", "exception_type": type(error).__name__,
                          "detail": "Preflight/runner failed. Inspect input/config and run tests; no success claimed."}))
        sys.exit(1)

if __name__ == "__main__":
    main()

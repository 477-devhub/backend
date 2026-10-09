"""Sequential full-pipeline prompt-v2 diagnostic; separate from frozen common benchmark."""
import asyncio
import copy
import csv
import hashlib
import json
import time
from pathlib import Path
from pipeline477.budget import Budget
from pipeline477.contract import COLUMNS
from pipeline477.execution import execute_pipeline_stage
from pipeline477.io import load_env, load_json, scrub, write_json
from pipeline477.metrics import evaluate_item
from run import HERE, absent, check_lock, load_input, plugin, valid_detections, valid_routes


async def run_item(item, models, truth, budget, output):
    started = time.perf_counter()
    data = load_input(item)
    data["prompt"] = (HERE / "prompts/pipeline_v2_review.txt").read_text(encoding="utf-8")
    directory = output / item["item_id"]
    directory.mkdir()
    public = {k: v for k, v in data.items() if k not in {"item_id", "preparation_decode_ms", "first_decode"}}
    write_json(directory / "input_frames.json", [{**f, "image_path": str(Path(f["image_path"]).relative_to(HERE)).replace("\\", "/")} for f in data["frames"]])
    (directory / "prompt.txt").write_text(data["prompt"], encoding="utf-8")
    write_json(directory / "output_schema.json", data["output_schema"])
    context = {"artifact_dir": directory, "package_root": HERE, "budget": budget,
               "allow_paid": True, "write_json": write_json}
    records = {}
    records["yolo"] = await execute_pipeline_stage(plugin(models["yolo"]), public, context, models["timeout_sec"])
    if records["yolo"]["status"] == "ok" and not valid_detections(records["yolo"].get("output"), data["frames"]):
        records["yolo"].update(status="error", invalid_output=records["yolo"].get("output"), output=None)
        records["yolo"].setdefault("errors", []).append({"category": "benchmark", "code": "invalid_yolo_mapping"})
    if records["yolo"]["status"] == "ok":
        clef_input = {"sources": data["sources"], "frames": data["frames"], "cv_output": records["yolo"]["output"], "prompt": data["prompt"]}
        records["clef"] = await execute_pipeline_stage(plugin(models["clef"]), clef_input, context, models["timeout_sec"])
    else:
        records["clef"] = absent("skipped", "upstream_yolo_failure")
    active, fallback = [], None
    if records["clef"]["status"] == "ok":
        if valid_routes(records["clef"].get("output"), data["sources"]):
            active = [r["source_id"] for r in records["clef"]["output"]["sources"] if r["invoke_vlm"]]
        else:
            records["clef"].update(status="error", invalid_output=records["clef"].get("output"), output=None)
            records["clef"].setdefault("errors", []).append({"category": "model", "code": "route_source_mapping"})
    if records["clef"]["status"] != "ok" and models.get("fallback") == "invoke_vlm":
        active = list(data["sources"])
        fallback = {"from_stage": "clef", "reason": records["clef"]["status"], "path": "invoke_vlm_all_sources"}
    if active:
        records["vlm"] = await execute_pipeline_stage(plugin(models["vlm"]), {**public, "active_sources": active}, context, models["timeout_sec"])
    else:
        records["vlm"] = absent("skipped", "clef_no_action")
    records["vlm"].update(active_sources=active, fallback=fallback,
                          source_execution={sid: records["vlm"]["status"] if sid in active else "skipped" for sid in data["sources"]})
    for stage, record in records.items():
        record.setdefault("cost_usd", {"value": None, "basis": "unknown", "invoice_usd": None})
        write_json(directory / (stage + ".normalized.json"), record)
    metrics = evaluate_item(data, {sid: truth[sid] for sid in data["sources"]}, records)
    def relative(path):
        return str(path.relative_to(HERE)).replace("\\", "/")
    inputs = {stage: {"frame_manifest": relative(directory / "input_frames.json"),
                     "prompt_path": relative(directory / "prompt.txt"),
                     "request_path": relative(directory / (stage + ".request.json")) if (directory / (stage + ".request.json")).exists() else None,
                     "response_path": relative(directory / (stage + ".response.json")) if (directory / (stage + ".response.json")).exists() else None,
                     "active_sources": active if stage == "vlm" else data["sources"],
                     "actually_executed": records[stage].get("executed"),
                     "experiment": "prompt-v2 diagnostic; outside frozen common prompt"} for stage in records}
    cost_values = [r["cost_usd"].get("value") for r in records.values()]
    row = {"item_id": item["item_id"], "sources": item["sources"], "models": models,
           "ground_truth": {sid: truth[sid] for sid in data["sources"]}, "stage_inputs": inputs,
           "stage_outputs": {s: {"normalized_path": relative(directory / (s + ".normalized.json")), "status": r["status"], "executed": r.get("executed")} for s, r in records.items()},
           "metrics": metrics, "latency_ms": {**{s: r.get("latency_ms") for s, r in records.items()}, "total": (time.perf_counter() - started) * 1000},
           "cost_usd": {**{s: r["cost_usd"] for s, r in records.items()}, "total_usage_estimate": sum(cost_values) if all(v is not None for v in cost_values) else None, "invoice_actual": None},
           "status": "completed" if all(r["status"] == "ok" for r in records.values()) else "stage_failure",
           "errors": [{"stage": s, **e} for s, r in records.items() for e in r.get("errors", [])]}
    write_json(directory / "result.json", row)
    return scrub(row)


async def main_async():
    check_lock()
    load_env(HERE.parent / ".env")
    truth = load_json(HERE / "ground_truth/ai_review_v1/sources.json")
    for relative, expected in load_json(HERE / "ground_truth/ai_review_v1/ground_truth.lock.json").items():
        if hashlib.sha256((HERE / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Reference lock mismatch")
    models = load_json(HERE / "config/full_pipeline.json")
    output = HERE / "results/prompt_v2_diagnostic"
    if output.exists() and any(output.iterdir()):
        raise ValueError("Preserve prior diagnostic results")
    output.mkdir(exist_ok=True)
    items = [i for i in load_json(HERE / "items.json")["items"] if i["item_id"] in {"P002", "P004"}]
    plan = {"items": [i["item_id"] for i in items], "frame_count_per_item": 64,
            "purpose": "Failure-selected prompt clarification diagnostic; not a blind benchmark or all12 rerun",
            "changed": ["explicit observable-event definitions", "explicit null-axis human-review rule", "brief selective transition evidence"],
            "unchanged": ["64 original frames", "schema", "YOLO26s CPU960 conf0.1 ByteTrack", "Clef model/input", "VLM deepseek-flash nonthinking JPEG80 noresize/crop"],
            "expected_usage_cost_usd": 0.045, "expected_cost_is_estimate": True,
            "reservation_usd": len(items) * (models["clef"]["reservation_upper_usd"] + models["vlm"]["reservation_upper_usd"]),
            "price_checked_at_utc": "2026-10-08T17:07:02Z", "price_basis": "official off-peak tariff; invoice unknown",
            "price_sources": ["https://api-docs.deepseek.com/quick_start/pricing", "https://developers.cloudflare.com/workers-ai/models/clef/"],
            "repeats": 1, "first_model_load": True, "ground_truth_predeclared": True}
    write_json(output / "plan.json", plan)
    print(json.dumps({"plan": plan["items"], "expected_usage_cost_usd": plan["expected_usage_cost_usd"], "reservation_usd": plan["reservation_usd"]}), flush=True)
    budget, rows = Budget(HERE / "budget_ledger.json"), []
    for item in items:
        rows.append(await run_item(item, models, truth, budget, output))
        with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)
        print(json.dumps({"item_id": item["item_id"], "status": rows[-1]["status"], "accuracy": rows[-1]["metrics"]["pipeline"]["event_accuracy"]}), flush=True)
    write_json(output / "summary.json", {"problem_count": len(rows), "new_model_calls": len(rows) * 3,
        "new_paid_calls": sum(r["stage_outputs"][s]["executed"] is True for r in rows for s in ("clef", "vlm")),
        "event_accuracy": sum(r["metrics"]["pipeline"]["event_accuracy"] for r in rows) / len(rows),
        "total_usage_cost_estimate": sum(r["cost_usd"]["total_usage_estimate"] for r in rows) if all(r["cost_usd"]["total_usage_estimate"] is not None for r in rows) else None,
        "invoice_actual": None, "experiment_only": True, "selection": "previous failures P002/P004"})


if __name__ == "__main__":
    asyncio.run(main_async())

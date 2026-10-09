"""Offline summary of actual item rows; no model or API invocation."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics

from pipeline477.io import write_json

HERE = Path(__file__).resolve().parent

def analyze(output):
    csv.field_size_limit(32 * 1024 * 1024)
    with (output / "results.csv").open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    structured = ["sources", "models", "ground_truth", "stage_inputs", "stage_outputs", "metrics",
                  "latency_ms", "cost_usd", "errors"]
    for row in records:
        for field in structured:
            row[field] = json.loads(row[field])
    if len(records) != 12 or len({r["item_id"] for r in records}) != 12:
        raise ValueError("expected exactly one row for each of 12 items")
    links, missing = [], []
    for row in records:
        for value in row["stage_inputs"].values():
            links += [v for k, v in value.items() if (k.endswith("path") or k in ("frame_manifest", "sample_quality_inspection")) and isinstance(v, str)]
        links += [v["normalized_path"] for v in row["stage_outputs"].values()]
    for link in links:
        if not (HERE / link).is_file():
            missing.append(link)
    stage_statuses = {s: dict(Counter(r["stage_outputs"][s]["status"] for r in records)) for s in ("yolo", "clef", "vlm")}
    latency = {}
    for stage in ("yolo", "clef", "vlm", "current_run_wall", "total_first_use"):
        numbers = [r["latency_ms"].get(stage) for r in records]
        numbers = [v for v in numbers if v is not None]
        latency[stage] = {"n": len(numbers), "median_ms": statistics.median(numbers) if numbers else None,
                          "min_ms": min(numbers) if numbers else None, "max_ms": max(numbers) if numbers else None}
    by_category = {c: sum(any(e["category"] == c for e in r["errors"]) for r in records)
                   for c in ("benchmark", "model", "execution", "evaluation_unavailable")}
    error_codes = dict(Counter((e["stage"] + ":" + e["code"]) for r in records for e in r["errors"]))
    costs = {}
    for stage in ("yolo", "clef", "vlm"):
        values = [r["cost_usd"][stage]["value"] for r in records]
        costs[stage] = {"known_usage_estimate_usd": sum(v for v in values if v is not None),
                        "unknown_items": sum(v is None for v in values),
                        "complete_estimate_usd": sum(values) if all(v is not None for v in values) else None,
                        "invoice_usd": None}
    known = sum(c["known_usage_estimate_usd"] for c in costs.values())
    unknown = sum(c["unknown_items"] for c in costs.values())
    route_rows = [s for r in records for s in r["metrics"]["clef"]["per_source"].values() if s["reviewed"]]
    event_rows = [s for r in records for s in r["metrics"]["vlm"]["per_source"].values() if s["expected_event_type"] is not None]
    result = {"items": len(records), "json_cells_valid": True, "referenced_paths_checked": len(links),
        "missing_referenced_paths": missing, "stage_statuses": stage_statuses,
        "all_stages_completed": sum(all(s["status"] == "ok" for s in r["stage_outputs"].values()) for r in records),
        "format_valid_items": sum(r["metrics"]["vlm"]["output_format_valid"] is True for r in records),
        "reference_valid_items": sum(r["metrics"]["vlm"]["input_reference_valid"] is True for r in records),
        "fallback_items": sum(bool(r["stage_outputs"]["vlm"].get("fallback")) for r in records),
        "failure_categories_item_count": by_category, "error_codes": error_codes, "latency": latency,
        "costs": costs, "known_partial_usage_estimate_usd": known, "complete_usage_estimate_usd": known if not unknown else None,
        "actual_invoice_usd": None,
        "semantic_metrics": {"detection_map50_by_item": {r["item_id"]: r["metrics"]["yolo"]["map50"] for r in records},
            "route_accuracy": sum(s["correct"] is True for s in route_rows) / len(route_rows) if route_rows else None,
            "event_accuracy_including_omissions": sum(s["semantic_correct"] is True for s in event_rows) / len(event_rows) if event_rows else None,
            "reviewed_route_occurrences": len(route_rows), "reviewed_event_occurrences": len(event_rows),
            "evidence_content_accuracy": None, "reason": "Only reviewed truth is scored; source occurrences repeat across items."},
        "repeats": 1, "scope": "6 unique clips repeatedly composed into 12 small-demo items; no CCTV generalization"}
    write_json(output / "analysis.json", result)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.output.resolve())
    print(json.dumps({k: result[k] for k in ("items", "stage_statuses", "all_stages_completed", "format_valid_items",
                                            "fallback_items", "known_partial_usage_estimate_usd", "missing_referenced_paths")}, ensure_ascii=False))

if __name__ == "__main__":
    main()

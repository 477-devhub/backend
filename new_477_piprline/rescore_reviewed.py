"""Re-score preserved real inference against new AI visual references; no model calls."""
import csv
import hashlib
import json
from pathlib import Path
from pipeline477.contract import COLUMNS
from pipeline477.metrics import evaluate_item
from run import check_lock, load_input

HERE = Path(__file__).resolve().parent


def main():
    check_lock()
    review = HERE / "ground_truth/ai_review_v1"
    for relative, expected in json.loads((review / "ground_truth.lock.json").read_text()).items():
        if hashlib.sha256((HERE / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Reviewed reference lock mismatch")
    truth = json.loads((review / "sources.json").read_text(encoding="utf-8"))
    source = HERE / "results/full_pipeline_v2"
    output = HERE / "results/reviewed_reference_v1"
    output.mkdir(exist_ok=True)
    csv.field_size_limit(32 * 1024 * 1024)
    with (source / "results_readable.csv").open(encoding="utf-8-sig", newline="") as stream:
        originals = {r["item_id"]: r for r in csv.DictReader(stream)}
    rows, scored = [], []
    for item in json.loads((HERE / "items.json").read_text())["items"]:
        data = load_input(item)
        records = {name: json.loads((source / item["item_id"] / (name + ".normalized.json")).read_text())
                   for name in ("yolo", "clef", "vlm")}
        metrics = evaluate_item(data, {sid: truth[sid] for sid in data["sources"]}, records)
        row = originals[item["item_id"]].copy()
        row["ground_truth"] = json.dumps({sid: truth[sid] for sid in data["sources"]}, ensure_ascii=False)
        row["metrics"] = json.dumps(metrics, ensure_ascii=False, allow_nan=False)
        original_errors = json.loads(row["errors"])
        row["errors"] = json.dumps([e for e in original_errors if e.get("code") != "ground_truth_review_pending"], ensure_ascii=False)
        row["status"] = "model_error" if any(s["status"] == "error" for s in records.values()) else "completed"
        rows.append(row)
        scored.extend({"item_id": item["item_id"], "source_id": sid, **result}
                      for sid, result in metrics["vlm"]["per_source"].items())
        (output / (item["item_id"] + ".metrics.json")).write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    correct = sum(x["semantic_correct"] is True for x in scored)
    singles = [x for x in scored if int(x["item_id"][1:]) <= 6]
    summary = {"inference_origin": "preserved full_pipeline_v2; NOT new inference",
               "new_model_calls": 0, "new_api_cost_usd": 0,
               "reference_quality": "AI-assisted visually reviewed demo reference; not expert gold",
               "ground_truth_sha256": hashlib.sha256((review / "sources.json").read_bytes()).hexdigest(),
               "problem_count": len(rows), "source_occurrences": len(scored),
               "correct_source_occurrences": correct, "event_accuracy": correct / len(scored),
               "single_video_accuracy": sum(x["semantic_correct"] is True for x in singles) / len(singles),
               "per_source": {sid: {"count": sum(x["source_id"] == sid for x in scored),
                                     "correct": sum(x["source_id"] == sid and x["semantic_correct"] is True for x in scored)} for sid in truth},
               "source_results": scored,
               "normal_false_positive_rate": None,
               "unnecessary_vlm_call_rate": None,
               "semantic_explanation_accuracy": None,
               "limitations": ["Repeated clip combinations are not independent events.", "Sparse scoped box reference only.", "No verified normal control clips.", "GT was prepared after preserved historical inference; this is retrospective scoring, not a blind test."]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("problem_count", "source_occurrences", "correct_source_occurrences", "event_accuracy", "single_video_accuracy", "per_source", "new_model_calls")}))


if __name__ == "__main__":
    main()

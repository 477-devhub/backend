"""Export a readable 12-row CSV, preserving full results and all measured values."""
import argparse
from copy import deepcopy
import csv
import json
from pathlib import Path

from run import COLUMNS


def compact_row(original):
    row = deepcopy(original)
    for stage, record in row["stage_outputs"].items():
        metadata = record.get("metadata", {})
        if "images" in metadata:
            images = metadata.pop("images")
            metadata["image_metadata_ref"] = {"file": record["normalized_path"],
                "json_pointer": "/metadata/images", "image_count": len(images)}
        if stage == "yolo" and isinstance(record.get("output"), dict):
            full = record.pop("output")
            sources = {}
            for frame in full.get("frames", []):
                source = sources.setdefault(frame["source_id"], {"frames": 0, "detections_by_class": {}})
                source["frames"] += 1
                for detection in frame.get("detections", []):
                    label = detection["class_name"]
                    source["detections_by_class"][label] = source["detections_by_class"].get(label, 0) + 1
            record["output_summary"] = {"frame_count": len(full.get("frames", [])),
                "track_count": len(full.get("tracks", [])), "sources": sources,
                "full_output_ref": {"file": record["normalized_path"], "json_pointer": "/output"}}
    for stage, model in row.get("models", {}).items():
        metadata = model.get("actual_runtime_metadata")
        if isinstance(metadata, dict) and "images" in metadata:
            images = metadata.pop("images")
            metadata["image_metadata_ref"] = {"file": row["stage_outputs"][stage]["normalized_path"],
                "json_pointer": "/metadata/images", "image_count": len(images)}
    return row


def export(output):
    rows = []
    for index in range(1, 13):
        item = f"P{index:03d}"
        full = json.loads((output / item / "result.json").read_text(encoding="utf-8"))
        if full["item_id"] != item:
            raise ValueError("item mapping invalid")
        rows.append(compact_row(full))
    maximum = 0
    with (output / "results_readable.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            serialized = {k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (list, dict)) else v
                          for k, v in row.items()}
            maximum = max(maximum, *(len(str(v)) for v in serialized.values()))
            writer.writerow(serialized)
    print(json.dumps({"items": len(rows), "file": "results_readable.csv", "max_cell_characters": maximum,
                      "full_results_preserved": True, "metrics_changed": False, "paid_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    export(parser.parse_args().output.resolve())

"""Offline integrity audit; never calls a model or prints credentials."""
import argparse
import base64
import csv
import hashlib
import json
import os
from pathlib import Path

from pipeline477.io import load_env, write_json

HERE = Path(__file__).resolve().parent
STRUCTURED = ("sources", "models", "ground_truth", "stage_inputs", "stage_outputs",
              "metrics", "latency_ms", "cost_usd", "errors")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(output, original_root=None):
    csv.field_size_limit(32 * 1024 * 1024)
    with (output / "results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in STRUCTURED:
            row[key] = json.loads(row[key])
    failures, counts = [], {"items": len(rows), "raw_pairs": 0, "sent_jpeg_images": 0}
    expected_ids = {f"P{i:03d}" for i in range(1, 13)}
    if len(rows) != 12 or {r["item_id"] for r in rows} != expected_ids:
        failures.append("csv_item_count_or_ids")
    for name in ("benchmark.lock.json", "evaluation.lock.json"):
        locked = load(HERE / name)
        counts[name] = len(locked)
        for relative, sha in locked.items():
            path = HERE / relative
            if not path.is_file() or digest(path) != sha:
                failures.append(name + ":" + relative)
    counts["original_files_checked"] = 0
    if original_root:
        for relative, sha in load(HERE / "original_integrity.json").items():
            counts["original_files_checked"] += 1
            path = original_root / relative
            if not path.is_file() or digest(path) != sha:
                failures.append("original_changed:" + relative)
    for row in rows:
        item = row["item_id"]
        directory = output / item
        frames = load(directory / "input_frames.json")
        mapping = {f["frame_id"]: f for f in frames}
        if len(frames) != 64 or len(mapping) != 64:
            failures.append(item + ":input_frame_count")
        for stage, record in row["stage_outputs"].items():
            if not (HERE / record["normalized_path"]).is_file():
                failures.append(item + ":" + stage + ":normalized_missing")
            if record.get("executed") is not True:
                continue
            request, response = directory / (stage + ".request.json"), directory / (stage + ".response.json")
            if not request.is_file() or not response.is_file():
                failures.append(item + ":" + stage + ":actual_raw_missing")
                continue
            counts["raw_pairs"] += 1
            body = request.read_text(encoding="utf-8")
            forbidden = ("\"annotations\"", "\"reference_label\"", "\"caption_text\"",
                         "\"evidence_text\"", "\"obj_bbox\"", "01_swoon_fall.mp4",
                         "02_clear_wall_crossing.mp4", "03_ambiguous_gate_entry.mp4",
                         "04_fight.mp4", "05_multiview_fight_cam_a.mp4", "06_multiview_fight_cam_b.mp4")
            if any(term in body for term in forbidden):
                failures.append(item + ":" + stage + ":private_reference_in_request")
            if stage != "vlm":
                continue
            request_json = json.loads(body)
            images = [c for m in request_json["messages"] for c in m.get("content", [])
                      if isinstance(c, dict) and c.get("type") == "image_url"]
            meta = record["metadata"].get("images", [])
            if len(images) != 64 or len(meta) != 64:
                failures.append(item + ":vlm_image_count")
            for image, info in zip(images, meta):
                data = base64.b64decode(image["image_url"]["url"].split(",", 1)[1], validate=True)
                counts["sent_jpeg_images"] += 1
                if hashlib.sha256(data).hexdigest() != info["sent_jpeg_sha256"]:
                    failures.append(item + ":sent_jpeg_hash")
                if info["frame_id"] not in mapping or info["png_sha256"] != mapping[info["frame_id"]]["sha256"]:
                    failures.append(item + ":vlm_frame_mapping")
            raw = load(response)
            converted = directory / "vlm.converted.json"
            if converted.is_file():
                original = json.loads(raw["choices"][0]["message"]["content"])
                if original != load(converted):
                    failures.append(item + ":raw_converted_output_changed")
    # Exact-value scan: output counts/paths only, never secret values.
    secrets = [os.environ[k].encode() for k in ("VLM_API_KEY", "CLEF_API_TOKEN",
               "CLOUDFLARE_AUTH_TOKEN", "CLEF_ACCOUNT") if len(os.environ.get(k, "")) >= 8]
    counts["secret_values_checked"] = len(secrets)
    counts["text_files_scanned"] = 0
    for path in HERE.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".csv", ".md", ".txt", ".py", ".toml"}:
            continue
        counts["text_files_scanned"] += 1
        overlap = b""
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1048576), b""):
                combined = overlap + block
                if any(secret in combined for secret in secrets):
                    failures.append("credential_in_artifact:" + path.relative_to(HERE).as_posix())
                    break
                overlap = combined[-max([len(s) for s in secrets] + [1]):]
    result = {"technical_integrity_pass": not failures, "checks": counts,
              "failures": failures, "paid_calls": 0,
              "semantic_correctness_claimed": False,
              "original_check": "performed" if original_root else "not_requested"}
    write_json(output / "audit.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-root", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    load_env(args.env_file)
    result = audit(args.output.resolve(), args.original_root.resolve() if args.original_root else None)
    print(json.dumps(result, ensure_ascii=False))
    if not result["technical_integrity_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

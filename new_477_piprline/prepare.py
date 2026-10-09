"""MAIN-owned exporter and frozen neutral input generator; originals are read-only."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from pipeline477.contract import COMBINATIONS, allocations, indices, digest, output_schema
from pipeline477.io import write_json

HERE = Path(__file__).resolve().parent
FILENAMES = ["01_swoon_fall.mp4", "02_clear_wall_crossing.mp4", "03_ambiguous_gate_entry.mp4",
             "04_fight.mp4", "05_multiview_fight_cam_a.mp4", "06_multiview_fight_cam_b.mp4"]
REFERENCES = ["fall_ground_posture", "boundary_crossing", "gate_entry_authorization_unknown",
              "physical_conflict", "physical_conflict", "physical_conflict"]

def snapshot(root):
    result = {}
    for folder in ("477_modeling_benchmark_v1", "final_candidates_v1", "data", "media", "runs/baseline-final"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file():
                result[path.relative_to(root).as_posix()] = digest(path)
    return result

def export(root):
    """Copy reviewed sources once; all future team execution is standalone."""
    targets = {"app/eval/new_pipeline_metrics.py": "pipeline477/metrics.py",
               "app/models/adapters/new_pipeline_cv.py": "pipeline477/adapters/cv.py",
               "app/models/adapters/new_pipeline_clef.py": "pipeline477/adapters/clef.py",
               "app/models/adapters/new_pipeline_vlm.py": "pipeline477/adapters/vlm.py",
               "app/models/adapters/yolo_benchmark_worker.py": "pipeline477/adapters/yolo_worker.py",
               "tests/eval/test_new_pipeline_metrics.py": "tests/test_metrics.py",
               "tests/models/test_new_pipeline_cv.py": "tests/test_cv.py",
               "tests/models/test_new_pipeline_clef.py": "tests/test_clef.py",
               "tests/models/test_new_pipeline_vlm.py": "tests/test_vlm.py"}
    exported = {}
    for src, dst in targets.items():
        source = root / src
        if not source.exists():
            continue
        target = HERE / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        replacements = {"app.eval.new_pipeline_metrics": "pipeline477.metrics",
                        "app.models.adapters.new_pipeline_cv": "pipeline477.adapters.cv",
                        "app.models.adapters.new_pipeline_clef": "pipeline477.adapters.clef",
                        "app.models.adapters.new_pipeline_vlm": "pipeline477.adapters.vlm"}
        for before, after in replacements.items():
            text = text.replace(before, after)
        if dst == "pipeline477/adapters/yolo_worker.py":
            # Only the isolated new-protocol copy supports 6 neutral sources and other local COCO weights.
            text = text.replace('if set(profiles) - {"CAM_01", "CAM_02", "CAM_03"}:',
                                'if set(profiles) - {"SRC01", "SRC02", "SRC03", "SRC04", "SRC05", "SRC06"}:')
            text = text.replace('if not path.is_absolute() or path.name != expected or not path.is_file():',
                                'if not path.is_absolute() or path.suffix != ".pt" or not path.is_file():')
        target.write_text(text, encoding="utf-8")
        exported[dst] = {"origin": src, "sha256": digest(target),
                         "transformation": "SRC01..06 and explicit local COCO .pt weights" if dst.endswith("yolo_worker.py") else "portable imports"}
    text = (root / "app/models/execution.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "execute_pipeline_stage")
    target = HERE / "pipeline477/execution.py"
    target.write_text("import asyncio\nimport copy\nimport time\n\n" + ast.get_source_segment(text, node) + "\n",
                      encoding="utf-8")
    exported["pipeline477/execution.py"] = {"origin": "app/models/execution.py", "sha256": digest(target)}
    write_json(HERE / "source_export.json", exported)

def probe(path):
    raw = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                          "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_read_frames,duration",
                          "-of", "json", str(path)], capture_output=True, check=True).stdout
    row = json.loads(raw)["streams"][0]
    a, b = row["avg_frame_rate"].split("/")
    return {"width": row["width"], "height": row["height"], "frame_count": int(row["nb_read_frames"]),
            "fps_num": int(a), "fps_den": int(b), "duration_sec": float(row["duration"])}

def freeze(root):
    if (HERE / "benchmark.lock.json").exists():
        raise ValueError("frozen input already exists; do not regenerate existing benchmark")
    before = snapshot(root)
    write_json(HERE / "original_integrity.json", before)
    (HERE / "data/media").mkdir(parents=True, exist_ok=True)
    registry, ground_truth, private_mapping = {}, {}, {}
    for number, name in enumerate(FILENAMES, 1):
        source_id = f"SRC{number:02d}"
        original = root / "final_candidates_v1/clips" / name
        benchmark = root / f"477_modeling_benchmark_v1/media/asset_{number:02d}.mp4"
        if digest(original) != digest(benchmark):
            raise ValueError("original copy mismatch")
        copied = HERE / "data/media" / (source_id + ".mp4")
        shutil.copyfile(benchmark, copied)
        registry[source_id] = {"source_id": source_id, "path": copied.relative_to(HERE).as_posix(),
                               "sha256": digest(copied), **probe(copied)}
        ground_truth[source_id] = {"reviewer": None, "reviewed_at": None,
            "yolo": {"frames": [], "class_scope": ["person", "bicycle", "car", "motorcycle", "bus", "truck"],
                     "note": "No annotation files supplied; exhaustive box review required."},
            "clef": {"invoke_vlm": None, "reviewed": False, "rationale": None},
            "vlm": {"label": None, "reviewed": False, "reference_label": REFERENCES[number - 1],
                    "reference_note": "Candidate README observable-behavior description, not adjudicated ground truth."}}
        private_mapping[source_id] = {"candidate_filename": name, "event_group": "G05" if number >= 5 else f"G{number:02d}",
                                      "source_readme": "final_candidates_v1/README.md"}
    write_json(HERE / "data/sources.json", registry)
    write_json(HERE / "ground_truth/sources.json", ground_truth)
    write_json(HERE / "ground_truth/source_provenance.json", private_mapping)
    write_json(HERE / "schemas/vlm_output.schema.json", output_schema())
    items = []
    for i, combination in enumerate(COMBINATIONS, 1):
        source_ids = [f"SRC{n:02d}" for n in combination]
        items.append({"item_id": f"P{i:03d}", "sources": [{"source_id": s, "frame_count": n}
                      for s, n in zip(source_ids, allocations(len(source_ids)))],
                      "scenario_semantics": "independent_clip_bundle_per_source_assessment",
                      "same_incident_groups": [["SRC05", "SRC06"]] if {5, 6} <= set(combination) else [],
                      "synchronization": "not_established"})
    write_json(HERE / "items.json", {"version": "new477-total64-v1", "item_count": len(items), "items": items})
    shutil.copyfile(root / "runs/477-paid-budget.json", HERE / "budget_ledger.json")
    (HERE / "models").mkdir(exist_ok=True)
    shutil.copyfile(root / "artifacts/models/yolo26s.pt", HERE / "models/yolo26s.pt")
    prepare_frames(items, registry)
    locked = [HERE / "items.json", HERE / "data/sources.json", HERE / "prompts/pipeline_v1.txt",
              HERE / "schemas/vlm_output.schema.json", HERE / "models/yolo26s.pt"]
    locked += sorted((HERE / "data/media").glob("*.mp4"))
    locked += sorted((HERE / "data/frames").rglob("*.*"))
    lock = {p.relative_to(HERE).as_posix(): digest(p) for p in locked}
    write_json(HERE / "benchmark.lock.json", lock)
    if snapshot(root) != before:
        raise ValueError("protected original changed")
    print(json.dumps({"items": len(items), "frame_slots": len(items) * 64,
                      "original_unchanged": True, "paid_calls": 0}))

def prepare_frames(items, registry):
    for item in items:
        directory = HERE / "data/frames" / item["item_id"]
        directory.mkdir(parents=True, exist_ok=True)
        rows, decode_ms = [], 0.0
        for allocation in item["sources"]:
            source_id, count = allocation["source_id"], allocation["frame_count"]
            source = registry[source_id]
            numbers = indices(source["frame_count"], count)
            prefix = directory / source_id
            prefix.mkdir(exist_ok=True)
            select = "+".join(f"eq(n\\,{n})" for n in numbers)
            started = time.perf_counter()
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(HERE / source["path"]),
                            "-vf", "select=" + select, "-vsync", "0", "-threads", "1",
                            str(prefix / "%03d.png")], capture_output=True, check=True)
            decode_ms += (time.perf_counter() - started) * 1000
            images = sorted(prefix.glob("*.png"))
            if len(images) != count:
                raise ValueError("decoder frame count mismatch")
            for number, image in zip(numbers, images):
                rows.append({"frame_id": f"{source_id}-F{number:06d}", "source_id": source_id,
                             "frame_number": number, "timestamp_sec": number * source["fps_den"] / source["fps_num"],
                             "width": source["width"], "height": source["height"],
                             "image_path": image.relative_to(HERE).as_posix(), "sha256": digest(image)})
        write_json(directory / "manifest.json", {"item_id": item["item_id"], "sources": [s["source_id"] for s in item["sources"]],
                    "frames": rows, "preparation_decode_ms": decode_ms, "first_decode": True})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=HERE.parent)
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--freeze-evaluation", action="store_true")
    args = parser.parse_args()
    export(args.source_root)
    if args.freeze_evaluation:
        files = ["run.py", "pipeline477/contract.py", "pipeline477/metrics.py",
                 "pipeline477/execution.py", "pipeline477/budget.py", "pipeline477/io.py",
                 "schemas/ground_truth.schema.json"]
        write_json(HERE / "evaluation.lock.json", {f: digest(HERE / f) for f in files})
    if not args.export_only:
        freeze(args.source_root)

if __name__ == "__main__":
    main()

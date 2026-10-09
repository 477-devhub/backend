"""Export fixed public input and a separate evaluator reference; no secrets/API calls."""
import argparse
import csv
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(destination.read_bytes()).digest():
        if source.suffix == ".png":
            if destination.exists():
                raise ValueError("Unexpected nonmatching input export; inspect before replacing")
            os.link(source, destination)  # Byte-identical fixed read-only inputs; no duplicated storage.
        else:
            shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-archive", action="store_true", help="Optional full lossless archive; needs additional disk space")
    args = parser.parse_args()
    # MAIN exports the owned evaluator module only after focused tests/review.
    module = HERE.parent / "app/eval/team_benchmark.py"
    copy_file(module, HERE / "pipeline477/team_benchmark.py")
    from pipeline477.team_benchmark import template_rows
    from score import write_csv
    from pipeline477.contract import COLUMNS

    package = HERE / "team_benchmark_v1"
    package.mkdir(exist_ok=True)
    original_lock = json.loads((HERE / "benchmark.lock.json").read_text())
    allowed = {k: v for k, v in original_lock.items() if k.startswith("data/frames/") or
               k in {"items.json", "data/sources.json", "prompts/pipeline_v1.txt", "schemas/vlm_output.schema.json"}}
    for relative, expected in allowed.items():
        source = HERE / relative
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Public fixed input lock mismatch: " + relative)
        copy_file(source, package / relative)
    (package / "benchmark.lock.json").write_text(json.dumps(allowed, indent=2) + "\n", encoding="utf-8")
    for relative in ["score.py", "restore_inputs.py", "pipeline477/__init__.py", "pipeline477/contract.py", "pipeline477/metrics.py", "pipeline477/team_benchmark.py", "schemas/ground_truth.schema.json", "TEAM_CONTRACT.md"]:
        copy_file(HERE / relative, package / relative)
    copy_file(HERE / "TEAM_README.md", package / "README.md")
    (package / "requirements.txt").write_text("jsonschema>=4.23,<5\n", encoding="utf-8")
    rows = template_rows(package)
    columns = [key for key in COLUMNS if key not in {"ground_truth", "metrics"}]
    write_csv(package / "submission_template.csv", rows, columns)
    write_csv(HERE / "submission_template.csv", rows, columns)
    code_paths = ["score.py", "pipeline477/contract.py", "pipeline477/metrics.py", "pipeline477/team_benchmark.py", "schemas/ground_truth.schema.json"]
    (package / "scorer.lock.json").write_text(json.dumps({k: hashlib.sha256((package / k).read_bytes()).hexdigest() for k in code_paths}, indent=2) + "\n", encoding="utf-8")
    delivery = HERE / "deliverables"
    delivery.mkdir(exist_ok=True)
    public_zip = delivery / ("477_team_benchmark_v1.zip" if args.image_archive else "477_team_tools_v1.zip")
    canonical, aliases = {}, {}
    for relative, expected in allowed.items():
        if relative.endswith(".png"):
            if expected in canonical:
                aliases[relative] = canonical[expected]
            else:
                canonical[expected] = relative
    (package / "input_aliases.json").write_text(json.dumps(aliases, indent=2) + "\n", encoding="utf-8")
    needed = sum((package / relative).stat().st_size for relative in canonical.values()) + 200 * 1024 * 1024
    if args.image_archive and shutil.disk_usage(delivery).free < needed:
        raise OSError("Not enough space for delivery archive plus 200MiB execution reserve; ready folder remains usable")
    with zipfile.ZipFile(public_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
        for file in sorted(package.rglob("*")):
            if file.is_file() and not any(x in file.parts for x in ("__pycache__", "scores", "submissions", "ground_truth")):
                relative = str(file.relative_to(package)).replace("\\", "/")
                if not args.image_archive and relative.endswith(".png"):
                    continue
                if relative not in aliases:
                    archive.write(file, relative)
    review = HERE / "ground_truth/ai_review_v1"
    private_paths = list(json.loads((review / "ground_truth.lock.json").read_text())) + ["ground_truth/ai_review_v1/ground_truth.lock.json"]
    private_zip = delivery / "477_evaluator_reference_v1.zip"
    with zipfile.ZipFile(private_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in private_paths:
            archive.write(HERE / relative, relative)
    report = {"public_zip": str(public_zip), "public_bytes": public_zip.stat().st_size,
              "private_reference_zip": str(private_zip), "private_bytes": private_zip.stat().st_size,
              "fixed_public_lock_entries": len(allowed), "items": len(rows), "image_slots": 768,
              "unique_pngs": len(canonical), "lossless_aliases": len(aliases), "after_extract": "python restore_inputs.py",
              "archive_contains_images": args.image_archive,
              "complete_delivery_folder": str(package), "handoff": "Copy entire team_benchmark_v1 folder including data/frames; tools ZIP alone excludes images",
              "api_keys_included": False, "model_calls": 0,
              "warning": "Private evaluator reference is for scoring only, never model input."}
    (delivery / "package_manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

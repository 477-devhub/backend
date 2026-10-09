"""Remove generated export debris and deduplicate byte-identical NEW input copies."""
import hashlib
import json
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    lock = json.loads((HERE / "benchmark.lock.json").read_text())
    export = HERE / "team_benchmark_v1"
    removed = 0
    # Only files produced by failed export, backed by matching original lock.
    for relative, expected in lock.items():
        copy = export / relative
        if copy.exists() and copy.resolve().is_relative_to(export.resolve()) and not copy.is_symlink():
            if copy.stat().st_size == 0 or digest(copy) == expected:
                removed += copy.stat().st_size
                copy.unlink()
    canonical, deduplicated, recovered = {}, 0, 0
    for relative, expected in lock.items():
        if not relative.startswith("data/frames/") or not relative.endswith(".png"):
            continue
        path = HERE / relative
        if path.is_symlink() or not path.resolve().is_relative_to((HERE / "data/frames").resolve()) or digest(path) != expected:
            raise ValueError("Refusing input outside scope or changed since freeze")
        if expected not in canonical:
            canonical[expected] = path
            continue
        source = canonical[expected]
        if os.path.samefile(source, path):
            continue
        size = path.stat().st_size
        temporary = path.with_name(path.name + ".dedup-link")
        if temporary.exists():
            raise ValueError("Unexpected temporary link; preserve for inspection")
        os.link(source, temporary)
        if digest(temporary) != expected:
            temporary.unlink()
            raise ValueError("Byte preservation failed")
        os.replace(temporary, path)
        deduplicated += 1
        recovered += size
    if any(digest(HERE / k) != v for k, v in lock.items()):
        raise ValueError("Fixed input verification failed")
    report = {"removed_generated_export_bytes": removed, "deduplicated_identical_pngs": deduplicated,
              "recovered_duplicate_bytes": recovered, "fixed_hashes_unchanged": len(lock),
              "free_bytes": shutil.disk_usage(HERE).free,
              "scope": "Only MAIN-created new_477_piprline copies; protected original folders/runs not modified"}
    (HERE / "storage_recovery_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

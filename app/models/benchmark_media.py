"""Read-only bridge to the unchanged public canonical loader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import sys
from app.schemas.benchmark import BenchmarkInput, CanonicalFrame


def snapshot_protected(root: Path):
    root = Path(root).resolve()
    snapshot = {}
    for name in ("477_modeling_benchmark_v1", "final_candidates_v1", "data", "media"):
        directory = root / name
        if not directory.exists():
            continue
        for file in sorted(directory.rglob("*")):
            if file.is_file():
                h = hashlib.sha256()
                with file.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(block)
                snapshot[file.relative_to(root).as_posix()] = {
                    "size_bytes": file.stat().st_size, "sha256": h.hexdigest()}
    return snapshot


def assert_output_outside_inputs(root: Path, output: Path):
    root, output = Path(root).resolve(), Path(output).resolve()
    for name in ("477_modeling_benchmark_v1", "final_candidates_v1", "data", "media"):
        protected = (root / name).resolve()
        if output == protected or output.is_relative_to(protected):
            raise ValueError("output must be outside protected input directories")
    if not output.is_relative_to(root) or output == root:
        raise ValueError("output must be a dedicated workspace directory")
    return output


def canonical_loader(package: Path):
    path = Path(package).resolve() / "scripts" / "load_model_input.py"
    spec = importlib.util.spec_from_file_location("_477_frozen_input_loader", path)
    if spec is None or spec.loader is None:
        raise ValueError("canonical loader unavailable")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def load_benchmark_input(package: Path, item_id: str):
    started = time.perf_counter()
    loader = canonical_loader(package)
    item = loader.load_item(item_id)
    frames = tuple(CanonicalFrame(**frame) for frame in loader.iter_model_frames(item_id))
    request = BenchmarkInput(item_id=item_id, task=item["task"], prompt=item["prompt"],
        schema_json=json.dumps(item["response_schema"], ensure_ascii=False, separators=(",", ":")),
        fingerprint_json=json.dumps(item["input_fingerprint"], sort_keys=True, separators=(",", ":")),
        frames=frames)
    return request, (time.perf_counter() - started) * 1000

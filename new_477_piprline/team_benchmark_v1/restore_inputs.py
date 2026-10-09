"""Restore identical image aliases omitted from the lossless delivery archive."""
import hashlib
import json
import os
import shutil
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    aliases = json.loads((root / "input_aliases.json").read_text())
    lock = json.loads((root / "benchmark.lock.json").read_text())
    for destination, original in aliases.items():
        target, source = root / destination, root / original
        if not all(p.resolve().is_relative_to(root.resolve()) for p in (target, source)):
            raise ValueError("Alias path escapes package")
        if lock[destination] != lock[original] or hashlib.sha256(source.read_bytes()).hexdigest() != lock[original]:
            raise ValueError("Alias hash mismatch")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != lock[destination]:
            raise ValueError("Existing input differs from frozen image")
    print(json.dumps({"restored_aliases": len(aliases), "input_bytes_changed": False, "model_calls": 0}))


if __name__ == "__main__":
    main()

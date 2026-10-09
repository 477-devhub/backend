"""Persist real verification after every check so interrupted tool calls lose no evidence."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "handoffs/ground_truth_validation.json"
    code_paths = ["app/models/adapters/annotation_detector.py", "app/eval/team_benchmark.py",
                  "new_477_piprline/score.py", "new_477_piprline/run_review_experiment.py"]
    report = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "checks": [],
              "code_hashes": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in code_paths}}
    commands = [(ROOT, ["-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
                (ROOT, ["-B", "scripts/check_contracts.py"]),
                (ROOT / "new_477_piprline", ["-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"])]
    for cwd, args in commands:
        result = subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=300)
        report["checks"].append({"cwd": str(cwd), "command": [str(Path(sys.executable)), *args],
                                  "exit_code": result.returncode,
                                  "stdout_tail": result.stdout[-3000:], "stderr_tail": result.stderr[-1000:]})
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"check": args, "exit_code": result.returncode}), flush=True)
        if result.returncode:
            return result.returncode
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["all_checks_passed"] = True
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

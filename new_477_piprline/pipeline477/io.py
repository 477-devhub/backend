"""Artifacts must stay neutral and secret-free; API payloads remain separate from CSV."""
import json
import os
from pathlib import Path

def scrub(value):
    secrets = [v for k, v in os.environ.items()
               if any(s in k.upper() for s in ("TOKEN", "API_KEY", "AUTH", "SECRET")) and len(v) >= 6]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if any(s in k.lower() for s in ("authorization", "api_key", "auth_token"))
                    else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
    return value

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scrub(data), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def load_env(path):
    """Local dotenv reader; values never enter artifacts. Existing process env wins."""
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.replace("_", "").isalnum():
            os.environ.setdefault(key, value.strip().strip("\"'"))

import hashlib
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
lock=json.loads((R/'docs/contracts.lock.json').read_text())
changed=[name for name,h in lock.items() if not (R/name).is_file() or hashlib.sha256((R/name).read_bytes()).hexdigest()!=h]
if changed:raise SystemExit('Frozen contracts changed: '+', '.join(changed))
print('Frozen contracts match.')

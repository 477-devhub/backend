import hashlib
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1]
paths=sorted([*R.glob('app/schemas/*.py'),R/'app/models/base.py',R/'app/models/execution.py',R/'app/models/registry.py',R/'app/models/media.py',
    R/'app/models/budget.py',
    R/'app/models/benchmark_media.py',
    R/'app/models/benchmark_assessment.py',
    R/'app/repositories/protocol.py',R/'app/config.py',R/'docs/model-contract.md',R/'docs/api-contract.md',
    R/'docs/dataset-handoff.md',R/'docs/evaluation-contract.md'])
value={p.relative_to(R).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
(R/'docs/contracts.lock.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
print('Contract hashes written; MAIN must review and commit this change.')

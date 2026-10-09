import argparse
import hashlib
import json
from pathlib import Path
from app.eval.dataset import validate_manifest
p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--run-config',required=True);p.add_argument('--output',required=True)
a=p.parse_args();m=Path(a.manifest);c=Path(a.run_config);o=Path(a.output)
validate_manifest(m)
if o.exists():raise SystemExit('Refusing to overwrite an existing dataset lock')
v={'manifest_sha256':hashlib.sha256(m.read_bytes()).hexdigest(),'run_config_sha256':hashlib.sha256(c.read_bytes()).hexdigest()}
o.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8');print('Dataset/run config locked.')

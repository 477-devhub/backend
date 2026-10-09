"""Local helpers; no benchmark paths or environment-file discovery."""
import hashlib,json,math,os
from pathlib import Path
EXP_ROOT=Path(__file__).resolve().parent
P1_QUESTIONS_CONFIG=EXP_ROOT/'decisions_questions_v1.json'
P4_PROMPT=EXP_ROOT/'visual_prompt_v1.txt'
SCHEMA_DIR=EXP_ROOT/'schemas'
def canonical_json(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def sha256_bytes(b):return hashlib.sha256(b).hexdigest()
def sha256_file(p):return sha256_bytes(Path(p).read_bytes())
def norm_float(v,digits=4):
 if v is None:return None
 v=float(v)
 return (round(v,digits) or 0.0) if math.isfinite(v) else None
rnd=norm_float
def clip01(v):return max(0.,min(1.,float(v)))
def reliability_label(v,cfg):return 'unknown' if v is None else 'high' if v>=cfg['high'] else 'medium' if v>=cfg['medium'] else 'low'
def read_allowed_json(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def read_allowed_text(p):return Path(p).read_text(encoding='utf-8')
def load_api_key_env():return bool(os.environ.get('OPENAI_API_KEY'))
def redact(s):return 'provider_error'

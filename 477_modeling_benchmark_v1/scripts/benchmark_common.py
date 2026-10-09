import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.stdout.reconfigure(encoding='utf-8')
def unique_pairs(pairs):
 out={}
 for key,value in pairs:
  if key in out:raise ValueError('Duplicate JSON key: '+key)
  out[key]=value
 return out
def invalid_constant(value):raise ValueError('Invalid JSON numeric constant: '+value)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'),object_pairs_hook=unique_pairs,parse_constant=invalid_constant)
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def probe(p):
 d=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)],encoding='utf-8'))
 v=next(s for s in d['streams'] if s['codec_type']=='video');a,b=map(int,v['avg_frame_rate'].split('/'))
 return {'duration':float(v.get('duration',d['format']['duration'])),'fps':a/b,'width':v['width'],'height':v['height'],'codec':v['codec_name'],'pixel_format':v['pix_fmt'],'frame_count':int(v['nb_frames']) if v.get('nb_frames','N/A')!='N/A' else None,'audio_streams':sum(s['codec_type']=='audio' for s in d['streams']),'format_tags':d['format'].get('tags',{})}
def safe(root,relative):
 p=(Path(root)/relative).resolve()
 if not p.is_relative_to(Path(root).resolve()):raise ValueError('Path escapes benchmark')
 return p

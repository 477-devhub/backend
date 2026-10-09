"""Bounded process entry point. SDKs and CV never run on the API event loop."""
import json,sys,subprocess,math,hashlib,io,base64
from pathlib import Path

def prepare(p):
 from PIL import Image
 clip=str(Path(p['work_dir'])/'clip.mp4')
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time,width,height','-of','json',clip],stderr=subprocess.DEVNULL,timeout=90))['frames']
 if len(probe)>2000000:raise ValueError('frame_budget')
 available=[(i,f) for i,f in enumerate(probe) if p['start_ms']<=float(f['best_effort_timestamp_time'])*1000<=p['end_ms']]
 if len(available)<64:raise ValueError('too_few_frames')
 schedule=[available[int(math.floor(j*(len(available)-1)/63+.5))] for j in range(64)]
 indices=[i for i,f in schedule];first=schedule[0][1];w,h=first['width'],first['height']
 if w*h>1920*1080 or any((f['width'],f['height'])!=(w,h) for i,f in schedule):raise ValueError('resolution_budget')
 expression='+'.join('eq(n,%d)'%i for i in indices)
 raw=subprocess.check_output(['ffmpeg','-v','error','-nostdin','-protocol_whitelist','file,pipe','-threads','1','-i',clip,'-vf',"select='"+expression+"'",'-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stderr=subprocess.DEVNULL,timeout=90)
 size=w*h*3
 if len(raw)!=64*size:raise ValueError('decode_count')
 from concurrent.futures import ThreadPoolExecutor
 def encode(item):
  j,(i,f)=item
  rgb=raw[j*size:(j+1)*size];im=Image.frombytes('RGB',(w,h),rgb);buf=io.BytesIO();im.save(buf,format='WEBP',lossless=True,quality=50,method=2)
  if Image.open(io.BytesIO(buf.getvalue())).convert('RGB').tobytes()!=rgb:raise ValueError('roundtrip')
  ref=f'F{j+1:03d}';(Path(p['work_dir'])/(ref+'.webp')).write_bytes(buf.getvalue())
  return {'ref':ref,'timestamp_ms':round(float(f['best_effort_timestamp_time'])*1000),'rgb_sha256':hashlib.sha256(rgb).hexdigest()}
 with ThreadPoolExecutor(max_workers=16) as pool:frames=list(pool.map(encode,enumerate(schedule)))
 return {'frames':frames,'frame_numbers':indices,'ffmpeg_version':subprocess.check_output(['ffmpeg','-version']).decode().splitlines()[0]}

def cv(p):
 import yaml,numpy as np
 from PIL import Image
 from .frozen_v1.pose_detector import PoseDetector
 from .frozen_v1.sparse_tracker import SparseTracker
 from .frozen_v1.feature_extractor import CameraFeatureExtractor
 cfg=yaml.safe_load((Path(__file__).parent/'frozen_v1/cv_state_v1.yaml').read_text(encoding='utf-8'));cfg['model']['weights']=p['weights_path']
 expected=json.loads((Path(__file__).parent/'frozen_v1/provenance.json').read_text(encoding='utf-8'))['weights']['sha256']
 if hashlib.sha256(Path(p['weights_path']).read_bytes()).hexdigest()!=expected:raise ValueError('weights_hash_mismatch')
 detector=PoseDetector(cfg);warmup_ms=detector.warmup()
 arrays=[np.asarray(Image.open(Path(p['work_dir'])/(f['ref']+'.webp')).convert('RGB')) for f in p['frames']]
 detections=detector.detect(arrays)
 for j,(d,f) in enumerate(zip(detections,p['frames'])):d.update(index=j,timestamp_sec=f['timestamp_sec'],frame_number=p['frame_numbers'][j])
 tracks=SparseTracker(cfg).run(detections);camera=CameraFeatureExtractor(cfg).extract('CAM_01',detections,tracks)
 return {'state':{'state_version':cfg['state_version'],'generator':{'layer':'shared_cheap_cv','cv_model':detector.info,'load_ms':detector.load_ms,'warmup_ms':warmup_ms,'cv_config_sha256':hashlib.sha256((Path(__file__).parent/'frozen_v1/cv_state_v1.yaml').read_bytes()).hexdigest()},'input':{'task':'single'},'cameras':[camera],'cross_camera':None}}

def p1(p):
 import yaml
 from .frozen_v1.compact_serializer import CompactSerializer
 from .frozen_v1.decisions_client import DecisionsClient,build_questions
 from .frozen_v1 import decisions_client
 decisions_client.MAX_RETRIES=p.get('max_retries',2)
 root=Path(__file__).parent/'frozen_v1';q=json.loads((root/'decisions_questions_v1.json').read_text(encoding='utf-8'));serializer=CompactSerializer(yaml.safe_load((root/'compact_state_v1.yaml').read_text(encoding='utf-8')))
 compact=serializer.serialize(p['state']);text=serializer.model_input_text(compact);questions=build_questions('single',['CAM_01'],q)
 if p.get('request_budget_usd') and len((text+json.dumps(questions,ensure_ascii=False)).encode('utf-8'))>128*1024:return {'status':'budget_exceeded','attempt_count':0}
 result=DecisionsClient().decide(text,questions)
 for key in ('response_body','errors','errors_before_success'):result.pop(key,None)
 return result

def p4(p):
 import jsonschema
 from .frozen_v1.visual_prompt_builder import VisualPromptBuilder
 from .frozen_v1.openai_client import ResponsesClient
 from .frozen_v1 import openai_client
 openai_client.MAX_RETRIES=p.get('max_retries',2)
 builder=VisualPromptBuilder();frames=p['frames'];urls=['data:image/webp;base64,'+base64.b64encode((Path(p['work_dir'])/(f['ref']+'.webp')).read_bytes()).decode() for f in frames]
 content=builder.content('single',['CAM_01'],frames,urls,'high');text_format=builder.text_format('single',['CAM_01'],frames);client=ResponsesClient()
 if p.get('request_budget_usd'):
  budget=float(p['request_budget_usd'])
  if not math.isfinite(budget) or budget<=0:raise ValueError('invalid_budget')
  # Official token count is a preflight, not a second inference request.
  count=client.client.responses.input_tokens.count(model=openai_client.MODEL,input=[{'role':'user','content':content}],reasoning={'effort':'high'},text={'format':text_format})
  tokens=count.input_tokens
  ceiling=(tokens*(5 if tokens>272000 else 2.5)+32000*(15 if tokens>272000 else 10))/1e6*1.1
  if ceiling>budget:return {'status':'budget_exceeded','attempt_count':0,'preflight_input_tokens':tokens,'upper_cost_usd':ceiling}
  openai_client.MAX_RETRIES=0
 result=client.decide(content,text_format)
 if result['status']=='ok':
  try:jsonschema.validate(result['parsed'],builder.output_schema('single',['CAM_01'],frames))
  except jsonschema.ValidationError:
   result['status']='schema_or_frame_ref_failure';result['error_code']='schema_or_frame_ref_failure';result.pop('parsed',None)
 # Credentials, request payloads and provider error text are never returned/logged.
 result.pop('response_body',None);result.pop('errors_before_success',None);result.pop('errors',None);result.pop('refusal',None)
 return result

if __name__=='__main__':
 stage,request,result=sys.argv[1:];payload=json.loads(Path(request).read_text(encoding='utf-8'))
 try:
  frozen_root=Path(__file__).parent/'frozen_v1';manifest=json.loads((frozen_root/'provenance.json').read_text(encoding='utf-8'))
  for record in manifest['files']:
   if hashlib.sha256((frozen_root/record['ported']).read_bytes()).hexdigest()!=record['ported_sha256']:raise ValueError('frozen_artifact_hash_mismatch')
  output=globals()[stage](payload)
 except Exception as exc:output={'status':'failed','error_code':stage+'_worker_error','error_type':type(exc).__name__}
 Path(result).write_text(json.dumps(output,allow_nan=False),encoding='utf-8')

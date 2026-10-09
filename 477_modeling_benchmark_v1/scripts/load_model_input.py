# This loader has no private-data imports or private paths. It only reads four public artifacts and media.
import json,math,hashlib,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
def unique_pairs(pairs):
 out={}
 for key,value in pairs:
  if key in out:raise ValueError('Duplicate JSON key: '+key)
  out[key]=value
 return out
def invalid_constant(value):raise ValueError('Invalid JSON numeric constant: '+value)
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_pairs,parse_constant=invalid_constant)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load_item(item_id):
 manifest=read(ROOT/'public_manifest.json');scenarios=read(ROOT/'model_input/scenarios.json')
 if set(scenarios)!={'benchmark_version','protocol','items'}:raise ValueError('Unexpected public keys')
 item=next(x for x in scenarios['items'] if x['item_id']==item_id)
 if set(item)!={'item_id','task','cameras'}:raise ValueError('Unexpected item keys')
 media=manifest['media'];frames={};handles=[];hashes={};ncam=len(item['cameras']);base=64//ncam;remainder=64%ncam
 for i,c in enumerate(item['cameras']):
  if set(c)!={'camera','asset'} or c['camera'] not in ['CAM_01','CAM_02','CAM_03']:raise ValueError('Unexpected camera keys')
  asset=c['asset'];meta=media[asset];p=(ROOT/meta['path']).resolve()
  if not p.is_relative_to((ROOT/'media').resolve()) or not p.name.startswith('asset_'):raise ValueError('Unsafe media path')
  count=base+(i<remainder);last=meta['frame_count']-1
  indices=[int(math.floor(j*last/(count-1)+.5)) for j in range(count)]
  frames[c['camera']]=indices;hashes[c['camera']]=meta['sha256'];handles.append({'camera':c['camera'],'local_path':str(p),'upload_name':c['camera']+'.mp4','frame_numbers':indices,'frame_timestamps_sec':[n/meta['fps'] for n in indices]})
 pred=read(ROOT/'schemas/prediction.schema.json');branch={'single':'single','attention':'attention','multi_camera':'multi'}[item['task']]
 response_schema={**pred['$defs'][branch],'$defs':pred['$defs'],'$schema':pred['$schema']}
 return {'item_id':item_id,'task':item['task'],'prompt':(ROOT/'model_input/prompt_v1.txt').read_text(encoding='utf-8'),'response_schema':response_schema,'media_handles_private_to_harness':handles,'input_fingerprint':{'prompt_sha256':digest(ROOT/'model_input/prompt_v1.txt'),'prediction_schema_sha256':digest(ROOT/'schemas/prediction.schema.json'),'media_sha256':hashes,'sampling_protocol_id':'uniform_total64_v1','frame_numbers':frames}}
# Harness uses uniform frames from media_handles; only pixels, camera ID, neutral relative times and common prompt/task/schema are sent. Paths and item IDs are not prompt text.
def iter_model_frames(item_id):
 """Yield only RGB pixels, generic camera ID and neutral clip-relative time. No file writes or API/model calls."""
 item=load_item(item_id);frame_size=1920*1080*3
 for handle in item['media_handles_private_to_harness']:
  indices=handle['frame_numbers'];expression='+'.join('eq(n,%d)'%n for n in indices)
  command=['ffmpeg','-v','error','-nostdin','-i',handle['local_path'],'-vf',"select='"+expression+"'",'-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1']
  process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
  try:
   for number,timestamp in zip(indices,handle['frame_timestamps_sec']):
    chunks=[];remaining=frame_size
    while remaining:
     block=process.stdout.read(remaining)
     if not block:raise RuntimeError('Uniform frame decoding truncated')
     chunks.append(block);remaining-=len(block)
    yield {'camera':handle['camera'],'timestamp_sec':timestamp,'width':1920,'height':1080,'rgb24':b''.join(chunks)}
   if process.stdout.read(1):raise RuntimeError('Unexpected extra decoded frame')
   if process.wait()!=0:raise RuntimeError('Uniform frame decoding failed')
  finally:
   process.stdout.close()
   if process.poll() is None:process.terminate()
   process.wait()
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('item_id');a=p.parse_args();sys.stdout.reconfigure(encoding='utf-8');print(json.dumps(load_item(a.item_id),ensure_ascii=False,indent=2))

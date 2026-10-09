from benchmark_common import *
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from load_model_input import load_item

def schemas():
 p=read(ROOT/'schemas/prediction.schema.json');r=read(ROOT/'schemas/result.schema.json');reg=Registry().with_resource(p['$id'],Resource.from_contents(p)).with_resource(r['$id'],Resource.from_contents(r))
 return p,r,reg

def observations_check(pred,cameras,durations):
 obs=pred['observations']
 for x in obs:
  if x['camera'] not in cameras:raise ValueError('Unknown observation camera')
  if x['timestamp_sec']>durations[x['camera']]+1/30:raise ValueError('Observation time beyond clip')

def validate(pred,item_id):
 json.dumps(pred,allow_nan=False)
 p,_,reg=schemas();item=load_item(item_id);branch={'single':'single','attention':'attention','multi_camera':'multi'}[item['task']]
 Draft202012Validator({'$ref':p['$id']+'#/$defs/'+branch},registry=reg).validate(pred)
 cams=[h['camera'] for h in item['media_handles_private_to_harness']];durations={h['camera']:probe(h['local_path'])['duration'] for h in item['media_handles_private_to_harness']}
 if item['task']=='attention':
  if set(x['camera'] for x in pred['assessments'])!=set(cams):raise ValueError('Assess each camera exactly once')
  if set(x['camera'] for x in pred['attention_queue'])!=set(cams) or {x['rank'] for x in pred['attention_queue']}!={1,2,3}:raise ValueError('Rank all three cameras exactly once with unique ranks')
  for row in pred['assessments']:observations_check(row['assessment'],[row['camera']],durations)
 else:
  observations_check(pred,cams,durations)
  if item['task']=='multi_camera':
   if set(pred['camera_evidence'])!=set(cams):raise ValueError('Evidence keys must match input cameras')
   for camera,obs in pred['camera_evidence'].items():
    for x in obs:
     if x['camera']!=camera:raise ValueError('Evidence attribution mismatch')
    observations_check({'observations':obs},[camera],durations)
 return True

def validate_result(result):
 json.dumps(result,allow_nan=False)
 _,r,reg=schemas();Draft202012Validator(r,registry=reg).validate(result);validate(result['prediction'],result['item_id'])
 if result['input_fingerprint']!=load_item(result['item_id'])['input_fingerprint']:raise ValueError('Input protocol/hash mismatch')
 return True
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('path',type=Path);p.add_argument('--item');p.add_argument('--result',action='store_true');a=p.parse_args()
 try:
  data=read(a.path)
  if a.result:validate_result(data)
  elif a.item:validate(data,a.item)
  else:p.error('--item required for prediction')
  print('Schema and context validation: PASS')
 except Exception as e:print(str(e),file=sys.stderr);raise SystemExit(1)

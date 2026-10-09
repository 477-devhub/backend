"""Frozen Cheap CV -> Decisions -> visual cascade; default is shadow routing."""
import asyncio,sys,math,json,os
from pathlib import Path
from time import perf_counter
from app.models.base import ModelAdapter
from app.schemas.model import ModelInput,ModelAssessment,ModelMetadata,RoutingAssessment,StageRecord
from .assessment_mapper import decision_from_answers,guards,map_decision,visual_decision
from .cascade_media import run_worker

class CascadeV1Adapter(ModelAdapter):
 name='cascade_v1'
 def __init__(self,resolver=None,*,python_executable=None,cv_python_executable=None,weights_path=None,mode='shadow',cv_timeout_sec=180,p1_timeout_sec=150,p4_timeout_sec=900,max_concurrency=1,progress=None,stage_runner=None):
  if mode not in ('shadow','frozen_cascade_v1'):raise ValueError('invalid cascade mode')
  if type(max_concurrency)is not int or max_concurrency<1 or max_concurrency>4:raise ValueError('invalid concurrency')
  for value in (cv_timeout_sec,p1_timeout_sec,p4_timeout_sec):
   if not math.isfinite(value) or value<=0:raise ValueError('invalid timeout')
  self.cv_python_executable=cv_python_executable;self.resolver=resolver;self.python_executable=python_executable or sys.executable;self.weights_path=str(weights_path) if weights_path else None;self.mode=mode
  self.timeouts={'cv':cv_timeout_sec,'p1':p1_timeout_sec,'p4':p4_timeout_sec};self.progress=progress;self.runner=stage_runner or run_worker;self.max_retries=int(os.environ.get('AI_MAX_RETRIES','2'))
  if not 0<=self.max_retries<=2:raise ValueError('invalid retries')
  self.diagnostics={}
  self._semaphore=asyncio.Semaphore(max_concurrency);self._max_concurrency=max_concurrency
 def with_resolver(self,resolver,*,progress=None):
  clone=type(self)(resolver,python_executable=self.python_executable,cv_python_executable=self.cv_python_executable,weights_path=self.weights_path,mode=self.mode,cv_timeout_sec=self.timeouts['cv'],p1_timeout_sec=self.timeouts['p1'],p4_timeout_sec=self.timeouts['p4'],max_concurrency=self._max_concurrency,progress=progress or self.progress,stage_runner=self.runner)
  clone._semaphore=self._semaphore
  return clone
 async def _stage(self,stage,payload,trace):
  if self.progress:await self.progress(stage)
  started=perf_counter()
  try:
   payload=dict(payload,max_retries=self.max_retries,request_budget_usd=os.environ.get('AI_REQUEST_BUDGET_USD'))
   response=await self.runner(stage,payload,python_executable=(self.cv_python_executable or self.python_executable) if stage=='cv' else self.python_executable,timeout_sec=self.timeouts[stage])
   usage=response.get('usage') or {};cost=None
   if usage.get('input_tokens') is not None:
    n=usage['input_tokens'];out=usage.get('output_tokens',0)
    if stage=='p1':cost=n*.1*(2 if n>272000 else 1)/1e6
    elif stage=='p4':
     det=usage.get('input_tokens_details') or {};cached=det.get('cached_tokens') or 0;write=det.get('cache_write_tokens') or 0
     cost=((n-cached-write)*2+cached*.1+write*2.5)*(2 if n>272000 else 1)/1e6+out*10*(1.5 if n>272000 else 1)/1e6
   ok=response.get('status','ok')=='ok'
   trace.append(StageRecord(stage=stage,status='ok' if ok else 'failed',latency_ms=(perf_counter()-started)*1000,attempts=response.get('attempt_count',1+response.get('retry_count',0)),input_tokens=usage.get('input_tokens'),output_tokens=usage.get('output_tokens'),estimated_cost_usd=cost,request_id=response.get('request_id')))
   if not ok:raise ValueError('provider_failed')
   return response
  except asyncio.CancelledError:
   trace.append(StageRecord(stage=stage,status='failed',latency_ms=(perf_counter()-started)*1000,attempts=1))
   raise
  except Exception:
   if not trace or trace[-1].stage!=stage:trace.append(StageRecord(stage=stage,status='failed',latency_ms=(perf_counter()-started)*1000,attempts=1))
   raise
 def _failure(self,stage,trace,started):
  return ModelAssessment(event_type='uncertain',event_confidence=0,risk_axes=None,needs_human_review=True,uncertainty_reason=stage+'_failed',metadata=ModelMetadata(adapter=self.name,model='frozen-cascade-v1',error_code=stage+'_error',latency_ms=(perf_counter()-started)*1000,stage_trace=trace),routing=RoutingAssessment(mode=self.mode,selected_stage='fallback'))
 async def evaluate(self,model_input):
  async with self._semaphore:return await self._evaluate(model_input)
 async def _evaluate(self,model_input):
  started=perf_counter();trace=[];self.failure_trace=trace;mi=ModelInput.model_validate(model_input.model_dump());frames=[];assets={}
  if self.resolver is None or len(mi.evidence)!=64 or not self.weights_path:return self._failure('configuration',trace,started)
  try:
   for i,e in enumerate(mi.evidence):
    if e.frame_id!=f'F{i+1:03d}':raise ValueError('invalid_frame_schedule')
    # Both provider prompts use neutral camera id and window-relative actual PTS.
    frames.append({'ref':e.frame_id,'camera':'CAM_01','timestamp_sec':(e.timestamp_ms-mi.window.start_ms)/1000})
    assets[e.frame_id+'.webp']=await asyncio.to_thread(self.resolver.read,e.media_ref,max_bytes=8*1024*1024)
   profile_ref=mi.sample_id+':AI_PROFILE'
   frame_numbers=json.loads(self.resolver.read(profile_ref,max_bytes=4096))['frame_numbers']
   if len(frame_numbers)!=64 or len(set(frame_numbers))!=64 or any(type(n)is not int or n<0 for n in frame_numbers) or frame_numbers!=sorted(frame_numbers):raise ValueError('invalid_prepared_profile')
   payload={'frames':frames,'frame_numbers':frame_numbers,'_assets':assets,'weights_path':self.weights_path}
   cv=await self._stage('cv',payload,trace)
   self.diagnostics['cv']={'generator':cv['state'].get('generator'),'frame_numbers':frame_numbers}
  except asyncio.CancelledError:raise
  except Exception:return self._failure('cv',trace,started)
  d=None
  try:
   result=await self._stage('p1',{'state':cv['state']},trace)
   d=decision_from_answers(result['answers'])
   self.diagnostics['p1']={'raw_answers':result['answers'],'frozen_decision':d,'guards':guards(d)}
  except asyncio.CancelledError:raise
  except Exception:
   if trace and trace[-1].stage=='p1' and trace[-1].status=='ok':trace[-1]=trace[-1].model_copy(update={'status':'failed'})
  if d and self.mode=='frozen_cascade_v1' and all(guards(d)):
   trace.append(StageRecord(stage='p4',status='skipped'))
   return map_decision(d,mode=self.mode,stage='p1',trace=trace,latency_ms=(perf_counter()-started)*1000)
  try:
   result=await self._stage('p4',payload,trace);mapping_started=perf_counter();final,visual=visual_decision(result['parsed'],frames)
   from .frozen_v1.common_adapter_v2 import CommonAdapterV2
   self.diagnostics['p4']={'raw_visual':result['parsed'],'frozen_decision':final,'normalized_decision':CommonAdapterV2().reconcile(final)}
   trace.append(StageRecord(stage='map',status='ok',attempts=1,latency_ms=(perf_counter()-mapping_started)*1000))
   return map_decision(final,mode=self.mode,stage='p4',trace=trace,visual=visual,p1_decision=d,latency_ms=(perf_counter()-started)*1000)
  except asyncio.CancelledError:raise
  except Exception:
   if trace and trace[-1].stage=='p4' and trace[-1].status=='ok':trace[-1]=trace[-1].model_copy(update={'status':'failed'})
   return self._failure('p4',trace,started)


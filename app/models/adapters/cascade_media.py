"""Native-resolution uniform index sampler with actual PTS and lossless transport."""
import asyncio,hashlib,math,sys,tempfile,json,os,signal
from pathlib import Path
from time import perf_counter
from app.models.adapters.ingestion import PreparedMedia,IngestionError
from app.schemas.model import ModelInput,EvidenceFrame,TemporalState

async def run_worker(stage,payload,*,python_executable=None,timeout_sec=120):
 with tempfile.TemporaryDirectory(prefix='477-ai-') as directory:
  root=Path(directory); request=root/'request.json';result=root/'result.json'
  payload=dict(payload);payload['work_dir']=str(root)
  # Assets are local-only IPC and never provider text.
  blobs=payload.pop('_assets',{})
  for name,blob in blobs.items(): (root/name).write_bytes(blob)
  request.write_text(json.dumps(payload,allow_nan=False),encoding='utf-8')
  proc=await asyncio.create_subprocess_exec(str(python_executable or sys.executable),'-m','app.models.adapters.cascade_worker',stage,str(request),str(result),cwd=str(Path(__file__).resolve().parents[3]),stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,**({'start_new_session':True} if os.name!='nt' else {}))
  try:
   await asyncio.wait_for(proc.wait(),timeout_sec)
   if proc.returncode or not result.is_file():raise ValueError('worker_failed')
   record=json.loads(result.read_text(encoding='utf-8'))
   if stage=='prepare' and record.get('status')=='failed':raise ValueError(record.get('error_code','worker_failed'))
   if stage=='prepare':
    record['_assets']={f['ref']:(root/(f['ref']+'.webp')).read_bytes() for f in record['frames']}
   return record
  finally:
   if proc.returncode is None:
    if os.name=='nt':
     killer=await asyncio.create_subprocess_exec('taskkill','/PID',str(proc.pid),'/T','/F',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
     await killer.wait()
     if proc.returncode is None:proc.kill()
    else:
     try:os.killpg(proc.pid,signal.SIGKILL)
     except ProcessLookupError:pass
    await proc.wait()

async def prepare_frozen_input(model_input,resolver,*,python_executable=None,timeout_sec=120):
 started=perf_counter();mi=ModelInput.model_validate(model_input.model_dump())
 if not mi.clip_ref:raise IngestionError('clip_ref is required')
 try:
  clip=await asyncio.to_thread(resolver.read,mi.clip_ref,max_bytes=64*1024*1024)
  record=await run_worker('prepare',{'start_ms':mi.window.start_ms,'end_ms':mi.window.end_ms,'_assets':{'clip.mp4':clip}},python_executable=python_executable,timeout_sec=timeout_sec)
  assets={mi.sample_id+':AI_PROFILE':json.dumps({'frame_numbers':record['frame_numbers']}).encode()};evidence=[]
  for f in record['frames']:
   token=mi.sample_id+':'+f['ref'];assets[token]=record['_assets'][f['ref']]
   if len(assets[token])>8*1024*1024:raise IngestionError('frame byte budget exceeded')
   evidence.append(EvidenceFrame(frame_id=f['ref'],timestamp_ms=f['timestamp_ms'],media_ref=token))
  prepared=mi.model_copy(update={'evidence':evidence,'temporal_state':TemporalState()})
  return PreparedMedia(model_input=prepared,resolver=resolver.with_assets(assets),clip_sha256=hashlib.sha256(clip).hexdigest(),frame_sha256={f['ref']:f['rgb_sha256'] for f in record['frames']},extractor_version='ai-frozen-uniform64-pts-v1',ffmpeg_version=record['ffmpeg_version'],profile={'profile_id':'ai_frozen_v1','frame_protocol':'uniform_total64_v1','actual_frame_count':64,'native_resolution':True,'image_format':'lossless_webp','timestamp_reference':'source_pts_ms','window_offset_ms':mi.window.start_ms,'frame_numbers':record['frame_numbers'],'parity_note':'index schedule and RGB retained; actual PTS replaces benchmark fps-derived timestamps'},preprocessing_ms=(perf_counter()-started)*1000)
 except asyncio.CancelledError:raise
 except Exception:raise IngestionError('frozen media preprocessing failed') from None

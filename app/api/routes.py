import asyncio
import json
from pathlib import Path
from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from app.api.contracts import API_CONTRACT_VERSION, CameraState, ServerStatus, SnapshotEnvelope, ClipMetadata, PipelineStats
from app.api.media import clip_metadata, frame_asset, present_incident, video_response
from pydantic import Field
from app.schemas.model import ContractModel
from app.schemas.incident import AckBody, Incident
router = APIRouter()

def state(request): return request.app.state

@router.get("/api/status", response_model=ServerStatus)
async def status(request: Request):
    s=state(request); snap=s.store.snapshot()
    return {"ok":True,"mode":s.settings.mode,"system_status":"demo" if s.settings.mode=="demo" else "unconfigured",
        "timestamp":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
        "active_count":snap["active_count"],"total_cameras":477,"configured_cameras":len(s.store.cameras),"revision":snap["revision"],
        "server_instance_id":s.store.server_instance_id,"api_contract_version":API_CONTRACT_VERSION,
        "target_camera_capacity":477,"observed_cameras":snap["observed_cameras"],"is_demo":s.settings.mode=="demo"}

@router.get("/api/cameras", response_model=list[CameraState])
async def cameras(request: Request): return state(request).store.camera_states()

@router.get("/api/snapshot", response_model=SnapshotEnvelope)
async def snapshot(request: Request):
    s = state(request)
    async with s.lock:
        return s.store.snapshot()

@router.get("/api/pipeline/stats", response_model=PipelineStats)
async def stats(request: Request):
    snap=state(request).store.snapshot(); n=snap["active_count"]; excluded=snap["suppressed_count"]
    return {"total":477,"configured_cameras":len(state(request).store.cameras),"candidates":n+excluded,"reasoned":n+excluded,"incidents":n,
        "suppressed":excluded,"needs_review":snap["level_counts"]["review"],"avg_latency_sec":None,
        "total_latency_sec":None,"stage_trace":[],"today_summary":{"incidents":n,"suppressed":excluded,"avg_latency_sec":None},
        "measurement_scope":"demo_snapshot" if state(request).settings.mode=="demo" else "current_snapshot",
        "counter_semantics":"candidates/reasoned are legacy active+suppressed snapshot counts, not measured pipeline stages",
        "target_camera_capacity":477,"observed_cameras":snap["observed_cameras"],
        "accepted_inputs":len(state(request).store.assessment_inputs),
        "latency_measurement_status":"not_aggregated","today_summary_scope":"current_snapshot_not_daily",
        "server_instance_id":snap["server_instance_id"],"api_contract_version":API_CONTRACT_VERSION}

@router.get("/api/suppressed")
async def suppressed(request: Request): return list(state(request).store.suppressed.values())

@router.get("/api/incidents/{incident_id}", response_model=Incident)
async def incident(incident_id: str, request: Request):
    store=state(request).store
    try: result=store.get(incident_id)
    except KeyError: raise HTTPException(404,"incident not found")
    for item in store.ordered():
        if item.id==incident_id: result=item
    return present_incident(state(request), incident_id)

@router.get("/api/incidents/{incident_id}/clip", response_model=ClipMetadata)
async def clip(incident_id: str, request: Request):
    try: i=state(request).store.get(incident_id)
    except KeyError: raise HTTPException(404,"incident not found")
    return await clip_metadata(state(request), i)

async def mutate(s, scope, key, payload, operation):
    # Entire update + audit + key + publication is atomic within this one process.
    if not key or len(key)>200: raise HTTPException(400,"Idempotency-Key required (1..200 chars)")
    signature=json.dumps({"scope":scope,"payload":payload},sort_keys=True,ensure_ascii=False)
    async with s.lock:
        if key in s.store.requests:
            previous,response=s.store.requests[key]
            if previous!=signature: raise HTTPException(409,"key already used for another request")
            return response
        try: response=operation()
        except KeyError: raise HTTPException(404,"record not found")
        except ValueError as e: raise HTTPException(409,str(e))
        response = {**response, "server_instance_id":s.store.server_instance_id, "api_contract_version":API_CONTRACT_VERSION}
        s.store.requests[key]=(signature,response)
        s.hub.publish(s.store.snapshot())
        return response

@router.post("/api/incidents/{incident_id}/ack")
async def ack(incident_id: str, body: AckBody, request: Request, idempotency_key: str | None = Header(default=None)):
    return await mutate(state(request),"ack:"+incident_id,idempotency_key,body.model_dump(),
        lambda:state(request).store.ack(incident_id,body))

# Additive extension: required to make Figma's 'recoverable suppression' actionable.
@router.post("/api/suppressed/{suppressed_id}/restore")
async def restore(suppressed_id: str, request: Request, idempotency_key: str | None = Header(default=None)):
    from app.schemas.incident import Incident
    from datetime import datetime, timezone
    s=state(request)
    def action():
        item=s.store.suppressed[suppressed_id]
        if not item["restored"]:
            restored_id = "RESTORED-"+suppressed_id
            s.store.put(Incident(id=restored_id,sample_id="restore-"+suppressed_id,type="uncertain",
                title="제외 알림 재검토",primary_cam=item["cam_id"],risk=None,level="UNKNOWN",risk_axes=None,confidence=0,
                needs_human_review=True,uncertainty_reason="operator_restored",created_at=datetime.now(timezone.utc)))
            if suppressed_id in s.store.media_context:
                s.store.media_context[restored_id] = dict(s.store.media_context[suppressed_id])
            if suppressed_id in s.store.incident_resolvers:
                s.store.incident_resolvers[restored_id] = s.store.incident_resolvers[suppressed_id]
            item["restored"]=True;s.store.revision+=1
            s.store.audit.append({"action":"restore","suppressed_id":suppressed_id,"at":datetime.now(timezone.utc).isoformat()})
        return {"ok":True,"revision":s.store.revision}
    return await mutate(s,"restore:"+suppressed_id,idempotency_key,{},action)

class DemoStep(ContractModel): step: int = Field(ge=1,le=6)
@router.post("/api/demo/step")
async def demo_step(body: DemoStep, request: Request, idempotency_key: str | None = Header(default=None)):
    s=state(request)
    if s.settings.mode!="demo": raise HTTPException(404,"demo disabled")
    def action():
        s.store.demo(body.step)
        return {"ok":True,"step":body.step,"revision":s.store.revision}
    return await mutate(s,"demo",idempotency_key,body.model_dump(),action)

def media_path(s, cam_id):
    if cam_id not in {c["id"] for c in s.store.cameras}: raise HTTPException(404,"camera not found")
    root=s.settings.media_root.resolve(); path=(root/(cam_id+".mp4")).resolve()
    if not path.is_relative_to(root): raise HTTPException(400,"invalid media path")
    return path

@router.get("/stream/{cam_id}")
async def stream(cam_id: str, request: Request):
    path=media_path(state(request),cam_id)
    if not path.is_file(): raise HTTPException(503,"place a licensed MP4 at MEDIA_ROOT/CAM_XX.mp4")
    return FileResponse(path,media_type="video/mp4")

@router.get("/api/incidents/{incident_id}/video")
async def incident_video(incident_id: str, request: Request):
    s=state(request)
    try: incident=s.store.get(incident_id)
    except KeyError: raise HTTPException(404,"incident not found")
    return video_response(s,incident)

@router.get("/api/incidents/{incident_id}/frames/{frame_index}")
async def evidence_frame(incident_id: str, frame_index: int, request: Request):
    s=state(request)
    try: incident=s.store.get(incident_id)
    except KeyError: raise HTTPException(404,"incident not found")
    value,mime=frame_asset(s,incident,frame_index)
    return Response(value,media_type=mime,headers={"Cache-Control":"no-store"})

@router.websocket("/ws/attention")
async def attention(ws: WebSocket):
    s=ws.app.state
    origin=ws.headers.get("origin")
    if origin and origin not in s.settings.origins:
        await ws.close(code=1008); return
    await ws.accept()
    async with s.lock:
        q=s.hub.subscribe(); initial=s.store.snapshot()
    async def send():
        await ws.send_json(initial)
        while True:
            try: snapshot=await asyncio.wait_for(q.get(),timeout=15)
            except TimeoutError:
                async with s.lock: snapshot=s.store.snapshot()
            await ws.send_json(snapshot)
    task=asyncio.create_task(send())
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        s.hub.unsubscribe(q);task.cancel()
        try: await task
        except (asyncio.CancelledError,WebSocketDisconnect,RuntimeError): pass


@router.get("/api/demo/scenario")
async def demo_scenario(request: Request):
    s=state(request)
    if s.settings.mode!="demo":
        raise HTTPException(404,"demo disabled")
    return {"configured":bool(s.store.scenario),"scenario":s.store.scenario.model_dump(mode="json") if s.store.scenario else None}

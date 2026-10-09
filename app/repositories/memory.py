from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from app.schemas.incident import Incident, AckBody
from app.schemas.model import RiskAxes, SCHEMA_VERSION
from app.services.risk import risk_score, risk_level

class MemoryStore:
    """Demo only: one ASGI worker; restart loses state. Mutations locked by routes."""
    def __init__(self, *, mode="demo", media_root=None):
        self.mode = mode
        self.media_root = Path(media_root or "media")
        self.server_instance_id = str(uuid4())
        self.media_context = {}
        self.frame_bindings = {}
        self.incident_resolvers = {}
        self.incidents: dict[str, Incident] = {}
        self.suppressed: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.requests: dict[str, tuple[str, dict]] = {}
        # First accepted input wins until an explicit demo reset. Caller holds the lock.
        self.assessment_inputs: dict[str, dict] = {}
        self.revision = 0
        self.step = 1
        self.cameras = [{"id":f"CAM_{i:02d}","name":f"CAM {i:02d}","location":"demo",
            "stream_url":f"/stream/CAM_{i:02d}","status":"normal","bbox":[]} for i in range(1,10)]
    def get(self, incident_id):
        return self.incidents[incident_id]
    def put(self, incident):
        self.incidents[incident.id] = incident
    def ordered(self):
        # Unknown risks are visible before numeric risks. Known risks remain descending.
        active = [x for x in self.incidents.values() if x.status == "open"]
        active.sort(key=lambda x:(0 if x.risk is None else 1, -(x.risk or 0), x.created_at, x.id))
        return [x.model_copy(update={"rank":i+1,"next_incident_id":active[i+1].id if i+1<len(active) else None,
            "rank_reason":"위험도 미측정: 사람 검토 우선" if x.risk is None else "서버 위험도 내림차순"}) for i,x in enumerate(active)]
    def present(self, incident_id):
        for item in self.ordered():
            if item.id == incident_id:
                return item
        return self.get(incident_id).model_copy(update={"rank":None, "rank_reason":None, "next_incident_id":None})
    def camera_states(self):
        active = self.ordered()
        result = []
        for cam in self.cameras:
            relevant = [x for x in active if cam["id"] in [x.primary_cam,*x.related_cams]]
            c = {**cam, "level":None, "suppressed":False}
            observed = any(x.get("camera_id") == cam["id"] for x in self.assessment_inputs.values())
            media_path = (self.media_root.resolve() / (cam["id"] + ".mp4")).resolve()
            available = media_path.is_relative_to(self.media_root.resolve()) and media_path.is_file()
            c.update(analysis_status="analyzed" if observed else ("demo" if self.mode == "demo" else "not_analyzed"),
                media_available=available, video_source="local_file" if available else "not_configured", is_demo=self.mode=="demo")
            if self.mode != "demo":
                c["status"] = "idle" if observed else "unobserved"
            if relevant:
                c.update(status="review" if any(x.needs_human_review for x in relevant) else "incident", level=relevant[0].level)
            elif any(s["cam_id"]==cam["id"] and not s["restored"] for s in self.suppressed.values()):
                c.update(status="normal",suppressed=True)
            result.append(c)
        return result
    def snapshot(self):
        incidents = self.ordered()
        counts = {k:0 for k in ["critical","high","medium","low","review","unknown"]}
        for i in incidents:
            counts["review" if i.needs_human_review else i.level.lower()] += 1
        return {"event_type":"snapshot","schema_version":SCHEMA_VERSION,"revision":self.revision,
            "active_count":len(incidents),"total_cameras":477,"configured_cameras":len(self.cameras),
            "suppressed_count":sum(not s["restored"] for s in self.suppressed.values()),"level_counts":counts,
            "incidents":[i.model_dump(mode="json") for i in incidents],"cameras":self.camera_states(),
            "server_instance_id":self.server_instance_id,"api_contract_version":"1.2",
            "target_camera_capacity":477,"observed_cameras":len({x["camera_id"] for x in self.assessment_inputs.values() if "camera_id" in x}),
            "is_demo":self.mode=="demo"}
    def ack(self, incident_id: str, body: AckBody):
        old = self.get(incident_id)
        if body.action == "handover" and not body.to_operator:
            raise ValueError("handover requires to_operator")
        if old.status == "dismissed" and body.action != "dismiss":
            raise ValueError("dismissed incident is terminal")
        update = {"revision":old.revision+1}
        if body.action == "verify": update["status"] = "acked"
        elif body.action == "dismiss": update["status"] = "dismissed"
        elif body.action == "needs_review": update.update(status="open",needs_human_review=True)
        elif body.action == "confirm_review": update.update(status="open",needs_human_review=False)
        elif body.action == "request_dispatch": update["dispatch_requested"] = True
        elif body.action == "handover": update["assigned_operator"] = body.to_operator
        result = old.model_copy(update=update)
        self.put(result)
        self.audit.append({"incident_id":incident_id,**body.model_dump(),"at":datetime.now(timezone.utc).isoformat()})
        self.revision += 1
        return {"ok":True,"incident":self.present(incident_id).model_dump(mode="json"),"revision":self.revision}
    def demo(self, step: int):
        self.incidents.clear(); self.suppressed.clear(); self.step = step
        self.assessment_inputs.clear()
        self.media_context.clear(); self.frame_bindings.clear(); self.incident_resolvers.clear()
        # Keep idempotency ledger: replaying an old key must never repeat an action.
        now = datetime.now(timezone.utc)
        if step == 2:
            self.suppressed["SUP-001"] = {"id":"SUP-001","cam_id":"CAM_04","stage1_label":"Possible fall",
                "ai_verdict":"normal","reason":"데모: 자세를 낮춘 뒤 다시 걸음","risk":8,
                "resumed_walking":True,"restored":False}
        if step >= 3:
            scenarios=[("INC-032","CAM_08","collapse",(.9,.95,.8,.85),.92,False)]
            if step>=4: scenarios.append(("INC-033","CAM_05","conflict",(.8,.75,.5,.6),.89,False))
            if step>=5: scenarios.append(("INC-034","CAM_03","intrusion",(.7,.7,.5,.6),.66,True))
            for key,cam,event,axes,confidence,review in scenarios:
                a=RiskAxes(severity=axes[0],imminence=axes[1],exposure=axes[2],persistence=axes[3]); score=risk_score(a)
                self.put(Incident(id=key,sample_id="demo-"+key,type=event,title="데모: "+event,primary_cam=cam,
                    risk=score,level=risk_level(score),risk_axes=a,confidence=confidence,needs_human_review=review,
                    uncertainty_reason="occlusion" if review else None,created_at=now))
        self.revision += 1

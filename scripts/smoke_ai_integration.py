"""One explicit live integration check. Default refuses paid calls; no ground truth."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models.media import MediaResolver


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asset-root",type=Path,required=True)
    ap.add_argument("--asset",required=True,help="MP4 path relative to trusted asset root")
    ap.add_argument("--weights",type=Path,required=True)
    ap.add_argument("--cv-python",type=Path)
    ap.add_argument("--provider-python",type=Path,default=Path(sys.executable))
    ap.add_argument("--key-env-file",type=Path)
    ap.add_argument("--start-ms",type=int,default=0)
    ap.add_argument("--end-ms",type=int,default=10000)
    ap.add_argument("--budget-usd",type=float,default=2.0)
    ap.add_argument("--output",type=Path,default=Path("outputs/ai-live-smoke"))
    ap.add_argument("--live",action="store_true")
    args=ap.parse_args()
    if not args.live:
        raise SystemExit("Paid inference disabled. Add --live only with an authorized budget.")
    if not .02<args.budget_usd<=2:
        raise SystemExit("This smoke supports a total authorized budget <=2 USD.")
    args.output.mkdir(parents=True,exist_ok=True)
    marker=args.output/"attempt.json"
    if marker.exists():
        raise SystemExit("An attempt already exists here; refusing silent repeated inference.")
    if args.key_env_file:
        from dotenv import dotenv_values
        key=dotenv_values(args.key_env_file).get("OPENAI_API_KEY")
        if key:
            os.environ["OPENAI_API_KEY"]=key
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured.")
    # A single P1 and P4 attempt; P4 counts its identical payload before inference.
    os.environ["AI_MAX_RETRIES"]="0"
    os.environ["AI_REQUEST_BUDGET_USD"]=str(args.budget_usd-.02)
    marker.write_text(json.dumps({"state":"STARTED","at":datetime.now(timezone.utc).isoformat(),
        "budget_usd":args.budget_usd,"max_p1_attempts":1,"max_p4_attempts":1},indent=2),encoding="utf-8")
    resolver=MediaResolver(args.asset_root,{"ASSET_0001":args.asset})
    settings=Settings(mode="development",model_adapter="cascade_v1",ai_weights=args.weights,
        ai_python=args.provider_python,ai_cv_python=args.cv_python,ai_mode="shadow",
        ai_stage_timeout_sec=300,ai_total_timeout_sec=1200)
    app=create_app(settings,media_resolver=resolver)
    with TestClient(app) as client:
        accepted=client.post("/api/analysis/jobs",headers={"Idempotency-Key":"authorized-ai-smoke-v1"},
            json={"camera_id":"CAM_02","clip_ref":"ASSET_0001","start_ms":args.start_ms,"end_ms":args.end_ms})
        if accepted.status_code!=202:
            raise SystemExit("Analysis job admission failed: "+str(accepted.status_code))
        job_id=accepted.json()["job_id"]
        async def wait():
            last=None
            for _ in range(1250):
                job=app.state.analysis_jobs.get(job_id)
                if job["state"]!=last:
                    print("analysis stage:",job["state"],flush=True)
                    last=job["state"]
                if job["state"] in {"completed","failed"}:
                    return job
                await asyncio.sleep(1)
            raise RuntimeError("analysis deadline exceeded")
        job=client.portal.call(wait)
        report={"job":job,"diagnostics":app.state.analysis_diagnostics.get(job_id),
            "stats":client.get("/api/analysis/stats").json(),"input_scope":"registered MP4 integration check; no GT"}
        if job.get("incident_id"):
            incident=client.get("/api/incidents/"+job["incident_id"]).json()
            report["incident"]=incident
            report["clip"]=client.get("/api/incidents/"+job["incident_id"]+"/clip").json()
            report["evidence_delivery"]=[{"frame_id":e["frame_id"],"status_code":client.get(e["frame_url"]).status_code}
                for e in incident["evidence"] if e["frame_url"]]
            report["ack_status_code"]=client.post("/api/incidents/"+job["incident_id"]+"/ack",
                headers={"Idempotency-Key":"authorized-smoke-ack"},json={"action":"verify"}).status_code
            report["post_ack_active_count"]=client.get("/api/snapshot").json()["active_count"]
        (args.output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
        paid=[r for r in job["stage_trace"] if r["stage"] in {"p1","p4"}]
        success=job["state"]=="completed" and len(paid)==2 and all(r["status"]=="ok" and r["attempts"]==1 for r in paid)
        costs=[r["estimated_cost_usd"] for r in paid]
        cost=sum(costs) if costs and all(c is not None for c in costs) else None
        final={"state":"PASS" if success else "FAILED","cost_usd":cost,"report":str(args.output/"report.json"),"inference_attempts":{r["stage"]:r["attempts"] for r in paid}}
        marker.write_text(json.dumps(final,indent=2),encoding="utf-8")
        print(json.dumps(final),flush=True)
        if not success:
            raise SystemExit(2)


if __name__=="__main__":
    main()

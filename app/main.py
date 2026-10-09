import asyncio
from contextlib import asynccontextmanager
from time import perf_counter
from weakref import WeakValueDictionary
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.config import Settings
from app.repositories.memory import MemoryStore
from app.services.events import SnapshotHub
from app.services.incidents import apply_assessment, lookup_assessment
from app.models.base import ModelAdapter
from app.models.execution import execute, failure_assessment
from app.models.registry import get_adapter
from app.models.media import MediaResolver
from app.models.adapters.ingestion import MediaIngestion
from app.schemas.model import ModelInput, CameraContext, TimeWindow, StageRecord
from app.services.analysis_jobs import AnalysisJobService, AnalysisJobError
from app.api.analysis import router as analysis_router


class _PreparationFailure(ModelAdapter):
    def __init__(self, name, elapsed_ms):
        self.name = name
        self.elapsed_ms = elapsed_ms

    async def evaluate(self, model_input):
        result = failure_assessment(self.name, model_input, "preprocessing_error")
        return result.model_copy(update={"metadata": result.metadata.model_copy(update={
            "stage_trace": [StageRecord(stage="prepare", status="failed", latency_ms=self.elapsed_ms)]
        })})
from app.api.errors import register_errors

def create_app(settings: Settings | None = None, *, adapter: ModelAdapter | None = None,
               media_resolver: MediaResolver | None = None):
    settings=settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await app.state.analysis_jobs.close()

    app=FastAPI(title="477 AI Role 1 Development Backend",version="0.2.0", lifespan=lifespan)
    app.state.settings=settings;app.state.store=MemoryStore(mode=settings.mode, media_root=settings.media_root, scenario_path=settings.demo_scenario_path);app.state.hub=SnapshotHub();app.state.lock=asyncio.Lock()
    if media_resolver is None and settings.asset_map_path is not None:
        media_resolver = MediaResolver.from_asset_map(settings.asset_map_path, settings.asset_root)
    if adapter is None and settings.model_adapter == "cascade_v1" and media_resolver is not None:
        from app.models.adapters.cascade_v1 import CascadeV1Adapter
        adapter = CascadeV1Adapter(media_resolver, python_executable=settings.ai_python,
            cv_python_executable=settings.ai_cv_python,
            weights_path=settings.ai_weights, mode=settings.ai_mode,
            cv_timeout_sec=settings.ai_stage_timeout_sec, p1_timeout_sec=settings.ai_stage_timeout_sec,
            p4_timeout_sec=settings.ai_stage_timeout_sec)
    app.state.model_adapter = adapter if adapter is not None else get_adapter(settings.model_adapter, resolver=media_resolver)
    app.state.media_resolver = media_resolver
    app.state.media_ingestion = MediaIngestion(media_resolver) if media_resolver is not None else None
    sample_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    prepared_resolvers = {}

    async def prepare_model_input(model_input: ModelInput):
        if app.state.media_ingestion is None:
            raise ValueError("media resolver is not configured")
        prepared = await app.state.media_ingestion.prepare(model_input)
        prepared_resolvers[prepared.model_input.model_dump_json()] = prepared.resolver
        return prepared

    app.state.prepare_model_input = prepare_model_input

    async def ingest_model_input(model_input: ModelInput, *, adapter=None, resolver=None, timeout_sec=None):
        # Internal integration seam; live ingestion and real media remain separate work.
        model_input = ModelInput.model_validate(model_input)
        # Waiting callers keep a strong reference; unused locks are released automatically.
        sample_lock = sample_locks.setdefault(model_input.sample_id, asyncio.Lock())
        async with sample_lock:
            async with app.state.lock:
                cached = lookup_assessment(app.state.store, model_input)
                if cached is not None:
                    prepared_resolvers.pop(model_input.model_dump_json(), None)
                    return cached
            active_resolver = resolver or prepared_resolvers.get(model_input.model_dump_json(), app.state.media_resolver)
            active_adapter = adapter or app.state.model_adapter
            if hasattr(active_adapter, "with_resolver") and active_resolver is not None and getattr(active_adapter, "resolver", None) is not active_resolver:
                active_adapter = active_adapter.with_resolver(active_resolver)
            budget = timeout_sec or (settings.ai_total_timeout_sec if active_adapter.name == "cascade_v1" else settings.model_timeout_sec)
            assessment = await execute(active_adapter, model_input, budget)
            async with app.state.lock:
                applied = apply_assessment(app.state.store, model_input, assessment)
                if applied.changed:
                    prepared_resolvers.pop(model_input.model_dump_json(), None)
                    if active_resolver is not None:
                        record_id = applied.record.id if hasattr(applied.record, "id") else applied.record["id"]
                        app.state.store.incident_resolvers[record_id] = active_resolver
                    if active_resolver is not None and hasattr(applied.record, "evidence"):
                        by_id = {e.frame_id:e.media_ref for e in model_input.evidence}
                        for e in applied.record.evidence:
                            app.state.store.frame_bindings[(applied.record.id,e.frame_id)] = (active_resolver,by_id[e.frame_id])
                    app.state.hub.publish(app.state.store.snapshot())
                return applied

    app.state.ingest_model_input = ingest_model_input

    async def validate_analysis(body):
        if body.camera_id not in {c["id"] for c in app.state.store.cameras}:
            raise AnalysisJobError(404, "unknown camera")
        if app.state.media_resolver is None:
            raise AnalysisJobError(503, "media resolver not configured")
        if app.state.model_adapter.name != "cascade_v1":
            raise AnalysisJobError(503, "cascade_v1 adapter not configured")
        if body.end_ms - body.start_ms > 600000:
            raise AnalysisJobError(422, "analysis window exceeds 10 minutes")
        def check():
            lookup = app.state.media_resolver
            if body.clip_ref in lookup.assets:
                raise ValueError("analysis API requires a registered source file")
            path = lookup.trusted_path(body.clip_ref)
            if path.suffix.lower() != ".mp4":
                raise ValueError("unsupported media")
            size = path.stat().st_size
            with path.open("rb") as stream:
                header = stream.read(32)
            if not 0 < size <= 64 * 1024 * 1024 or header[4:8] != b"ftyp":
                raise ValueError("invalid MP4")
        try:
            await asyncio.to_thread(check)
        except (KeyError, OSError, ValueError):
            raise AnalysisJobError(422, "registered MP4 unavailable or invalid") from None

    async def prepare_analysis(mi):
        from app.models.adapters.cascade_media import prepare_frozen_input
        return await prepare_frozen_input(mi, app.state.media_resolver,
            python_executable=settings.ai_python, timeout_sec=min(settings.ai_stage_timeout_sec, 120))

    app.state.analysis_preparer = prepare_analysis
    # Local diagnostics have the same bounded job lifetime, never provider error text or credentials.
    app.state.analysis_diagnostics = {}

    async def process_analysis(job_id, body, progress):
        camera = next(c for c in app.state.store.cameras if c["id"] == body.camera_id)
        raw = ModelInput(sample_id=job_id, camera=CameraContext(id=body.camera_id, location=camera.get("location")),
            window=TimeWindow(start_ms=body.start_ms, end_ms=body.end_ms), clip_ref=body.clip_ref)
        started = perf_counter()
        try:
            prepared = await app.state.analysis_preparer(raw)
        except asyncio.CancelledError:
            raise
        except Exception:
            applied = await ingest_model_input(raw, adapter=_PreparationFailure("cascade_v1", (perf_counter()-started)*1000))
        else:
            active_adapter = app.state.model_adapter.with_resolver(prepared.resolver)
            active_adapter.progress = progress
            remaining = max(.001, settings.ai_total_timeout_sec - (perf_counter() - started))
            applied = await ingest_model_input(prepared.model_input, adapter=active_adapter, resolver=prepared.resolver, timeout_sec=remaining)
            app.state.analysis_diagnostics[job_id] = {
                "input": {"clip_sha256": prepared.clip_sha256, "frame_sha256": prepared.frame_sha256,
                    "extractor_version": prepared.extractor_version, "profile": prepared.profile},
                "decisions": getattr(active_adapter, "diagnostics", {}),
                "backend_disposition": applied.decision.disposition,
            }
            # Preparation is measured separately from provider/model execution.
            ledger = app.state.store.assessment_inputs[raw.sample_id]
            ledger["metadata"]["stage_trace"].insert(0, StageRecord(stage="prepare", status="ok", latency_ms=prepared.preprocessing_ms).model_dump(mode="json"))
        meta = app.state.store.assessment_inputs[raw.sample_id]["metadata"]
        is_incident = hasattr(applied.record, "evidence")
        return {"incident_id": applied.record.id if is_incident else None,
            "suppressed_id": None if is_incident else applied.record["id"],
            "needs_review": applied.decision.disposition == "review", "stage_trace": meta.get("stage_trace", [])}

    app.state.analysis_jobs = AnalysisJobService(process_analysis, validate_analysis,
        queue_size=settings.analysis_queue_size, max_jobs=settings.analysis_max_jobs,
        request_ledger=app.state.store.requests, state_lock=app.state.lock)
    app.add_middleware(CORSMiddleware,allow_origins=list(settings.origins),allow_credentials=False,
        allow_methods=["GET","POST"],allow_headers=["Content-Type","Idempotency-Key"])
    register_errors(app)
    app.include_router(router)
    app.include_router(analysis_router)
    return app
app=create_app()

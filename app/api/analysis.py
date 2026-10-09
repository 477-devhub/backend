"""Additive development-only API for trusted registered MP4 analysis."""
from typing import Literal
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import Field, model_validator
from app.schemas.model import ContractModel, StageRecord
from app.services.analysis_jobs import AnalysisJobError

router = APIRouter()


class AnalysisJobBody(ContractModel):
    camera_id: str = Field(min_length=1, max_length=100)
    clip_ref: str = Field(min_length=1, max_length=200)
    start_ms: int = Field(ge=0, strict=True)
    end_ms: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be after start_ms")
        return self


class AnalysisJobResult(ContractModel):
    incident_id: str | None = None
    suppressed_id: str | None = None
    needs_review: bool = Field(strict=True)
    stage_trace: list[StageRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_record(self):
        if bool(self.incident_id) == bool(self.suppressed_id):
            raise ValueError("analysis result must reference exactly one record")
        return self


class AnalysisJobResponse(AnalysisJobResult):
    job_id: str
    state: Literal["queued", "preparing", "cv", "p1", "p4", "completed", "failed"]
    camera_id: str
    clip_ref: str
    start_ms: int
    end_ms: int
    created_at: str
    updated_at: str
    needs_review: bool | None = Field(default=None, strict=True)
    error_code: Literal["analysis_failed", "cancelled"] | None = None

    @model_validator(mode="after")
    def one_record(self):
        if self.state == "completed" and bool(self.incident_id) == bool(self.suppressed_id):
            raise ValueError("completed job must reference exactly one record")
        if self.state == "completed" and (self.needs_review is None or self.error_code is not None):
            raise ValueError("completed job must have a review decision and no error")
        if self.state != "completed" and (self.incident_id is not None or self.suppressed_id is not None or self.needs_review is not None):
            raise ValueError("unfinished job cannot expose an assessment result")
        if (self.state == "failed") != (self.error_code is not None):
            raise ValueError("only failed jobs must expose a failure code")
        return self


class AnalysisStageStats(ContractModel):
    stage: Literal["prepare", "cv", "p1", "p4", "map"]
    records: int = Field(ge=0)
    ok: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    attempts: int = Field(ge=0)
    known_cost_count: int = Field(ge=0)
    unknown_cost_count: int = Field(ge=0)
    known_cost_usd: float | None = Field(ge=0)
    known_latency_count: int = Field(ge=0)
    unknown_latency_count: int = Field(ge=0)
    known_latency_total_ms: float | None = Field(ge=0)
    known_latency_average_ms: float | None = Field(ge=0)


class AnalysisStats(ContractModel):
    job_counts: dict[Literal["queued", "preparing", "cv", "p1", "p4", "completed", "failed"], int]
    total_jobs: int = Field(ge=0)
    completed_jobs: int = Field(ge=0)
    failed_jobs: int = Field(ge=0)
    stages: list[AnalysisStageStats]
    provider_attempts: int = Field(ge=0)
    known_cost_usd: float | None = Field(ge=0)
    unknown_cost_records: int = Field(ge=0)
    measured_elapsed_jobs: int = Field(ge=0)
    unknown_elapsed_jobs: int = Field(ge=0)
    known_elapsed_total_ms: float | None = Field(ge=0)
    known_elapsed_average_ms: float | None = Field(ge=0)
    measurement_scope: Literal["terminal_job_stage_traces"]
    elapsed_semantics: str
    failure_semantics: str
    cost_semantics: str


def _service(request):
    if request.app.state.settings.mode != "development":
        raise HTTPException(404, "analysis disabled")
    service = getattr(request.app.state, "analysis_jobs", None)
    if service is None:
        raise HTTPException(503, "analysis service not configured")
    return service


@router.post("/api/analysis/jobs", status_code=202, response_model=AnalysisJobResponse)
async def submit_analysis(body: AnalysisJobBody, request: Request,
                          idempotency_key: str | None = Header(default=None)):
    try:
        return await _service(request).submit(body, idempotency_key)
    except AnalysisJobError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None


@router.get("/api/analysis/jobs/{job_id}", response_model=AnalysisJobResponse)
async def analysis_job(job_id: str, request: Request):
    try:
        return _service(request).get(job_id)
    except AnalysisJobError as exc:
        raise HTTPException(exc.status_code, exc.detail) from None


@router.get("/api/analysis/stats", response_model=AnalysisStats)
async def analysis_stats(request: Request):
    return _service(request).metrics()

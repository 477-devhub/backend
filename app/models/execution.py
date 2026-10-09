import asyncio
import time
import copy
from pydantic import ValidationError
from app.models.base import ModelAdapter
from app.schemas.model import ModelInput, ModelAssessment, ModelMetadata
from app.schemas.benchmark import BenchmarkAdapter, BenchmarkInput, BenchmarkOutcome, BenchmarkError

FAILURE_CODES = frozenset({"timeout", "schema_or_contract", "provider_error", "preprocessing_error"})

def failure_assessment(adapter_name: str, model_input: ModelInput, error_code: str,
                       latency_ms: float | None = None) -> ModelAssessment:
    """Create a sanitized review result; never accept a provider exception string."""
    if error_code not in FAILURE_CODES:
        raise ValueError("unsupported failure code")
    model_input = ModelInput.model_validate(model_input)
    return ModelAssessment(event_type="uncertain", event_confidence=0, risk_axes=None,
        needs_human_review=True, uncertainty_reason=error_code,
        # Failed decoding has established no actual frame evidence.
        evidence_refs=[] if error_code == "preprocessing_error" else [e.frame_id for e in model_input.evidence],
        recommended_actions=["verify"],
        metadata=ModelMetadata(adapter=adapter_name, model="unavailable", error_code=error_code,
                               latency_ms=latency_ms))

async def execute(adapter: ModelAdapter, model_input: ModelInput, timeout_sec: float = 5.0) -> ModelAssessment:
    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")
    started = time.perf_counter()
    isolated = model_input.model_copy(deep=True)
    before = isolated.model_dump(mode="json")
    code = None
    try:
        raw = await asyncio.wait_for(adapter.evaluate(isolated), timeout=timeout_sec)
        result = ModelAssessment.model_validate(raw)
        if isolated.model_dump(mode="json") != before:
            raise ValueError("input mutation")
        if result.metadata.adapter != adapter.name:
            raise ValueError("wrong adapter identifier")
        if set(result.evidence_refs) - {e.frame_id for e in model_input.evidence}:
            raise ValueError("unknown evidence reference")
        if result.risk_axes is not None and not result.evidence_refs:
            raise ValueError("event has no evidence")
    except TimeoutError:
        code = "timeout"
    except (ValidationError, ValueError, TypeError):
        code = "schema_or_contract"
    except Exception:
        code = "provider_error"
    latency = (time.perf_counter() - started) * 1000
    if code:
        # Sanitized reason: never expose exception payloads, prompts or credentials.
        return failure_assessment(adapter.name, model_input, code, latency)
    return result.model_copy(update={"metadata": result.metadata.model_copy(update={"latency_ms": latency})})


async def execute_benchmark(adapter: BenchmarkAdapter, model_input: BenchmarkInput,
                            timeout_sec: float = 300.0) -> BenchmarkOutcome:
    """Independent benchmark stages share the same sanitized execution boundary.

    Frozen prediction validation belongs to the evaluator. Failure predictions remain
    null in diagnostic records, never fabricated as frozen successful submissions.
    """
    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive")
    started = time.perf_counter()
    before = await asyncio.to_thread(lambda: model_input.input_digest)
    code = None
    try:
        result = await asyncio.wait_for(adapter.evaluate_benchmark(model_input), timeout_sec)
        if not isinstance(result, BenchmarkOutcome) or result.adapter != adapter.name:
            raise ValueError("wrong benchmark output")
        if await asyncio.to_thread(lambda: model_input.input_digest) != before:
            raise ValueError("input mutation")
        if result.status not in {"ok", "error"}:
            raise ValueError("invalid benchmark status")
    except TimeoutError:
        code = "timeout"
    except BenchmarkError as error:
        code = error.code
    except (ValueError, TypeError, ValidationError):
        code = "schema_or_contract"
    except Exception:
        code = "provider_error"
    latency = (time.perf_counter() - started) * 1000
    if code:
        return BenchmarkOutcome(adapter=adapter.name, model=adapter.model, status="error",
            error_code=code, latency_ms=latency, metadata={"needs_human_review": True})
    result.latency_ms = latency
    return result


async def execute_pipeline_stage(adapter, model_input: dict, context: dict,
                                 timeout_sec: float = 600.0) -> dict:
    """Portable source-resolved benchmark boundary; never leaks exception payloads."""
    if timeout_sec <= 0:
        raise ValueError("timeout must be positive")
    started = time.perf_counter()
    isolated = copy.deepcopy(model_input)
    before = copy.deepcopy(isolated)
    try:
        result = await asyncio.wait_for(adapter.run(isolated, context), timeout_sec)
        if isolated != before or not isinstance(result, dict):
            raise ValueError("input mutation or invalid result")
        if result.get("status") not in {"ok", "error", "blocked", "skipped"}:
            raise ValueError("invalid stage status")
    except TimeoutError:
        result = {"status": "error", "output": None, "errors": [{"category": "execution",
                  "code": "timeout", "detail": "Stage timeout; billing may be unknown."}]}
    except (ValueError, TypeError):
        result = {"status": "error", "output": None, "errors": [{"category": "benchmark",
                  "code": "input_or_adapter_contract", "detail": "Invalid stage contract."}]}
    except Exception:
        result = {"status": "error", "output": None, "errors": [{"category": "evaluation_unavailable",
                  "code": "unclassified_failure", "detail": "Sanitized failure; cause requires review."}]}
    result["latency_ms"] = (time.perf_counter() - started) * 1000
    return result

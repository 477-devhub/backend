import asyncio
import time
from pydantic import ValidationError
from app.models.base import ModelAdapter
from app.schemas.model import ModelInput, ModelAssessment, ModelMetadata

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

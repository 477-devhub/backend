import asyncio
import copy
import time

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

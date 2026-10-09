"""Sequential real-model benchmark evaluation without ground-truth inference.

Frozen submissions are emitted only after original and canonical-evidence checks.
Every planned attempt, including skipped and unavailable attempts, has a diagnostic.
Provider serializers and credentials belong to adapters, never this module.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict, replace
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

from app.models.benchmark_assessment import common_assessments
from app.models.benchmark_media import (
    assert_output_outside_inputs, load_benchmark_input, snapshot_protected,
)
from app.models.budget import PaidBudget
from app.models.execution import execute_benchmark
from app.schemas.benchmark import BenchmarkInput, BenchmarkOutcome

MODES = {
    "suite": ("vlm_only", "cv_llm"), "vlm": ("vlm_only",),
    "pipeline": ("cv_llm",), "local_cv": ("local_cv",), "clef": ("clef_direct",),
}
TIMEOUTS = {"local_cv": 1800, "clef_direct": 150, "general_vlm": 210}
PAID = {"clef_direct", "general_vlm"}
UNAVAILABLE_HTTP = {401, 402, 403, 404}
UNMEASURABLE = {
    "event_accuracy": "No event-class ground truth is present in the public package.",
    "event_miss_rate": "No labeled incidents are present; routing omissions are recorded separately.",
    "false_alarm_rate": "No labeled normal/negative clips are present.",
    "evidence_correctness": "No reference evidence frames or semantic evidence grades are present.",
    "risk_error": "No reference risk-axis scores are present.",
}


def _scrub(value: Any) -> Any:
    """A second boundary against a provider echoing a configured credential."""
    secrets = [os.environ.get(key, "") for key in
               ("VLM_API_KEY", "CLEF_API_TOKEN", "CLEF_ACCOUNT", "CLOUDFLARE_AUTH_TOKEN")]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {_scrub(str(key)): _scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_scrub(value), ensure_ascii=False, allow_nan=False,
                               indent=2), encoding="utf-8")


def _original_validator(package: Path):
    """Import the unchanged three public helpers, suppressing protected pycache."""
    names = ("benchmark_common", "load_model_input", "validate_prediction")
    old_modules = {name: sys.modules.get(name) for name in names}
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name in names:
            path = package / "scripts" / f"{name}.py"
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ValueError("original validator unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        return sys.modules["validate_prediction"]
    finally:
        sys.dont_write_bytecode = previous
        for name, previous_module in old_modules.items():
            if previous_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module


def canonical_evidence_check(request: BenchmarkInput, prediction: dict) -> bool:
    """A clip-valid timestamp must also reference an actually supplied frame."""
    observations = []
    if request.task == "attention":
        for row in prediction["assessments"]:
            for observation in row["assessment"]["observations"]:
                if observation["camera"] != row["camera"]:
                    raise ValueError("canonical evidence attribution")
                observations.append(observation)
    else:
        observations.extend(prediction["observations"])
        if request.task == "multi_camera":
            for camera, rows in prediction["camera_evidence"].items():
                for observation in rows:
                    if observation["camera"] != camera:
                        raise ValueError("canonical evidence attribution")
                    observations.append(observation)
    for observation in observations:
        timestamp = observation["timestamp_sec"]
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (float, int))
                or not math.isfinite(timestamp)
                or not any(frame.camera == observation["camera"]
                           and abs(frame.timestamp_sec - timestamp) <= 1 / 30 + 1e-9
                           for frame in request.frames)):
            raise ValueError("canonical evidence reference")
    return True


def _validate(request: BenchmarkInput, outcome: BenchmarkOutcome,
              candidate: dict, validator: Any) -> dict:
    from jsonschema import Draft202012Validator

    checks = {"prediction_schema": False, "original_context": False,
              "canonical_evidence": False, "result_schema_context": False,
              "errors": []}
    if outcome.status != "ok" or not isinstance(outcome.prediction, dict):
        checks["errors"].append(outcome.error_code or "prediction_unavailable")
        return checks
    try:
        json.dumps(outcome.prediction, allow_nan=False)
        Draft202012Validator(json.loads(request.schema_json)).validate(outcome.prediction)
        checks["prediction_schema"] = True
    except Exception:
        checks["errors"].append("prediction_schema_invalid")
        return checks
    try:
        validator.validate(outcome.prediction, request.item_id)
        checks["original_context"] = True
    except Exception:
        checks["errors"].append("original_context_invalid")
    try:
        canonical_evidence_check(request, outcome.prediction)
        checks["canonical_evidence"] = True
    except (ValueError, KeyError, TypeError):
        checks["errors"].append("canonical_evidence_invalid")
    try:
        validator.validate_result(candidate)
        checks["result_schema_context"] = True
    except Exception:
        checks["errors"].append("result_schema_context_invalid")
    return checks


def _valid(checks: dict) -> bool:
    return all(checks.get(key) is True for key in
               ("prediction_schema", "original_context", "canonical_evidence", "result_schema_context"))


def _cv_uncertain(outcome: BenchmarkOutcome) -> bool:
    if outcome.status != "ok" or not isinstance(outcome.features, dict):
        return True
    compact = outcome.features.get("compact_state", {})
    return (not compact.get("rule_policy", {}).get("event_classifier_available", False)
            or not compact.get("quality", {}).get("zone_configured", False)
            or any(compact.get("risk_axes", {}).get(axis) is None
                   for axis in ("severity", "imminence", "exposure", "persistence")))


def _safe_route(cv: BenchmarkOutcome, clef: BenchmarkOutcome | None) -> dict:
    """Current CV features supply no validated normal event assessment.

    Route confidence, incident probability and proxy axes cannot prove explicit
    normal + event confidence >= .90 + backend risk <20. Until a contracted,
    validated assessment exists, every provider proposal requires visual review.
    """
    decision = clef.decision if clef and isinstance(clef.decision, dict) else {}
    uncertain = _cv_uncertain(cv) or clef is None or clef.status != "ok"
    probability, confidence = decision.get("incident_probability"), decision.get("route_confidence")
    return {"invoke_vlm": True, "needs_human_review": True,
            "proposed_route": decision.get("proposed_route"),
            "incident_probability": probability, "route_confidence": confidence,
            "actual_route": "invoke_vlm", "normal_assessment_available": False,
            "reason": "upstream_uncertain" if uncertain else "normal_assessment_unavailable",
            "cv_uncertain": _cv_uncertain(cv), "provider_decision": decision}


def _cost(outcomes: dict[str, BenchmarkOutcome]) -> float | None:
    paid = [outcome for name, outcome in outcomes.items() if name in PAID]
    if not paid:
        return None
    values = [outcome.metadata.get("usage_cost_estimate_usd") for outcome in paid]
    return sum(values) if all(value is not None for value in values) else None


def _stage_record(name: str, outcome: BenchmarkOutcome) -> dict:
    """Separate execution/reservation evidence from unobservable invoicing."""
    metadata = outcome.metadata
    invoked = metadata.get("stage_invocation_index_in_run") is not None
    reservations = metadata.get("paid_request_records", [])
    # Ledger entries survive shared-executor timeout/cancellation, unlike adapter
    # metadata. A reservation proves possible billing, not receipt of an HTTP POST.
    if reservations:
        values = [entry.get("usage_cost_estimate_usd") for entry in reservations]
        paid_requests = len(reservations)
    elif name in PAID and "reservation_usd" in metadata:
        values = [metadata.get("usage_cost_estimate_usd")]
        paid_requests = 1
    else:
        values, paid_requests = [], 0
    known = [value for value in values if value is not None]
    response_received = metadata.get("http_status") is not None
    billing_state = ("not_applicable" if name not in PAID else
        "response_received" if response_received else
        "reserved_billing_unknown" if paid_requests else
        "not_reserved_pre_post" if invoked else "not_executed")
    return {"model": outcome.model, "status": outcome.status,
        "error_code": outcome.error_code, "invoked": invoked,
        "latency_ms": outcome.latency_ms, "metadata": metadata,
        "usage": outcome.usage, "decision": outcome.decision,
        "http_response_received": response_received,
        "paid_requests_reserved": paid_requests, "billing_state": billing_state,
        "unknown_billing_requests": sum(value is None for value in values),
        "known_partial_usage_cost_estimate_usd": sum(known) if known else None,
        "actual_invoice_cost_usd": None}


def _record_stages(row: dict, outcomes: dict[str, BenchmarkOutcome]) -> None:
    row["stages"] = {name: _stage_record(name, outcome) for name, outcome in outcomes.items()}
    row["upstream_errors"] = {name: outcome.error_code or "stage_error"
        for name, outcome in outcomes.items()
        if name != "general_vlm" and (outcome.status != "ok" or outcome.error_code)}
    row["errors"].extend(outcome.error_code or "stage_error" for outcome in outcomes.values()
                         if outcome.status != "ok" or outcome.error_code)
    row["estimated_cost_usd"] = _cost(outcomes)
    known = [stage["known_partial_usage_cost_estimate_usd"] for stage in row["stages"].values()
             if stage["known_partial_usage_cost_estimate_usd"] is not None]
    row["known_partial_usage_cost_estimate_usd"] = sum(known) if known else None
    row["unknown_billing_requests"] = sum(stage["unknown_billing_requests"]
                                          for stage in row["stages"].values())
    row["paid_requests_reserved"] = sum(stage["paid_requests_reserved"]
                                        for stage in row["stages"].values())
    row["upstream_failure_count"] = len(row["upstream_errors"])
    row["whole_pipeline_validated"] = (row["validated"] and not row["upstream_errors"]
        and all(name in row["stages"] and row["stages"][name]["invoked"]
                and row["stages"][name]["status"] == "ok"
                and row["stages"][name]["error_code"] is None
                for name in ("local_cv", "clef_direct", "general_vlm"))) \
        if row["condition"] == "cv_llm" else None


def _tokens(outcomes: dict[str, BenchmarkOutcome], key: str) -> int | None:
    values = []
    for name, outcome in outcomes.items():
        if name not in PAID:
            continue
        alternative = "prompt_tokens" if key == "input_tokens" else "completion_tokens"
        values.append(outcome.usage.get(key, outcome.usage.get(alternative)))
    return sum(values) if values and all(value is not None for value in values) else None


class _MemorySampler:
    """Sample host RSS; remote provider GPU memory is never inferred from it."""
    def __init__(self):
        self.peak = None
        self.samples = 0
        self.task = None
        try:
            import psutil
            self.process = psutil.Process()
        except ImportError:
            self.process = None

    async def start(self):
        if self.process is not None:
            self.task = asyncio.create_task(self._sample())

    async def _sample(self):
        while True:
            try:
                memory = self.process.memory_info().rss
                self.peak = max(self.peak or 0, memory)
                self.samples += 1
            except Exception:
                return
            await asyncio.sleep(.02)

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        return {"host_peak_rss_bytes": self.peak, "host_rss_sample_count": self.samples,
                "host_rss_sampling_interval_ms": 20 if self.process is not None else None,
                "provider_gpu_vram_bytes": None, "worker_memory_recorded_separately": True}


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def _labels(prediction: dict | None) -> Any:
    if prediction is None:
        return None
    if "assessments" in prediction:
        return {row["camera"]: {"event_type": row["assessment"]["event_type"],
                                "is_incident": row["assessment"]["is_incident"]}
                for row in prediction["assessments"]}
    return {key: prediction[key] for key in ("event_type", "is_incident", "same_incident")
            if key in prediction}


def _stage_metrics(rows: list[dict], condition: str) -> dict:
    expected = ({"general_vlm"} if condition == "vlm_only" else {"local_cv"}
        if condition == "local_cv" else {"local_cv", "clef_direct"}
        if condition == "clef_direct" else {"local_cv", "clef_direct", "general_vlm"})
    metrics = {}
    for name in sorted(expected):
        stages = [row["stages"][name] for row in rows if name in row["stages"]]
        invoked = [stage for stage in stages if stage["invoked"]]
        costs = [stage["known_partial_usage_cost_estimate_usd"] for stage in stages
                 if stage["known_partial_usage_cost_estimate_usd"] is not None]
        times = [stage["latency_ms"] for stage in invoked if stage["latency_ms"] is not None]
        timing_keys = {key for stage in stages for key in stage["metadata"].get("timings_ms", {})}
        profiles = ("cv_profile", "pose_enabled", "conversion_profile", "transport_profile")
        metrics[name] = {
            "planned_attempts": len(rows), "invocations": len(invoked),
            "ok_invocations": sum(stage["status"] == "ok" and stage["error_code"] is None
                                  for stage in invoked),
            "not_invoked_attempts": len(rows) - len(invoked),
            "http_responses": sum(stage["http_response_received"] for stage in stages),
            "http_statuses": dict(Counter(str(stage["metadata"]["http_status"])
                for stage in stages if stage["http_response_received"])),
            "error_codes": dict(Counter(stage["error_code"] for stage in stages if stage["error_code"])),
            "paid_requests_reserved": sum(stage["paid_requests_reserved"] for stage in stages),
            "unknown_billing_requests": sum(stage["unknown_billing_requests"] for stage in stages),
            "pre_post_failures": sum(stage["billing_state"] == "not_reserved_pre_post"
                                     and stage["status"] != "ok" for stage in stages),
            "billing_states": dict(Counter(stage["billing_state"] for stage in stages)),
            "known_partial_usage_cost_estimate_usd": sum(costs) if costs else None,
            "actual_invoice_cost_usd": None,
            "latency_ms_total": sum(times) if times else None,
            "latency_ms_p50": _percentile(times, .5), "latency_ms_p95": _percentile(times, .95),
            "latency_measurements": len(times),
            "usage_records": [stage["usage"] for stage in invoked],
            "profiles": {key: dict(Counter(stage["metadata"][key]
                if isinstance(stage["metadata"][key], str) else json.dumps(stage["metadata"][key])
                for stage in stages if key in stage["metadata"])) for key in profiles},
            "timings_ms_total": {key: sum(stage["metadata"].get("timings_ms", {}).get(key, 0)
                for stage in stages) for key in sorted(timing_keys)},
            "preprocessing_ms_total": _sum_metadata(stages, "preprocessing_ms"),
            "request_ms_total": _sum_metadata(stages, "request_ms"),
        }
    return metrics


def _sum_metadata(stages: list[dict], key: str) -> float | None:
    values = [stage["metadata"][key] for stage in stages if stage["metadata"].get(key) is not None]
    return sum(values) if values else None


def _aggregate(records: list[dict], budget: PaidBudget, protected_unchanged: bool,
               stop_reason: str | None, blocked: dict, mode: str, repeats: int) -> dict:
    metrics = {}
    for condition in dict.fromkeys(row["condition"] for row in records):
        rows = [row for row in records if row["condition"] == condition]
        applicable = condition in {"vlm_only", "cv_llm"}
        valid = sum(row["validated"] for row in rows)
        structural = sum(row["checks"].get("prediction_schema", False) for row in rows)
        times = [row["latency_ms"] for row in rows if row["latency_ms"] is not None]
        completed = sum(row["status"] != "not_executed" for row in rows)
        costs = [row["estimated_cost_usd"] for row in rows if row["status"] != "not_executed"]
        known_costs = [row["known_partial_usage_cost_estimate_usd"] for row in rows
                       if row["known_partial_usage_cost_estimate_usd"] is not None]
        whole_pipeline = sum(row["whole_pipeline_validated"] is True for row in rows)
        metrics[condition] = {
            "planned_attempts": len(rows), "executed_attempts": completed,
            "valid_frozen_submissions": valid,
            "final_output_validated": valid,
            "whole_pipeline_validated": whole_pipeline if condition == "cv_llm" else None,
            "whole_pipeline_validation_rate_all_planned": whole_pipeline / len(rows)
                if condition == "cv_llm" else None,
            "whole_pipeline_validation_rate_executed": whole_pipeline / completed
                if condition == "cv_llm" and completed else None,
            "upstream_failure_attempts": sum(bool(row["upstream_errors"]) for row in rows),
            "upstream_failure_count": sum(row["upstream_failure_count"] for row in rows),
            "valid_fallback_outputs": sum(row["validated"] and bool(row["upstream_errors"])
                                          for row in rows),
            "stages": _stage_metrics(rows, condition),
            "schema_applicable": applicable,
            "prediction_schema_rate_all_planned": structural / len(rows) if applicable else None,
            "schema_and_evidence_rate_all_planned": valid / len(rows) if applicable else None,
            "schema_and_evidence_rate_executed": valid / completed if applicable and completed else None,
            "statuses": dict(Counter(row["status"] for row in rows)),
            "routing_skips": sum(row.get("route", {}).get("actual_route") == "skip" for row in rows),
            "error_codes": dict(Counter(code for row in rows for code in row["errors"])),
            "latency_ms_p50": _percentile(times, .5), "latency_ms_p95": _percentile(times, .95),
            "latency_measurements": len(times),
            "latency_within_120s": sum(value <= 120_000 for value in times),
            "estimated_cost_usd": sum(costs) if costs and all(cost is not None for cost in costs) else None,
            "known_partial_usage_cost_estimate_usd": sum(known_costs) if known_costs else None,
            "paid_requests_reserved": sum(row["paid_requests_reserved"] for row in rows),
            "unknown_billing_requests": sum(row["unknown_billing_requests"] for row in rows),
            "actual_invoice_cost_usd": None,
            "event_accuracy": None, "event_miss_rate": None, "false_alarm_rate": None,
            "evidence_correctness": None, "risk_error": None,
            "predicted_event_counts": dict(Counter(
                label for row in rows if row["prediction"] is not None
                for label in ([assessment["assessment"]["event_type"]
                               for assessment in row["prediction"]["assessments"]]
                              if "assessments" in row["prediction"]
                              else [row["prediction"]["event_type"]]))),
        }
    pairs = {}
    for row in records:
        if row["condition"] in {"vlm_only", "cv_llm"}:
            pairs.setdefault((row["item_id"], row["repeat"]), {})[row["condition"]] = row
    comparisons = []
    for (item, repeat), pair in pairs.items():
        if set(pair) != {"vlm_only", "cv_llm"}:
            continue
        direct, pipeline = pair["vlm_only"], pair["cv_llm"]
        comparable = direct["validated"] and pipeline["validated"]
        comparisons.append({"item_id": item, "repeat": repeat,
            "same_canonical_input": (direct["input_digest"] == pipeline["input_digest"])
                if direct["input_digest"] is not None and pipeline["input_digest"] is not None else None,
            "direct_status": direct["status"], "pipeline_status": pipeline["status"],
            "direct_labels": _labels(direct["prediction"]),
            "pipeline_labels": _labels(pipeline["prediction"]),
            "label_agreement": _labels(direct["prediction"]) == _labels(pipeline["prediction"])
                if comparable else None,
            "routing_skip": pipeline.get("route", {}).get("actual_route") == "skip",
            "upstream_errors": pipeline["upstream_errors"],
            "whole_pipeline_validated": pipeline["whole_pipeline_validated"],
            "ground_truth_error_attribution": None,
            "interpretation": "Agreement is not accuracy; an upstream omission is not a VLM failure."})
    completed = sum(row["status"] != "not_executed" for row in records)
    budget_summary = budget.summary()
    known = budget_summary.get("usage_cost_known_requests", 0)
    budget_summary["known_partial_usage_cost_estimate_usd"] = (
        budget_summary["usage_cost_estimate_usd"] if known else None)
    budget_summary["unknown_billing_requests"] = budget_summary["requests"] - known
    if not known or known != budget_summary["requests"]:
        budget_summary["usage_cost_estimate_usd"] = None
    return {"benchmark_version": "477-reasoning-v1", "mode": mode, "repeats": repeats,
        "status": "incomplete" if stop_reason or completed < len(records) or any(
            row["status"] in {"error", "invalid_output"} or row["upstream_errors"]
            for row in records) else "executed",
        "planned_attempts": len(records), "executed_attempts": completed,
        "stop_reason": stop_reason, "provider_circuit_breakers": blocked,
        "protected_inputs_unchanged": protected_unchanged,
        "budget": budget_summary, "metrics": metrics, "comparisons": comparisons,
        "unmeasurable_metrics": {key: {"value": None, "reason": reason}
                                 for key, reason in UNMEASURABLE.items()},
        "scope": {"unique_source_videos_available": 6, "public_items_available": 7,
                  "small_demo_evaluation": True, "generalization_supported": False,
                  "source_scenario_groups_resplit": False},
        "acceptance_criteria": {"schema_and_canonical_evidence_rate_all_planned": 1,
                                "whole_pipeline_validation_rate_all_planned": 1,
                                "demo_end_to_end_latency_ms_per_item": 120_000,
                                "protected_input_changes": 0, "maximum_paid_usd": 5,
                                "accuracy_threshold": None},
        "attempts": records}


async def run_baseline(*, root: Path, output: Path, adapters: dict,
                       budget: PaidBudget, items: tuple[str, ...],
                       repeats: int = 3, mode: str = "suite") -> dict:
    """Execute selected real conditions sequentially and save all planned attempts."""
    if (mode not in MODES or isinstance(repeats, bool)
            or not isinstance(repeats, int) or not 1 <= repeats <= 3):
        raise ValueError("invalid baseline mode or repetition count")
    if not items or len(set(items)) != len(items) or any(
            item not in {f"ITEM_{i:02d}" for i in range(1, 8)} for item in items):
        raise ValueError("invalid public item selection")
    required = ({"general_vlm"} if mode == "vlm" else {"local_cv"} if mode == "local_cv"
                else {"local_cv", "clef_direct"} if mode == "clef"
                else {"local_cv", "clef_direct", "general_vlm"})
    for name in required:
        adapter = adapters.get(name)
        if adapter is None or adapter.name != name or any(
                str(value).lower().startswith("mock") for value in
                (adapter.name, adapter.model, type(adapter).__name__)):
            raise ValueError("real baseline requires configured real adapters")
    root = Path(root).resolve()
    output = assert_output_outside_inputs(root, output)
    if output.exists():
        raise ValueError("baseline output already exists; choose a new run directory")
    package = root / "477_modeling_benchmark_v1"
    before = await asyncio.to_thread(snapshot_protected, root)
    validator = await asyncio.to_thread(_original_validator, package)
    output.mkdir(parents=True)
    _write_json(output / "protected-before.json", before)
    calls, provider_requests, blocked = Counter(), Counter(), {}
    stop_reason = None
    records = []

    async def call(name: str, request: BenchmarkInput) -> BenchmarkOutcome:
        nonlocal stop_reason
        adapter = adapters[name]
        if name in blocked:
            return BenchmarkOutcome(adapter=name, model=adapter.model, status="error",
                error_code="provider_unavailable", metadata={"not_executed": True,
                "circuit_breaker_reason": blocked[name], "needs_human_review": True})
        calls[name] += 1
        ledger_offset = len(budget.state["requests"])
        try:
            outcome = await execute_benchmark(adapter, request, timeout_sec=TIMEOUTS[name])
        except asyncio.CancelledError:
            # Persist the current attempt and all unexecuted planned attempts.
            stop_reason = "cancelled"
            outcome = BenchmarkOutcome(adapter=name, model=adapter.model, status="error",
                error_code="cancelled", metadata={"needs_human_review": True})
        paid_records = [{key: entry[key] for key in
            ("provider", "reserved_usd", "usage_cost_estimate_usd", "status", "usage")}
            for entry in budget.state["requests"][ledger_offset:]]
        if paid_records:
            outcome.metadata["paid_request_records"] = paid_records
            outcome.metadata.setdefault("reservation_usd", sum(entry["reserved_usd"] for entry in paid_records))
            costs = [entry["usage_cost_estimate_usd"] for entry in paid_records]
            outcome.metadata.setdefault("usage_cost_estimate_usd",
                sum(costs) if all(cost is not None for cost in costs) else None)
            if not outcome.usage and len(paid_records) == 1:
                outcome.usage = paid_records[0]["usage"]
        outcome.metadata["stage_invocation_index_in_run"] = calls[name]
        outcome.metadata["first_stage_invocation_in_run"] = calls[name] == 1
        outcome.metadata["warm_start_verified"] = False
        if name in PAID and "reservation_usd" in outcome.metadata:
            provider_requests[name] += 1
            outcome.metadata["provider_request_index_in_run"] = provider_requests[name]
            outcome.metadata["first_provider_request_in_run"] = provider_requests[name] == 1
        if outcome.error_code == "budget_exhausted":
            stop_reason = "budget_exhausted"
        elif outcome.metadata.get("http_status") in UNAVAILABLE_HTTP or outcome.error_code in {
                "credentials_missing", "unsupported_model"}:
            blocked[name] = {"error_code": outcome.error_code,
                             "http_status": outcome.metadata.get("http_status")}
        return outcome

    for item_id in items:
        for repeat in range(1, repeats + 1):
            for condition in MODES[mode]:
                attempt_id = f"{item_id}-r{repeat:02d}-{condition}"
                row = {"attempt_id": attempt_id, "item_id": item_id, "repeat": repeat,
                       "condition": condition, "status": "not_executed", "validated": False,
                       "checks": {}, "prediction": None, "input_digest": None,
                       "input_fingerprint": None, "source_groups": [], "route": {},
                       "stages": {}, "errors": [], "upstream_errors": {},
                       "latency_ms": None, "estimated_cost_usd": None,
                       "actual_invoice_cost_usd": None, "human_grading": None,
                       "whole_pipeline_validated": False if condition == "cv_llm" else None,
                       "upstream_failure_count": 0, "paid_requests_reserved": 0,
                       "unknown_billing_requests": 0,
                       "known_partial_usage_cost_estimate_usd": None,
                       "needs_human_review": True}
                request, outcomes, common, frozen = None, {}, {}, None
                if stop_reason is not None or condition == "vlm_only" and "general_vlm" in blocked:
                    row["errors"].append(stop_reason or "provider_unavailable")
                else:
                    started = perf_counter()
                    memory = _MemorySampler()
                    await memory.start()
                    try:
                        request, decoding_ms = await asyncio.to_thread(load_benchmark_input, package, item_id)
                        if request.features_json is not None:
                            raise ValueError("canonical input cannot contain supplied features")
                        row.update(status="executed", input_digest=await asyncio.to_thread(
                            lambda: request.input_digest),
                            input_fingerprint=json.loads(request.fingerprint_json),
                            source_groups=sorted(set(json.loads(request.fingerprint_json)["media_sha256"].values())),
                            preprocessing_decode_ms=decoding_ms,
                            frame_count=len(request.frames), raw_rgb_bytes=sum(len(frame.rgb24) for frame in request.frames))
                        if condition == "vlm_only":
                            outcomes["general_vlm"] = await call("general_vlm", request)
                        else:
                            cv = outcomes["local_cv"] = await call("local_cv", request)
                            if condition != "local_cv" and stop_reason is None:
                                if cv.status == "ok" and cv.features is not None:
                                    clef_input = replace(request, features_json=json.dumps(cv.features,
                                        ensure_ascii=False, allow_nan=False, separators=(",", ":")))
                                    outcomes["clef_direct"] = await call("clef_direct", clef_input)
                                    clef_input = None
                                else:
                                    outcomes["clef_direct"] = BenchmarkOutcome(adapter="clef_direct",
                                        model=adapters["clef_direct"].model, status="error",
                                        error_code="upstream_cv_unavailable", metadata={"not_executed": True,
                                        "needs_human_review": True})
                                row["route"] = _safe_route(cv, outcomes["clef_direct"])
                                if condition == "cv_llm" and stop_reason is None:
                                    if row["route"]["invoke_vlm"]:
                                        outcomes["general_vlm"] = await call("general_vlm", request)
                                    else:
                                        row["status"] = "routing_skip"
                        row["model_outputs_ms"] = (perf_counter() - started) * 1000
                        _record_stages(row, outcomes)
                        final = outcomes.get("general_vlm")
                        if final is not None:
                            candidate = {"benchmark_version": "477-reasoning-v1", "pipeline": condition,
                                "run_id": attempt_id, "item_id": item_id, "model_id": final.model,
                                "runtime_config": {"stages": row["stages"], "repeat": repeat,
                                    "input_mode": "canonical_64_pixels_no_cv_features_for_vlm",
                                    "decode_ms": row["preprocessing_decode_ms"], "route": row["route"],
                                    "actual_invoice_cost_usd": None},
                                "input_fingerprint": row["input_fingerprint"], "prediction": final.prediction,
                                "human_grading": None, "latency_ms": row["model_outputs_ms"],
                                "estimated_cost_usd": row["estimated_cost_usd"],
                                "input_tokens": _tokens(outcomes, "input_tokens"),
                                "output_tokens": _tokens(outcomes, "output_tokens")}
                            check_started = perf_counter()
                            row["checks"] = await asyncio.to_thread(_validate, request, final, candidate, validator)
                            row["validation_ms"] = (perf_counter() - check_started) * 1000
                            row["validated"] = _valid(row["checks"])
                            row["errors"].extend(row["checks"]["errors"])
                            row["status"] = "ok" if row["validated"] else "error" if final.status != "ok" else "invalid_output"
                            if row["validated"]:
                                row["prediction"], frozen = final.prediction, candidate
                        elif row["status"] != "routing_skip":
                            row["status"] = "observed" if all(outcome.status == "ok" for outcome in outcomes.values()) else "error"
                        for name, outcome in outcomes.items():
                            mapped = replace(outcome, metadata={**outcome.metadata,
                                "estimated_cost_usd": outcome.metadata.get("usage_cost_estimate_usd")})
                            common[name] = common_assessments(request, mapped,
                                validated=row["validated"] and name == "general_vlm",
                                force_review=condition == "cv_llm" and row["route"].get("needs_human_review", True))
                    except Exception:
                        # Never persist arbitrary exception strings (may contain credentials).
                        row["status"] = "error"
                        row["validated"] = False
                        row["prediction"], frozen = None, None
                        row["errors"].append("evaluation_or_preprocessing_error")
                        for name, outcome in outcomes.items():
                            if outcome.error_code and outcome.error_code not in row["errors"]:
                                row["errors"].append(outcome.error_code)
                    finally:
                        row["latency_ms"] = (perf_counter() - started) * 1000
                        row["memory"] = await memory.stop()
                    if frozen is not None:
                        frozen["latency_ms"] = row["latency_ms"]
                        frozen["runtime_config"].update(memory=row["memory"], validation_ms=row["validation_ms"],
                                                       end_to_end_ms=row["latency_ms"])
                artifact_started = perf_counter()
                # Also retain partial-stage accounting after evaluation exceptions.
                _record_stages(row, outcomes)
                if frozen is not None:
                    frozen["runtime_config"].update(
                        whole_pipeline_validated=row["whole_pipeline_validated"],
                        upstream_errors=row["upstream_errors"],
                        known_partial_usage_cost_estimate_usd=row["known_partial_usage_cost_estimate_usd"],
                        unknown_billing_requests=row["unknown_billing_requests"])
                for name, outcome in outcomes.items():
                    _write_json(output / "raw" / f"{attempt_id}-{name}.json", asdict(outcome))
                _write_json(output / "common" / f"{attempt_id}.json", common)
                if frozen is not None:
                    _write_json(output / "submissions" / f"{attempt_id}.json", frozen)
                row["artifact_write_ms_excluding_diagnostic"] = (perf_counter() - artifact_started) * 1000
                row["errors"] = list(dict.fromkeys(row["errors"]))
                _write_json(output / "diagnostics" / f"{attempt_id}.json", row)
                records.append(row)
                # Avoid retaining 380 MiB frame payloads across conditions.
                request, outcomes, common, frozen = None, {}, {}, None

    after = await asyncio.to_thread(snapshot_protected, root)
    protected_unchanged = before == after
    _write_json(output / "protected-after.json", after)
    summary = _aggregate(records, budget, protected_unchanged, stop_reason, blocked, mode, repeats)
    if not protected_unchanged:
        summary["status"] = "incomplete"
        summary["stop_reason"] = "protected_input_changed"
    _write_json(output / "summary.json", summary)
    _write_json(output / "failures.json", [row for row in records if row["errors"] or not row["validated"]])
    fields = ("attempt_id", "item_id", "repeat", "condition", "status", "validated", "latency_ms",
              "whole_pipeline_validated", "upstream_failure_count", "paid_requests_reserved",
              "known_partial_usage_cost_estimate_usd", "unknown_billing_requests",
              "estimated_cost_usd", "actual_invoice_cost_usd", "errors", "upstream_errors", "stages")
    with (output / "evaluation.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in records:
            writer.writerow({key: json.dumps(_scrub(row[key]), ensure_ascii=False)
                             if isinstance(row[key], (dict, list)) else _scrub(row[key]) for key in fields})
    return summary

"""Explicit synthetic unit fixtures; no provider or actual benchmark inference."""
from copy import deepcopy
import asyncio
import csv
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.eval import benchmark_baseline as baseline
from app.models.benchmark_media import canonical_loader
from app.models.budget import PaidBudget
from app.schemas.benchmark import BenchmarkInput, BenchmarkOutcome, CanonicalFrame

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mock_request():
    item = canonical_loader(ROOT / "477_modeling_benchmark_v1").load_item("ITEM_01")
    # One shared synthetic RGB bytes object keeps this test below 7 MiB.
    pixels = bytes(1920 * 1080 * 3)
    return BenchmarkInput(item_id="ITEM_01", task="single", prompt=item["prompt"],
        schema_json=json.dumps(item["response_schema"]), fingerprint_json=json.dumps(item["input_fingerprint"]),
        frames=tuple(CanonicalFrame("CAM_01", float(i), pixels) for i in range(64)))


@pytest.fixture
def mock_prediction():
    return {"event_type": "collapse", "is_incident": True,
            "observations": [{"camera": "CAM_01", "timestamp_sec": 0.0,
                              "description": "Synthetic unit-test observation."}],
            "temporal_summary": "Synthetic unit-test sequence.",
            "risk": {"severity": .7, "imminence": .7, "exposure": .2, "persistence": .1},
            "confidence": .8, "uncertainties": ["Synthetic test only."],
            "reason": "Synthetic unit-test reason.", "human_review_required": True}


def mock_cv_features(*, measured=False):
    return {"compact_state": {"rule_policy": {"event_classifier_available": measured},
        "quality": {"zone_configured": measured}, "risk_axes": {
            key: .1 if measured else None for key in
            ("severity", "imminence", "exposure", "persistence")}}}


def mock_clef_decision(*, skip=False):
    return {"invoke_vlm": not skip, "proposed_route": "no_action" if skip else "invoke_vlm",
            "route_confidence": .95, "incident_probability": .05 if skip else .8}


@pytest.fixture
def mock_setup(monkeypatch, tmp_path, mock_request, mock_prediction):
    calls = []
    adapters = {"local_cv": SimpleNamespace(name="local_cv", model="yolo26s.pt"),
                "clef_direct": SimpleNamespace(name="clef_direct", model="clef"),
                "general_vlm": SimpleNamespace(name="general_vlm", model="deepseek-flash")}
    replies = {"local_cv": BenchmarkOutcome("local_cv", "yolo26s.pt", features=mock_cv_features()),
               "clef_direct": BenchmarkOutcome("clef_direct", "clef", decision=mock_clef_decision(),
                   usage={"input_tokens": 100, "output_tokens": 10},
                   metadata={"usage_cost_estimate_usd": .000024, "reservation_usd": .03145728}),
               "general_vlm": BenchmarkOutcome("general_vlm", "deepseek-flash",
                   prediction=mock_prediction, raw_response={"synthetic_test_response": mock_prediction},
                   usage={"prompt_tokens": 100, "completion_tokens": 50},
                   metadata={"usage_cost_estimate_usd": .00009, "reservation_usd": .0685824})}

    async def mock_execute(adapter, request, timeout_sec):
        calls.append((adapter.name, request.features_json, timeout_sec, request.frames))
        return deepcopy(replies[adapter.name])

    # Original schema validation still runs; slow ffprobe/context calls are explicit unit mocks.
    mock_validator = SimpleNamespace(validate=lambda prediction, item: True,
                                     validate_result=lambda result: True)
    monkeypatch.setattr(baseline, "load_benchmark_input", lambda package, item:
                        (replace(mock_request, item_id=item), 12.0))
    monkeypatch.setattr(baseline, "snapshot_protected", lambda root: {"synthetic_input": "unchanged"})
    monkeypatch.setattr(baseline, "_original_validator", lambda package: mock_validator)
    monkeypatch.setattr(baseline, "execute_benchmark", mock_execute)
    # Input hashing is separately covered by execution-contract tests.
    monkeypatch.setattr(BenchmarkInput, "input_digest", property(lambda self: "synthetic_canonical_digest"))
    budget = PaidBudget(tmp_path / "budget.json")

    async def run(*, mode="suite", items=("ITEM_01",), repeats=1, output=None):
        return await baseline.run_baseline(root=tmp_path, output=output or tmp_path / "run",
            adapters=adapters, budget=budget, items=items, repeats=repeats, mode=mode)

    return SimpleNamespace(run=run, replies=replies, calls=calls, adapters=adapters,
                           budget=budget, root=tmp_path, validator=mock_validator)


@pytest.mark.asyncio
async def test_suite_pixel_inputs_remain_identical_and_cv_features_only_reach_clef(mock_setup):
    result = await mock_setup.run()
    assert result["planned_attempts"] == 2
    assert [call[0] for call in mock_setup.calls] == ["general_vlm", "local_cv", "clef_direct", "general_vlm"]
    assert [call[1] is None for call in mock_setup.calls] == [True, True, False, True]
    assert all(call[3] is mock_setup.calls[0][3] for call in mock_setup.calls)
    assert result["comparisons"][0]["same_canonical_input"] is True
    assert result["comparisons"][0]["label_agreement"] is True
    assert result["metrics"]["cv_llm"]["schema_and_evidence_rate_all_planned"] == 1
    assert len(list((mock_setup.root / "run/submissions").glob("*.json"))) == 2
    common = json.loads((mock_setup.root / "run/common/ITEM_01-r01-cv_llm.json").read_text())
    assert common["general_vlm"][0]["assessment"]["needs_human_review"] is True
    assert common["general_vlm"][0]["backend_risk_score"] == 51


@pytest.mark.asyncio
async def test_mock_policy_boundary_omission_remains_in_pipeline_denominator(mock_setup, monkeypatch):
    # Explicit policy-boundary simulation only: current real CV cannot prove
    # a normal event. This tests omission accounting, not real routing judgment.
    def mock_route_boundary(cv, clef):
        return {"invoke_vlm": False, "needs_human_review": True,
                "actual_route": "skip", "synthetic_policy_boundary": True}
    monkeypatch.setattr(baseline, "_safe_route", mock_route_boundary)
    result = await mock_setup.run()
    metrics = result["metrics"]["cv_llm"]
    assert metrics["planned_attempts"] == 1
    assert metrics["executed_attempts"] == 1
    assert metrics["routing_skips"] == 1
    assert metrics["schema_and_evidence_rate_all_planned"] == 0
    assert result["comparisons"][0]["label_agreement"] is None
    assert result["comparisons"][0]["routing_skip"] is True
    assert result["attempts"][1]["prediction"] is None
    assert len(list((mock_setup.root / "run/submissions").glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_unmeasured_cv_overrides_clef_skip_proposal(mock_setup):
    mock_setup.replies["clef_direct"].decision = mock_clef_decision(skip=True)
    result = await mock_setup.run(mode="pipeline")
    route = result["attempts"][0]["route"]
    assert route["proposed_route"] == "no_action"
    assert route["actual_route"] == "invoke_vlm"
    assert route["cv_uncertain"] is True
    assert result["attempts"][0]["validated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["local_cv", "clef_direct"])
async def test_upstream_failures_fallback_and_are_not_assigned_to_vlm(mock_setup, failed):
    mock_setup.replies[failed] = BenchmarkOutcome(failed, mock_setup.adapters[failed].model,
        status="error", error_code="worker_error" if failed == "local_cv" else "provider_transport_error")
    result = await mock_setup.run(mode="pipeline")
    row = result["attempts"][0]
    assert row["validated"] is True
    assert row["stages"]["general_vlm"]["error_code"] is None
    assert failed in row["upstream_errors"]
    assert row["route"]["needs_human_review"] is True
    assert row["whole_pipeline_validated"] is False
    assert result["status"] == "incomplete"
    metrics = result["metrics"]["cv_llm"]
    assert metrics["final_output_validated"] == 1
    assert metrics["whole_pipeline_validated"] == 0
    assert metrics["whole_pipeline_validation_rate_all_planned"] == 0
    assert metrics["valid_fallback_outputs"] == 1
    diagnostic = json.loads((mock_setup.root / "run/diagnostics/ITEM_01-r01-cv_llm.json").read_text())
    assert diagnostic["whole_pipeline_validated"] is False
    with (mock_setup.root / "run/evaluation.csv").open(newline="", encoding="utf-8") as stream:
        csv_row = next(csv.DictReader(stream))
    assert csv_row["validated"] == "True"
    assert csv_row["whole_pipeline_validated"] == "False"
    assert failed in json.loads(csv_row["upstream_errors"])
    if failed == "local_cv":
        assert [call[0] for call in mock_setup.calls] == ["local_cv", "general_vlm"]
        assert row["stages"]["clef_direct"]["metadata"]["not_executed"] is True


@pytest.mark.asyncio
async def test_noncanonical_time_fails_even_if_original_context_accepts(mock_setup):
    mock_setup.replies["general_vlm"].prediction["observations"][0]["timestamp_sec"] = .123
    result = await mock_setup.run(mode="vlm")
    row = result["attempts"][0]
    assert row["checks"]["prediction_schema"] is True
    assert row["checks"]["original_context"] is True
    assert row["checks"]["canonical_evidence"] is False
    assert row["prediction"] is None
    assert row["status"] == "invalid_output"
    assert not (mock_setup.root / "run/submissions").exists()
    raw = json.loads((mock_setup.root / "run/raw/ITEM_01-r01-vlm_only-general_vlm.json").read_text())
    assert raw["prediction"]["observations"][0]["timestamp_sec"] == .123
    assert result["metrics"]["vlm_only"]["prediction_schema_rate_all_planned"] == 1
    assert result["metrics"]["vlm_only"]["schema_and_evidence_rate_all_planned"] == 0
    common = json.loads((mock_setup.root / "run/common/ITEM_01-r01-vlm_only.json").read_text())
    assert common["general_vlm"][0]["assessment"]["needs_human_review"] is True
    assert common["general_vlm"][0]["backend_risk_score"] is None
    assert common["general_vlm"][0]["backend_risk_level"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_missing_annotation_and_cost_are_null(mock_setup):
    mock_setup.replies["general_vlm"].metadata.pop("usage_cost_estimate_usd")
    result = await mock_setup.run(mode="vlm")
    assert all(metric["value"] is None and metric["reason"]
               for metric in result["unmeasurable_metrics"].values())
    assert result["metrics"]["vlm_only"]["estimated_cost_usd"] is None
    assert result["metrics"]["vlm_only"]["actual_invoice_cost_usd"] is None
    assert result["budget"]["usage_cost_estimate_usd"] is None
    submitted = json.loads((mock_setup.root / "run/submissions/ITEM_01-r01-vlm_only.json").read_text())
    assert submitted["estimated_cost_usd"] is None
    assert submitted["human_grading"] is None


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_paid_run_keeps_remaining_attempts(mock_setup):
    mock_setup.replies["general_vlm"] = BenchmarkOutcome("general_vlm", "deepseek-flash",
        status="error", error_code="budget_exhausted")
    result = await mock_setup.run(repeats=3)
    assert result["stop_reason"] == "budget_exhausted"
    assert result["planned_attempts"] == 6
    assert result["executed_attempts"] == 1
    assert len(mock_setup.calls) == 1
    assert result["metrics"]["vlm_only"]["schema_and_evidence_rate_all_planned"] == 0
    assert len(list((mock_setup.root / "run/diagnostics").glob("*.json"))) == 6
    assert result["attempts"][-1]["status"] == "not_executed"


@pytest.mark.asyncio
async def test_provider_auth_circuit_breaker_keeps_cv_independent(mock_setup):
    mock_setup.replies["general_vlm"] = BenchmarkOutcome("general_vlm", "deepseek-flash",
        status="error", error_code="provider_http_error", metadata={"http_status": 401})
    result = await mock_setup.run(repeats=2)
    assert [call[0] for call in mock_setup.calls].count("general_vlm") == 1
    assert [call[0] for call in mock_setup.calls].count("local_cv") == 2
    assert [call[0] for call in mock_setup.calls].count("clef_direct") == 2
    assert result["metrics"]["vlm_only"]["planned_attempts"] == 2
    assert result["metrics"]["vlm_only"]["executed_attempts"] == 1
    assert result["metrics"]["cv_llm"]["executed_attempts"] == 2
    assert result["provider_circuit_breakers"]["general_vlm"]["http_status"] == 401


@pytest.mark.asyncio
async def test_transport_failures_remain_denominator_without_auto_retry(mock_setup):
    mock_setup.replies["general_vlm"] = BenchmarkOutcome("general_vlm", "deepseek-flash",
        status="error", error_code="provider_transport_error")
    result = await mock_setup.run(mode="vlm", repeats=3)
    assert len(mock_setup.calls) == 3
    assert result["metrics"]["vlm_only"]["planned_attempts"] == 3
    assert result["metrics"]["vlm_only"]["error_codes"]["provider_transport_error"] == 3
    assert result["metrics"]["vlm_only"]["schema_and_evidence_rate_executed"] == 0


@pytest.mark.asyncio
async def test_decode_failure_preserved_without_model_calls(mock_setup, monkeypatch):
    def mock_failed_decode(*args):
        raise RuntimeError("Do not persist arbitrary exception payloads")
    monkeypatch.setattr(baseline, "load_benchmark_input", mock_failed_decode)
    result = await mock_setup.run(mode="vlm")
    assert not mock_setup.calls
    assert result["attempts"][0]["errors"] == ["evaluation_or_preprocessing_error"]
    assert result["attempts"][0]["prediction"] is None
    assert result["metrics"]["vlm_only"]["schema_and_evidence_rate_all_planned"] == 0


@pytest.mark.asyncio
async def test_protected_output_rejected_before_any_model_call(mock_setup):
    with pytest.raises(ValueError, match="protected"):
        await mock_setup.run(output=mock_setup.root / "477_modeling_benchmark_v1" / "results")
    assert not mock_setup.calls


@pytest.mark.asyncio
async def test_existing_run_cannot_be_overwritten(mock_setup):
    await mock_setup.run(mode="vlm")
    with pytest.raises(ValueError, match="already exists"):
        await mock_setup.run(mode="vlm")
    assert len(mock_setup.calls) == 1


@pytest.mark.asyncio
async def test_mock_model_slot_is_forbidden(mock_setup):
    mock_setup.adapters["general_vlm"].model = "mock_vlm"
    with pytest.raises(ValueError, match="real adapters"):
        await mock_setup.run(mode="vlm")
    assert not mock_setup.calls


@pytest.mark.asyncio
async def test_raw_response_and_csv_redact_credential_echo(mock_setup, monkeypatch):
    monkeypatch.setenv("VLM_API_KEY", "synthetic-unit-test-secret")
    mock_setup.replies["general_vlm"].raw_response = {"error": "synthetic-unit-test-secret"}
    await mock_setup.run(mode="vlm")
    for path in (mock_setup.root / "run").rglob("*"):
        if path.is_file():
            assert "synthetic-unit-test-secret" not in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_independent_cv_and_clef_do_not_invent_event_prediction(mock_setup):
    cv = await mock_setup.run(mode="local_cv", output=mock_setup.root / "cv")
    clef = await mock_setup.run(mode="clef", output=mock_setup.root / "clef")
    assert cv["attempts"][0]["status"] == "observed"
    assert clef["attempts"][0]["status"] == "observed"
    assert cv["attempts"][0]["prediction"] is None
    assert clef["attempts"][0]["prediction"] is None
    assert cv["metrics"]["local_cv"]["schema_and_evidence_rate_all_planned"] is None
    assert clef["metrics"]["clef_direct"]["event_accuracy"] is None


def test_original_validator_import_creates_no_protected_pycache():
    package = ROOT / "477_modeling_benchmark_v1"
    before = set(package.rglob("*"))
    previous = {name: __import__("sys").modules.get(name)
                for name in ("benchmark_common", "load_model_input", "validate_prediction")}
    validator = baseline._original_validator(package)
    assert callable(validator.validate) and callable(validator.validate_result)
    assert set(package.rglob("*")) == before
    assert all(__import__("sys").modules.get(name) is module for name, module in previous.items())


@pytest.mark.parametrize("offset,accepted", [(.03, True), (.034, False)])
def test_canonical_evidence_tolerance_is_fixed(mock_request, mock_prediction, offset, accepted):
    mock_prediction["observations"][0]["timestamp_sec"] = offset
    if accepted:
        assert baseline.canonical_evidence_check(mock_request, mock_prediction) is True
    else:
        with pytest.raises(ValueError, match="canonical"):
            baseline.canonical_evidence_check(mock_request, mock_prediction)


@pytest.mark.parametrize("extra_offset,accepted", [(0.0, True), (1e-6, False)])
def test_canonical_evidence_float_boundary_preserves_one_frame_tolerance(
        mock_request, mock_prediction, extra_offset, accepted):
    # 0.1 - 2/30 exceeds 1/30 by representation error alone.
    frames = tuple(replace(frame, timestamp_sec=2 / 30 if index == 0 else float(index))
                   for index, frame in enumerate(mock_request.frames))
    request = replace(mock_request, frames=frames)
    mock_prediction["observations"][0]["timestamp_sec"] = .1 + extra_offset
    if accepted:
        assert baseline.canonical_evidence_check(request, mock_prediction) is True
    else:
        with pytest.raises(ValueError, match="canonical"):
            baseline.canonical_evidence_check(request, mock_prediction)


def test_actual_frozen_result_schema_and_context_are_applied(mock_request, mock_prediction):
    validator = baseline._original_validator(ROOT / "477_modeling_benchmark_v1")
    outcome = BenchmarkOutcome("general_vlm", "deepseek-flash", prediction=mock_prediction)
    candidate = {"benchmark_version": "477-reasoning-v1", "pipeline": "vlm_only",
        "run_id": "synthetic-unit-test", "item_id": "ITEM_01", "model_id": "deepseek-flash",
        "runtime_config": {}, "input_fingerprint": json.loads(mock_request.fingerprint_json),
        "prediction": mock_prediction, "human_grading": None, "latency_ms": None,
        "estimated_cost_usd": None, "input_tokens": None, "output_tokens": None}
    checks = baseline._validate(mock_request, outcome, candidate, validator)
    assert baseline._valid(checks)
    candidate["unexpected_top_level_field"] = "Must not enter a frozen submission"
    checks = baseline._validate(mock_request, outcome, candidate, validator)
    assert checks["prediction_schema"] is True
    assert checks["original_context"] is True
    assert checks["result_schema_context"] is False


@pytest.mark.asyncio
async def test_changed_protected_input_is_reported_not_passed(mock_setup, monkeypatch):
    snapshots = iter([{"synthetic_input": "before"}, {"synthetic_input": "after"}])
    monkeypatch.setattr(baseline, "snapshot_protected", lambda root: next(snapshots))
    result = await mock_setup.run(mode="vlm")
    assert result["protected_inputs_unchanged"] is False
    assert result["status"] == "incomplete"
    assert result["stop_reason"] == "protected_input_changed"


@pytest.mark.asyncio
async def test_invalid_provider_schema_preserves_failure_and_review(mock_setup):
    mock_setup.replies["general_vlm"].prediction["risk"]["severity"] = None
    result = await mock_setup.run(mode="vlm")
    row = result["attempts"][0]
    assert row["checks"]["prediction_schema"] is False
    assert row["status"] == "invalid_output"
    assert row["prediction"] is None
    assert row["needs_human_review"] is True
    assert not (mock_setup.root / "run/submissions").exists()


@pytest.mark.asyncio
async def test_partial_pipeline_usage_cost_is_unknown_not_free(mock_setup):
    mock_setup.replies["clef_direct"].metadata["usage_cost_estimate_usd"] = None
    result = await mock_setup.run(mode="pipeline")
    assert result["attempts"][0]["estimated_cost_usd"] is None
    assert result["metrics"]["cv_llm"]["estimated_cost_usd"] is None
    assert result["attempts"][0]["known_partial_usage_cost_estimate_usd"] == .00009
    assert result["metrics"]["cv_llm"]["known_partial_usage_cost_estimate_usd"] == .00009
    assert result["metrics"]["cv_llm"]["unknown_billing_requests"] == 1
    submitted = json.loads((mock_setup.root / "run/submissions/ITEM_01-r01-cv_llm.json").read_text())
    assert submitted["estimated_cost_usd"] is None


def test_attention_and_multicamera_evidence_keep_camera_attribution(mock_request, mock_prediction):
    attention = replace(mock_request, task="attention")
    wrong_attention = {"assessments": [{"camera": "CAM_02", "assessment": mock_prediction}]}
    with pytest.raises(ValueError, match="attribution"):
        baseline.canonical_evidence_check(attention, wrong_attention)
    multi = replace(mock_request, task="multi_camera")
    wrong_multi = {**mock_prediction, "camera_evidence": {"CAM_02": mock_prediction["observations"]}}
    with pytest.raises(ValueError, match="attribution"):
        baseline.canonical_evidence_check(multi, wrong_multi)


@pytest.mark.asyncio
async def test_route_proxies_cannot_prove_normal_assessment(mock_setup):
    mock_setup.replies["local_cv"].features = mock_cv_features(measured=True)
    # Adding uncontracted proxy event fields must not enable suppression either.
    mock_setup.replies["local_cv"].features["compact_state"].update(
        event_type="normal", event_confidence=1, backend_risk_score=0)
    mock_setup.replies["clef_direct"].decision = mock_clef_decision(skip=True)
    result = await mock_setup.run(mode="pipeline")
    row = result["attempts"][0]
    assert [call[0] for call in mock_setup.calls] == ["local_cv", "clef_direct", "general_vlm"]
    assert row["route"]["cv_uncertain"] is False
    assert row["route"]["normal_assessment_available"] is False
    assert row["route"]["reason"] == "normal_assessment_unavailable"
    assert row["route"]["actual_route"] == "invoke_vlm"
    assert row["needs_human_review"] is True


@pytest.mark.asyncio
async def test_success_reports_whole_pipeline_stages_and_profiles(mock_setup):
    cv = mock_setup.replies["local_cv"]
    cv.latency_ms = 30
    cv.metadata.update(cv_profile="pose-off", pose_enabled=False, timings_ms={"detect": 15, "track": 5})
    clef = mock_setup.replies["clef_direct"]
    clef.latency_ms = 10
    clef.metadata.update(http_status=200, conversion_profile="canonical64_cv_feature_state_v2",
                         preprocessing_ms=2, request_ms=8)
    vlm = mock_setup.replies["general_vlm"]
    vlm.latency_ms = 20
    vlm.metadata.update(http_status=200, transport_profile="synthetic-unit-profile",
                        preprocessing_ms=3, request_ms=17)
    result = await mock_setup.run(mode="suite", repeats=2)
    pipeline = result["metrics"]["cv_llm"]
    assert pipeline["whole_pipeline_validated"] == 2
    assert pipeline["whole_pipeline_validation_rate_all_planned"] == 1
    assert pipeline["whole_pipeline_validation_rate_executed"] == 1
    assert result["metrics"]["vlm_only"]["whole_pipeline_validated"] is None
    stages = pipeline["stages"]
    assert stages["local_cv"]["invocations"] == 2
    assert stages["local_cv"]["profiles"]["cv_profile"] == {"pose-off": 2}
    assert stages["local_cv"]["profiles"]["pose_enabled"] == {"false": 2}
    assert stages["local_cv"]["timings_ms_total"] == {"detect": 30, "track": 10}
    assert stages["general_vlm"]["latency_ms_total"] == 40
    assert stages["general_vlm"]["http_statuses"] == {"200": 2}
    assert stages["general_vlm"]["request_ms_total"] == 34
    assert stages["clef_direct"]["preprocessing_ms_total"] == 4
    assert stages["clef_direct"]["usage_records"] == [clef.usage, clef.usage]
    assert stages["general_vlm"]["known_partial_usage_cost_estimate_usd"] == .00018
    assert result["comparisons"][0]["whole_pipeline_validated"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("pre_post_error", ["payload_limit", "credentials_missing", "budget_exhausted"])
async def test_pre_post_failure_has_no_unknown_billing_but_retains_known_vlm_cost(mock_setup, pre_post_error):
    mock_setup.replies["clef_direct"] = BenchmarkOutcome("clef_direct", "clef",
        status="error", error_code=pre_post_error)
    result = await mock_setup.run(mode="pipeline")
    row = result["attempts"][0]
    stage = row["stages"]["clef_direct"]
    assert stage["billing_state"] == "not_reserved_pre_post"
    assert stage["unknown_billing_requests"] == 0
    assert stage["http_response_received"] is False
    assert row["whole_pipeline_validated"] is False
    assert row["estimated_cost_usd"] is None
    if pre_post_error == "budget_exhausted":
        assert row["known_partial_usage_cost_estimate_usd"] is None
        assert "general_vlm" not in row["stages"]
    else:
        assert row["known_partial_usage_cost_estimate_usd"] == .00009
        assert row["validated"] is True
    assert result["metrics"]["cv_llm"]["stages"]["clef_direct"]["pre_post_failures"] == 1


@pytest.mark.asyncio
async def test_reserved_http_failure_unknown_billing_retains_known_vlm_cost(mock_setup):
    mock_setup.replies["clef_direct"] = BenchmarkOutcome("clef_direct", "clef",
        status="error", error_code="provider_http_error", metadata={
            "reservation_usd": .03145728, "http_status": 500, "usage_cost_estimate_usd": None})
    result = await mock_setup.run(mode="pipeline")
    row = result["attempts"][0]
    assert row["validated"] is True
    assert row["whole_pipeline_validated"] is False
    assert row["estimated_cost_usd"] is None
    assert row["known_partial_usage_cost_estimate_usd"] == .00009
    assert row["unknown_billing_requests"] == 1
    assert row["stages"]["clef_direct"]["billing_state"] == "response_received"
    assert row["stages"]["clef_direct"]["http_response_received"] is True
    assert row["actual_invoice_cost_usd"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "cancelled"])
async def test_shared_executor_failure_keeps_ledger_and_remaining_denominators(mock_setup, monkeypatch, failure):
    from app.models.execution import execute_benchmark as shared_execute

    async def mock_paid_evaluate(request):
        # Synthetic execution/billing boundary only; no HTTP/provider call.
        token = mock_setup.budget.reserve("deepseek", .0685824)
        try:
            if failure == "cancelled":
                raise asyncio.CancelledError()
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            mock_setup.budget.settle(token, {}, None, "cancelled_billing_unknown")
            raise

    mock_setup.adapters["general_vlm"].evaluate_benchmark = mock_paid_evaluate
    monkeypatch.setattr(baseline, "execute_benchmark", shared_execute)
    monkeypatch.setitem(baseline.TIMEOUTS, "general_vlm", .01)
    result = await mock_setup.run(mode="vlm", repeats=3)
    assert len(result["attempts"]) == 3
    assert result["metrics"]["vlm_only"]["planned_attempts"] == 3
    assert result["metrics"]["vlm_only"]["schema_and_evidence_rate_all_planned"] == 0
    assert result["status"] == "incomplete"
    calls = 1 if failure == "cancelled" else 3
    assert result["executed_attempts"] == calls
    assert result["budget"]["requests"] == calls
    assert result["budget"]["unknown_billing_requests"] == calls
    assert result["metrics"]["vlm_only"]["unknown_billing_requests"] == calls
    assert result["metrics"]["vlm_only"]["known_partial_usage_cost_estimate_usd"] is None
    for row in result["attempts"][:calls]:
        assert row["status"] == "error"
        assert row["stages"]["general_vlm"]["error_code"] == failure
        assert row["stages"]["general_vlm"]["billing_state"] == "reserved_billing_unknown"
        assert row["stages"]["general_vlm"]["http_response_received"] is False
        assert row["stages"]["general_vlm"]["metadata"]["paid_request_records"][0]["status"] == "cancelled_billing_unknown"
    if failure == "cancelled":
        assert result["stop_reason"] == "cancelled"
        assert all(row["status"] == "not_executed" for row in result["attempts"][1:])


@pytest.mark.asyncio
async def test_all_model_calls_use_shared_execution_boundary(mock_setup, monkeypatch):
    from app.models.execution import execute_benchmark as shared_execute

    boundary_calls = []
    async def mock_recorded_execute(adapter, request, timeout_sec):
        boundary_calls.append(adapter.name)
        return await shared_execute(adapter, request, timeout_sec)

    for name, adapter in mock_setup.adapters.items():
        async def mock_evaluate(request, stage=name):
            return deepcopy(mock_setup.replies[stage])
        adapter.evaluate_benchmark = mock_evaluate
    monkeypatch.setattr(baseline, "execute_benchmark", mock_recorded_execute)
    result = await mock_setup.run()
    assert boundary_calls == ["general_vlm", "local_cv", "clef_direct", "general_vlm"]
    assert result["metrics"]["cv_llm"]["whole_pipeline_validated"] == 1


@pytest.mark.asyncio
async def test_unknown_cost_without_any_known_stage_stays_null(mock_setup):
    mock_setup.replies["clef_direct"].metadata["usage_cost_estimate_usd"] = None
    mock_setup.replies["general_vlm"].metadata["usage_cost_estimate_usd"] = None
    result = await mock_setup.run(mode="pipeline")
    assert result["attempts"][0]["known_partial_usage_cost_estimate_usd"] is None
    assert result["metrics"]["cv_llm"]["known_partial_usage_cost_estimate_usd"] is None
    assert result["metrics"]["cv_llm"]["unknown_billing_requests"] == 2


@pytest.mark.asyncio
async def test_shared_executor_error_recovers_known_ledger_usage(mock_setup, monkeypatch):
    from app.models.execution import execute_benchmark as shared_execute
    from app.schemas.benchmark import BenchmarkError

    async def mock_paid_evaluate(request):
        # Simulate the shared boundary losing output metadata after settlement.
        token = mock_setup.budget.reserve("deepseek", .0685824)
        mock_setup.budget.settle(token, {"input_tokens": 100, "output_tokens": 50},
                                .00009, "response_received")
        raise BenchmarkError("provider_schema_error")

    mock_setup.adapters["general_vlm"].evaluate_benchmark = mock_paid_evaluate
    monkeypatch.setattr(baseline, "execute_benchmark", shared_execute)
    result = await mock_setup.run(mode="vlm")
    row = result["attempts"][0]
    assert row["validated"] is False
    assert row["known_partial_usage_cost_estimate_usd"] == .00009
    assert row["unknown_billing_requests"] == 0
    stage = row["stages"]["general_vlm"]
    assert stage["usage"] == {"input_tokens": 100, "output_tokens": 50}
    assert stage["paid_requests_reserved"] == 1
    # No fabricated HTTP status: ledger settlement records are separate evidence.
    assert stage["metadata"]["paid_request_records"][0]["status"] == "response_received"
    assert stage["http_response_received"] is False
    assert result["metrics"]["vlm_only"]["known_partial_usage_cost_estimate_usd"] == .00009
    assert result["budget"]["known_partial_usage_cost_estimate_usd"] == .00009

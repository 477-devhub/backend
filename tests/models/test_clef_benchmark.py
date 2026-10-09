import asyncio
from dataclasses import replace
import json

import httpx
import pytest

from app.models.adapters.clef_benchmark import (
    ClefBenchmarkAdapter, MAX_REQUEST_BYTES, SOURCE, RESERVATION_USD,
)
from app.models.budget import PaidBudget
from app.schemas.benchmark import BenchmarkError, BenchmarkInput, CanonicalFrame


@pytest.fixture(scope="module")
def request64():
    rgb = b"\x00" * (1920 * 1080 * 3)
    compact = {"source": SOURCE, "frames": [{"frame_index": i, "camera": "CAM_01",
        "timestamp_sec": i / 2, "counts": {"person": 0}, "people": []} for i in range(64)],
        "tracks": [], "quality": {"zone_configured": False},
        "rule_policy": {"event_classifier_available": False}}
    return BenchmarkInput(item_id="label-bearing-private-item", task="single", prompt="frozen prompt",
        schema_json="{}", fingerprint_json='{"private_path":"never/provider"}',
        frames=tuple(CanonicalFrame("CAM_01", i / 2, rgb) for i in range(64)),
        features_json=json.dumps({"compact_state": compact, "annotations": {"answer": "secret-GT"}}))


def response(choice="invoke_vlm", incident=.8, confidence=.95):
    probabilities = {"invoke_vlm": .025, "no_action": .025, "human_review": .025}
    probabilities[choice] = .95
    return {"success": True, "result": {"model": "clef", "answers": {
        "incident": {"type": "noul", "noul": incident},
        "route": {"type": "choice", "choice": choice, "confidence": confidence,
                  "probabilities": probabilities}}, "usage": {"input_tokens": 100, "output_tokens": 8}}}


def adapter(tmp_path, handler, limit=5):
    budget = PaidBudget(tmp_path / "budget.json", limit)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ClefBenchmarkAdapter(budget, token="private-token", account="private-account", model="clef", client=client)


def populated_cv_request(request, people_per_frame):
    value = json.loads(request.features_json)
    for row in value["compact_state"]["frames"]:
        row["counts"]["person"] = people_per_frame
        row["people"] = [{"bbox": [743, 495, 831, 693], "track_id": i,
            "confidence": .95, "class_id": 0, "class_name": "person"}
            for i in range(people_per_frame)]
    return replace(request, features_json=json.dumps(value))


def test_request_uses_only_canonical_cv_state_and_preserves_prompt(tmp_path, request64):
    observed = []
    def handle(req):
        observed.append(json.loads(req.content))
        assert req.url.path.endswith("/@cf/cloudflare/clef")
        assert req.headers["authorization"] == "Bearer private-token"
        return httpx.Response(200, json=response())
    model = adapter(tmp_path, handle)
    result = asyncio.run(model.evaluate_benchmark(request64))
    body = observed[0]
    assert set(body) == {"model", "state", "questions"}
    assert body["questions"]["incident"]["instructions"].startswith(request64.prompt)
    assert len(body["state"]["frames"]) == 64
    encoded = json.dumps(body)
    for secret in (request64.item_id, "never/provider", "secret-GT", "annotations", "images"):
        assert secret not in encoded
    assert result.status == "ok" and result.prediction is None
    assert result.decision["invoke_vlm"] and result.decision["needs_human_review"]
    assert model.budget.summary()["actual_invoice_cost_usd"] is None
    assert result.metadata["usage_cost_estimate_usd"] == pytest.approx(.000024)


def test_no_action_cannot_suppress_incomplete_cv(tmp_path, request64):
    model = adapter(tmp_path, lambda req: httpx.Response(200, json=response("no_action", .02)))
    result = asyncio.run(model.evaluate_benchmark(request64))
    assert result.decision["proposed_route"] == "no_action"
    assert result.decision["invoke_vlm"] and result.decision["reason"] == "cv_information_incomplete"


def test_fixed_route_threshold_and_explicit_skip_policy():
    invoke = ClefBenchmarkAdapter._parse_decision(response("no_action", .35), False)
    assert invoke["invoke_vlm"] and invoke["reason"] == "incident_probability_threshold"
    assert not ClefBenchmarkAdapter._parse_decision(response("no_action", .349, .90), False)["invoke_vlm"]
    assert ClefBenchmarkAdapter._parse_decision(response("no_action", .349, .899), False)["invoke_vlm"]


@pytest.mark.parametrize("change", ["nested_ground_truth", "invalid_frame", "invalid_track_evidence", "duplicate_frame"])
def test_invalid_or_label_bearing_features_rejected_before_network(tmp_path, request64, change):
    def forbidden(req):
        pytest.fail("invalid input must not call provider")
    model = adapter(tmp_path, forbidden)
    value = json.loads(request64.features_json)
    compact = value["compact_state"]
    if change == "nested_ground_truth":
        compact["annotations"] = {"caption": "ground-truth"}
    elif change == "invalid_frame":
        compact["frames"][4]["timestamp_sec"] = 333
    elif change == "duplicate_frame":
        compact["frames"][4] = compact["frames"][3]
    else:
        compact["tracks"] = [{"evidence_frame_keys": [{"frame_index": 64, "camera": "CAM_01", "timestamp_sec": 32}]}]
    with pytest.raises(BenchmarkError, match="input_contract"):
        asyncio.run(model.evaluate_benchmark(replace(request64, features_json=json.dumps(value))))
    assert model.budget.summary()["requests"] == 0


def test_exhausted_budget_does_not_call_provider(tmp_path, request64):
    model = adapter(tmp_path, lambda req: pytest.fail("over-budget request"), limit=.01)
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        asyncio.run(model.evaluate_benchmark(request64))
    assert model.budget.summary()["requests"] == 0


def test_transport_failure_is_review_and_never_refunded_or_retried(tmp_path, request64):
    requests = []
    def handler(req):
        requests.append(req)
        raise httpx.ReadTimeout("private-token private-account", request=req)
    model = adapter(tmp_path, handler)
    result = asyncio.run(model.evaluate_benchmark(request64))
    assert len(requests) == 1
    assert result.status == "error" and result.error_code == "provider_transport_error"
    assert result.decision["invoke_vlm"] and result.decision["needs_human_review"]
    assert model.budget.summary()["reserved_usd"] == RESERVATION_USD
    assert "private-token" not in str(result)


def test_invalid_answer_retains_redacted_original_response_and_usage(tmp_path, request64, monkeypatch):
    monkeypatch.setenv("VLM_API_KEY", "other-private-key")
    raw = response()
    raw["result"]["answers"]["incident"]["noul"] = 9
    raw["errors"] = [{"message": "private-token private-account other-private-key", "api_key": "anything"}]
    model = adapter(tmp_path, lambda req: httpx.Response(200, json=raw))
    result = asyncio.run(model.evaluate_benchmark(request64))
    assert result.error_code == "provider_schema_error" and result.raw_response is not None
    assert result.raw_response["result"]["answers"]["incident"]["noul"] == 9
    assert result.usage["input_tokens"] == 100
    assert all(secret not in json.dumps(result.raw_response) for secret in
               ("private-token", "private-account", "other-private-key", "anything"))


@pytest.mark.parametrize("bad", [True, float("nan"), -.01, 1.01, "0.9"])
def test_invalid_probabilities_cannot_skip(bad):
    raw = response("no_action", .01)
    raw["result"]["answers"]["route"]["confidence"] = bad
    with pytest.raises(BenchmarkError, match="provider_schema_error"):
        ClefBenchmarkAdapter._parse_decision(raw, False)


def test_probability_distribution_must_match_selected_choice():
    raw = response("no_action", .01)
    raw["result"]["answers"]["route"]["probabilities"] = {"no_action": .1, "invoke_vlm": .8, "human_review": .1}
    with pytest.raises(BenchmarkError, match="provider_schema_error"):
        ClefBenchmarkAdapter._parse_decision(raw, False)


def test_http_failure_retains_redacted_raw_without_fabricated_prediction(tmp_path, request64):
    model = adapter(tmp_path, lambda req: httpx.Response(403, text="private-token forbidden"))
    result = asyncio.run(model.evaluate_benchmark(request64))
    assert result.status == "error" and result.error_code == "provider_http_error"
    assert result.raw_response == {"unparsed_response": "[REDACTED] forbidden"}
    assert result.prediction is None and result.metadata["http_status"] == 403


def test_cost_bound_violation_stops_future_requests(tmp_path, request64):
    raw = response()
    raw["result"]["usage"]["input_tokens"] = 200000
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(200, json=raw)
    model = adapter(tmp_path, handle)
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        asyncio.run(model.evaluate_benchmark(request64))
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        asyncio.run(model.evaluate_benchmark(request64))
    assert len(calls) == 1


def test_env_configuration_is_trimmed_and_never_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLEF_API_TOKEN", " private-token ")
    monkeypatch.setenv("CLEF_ACCOUNT", " private-account ")
    monkeypatch.setenv("CLEF_MODEL", " clef ")
    model = ClefBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"))
    assert model.model == "clef"
    assert model._token == "private-token" and model._account == "private-account"
    assert "private-token" not in str(model.budget.summary())


def test_payload_limit_prevents_network_and_reservation(tmp_path, request64):
    model = adapter(tmp_path, lambda req: pytest.fail("oversized payload must not call provider"))
    oversized = populated_cv_request(request64, 40)
    with pytest.raises(BenchmarkError, match="payload_limit"):
        asyncio.run(model.evaluate_benchmark(oversized))
    assert model.budget.summary()["requests"] == 0


@pytest.mark.parametrize("people_per_frame", [12, 20])
def test_large_canonical_cv_state_uses_byte_body_limit_not_token_proxy(
        tmp_path, request64, people_per_frame):
    observed = []
    def handle(req):
        observed.append(req.content)
        assert 65536 < len(req.content) <= MAX_REQUEST_BYTES
        body = json.loads(req.content)
        assert len(body["state"]["frames"]) == 64
        assert body["questions"]["incident"]["instructions"].startswith(request64.prompt)
        return httpx.Response(200, json=response())
    model = adapter(tmp_path, handle)
    result = asyncio.run(model.evaluate_benchmark(populated_cv_request(request64, people_per_frame)))
    assert len(observed) == 1 and result.status == "ok"
    assert result.metadata["request_bytes"] == len(observed[0])
    assert result.metadata["conversion_profile"] == "canonical64_cv_feature_state_v2"
    assert result.metadata["request_size_policy"] == {
        "max_request_bytes": MAX_REQUEST_BYTES,
        "provider_context_tokens": 65536, "byte_token_proxy": False}
    assert result.metadata["input_tokens_reported"] == 100
    assert result.metadata["context_truncation_status"] == "unknown"
    assert result.decision["needs_human_review"]
    assert all(value is None for value in result.metadata["risk_axes"].values())
    assert model.budget.summary()["requests"] == 1
    saved = json.dumps({"response": result.raw_response, "metadata": result.metadata,
                       "ledger": model.budget.summary()})
    for secret in ("private-token", "private-account", "secret-GT", request64.item_id):
        assert secret not in saved and secret.encode() not in observed[0]


def test_large_cv_state_still_cannot_exceed_budget(tmp_path, request64):
    model = adapter(tmp_path, lambda req: pytest.fail("over-budget request must not call provider"), limit=.01)
    request = populated_cv_request(request64, 12)
    body, _ = model._body(request)
    assert 65536 < len(body) <= MAX_REQUEST_BYTES
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        asyncio.run(model.evaluate_benchmark(request))
    assert model.budget.summary()["requests"] == 0


def test_nonfinite_provider_json_can_be_saved_as_safe_diagnostic(tmp_path, request64):
    raw = response()
    raw["result"]["answers"]["incident"]["noul"] = float("nan")
    model = adapter(tmp_path, lambda req: httpx.Response(200, text=json.dumps(raw)))
    result = asyncio.run(model.evaluate_benchmark(request64))
    assert result.error_code == "provider_schema_error"
    assert "INVALID_NONFINITE" in json.dumps(result.raw_response, allow_nan=False)


def test_cancellation_retains_billing_reservation(tmp_path, request64):
    async def handle(req):
        raise asyncio.CancelledError()
    model = adapter(tmp_path, handle)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(model.evaluate_benchmark(request64))
    assert model.budget.summary()["reserved_usd"] == RESERVATION_USD
    assert model.budget.state["requests"][0]["status"] == "cancelled_billing_unknown"

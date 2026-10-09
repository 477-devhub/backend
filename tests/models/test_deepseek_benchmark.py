"""Offline transport and media-boundary checks; these do not claim API access."""
import asyncio
import base64
import hashlib
import json
import threading
from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from app.models.adapters import deepseek_benchmark as module
from app.models.adapters.deepseek_benchmark import DeepSeekBenchmarkAdapter, RESERVATION_USD
from app.models.budget import PaidBudget
from app.schemas.benchmark import BenchmarkError, BenchmarkInput, CanonicalFrame


@pytest.fixture(scope="module")
def canonical():
    pixels = bytes(1920 * 1080 * 3)
    return BenchmarkInput(item_id="PRIVATE_ITEM_never_send", task="single", prompt="Frozen JSON prompt.",
        schema_json='{"$defs":{"single":{"type":"object"}}}', fingerprint_json='{"private":"never_send"}',
        frames=tuple(CanonicalFrame(camera="CAM_01", timestamp_sec=index / 2,
                                   rgb24=pixels) for index in range(64)))


def response(content='{"event_type":"uncertain"}', finish="stop", usage=None):
    return {"model": "deepseek-flash", "choices": [{"finish_reason": finish,
            "message": {"content": content}}], "usage": usage if usage is not None else {
                "prompt_tokens": 2000, "completion_tokens": 100, "prompt_cache_hit_tokens": 1000,
                "prompt_cache_miss_tokens": 1000}}


def fast_body(adapter):
    adapter._body = lambda request: (b'{"model":"deepseek-flash"}', {"frame_count": 64})


@pytest.mark.asyncio
async def test_exact_pixels_all64_frozen_prompt_schema_and_no_private_inputs(canonical, tmp_path):
    observed = {}
    def handle(request):
        observed.update(json.loads(request.content))
        assert request.url == module.ENDPOINT
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json=response())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="test-key", client=client)
        result = await adapter.evaluate_benchmark(canonical)
    content = observed["messages"][0]["content"]
    images = [entry for entry in content if entry["type"] == "image_url"]
    texts = [entry["text"] for entry in content if entry["type"] == "text"]
    assert len(images) == 64
    assert texts[0] == canonical.prompt
    assert canonical.schema_json in texts[1]
    assert "schema branch: single" in texts[1]
    assert texts[2] == module.TIMESTAMP_COPY_INSTRUCTION
    labels = [f"frame_index={index}; camera=CAM_01; timestamp_sec={index / 2!r}"
              for index in range(64)]
    assert texts[3:] == labels
    assert all(content[3 + 2 * index]["text"] == labels[index]
               and content[4 + 2 * index]["type"] == "image_url" for index in range(64))
    serialized = json.dumps(observed)
    assert canonical.item_id not in serialized and "never_send" not in serialized
    assert observed["thinking"] == {"type": "disabled"}
    assert observed["response_format"] == {"type": "json_object"}
    assert observed["max_tokens"] == 8192 and observed["temperature"] == 0
    import cv2
    import numpy as np
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(images[0]["image_url"]["url"].split(",")[1]),
                                        dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (1080, 1920, 3) and not decoded.any()
    assert result.status == "ok" and result.prediction == {"event_type": "uncertain"}
    assert len(result.metadata["images"]) == 64 and result.metadata["jpeg_quality"] == 80
    assert result.metadata["transport_profile"] == "deepseek_timestamp_copy_v2"
    assert result.metadata["source_prompt_sha256"] == hashlib.sha256(canonical.prompt.encode()).hexdigest()
    assert result.metadata["source_schema_sha256"] == hashlib.sha256(canonical.schema_json.encode()).hexdigest()
    assert result.metadata["timestamp_copy_instruction_sha256"] == hashlib.sha256(
        module.TIMESTAMP_COPY_INSTRUCTION.encode()).hexdigest()
    assert result.metadata["frame_labels_sha256"] == hashlib.sha256(
        json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert result.metadata["timestamp_label_format"] == "python_float_repr_exact_round_trip"
    assert result.metadata["provider_timestamp_postprocessing"] is False
    assert [image["transport_label"] for image in result.metadata["images"]] == labels
    assert result.metadata["actual_invoice_cost_usd"] is None
    assert result.metadata["usage_cost_estimate_usd"] == pytest.approx(.000426)


@pytest.mark.parametrize("task,branch", [("attention", "attention"), ("multi_camera", "multi")])
def test_exact_timestamp_labels_for_all_cameras_without_frozen_contract_changes(
        canonical, tmp_path, task, branch):
    times = (34.96666666666667, 31.066666666666666, 20.966666666666665)
    frames = tuple(replace(frame, camera=f"CAM_{index % 3 + 1:02d}",
                           timestamp_sec=times[index % 3] + index / 30)
                   for index, frame in enumerate(canonical.frames))
    request = replace(canonical, task=task, frames=frames)
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key")
    body, metadata = adapter._body(request)
    content = json.loads(body)["messages"][0]["content"]
    assert content[0]["text"].encode() == canonical.prompt.encode()
    assert content[1]["text"] == (
        f"Task: {task}; schema branch: {branch}\nOutput JSON schema:\n" + canonical.schema_json)
    assert content[2]["text"] == module.TIMESTAMP_COPY_INSTRUCTION
    assert sum(entry["type"] == "image_url" for entry in content) == 64
    for index, frame in enumerate(frames):
        expected = f"frame_index={index}; camera={frame.camera}; timestamp_sec={frame.timestamp_sec!r}"
        assert content[3 + index * 2]["text"] == expected
        assert content[4 + index * 2]["type"] == "image_url"
        assert metadata["images"][index]["transport_label"] == expected
        assert float(expected.split("timestamp_sec=")[1]) == frame.timestamp_sec
    assert metadata["text_utf8_bytes"] <= module.MAX_TEXT_BYTES
    assert metadata["request_bytes"] <= module.MAX_REQUEST_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_profile", [module.TRANSPORT_PROFILE, module.JSON_LABELS_PROFILE])
@pytest.mark.parametrize("exact,wrong", [(34.96666666666667, 34.9),
    (31.066666666666666, 31.0), (20.966666666666665, 20.9)])
async def test_wrong_provider_timestamp_preserved_and_rejected_by_external_validator(
        canonical, tmp_path, exact, wrong, transport_profile):
    from app.eval.benchmark_baseline import canonical_evidence_check
    frames = tuple(replace(frame, timestamp_sec=exact + index)
                   for index, frame in enumerate(canonical.frames))
    request = replace(canonical, frames=frames)
    prediction = {"observations": [{"camera": "CAM_01", "timestamp_sec": wrong}]}
    raw = response(json.dumps(prediction))
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=raw))) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"),
                                          api_key="key", client=client, transport_profile=transport_profile)
        fast_body(adapter)
        outcome = await adapter.evaluate_benchmark(request)
    assert outcome.status == "ok"  # Transport success is not a validation pass.
    assert outcome.prediction == prediction
    assert outcome.raw_response == raw
    assert outcome.prediction["observations"][0]["timestamp_sec"] == wrong
    with pytest.raises(ValueError):
        canonical_evidence_check(request, outcome.prediction)


@pytest.mark.asyncio
async def test_cpu_encoding_does_not_run_on_event_loop_thread(canonical, tmp_path):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="test-key")
    main_thread = threading.get_ident()
    def body(request):
        assert threading.get_ident() != main_thread
        return b"{}", {}
    adapter._body = body
    async def post(body):
        return 200, response()
    adapter._post = post
    assert (await adapter.evaluate_benchmark(canonical)).status == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("content,finish", [("", "stop"), ("```json\n{}\n```", "stop"),
    ("[]", "stop"), ('{"x":NaN}', "stop"), ("{}", "length")])
async def test_unusable_json_or_truncation_preserves_raw_and_reviews(canonical, tmp_path, content, finish):
    budget = PaidBudget(tmp_path / "budget.json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=response(content, finish)))) as client:
        adapter = DeepSeekBenchmarkAdapter(budget, api_key="test-key", client=client)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert result.status == "error" and result.prediction is None
    assert result.error_code == "provider_schema_error" and result.raw_response is not None
    assert result.metadata["needs_human_review"] is True
    assert budget.summary()["reserved_usd"] == pytest.approx(RESERVATION_USD)


@pytest.mark.asyncio
async def test_http_and_nonjson_errors_redact_secrets_without_retry(canonical, tmp_path, monkeypatch):
    monkeypatch.setenv("CLEF_ACCOUNT", "private-account-123")
    monkeypatch.setenv("CLEF_API_TOKEN", "private-clef-token")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(401, text="test-secret private-account-123 private-clef-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="test-secret", client=client)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert result.error_code == "provider_http_error" and len(calls) == 1
    assert result.raw_response == {"unparsed_response": "[REDACTED] [REDACTED] [REDACTED]"}
    assert "test-secret" not in json.dumps(result.__dict__)


def test_recursive_redaction_credentials_keys_and_values(tmp_path):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="private-api-key")
    redacted = adapter._redact({"API_KEY": "other-secret", "token": "undisclosed-token",
                                "account": "undisclosed-account", "prompt_tokens": 9,
                                "nested": [{"authorization": "Bearer unknown"}],
                                "private-api-key": "echo private-api-key"})
    assert "private-api-key" not in json.dumps(redacted)
    assert "other-secret" not in json.dumps(redacted) and "Bearer unknown" not in json.dumps(redacted)
    assert redacted["token"] == "[REDACTED]" and redacted["account"] == "[REDACTED]"
    assert redacted["prompt_tokens"] == 9


@pytest.mark.asyncio
async def test_cancelled_request_retains_reservation(canonical, tmp_path):
    budget = PaidBudget(tmp_path / "budget.json")
    adapter = DeepSeekBenchmarkAdapter(budget, api_key="test-key")
    fast_body(adapter)
    async def post(body):
        raise asyncio.CancelledError()
    adapter._post = post
    with pytest.raises(asyncio.CancelledError):
        await adapter.evaluate_benchmark(canonical)
    assert budget.state["requests"][0]["status"] == "cancelled_billing_unknown"
    assert budget.summary()["reserved_usd"] == pytest.approx(RESERVATION_USD)


@pytest.mark.asyncio
async def test_transport_exception_never_leaks_secret(canonical, tmp_path):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="test-key")
    fast_body(adapter)
    async def post(body):
        raise httpx.ConnectError("test-key connection failed")
    adapter._post = post
    result = await adapter.evaluate_benchmark(canonical)
    assert result.error_code == "provider_transport_error" and result.raw_response is None
    assert "test-key" not in json.dumps(result.__dict__)


@pytest.mark.asyncio
@pytest.mark.parametrize("key,model,expected", [("", "deepseek-flash", "credentials_missing"),
                                              ("key", "other-model", "unsupported_model")])
async def test_missing_auth_and_no_model_fallback(canonical, tmp_path, key, model, expected):
    budget = PaidBudget(tmp_path / "budget.json")
    adapter = DeepSeekBenchmarkAdapter(budget, api_key=key, model=model)
    with pytest.raises(BenchmarkError, match=expected):
        await adapter.evaluate_benchmark(canonical)
    assert len(budget.state["requests"]) == 0


def test_features_rejected_before_encoding_or_spending(canonical, tmp_path):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key")
    with pytest.raises(BenchmarkError, match="input_contract"):
        adapter._body(replace(canonical, features_json='{"source":"CV only"}'))


def test_text_and_request_size_bounds(canonical, tmp_path, monkeypatch):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key")
    with pytest.raises(BenchmarkError, match="payload_limit"):
        adapter._body(replace(canonical, prompt="x" * 16001))
    monkeypatch.setattr(module, "MAX_REQUEST_BYTES", 10)
    with pytest.raises(BenchmarkError, match="payload_limit"):
        adapter._body(canonical)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit_kind", ["text", "body"])
async def test_transport_size_guard_prevents_post_and_budget_reservation(
        canonical, tmp_path, monkeypatch, limit_kind):
    budget = PaidBudget(tmp_path / "budget.json")
    adapter = DeepSeekBenchmarkAdapter(budget, api_key="key")
    request = canonical
    if limit_kind == "text":
        request = replace(canonical, prompt="x" * (module.MAX_TEXT_BYTES + 1))
    else:
        monkeypatch.setattr(module, "MAX_REQUEST_BYTES", 10)
    async def must_not_post(body):
        pytest.fail("oversized transport must not reach the provider")
    adapter._post = must_not_post
    with pytest.raises(BenchmarkError, match="payload_limit"):
        await adapter.evaluate_benchmark(request)
    assert budget.state["requests"] == []
    assert budget.summary()["reserved_usd"] == 0


@pytest.mark.asyncio
async def test_response_limit(canonical, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "MAX_RESPONSE_BYTES", 32)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text="x" * 100))) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key", client=client)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert result.error_code == "payload_limit" and result.prediction is None


@pytest.mark.parametrize("usage", [{"prompt_tokens": -1, "completion_tokens": 1},
    {"prompt_tokens": True, "completion_tokens": 1}, {"prompt_tokens": 1},
    {"prompt_tokens": 1, "completion_tokens": 1, "prompt_cache_hit_tokens": 2},
    {"prompt_tokens": 5, "completion_tokens": 1, "prompt_cache_hit_tokens": 1, "prompt_cache_miss_tokens": 1}])
def test_invalid_usage_not_reported_as_actual_cost(usage):
    with pytest.raises(BenchmarkError, match="provider_schema_error"):
        DeepSeekBenchmarkAdapter._usage({"usage": usage})


@pytest.mark.asyncio
async def test_provider_cost_over_reservation_halts_future_requests(canonical, tmp_path):
    budget = PaidBudget(tmp_path / "budget.json")
    adapter = DeepSeekBenchmarkAdapter(budget, api_key="key")
    fast_body(adapter)
    async def post(body):
        return 200, response(usage={"prompt_tokens": 1_000_000, "completion_tokens": 1})
    adapter._post = post
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        await adapter.evaluate_benchmark(canonical)
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        budget.reserve("deepseek", RESERVATION_USD)


@pytest.mark.asyncio
async def test_balance_is_numeric_whitelist_without_inference_reservation(tmp_path):
    budget = PaidBudget(tmp_path / "budget.json")
    def handle(request):
        assert request.method == "GET" and request.url == "https://api.deepseek.com/user/balance"
        return httpx.Response(200, json={"is_available": True, "private": "secret",
            "balance_infos": [{"currency": "USD", "total_balance": "4.2",
                               "granted_balance": "1.2", "topped_up_balance": "3.0",
                               "account_id": "private-secret"}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(budget, api_key="key", client=client)
        result = await adapter.get_balance()
    assert result == {"status": "ok", "http_status": 200, "is_available": True,
        "balance_infos": [{"currency": "USD", "total_balance": "4.2",
                           "granted_balance": "1.2", "topped_up_balance": "3.0"}]}
    assert len(budget.state["requests"]) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,code", [(403, {"secret": "key"}, "provider_http_error"),
    (200, {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "NaN"}]},
     "provider_schema_error")])
async def test_balance_failures_never_return_provider_body(tmp_path, status, payload, code):
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(status, json=payload))) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key", client=client)
        result = await adapter.get_balance()
    assert result == {"status": "error", "http_status": status, "error_code": code}


@pytest.mark.asyncio
async def test_budget_limit_prevents_post(canonical, tmp_path):
    budget = PaidBudget(tmp_path / "budget.json", limit_usd=.01)
    adapter = DeepSeekBenchmarkAdapter(budget, api_key="key")
    fast_body(adapter)
    async def must_not_post(body):
        pytest.fail("paid call attempted without reservation")
    adapter._post = must_not_post
    with pytest.raises(BenchmarkError, match="budget_exhausted"):
        await adapter.evaluate_benchmark(canonical)


def test_environment_model_and_key_trimmed_without_reporting_key(tmp_path, monkeypatch):
    monkeypatch.setenv("VLM_MODEL", " deepseek-flash ")
    monkeypatch.setenv("VLM_API_KEY", " env-secret ")
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"))
    assert adapter.model == "deepseek-flash" and adapter._api_key == "env-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_model,expected_status", [
    ("DeepSeek-V4.1-Flash", "ok"), (None, "ok"), (7, "error"), ("", "error")])
async def test_resolved_model_recorded_without_changing_requested_model(canonical, tmp_path,
                                                                      returned_model, expected_status):
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        raw = response()
        raw["model"] = returned_model
        return httpx.Response(200, json=raw)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key", client=client)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert requests[0]["model"] == "deepseek-flash" and adapter.model == "deepseek-flash"
    assert len(requests) == 1 and result.status == expected_status
    if expected_status == "ok":
        assert result.metadata["returned_model"] == returned_model
    else:
        assert result.error_code == "provider_schema_error" and result.prediction is None


def test_default_v2_request_bytes_match_original_serializer(canonical, tmp_path):
    import cv2
    import numpy as np

    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key")
    actual, metadata = adapter._body(canonical)
    original_instruction = (
        "Image transport labels identify the actual input frames. For every observation, "
        "copy camera and timestamp_sec exactly from the label of the image used as evidence. "
        "Do not round, truncate, interpolate, or reconstruct timestamp_sec. "
        "Do not use a timestamp from a different camera. frame_index is a neutral transport "
        "reference only, not an additional output field; preserve the supplied JSON schema."
    )
    content = [{"type": "text", "text": text} for text in (
        canonical.prompt, "Task: single; schema branch: single\nOutput JSON schema:\n" + canonical.schema_json,
        original_instruction)]
    rgb = np.frombuffer(canonical.frames[0].rgb24, dtype=np.uint8).reshape(1080, 1920, 3)
    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                               [cv2.IMWRITE_JPEG_QUALITY, 80])
    assert ok
    url = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
    for index, frame in enumerate(canonical.frames):
        content.extend([
            {"type": "text", "text": f"frame_index={index}; camera={frame.camera}; "
                                     f"timestamp_sec={frame.timestamp_sec!r}"},
            {"type": "image_url", "image_url": {"url": url}},
        ])
    expected = json.dumps({"model": "deepseek-flash", "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
        "max_tokens": 8192, "temperature": 0}, ensure_ascii=False, allow_nan=False,
        separators=(",", ":")).encode()
    assert actual == expected
    assert adapter.transport_profile == "deepseek_timestamp_copy_v2"
    assert adapter.max_output_tokens == metadata["output_token_limit"] == 8192
    assert adapter.reservation_upper_usd == metadata["reservation_upper_usd"] == .0685824
    assert metadata["input_token_limit"] == 81536
    assert metadata["request_byte_limit"] == 48 * 1024 * 1024
    assert metadata["text_byte_limit"] == 16000


@pytest.mark.parametrize("task,branch", [("single", "single"), ("attention", "attention"),
                                         ("multi_camera", "multi")])
def test_v3_json_labels_exact64_and_same_pixels_prompt_schema(canonical, tmp_path, task, branch):
    times = (34.96666666666667, 31.066666666666666, 20.966666666666665)
    frames = tuple(replace(frame, camera=f"CAM_{index % 3 + 1:02d}",
                           timestamp_sec=times[index % 3] + index / 30)
                   for index, frame in enumerate(canonical.frames))
    request = replace(canonical, task=task, frames=frames)
    budget = PaidBudget(tmp_path / "budget.json")
    v2 = DeepSeekBenchmarkAdapter(budget, api_key="key")
    v3 = DeepSeekBenchmarkAdapter(budget, api_key="key", transport_profile=module.JSON_LABELS_PROFILE)
    v2_body, v2_metadata = v2._body(request)
    v3_body, metadata = v3._body(request)
    baseline, body = json.loads(v2_body), json.loads(v3_body)
    content = body["messages"][0]["content"]
    assert len(content) == 131
    assert content[0]["text"] == request.prompt
    assert content[1]["text"] == (
        f"Task: {task}; schema branch: {branch}\nOutput JSON schema:\n" + request.schema_json)
    assert content[2]["text"] == module.JSON_LABELS_COPY_INSTRUCTION
    assert "quoted JSON field names and colons" in content[2]["text"]
    assert sum(entry["type"] == "image_url" for entry in content) == 64
    labels = []
    for index, frame in enumerate(frames):
        label = content[3 + index * 2]["text"]
        labels.append(label)
        assert json.loads(label) == {"frame_index": index, "camera": frame.camera,
                                    "timestamp_sec": frame.timestamp_sec}
        assert label == (f'{{"frame_index":{index},"camera":"{frame.camera}",'
                         f'"timestamp_sec":{frame.timestamp_sec!r}}}')
        assert "=" not in label
        assert content[4 + index * 2] == baseline["messages"][0]["content"][4 + index * 2]
        assert metadata["images"][index]["transport_label"] == label
        assert metadata["images"][index]["timestamp_sec"] == frame.timestamp_sec
        for key in ("source_rgb_sha256", "sent_jpeg_sha256", "jpeg_bytes", "width", "height"):
            assert metadata["images"][index][key] == v2_metadata["images"][index][key]
    assert body["max_tokens"] == 4096
    # Only the transport instruction, image labels and selected output cap change.
    body["messages"][0]["content"] = baseline["messages"][0]["content"]
    body["max_tokens"] = 8192
    assert body == baseline
    for key in ("source_prompt_sha256", "source_schema_sha256", "jpeg_quality", "resize", "crop",
                "timestamp_label_format", "provider_timestamp_postprocessing", "input_token_limit",
                "request_byte_limit", "text_byte_limit"):
        assert metadata[key] == v2_metadata[key]
    assert metadata["transport_profile"] == "deepseek_json_labels_v3"
    assert metadata["timestamp_copy_instruction_sha256"] == hashlib.sha256(
        module.JSON_LABELS_COPY_INSTRUCTION.encode()).hexdigest()
    assert metadata["frame_labels_sha256"] == hashlib.sha256(
        json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert metadata["text_utf8_bytes"] <= 16000 and metadata["request_bytes"] <= 48 * 1024 * 1024
    assert "never_send" not in v3_body.decode()
    assert request.prompt == canonical.prompt and request.schema_json == canonical.schema_json
    assert budget.state["requests"] == []


@pytest.mark.parametrize("profile,output_limit,reserve", [
    (module.TRANSPORT_PROFILE, 8192, .0685824), (module.JSON_LABELS_PROFILE, 4096, .058752)])
def test_profile_reservation_is_twice_strict_peak_upper_bound(tmp_path, profile, output_limit, reserve):
    adapter = DeepSeekBenchmarkAdapter(PaidBudget(tmp_path / "budget.json"), api_key="key",
                                      transport_profile=profile)
    peak = (Decimal(81536) * Decimal(".30") + Decimal(output_limit) * Decimal("1.20")) / 1_000_000
    assert adapter.max_output_tokens == output_limit
    assert Decimal(str(adapter.reservation_upper_usd)) == 2 * peak == Decimal(str(reserve))


@pytest.mark.parametrize("profile", ["deepseek_json_labels_v4", "", None, ["deepseek_json_labels_v3"]])
def test_unsupported_profile_rejected_before_provider_or_spending(tmp_path, profile):
    budget = PaidBudget(tmp_path / "budget.json")
    with pytest.raises(ValueError, match="unsupported DeepSeek transport profile"):
        DeepSeekBenchmarkAdapter(budget, api_key="key", transport_profile=profile)
    assert budget.state["requests"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,limit", [(module.TRANSPORT_PROFILE, 8192),
                                         (module.JSON_LABELS_PROFILE, 4096)])
@pytest.mark.parametrize("axis,excess", [("input", 0), ("input", 1), ("output", 0), ("output", 1)])
async def test_selected_token_limits_are_enforced_with_raw_preserved(
        canonical, tmp_path, profile, limit, axis, excess):
    usage = {"prompt_tokens": 81536 + excess if axis == "input" else 2000,
             "completion_tokens": limit + excess if axis == "output" else 100}
    raw, calls = response(usage=usage), []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=raw)
    budget = PaidBudget(tmp_path / "budget.json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(budget, api_key="key", client=client, transport_profile=profile)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert len(calls) == 1 and result.raw_response == raw
    assert result.status == ("error" if excess else "ok")
    assert result.error_code == ("provider_schema_error" if excess else None)
    assert result.prediction == (None if excess else {"event_type": "uncertain"})
    assert result.metadata["reservation_usd"] == adapter.reservation_upper_usd
    assert budget.summary()["reserved_usd"] == adapter.reservation_upper_usd


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining,expected", [(.058751, "budget_exhausted"), (.058752, "ok")])
async def test_v3_reservation_boundary_controls_post_without_refund(canonical, tmp_path, remaining, expected):
    budget = PaidBudget(tmp_path / "budget.json", limit_usd=remaining)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(budget, api_key="key", client=client,
                                          transport_profile=module.JSON_LABELS_PROFILE)
        fast_body(adapter)
        if expected == "budget_exhausted":
            with pytest.raises(BenchmarkError, match=expected):
                await adapter.evaluate_benchmark(canonical)
            assert calls == [] and budget.state["requests"] == []
        else:
            assert (await adapter.evaluate_benchmark(canonical)).status == "ok"
            assert len(calls) == 1 and budget.summary()["reserved_usd"] == .058752


@pytest.mark.asyncio
@pytest.mark.parametrize("profile,expected_reserve", [(module.TRANSPORT_PROFILE, .0685824),
                                                     (module.JSON_LABELS_PROFILE, .058752)])
@pytest.mark.parametrize("content,finish", [("{}", "length"), ('{"observations":[', "length"),
    ('{"observations":[{"camera":"CAM_01","timestamp_sec=7.0, "risk":10}]}', "stop")])
async def test_truncated_or_equals_json_remains_original_review_error(
        canonical, tmp_path, profile, expected_reserve, content, finish):
    raw, calls = response(content, finish), []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=raw)
    budget = PaidBudget(tmp_path / "budget.json")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DeepSeekBenchmarkAdapter(budget, api_key="key", client=client, transport_profile=profile)
        fast_body(adapter)
        result = await adapter.evaluate_benchmark(canonical)
    assert len(calls) == 1 and result.status == "error" and result.prediction is None
    assert result.error_code == "provider_schema_error" and result.metadata["needs_human_review"] is True
    assert result.raw_response == raw
    assert result.raw_response["choices"][0]["message"]["content"] == content
    if profile == module.JSON_LABELS_PROFILE and finish == "length":
        assert result.metadata["truncation_reason"] == "provider_finish_reason_length"
    else:
        assert "truncation_reason" not in result.metadata
    assert result.metadata["retry_count"] == 0
    assert result.metadata["reservation_usd"] == budget.summary()["reserved_usd"] == expected_reserve

"""Network-off adapter contract tests; fake responses are not model evaluation."""
import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from pipeline477.adapters.vlm import Adapter, JPEG_QUALITY, MAX_RESPONSE_BYTES


class FakeBudget:
    def __init__(self, blocked=False):
        self.blocked, self.reserved, self.settled = blocked, [], []

    def reserve(self, provider, upper):
        if self.blocked:
            raise RuntimeError("budget_exhausted")
        self.reserved.append((provider, upper))
        return "fake-reservation"

    def settle(self, token, usage, cost, status):
        self.settled.append((token, usage, cost, status))


@pytest.fixture(scope="module")
def schema():
    path = Path(__file__).resolve().parents[2] / "new_477_piprline/pipeline477/contract.py"
    spec = importlib.util.spec_from_file_location("standalone_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.output_schema()


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    path = tmp_path_factory.mktemp("private_ground_truth_collapse") / "caption_answer.png"
    bgr = np.zeros((1080, 1920, 3), np.uint8)
    bgr[:, :960] = (12, 75, 196)
    bgr[:, 960:] = (140, 35, 7)
    assert cv2.imwrite(str(path), bgr)
    return path


def model_input(image, schema, count=1, active=None):
    sources = [f"SRC{i+1:02}" for i in range(count)]
    frames = []
    for index, sid in enumerate(sources):
        for n in range(64 // count + (index < 64 % count)):
            frames.append({"frame_id": f"{sid}-F{n*30:06}", "source_id": sid, "frame_number": n * 30,
                "timestamp_sec": float(n), "width": 1920, "height": 1080, "image_path": str(image),
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
    return {"sources": sources, "frames": frames, "active_sources": active or sources,
        "prompt": "Inspect these independent sources; JSON only.", "output_schema": schema}


def response(data):
    rows = [{"source_id": sid, "event_type": "uncertain", "event_confidence": .5,
        "risk_axes": {k: None for k in ("severity", "imminence", "exposure", "persistence")},
        "evidence_refs": [next(f["frame_id"] for f in data["frames"] if f["source_id"] == sid)],
        "needs_human_review": True, "uncertainty_reason": "Not enough visible evidence"}
        for sid in data["active_sources"]]
    return {"model": "deepseek-flash", "choices": [{"message": {"content": json.dumps({"assessments": rows})}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 100, "prompt_cache_miss_tokens": 900}}


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("VLM_API_KEY", "private-secret-do-not-save")
    monkeypatch.setenv("VLM_MODEL", " deepseek-flash ")
    return Adapter({})


def context(tmp_path, paid=True, blocked=False):
    def write(path, value):
        Path(path).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return {"artifact_dir": tmp_path, "package_root": tmp_path, "write_json": write,
        "allow_paid": paid, "budget": FakeBudget(blocked)}


def run_fake(adapter, data, ctx, payload=None, status=200, exception=None, fast=True):
    calls = []
    if fast:
        def body(_):
            body = {"model": adapter.model, "messages": []}
            return body, json.dumps(body).encode(), {"images_sent": 64}
        adapter._body = body
    async def post(encoded):
        assert (ctx["artifact_dir"] / "vlm.request.json").is_file()
        assert ctx["budget"].reserved
        calls.append(encoded)
        if exception:
            raise exception
        return status, payload if payload is not None else response(data)
    adapter._post = post
    return asyncio.run(adapter.run(data, ctx)), calls


@pytest.mark.parametrize("count", range(1, 7))
def test_exact64_and_source_scoped_request(adapter, image, schema, count):
    data = model_input(image, schema, count, active=["SRC01"])
    body, encoded, meta = adapter._body(data)
    assert len([c for c in body["messages"][0]["content"] if c["type"] == "image_url"]) == 64
    assert meta["active_sources"] == ["SRC01"] and meta["images_sent"] == 64
    assert body["max_tokens"] == 4096
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert json.loads(encoded) == body
    for forbidden in ("private_ground_truth", "caption_answer", "image_path", "private-secret", "cv_output"):
        assert forbidden not in encoded.decode()
    assert meta["prompt_sha256"] == hashlib.sha256(data["prompt"].encode()).hexdigest()
    assert meta["jpeg_quality"] == JPEG_QUALITY
    first_image = next(c for c in body["messages"][0]["content"] if c["type"] == "image_url")
    jpeg = base64.b64decode(first_image["image_url"]["url"].split(",", 1)[1])
    assert hashlib.sha256(jpeg).hexdigest() == meta["images"][0]["sent_jpeg_sha256"]
    bgr = cv2.imread(str(image))
    assert hashlib.sha256(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes()).hexdigest() == meta["images"][0]["source_rgb_sha256"]
    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape == (1080, 1920, 3)
    labels = [json.loads(c["text"]) for c in body["messages"][0]["content"][2:] if c["type"] == "text"]
    assert labels == [{k: f[k] for k in ("frame_id", "source_id", "frame_number", "timestamp_sec")} for f in data["frames"]]


@pytest.mark.parametrize("mutation", ["checksum", "dimensions", "order", "count", "active", "source", "label", "frame_number", "nonfinite", "relative"])
def test_bad_input_rejected_before_post(adapter, image, schema, tmp_path, mutation):
    data = model_input(image, schema, 2)
    if mutation == "checksum":
        data["frames"][0]["sha256"] = "0" * 64
    elif mutation == "dimensions":
        data["frames"][0]["width"] = 100
    elif mutation == "order":
        data["frames"] = list(reversed(data["frames"]))
    elif mutation == "count":
        data["frames"].pop()
    elif mutation == "active":
        data["active_sources"] = ["SRC06"]
    elif mutation == "source":
        data["sources"][0] = "collapse"
    elif mutation == "label":
        data["annotations"] = "never infer from labels"
    elif mutation == "frame_number":
        data["frames"][0]["frame_number"] = 2
    elif mutation == "nonfinite":
        data["frames"][0]["timestamp_sec"] = float("nan")
    elif mutation == "relative":
        data["frames"][0]["image_path"] = "image.png"
    result, calls = run_fake(adapter, data, context(tmp_path), fast=False)
    assert not calls and not result["executed"]
    assert result["errors"][0]["category"] == "benchmark"


def test_valid_output_raw_and_converted_preserved(adapter, image, schema, tmp_path):
    data = model_input(image, schema, 6, active=["SRC02", "SRC05"])
    payload, ctx = response(data), context(tmp_path)
    result, calls = run_fake(adapter, data, ctx, payload)
    assert len(calls) == 1 and result["status"] == "ok" and result["executed"]
    assert result["metadata"]["format_valid"] is True
    assert {a["source_id"] for a in result["output"]["assessments"]} == {"SRC02", "SRC05"}
    assert json.loads((tmp_path / "vlm.response.json").read_text()) == payload
    assert json.loads((tmp_path / "vlm.converted.json").read_text()) == result["output"]
    assert result["cost_usd"]["value"] == pytest.approx(.0003906)
    assert result["cost_usd"]["invoice_usd"] is None and len(ctx["budget"].settled) == 1


@pytest.mark.parametrize("mutation", ["missing_active", "duplicate_active", "unknown_ref", "cross_source", "schema", "review", "bad_json", "nan_json", "envelope"])
def test_model_errors_preserve_usage_and_raw(adapter, image, schema, tmp_path, mutation):
    data = model_input(image, schema, 2)
    payload = response(data)
    parsed = json.loads(payload["choices"][0]["message"]["content"])
    if mutation == "missing_active":
        parsed["assessments"].pop()
    elif mutation == "duplicate_active":
        parsed["assessments"][1] = copy.deepcopy(parsed["assessments"][0])
    elif mutation == "unknown_ref":
        parsed["assessments"][0]["evidence_refs"] = ["SRC01-F999999"]
    elif mutation == "cross_source":
        parsed["assessments"][0]["evidence_refs"] = [parsed["assessments"][1]["evidence_refs"][0]]
    elif mutation == "schema":
        parsed["assessments"][0]["event_confidence"] = 2
    elif mutation == "review":
        parsed["assessments"][0]["needs_human_review"] = False
    payload["choices"][0]["message"]["content"] = json.dumps(parsed)
    if mutation == "bad_json":
        payload["choices"][0]["message"]["content"] = "timestamp_sec=7.0"
    elif mutation == "nan_json":
        payload["choices"][0]["message"]["content"] = '{"assessments":NaN}'
    elif mutation == "envelope":
        payload["choices"] = []
    result, calls = run_fake(adapter, data, context(tmp_path), payload)
    assert len(calls) == 1 and result["status"] == "error"
    assert result["metadata"]["format_valid"] is False
    assert result["errors"][0]["category"] == "model"
    assert result["cost_usd"]["basis"] == "usage_based_estimate"
    assert json.loads((tmp_path / "vlm.response.json").read_text()) == payload
    if mutation not in {"bad_json", "nan_json", "envelope"}:
        assert result["output"] == parsed == result["invalid_output"]
    else:
        assert result["output"] is None


@pytest.mark.parametrize("usage", [{}, {"prompt_tokens": True, "completion_tokens": 1}, {"prompt_tokens": 2, "completion_tokens": -1},
    {"prompt_tokens": 100, "completion_tokens": 1, "prompt_cache_hit_tokens": 101},
    {"prompt_tokens": 100, "completion_tokens": 1, "prompt_cache_hit_tokens": True},
    {"prompt_tokens": 100, "completion_tokens": 1, "prompt_cache_hit_tokens": 10, "prompt_cache_miss_tokens": 100}])
def test_unknown_usage_never_zero(adapter, usage):
    assert adapter._usage({"usage": usage})[1] is None


@pytest.mark.parametrize("mode", ["disabled", "budget", "credentials"])
def test_no_post_when_blocked(adapter, image, schema, tmp_path, mode):
    if mode == "credentials":
        adapter._token = ""
    ctx = context(tmp_path, paid=mode != "disabled", blocked=mode == "budget")
    result, calls = run_fake(adapter, model_input(image, schema), ctx)
    assert not calls and not result["executed"] and result["status"] == "blocked"
    assert result["cost_usd"] == {"value": 0, "basis": "not_called", "invoice_usd": 0}
    assert not ctx["budget"].settled


def test_http_error_and_secret_redaction(adapter, image, schema, tmp_path):
    payload = {"error": {"message": "private-secret-do-not-save quota reached"}}
    result, calls = run_fake(adapter, model_input(image, schema), context(tmp_path), payload, status=429)
    assert len(calls) == 1 and result["errors"][0]["category"] == "execution"
    assert result["metadata"]["http_status"] == 429 and result["cost_usd"]["value"] is None
    assert "private-secret-do-not-save" not in (tmp_path / "vlm.response.json").read_text()
    assert "private-secret-do-not-save" not in json.dumps(result)


def test_transport_exception_with_secret_is_not_logged(adapter, image, schema, tmp_path):
    ctx = context(tmp_path)
    result, _ = run_fake(adapter, model_input(image, schema), ctx, exception=RuntimeError("private-secret-do-not-save"))
    assert result["errors"][0]["category"] == "execution" and result["cost_usd"]["value"] is None
    assert "private-secret" not in json.dumps(result) and ctx["budget"].settled[0][2] is None


def test_cancelled_post_settles_once_as_unknown(adapter, image, schema, tmp_path):
    ctx = context(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        run_fake(adapter, model_input(image, schema), ctx, exception=asyncio.CancelledError())
    assert ctx["budget"].settled == [("fake-reservation", {}, None, "cancelled_unknown")]


@pytest.mark.parametrize("config", [{"base_url": "https://other-provider.example"},
    {"input_price_per_million": -1}, {"max_tokens": True}])
def test_invalid_provider_config_before_post(adapter, image, schema, tmp_path, config):
    adapter.config.update(config)
    if "max_tokens" in config:
        adapter.max_tokens = config["max_tokens"]
    result, calls = run_fake(adapter, model_input(image, schema), context(tmp_path), fast=False)
    assert not calls and result["errors"][0]["category"] == "benchmark"


def test_stream_invalid_provider_json_saved_as_raw_text(adapter, monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=b'{"value":NaN}')
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    status, raw = asyncio.run(adapter._post(b'{"model":"deepseek-flash"}'))
    assert status == 200 and raw["raw_text"] == '{"value":NaN}' and len(calls) == 1
    json.dumps(raw, allow_nan=False)
    assert calls[0].url == "https://api.deepseek.com/chat/completions"


def test_stream_response_size_bounded(adapter, monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    with pytest.raises(ValueError, match="response_size_limit"):
        asyncio.run(adapter._post(b"{}"))

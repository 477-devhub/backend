"""Explicit fake-HTTP fixtures; these tests are not real Clef evaluations."""
import asyncio
import json
from pathlib import Path

import pytest

from app.models.adapters.new_pipeline_clef import Adapter, MAX_REQUEST_BYTES


class FakeBudget:
    def __init__(self, blocked=False):
        self.blocked, self.reserved, self.settled = blocked, [], []

    def reserve(self, provider, upper):
        if self.blocked:
            raise RuntimeError("budget_exhausted")
        self.reserved.append((provider, upper))
        return "test-reservation"

    def settle(self, token, usage, cost, status):
        self.settled.append((token, usage, cost, status))


def model_input(count=1, measured=False):
    sources = [f"SRC{i+1:02}" for i in range(count)]
    frames, cv_frames = [], []
    for index, sid in enumerate(sources):
        number = 64 // count + (index < 64 % count)
        for n in range(number):
            frame = {"frame_id": f"{sid}_F{n:06}", "source_id": sid, "frame_number": n * 30,
                "timestamp_sec": float(n), "width": 1920, "height": 1080,
                "image_path": f"C:/private/groundtruth_collapse/{sid}/{n}.png", "sha256": "0" * 64}
            frames.append(frame)
            cv_frames.append({"frame_id": frame["frame_id"], "source_id": sid,
                "frame_number": frame["frame_number"], "timestamp_sec": frame["timestamp_sec"],
                "detections": [{"class_name": "person", "bbox": [1, 2, 10, 20],
                    "confidence": .8, "track_id": 1, "annotation": "NEVER_SEND_GROUND_TRUTH"}]})
    axes = {key: .1 if measured else None for key in ("severity", "imminence", "exposure", "persistence")}
    return {"sources": sources, "frames": frames, "prompt": "Inspect these independent sources.",
        "annotations": "NEVER_SEND_GROUND_TRUTH", "cv_output": {"frames": cv_frames,
            "tracks": [{"source_id": sid, "track_id": 1, "class_name": "person", "observations": 3,
                "caption": "NEVER_SEND_GROUND_TRUTH", "image_path": "C:/private"} for sid in sources],
            "quality": {"zone_configured": measured, "annotation": "NEVER_SEND_GROUND_TRUTH"},
            "compact_state": {"rule_policy": {"event_classifier_available": measured}, "risk_axes": axes,
                "answer": "NEVER_SEND_GROUND_TRUTH"}}}


def response(sources, route="human_review", confidence=.95, incident=.1):
    answers = {}
    for sid in sources:
        answers[f"incident.{sid}"] = {"type": "noul", "noul": incident}
        answers[f"route.{sid}"] = {"type": "choice", "choice": route, "confidence": confidence,
            "probabilities": {key: .96 if key == route else .02 for key in ("invoke_vlm", "no_action", "human_review")}}
    return {"success": True, "result": {"model": "clef", "answers": answers,
        "usage": {"input_tokens": 1000, "output_tokens": 40}}}


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setenv("CLEF_MODEL", " clef ")
    monkeypatch.setenv("CLEF_ACCOUNT", "private-account-test")
    monkeypatch.setenv("CLEF_API_TOKEN", "private-token-test")
    return Adapter({"model": "clef", "input_price_per_million": .24})


def context(tmp_path, paid=True, blocked=False):
    def write(path, value):
        Path(path).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return {"artifact_dir": tmp_path, "package_root": tmp_path, "write_json": write,
        "allow_paid": paid, "budget": FakeBudget(blocked)}


def run_fake(adapter, data, ctx, status=200, payload=None):
    calls = []
    async def post(body):
        assert (ctx["artifact_dir"] / "clef.request.json").is_file()
        assert ctx["budget"].reserved
        calls.append(body)
        return status, payload if payload is not None else response(data["sources"])
    adapter._post = post
    return asyncio.run(adapter.run(data, ctx)), calls


@pytest.mark.parametrize("count", range(1, 7))
def test_source_scoped_allowlisted_questions(adapter, count):
    data = model_input(count)
    body, encoded, uncertain = adapter._body(data)
    assert len(body["questions"]) == 2 * count
    assert sum(len(s["frames"]) for s in body["state"]["sources"]) == 64
    assert set(uncertain) == set(data["sources"])
    assert all(uncertain.values())
    for sid in data["sources"]:
        assert set(body["questions"][f"route.{sid}"]["criteria"]) == {"invoke_vlm", "no_action", "human_review"}
    text = encoded.decode()
    for forbidden in ("image_path", "private", "NEVER_SEND_GROUND_TRUTH", "annotations", "caption", "answer", "sha256"):
        assert forbidden not in text


def test_single_observation_track_unknown_gap_from_actual_cv_contract(adapter):
    """P001's real CV worker emitted this legitimate single-observation shape."""
    data = model_input()
    data["cv_output"]["tracks"] = [{"camera": "SRC01", "source_id": "SRC01", "track_id": "3",
        "class_name": "car", "first_timestamp_sec": 5.566666666666666,
        "last_timestamp_sec": 5.566666666666666, "observations": 1,
        "observed_span_sec": 0, "interpolated_visible_sec": 0,
        "max_observation_gap_sec": None, "path_length_pixels": 0, "net_displacement_pixels": 0,
        "person_dwell_candidate": False, "annotation": "NEVER_SEND_GROUND_TRUTH"}]
    body, encoded, uncertainty = adapter._body(data)
    track = body["state"]["sources"][0]["tracks"][0]
    assert track["max_observation_gap_sec"] is None
    assert track["observations"] == 1
    assert uncertainty == {"SRC01": True}
    assert "NEVER_SEND_GROUND_TRUTH" not in encoded.decode()


@pytest.mark.parametrize("observations,gap", [(2, None), (1, -1), (1, float("nan")), (1, float("inf"))])
def test_unknown_gap_exception_does_not_relax_track_numeric_validation(adapter, observations, gap):
    data = model_input()
    data["cv_output"]["tracks"][0].update(observations=observations, max_observation_gap_sec=gap)
    with pytest.raises(ValueError):
        adapter._body(data)


@pytest.mark.parametrize("mutation", ["duplicate_frame", "wrong_source", "wrong_timestamp", "sequence", "box", "class", "track_source", "short", "missing_detections", "timestamp_sequence"])
def test_invalid_mapping_rejected_before_post(adapter, tmp_path, mutation):
    data = model_input()
    if mutation == "duplicate_frame": data["cv_output"]["frames"][1]["frame_id"] = data["frames"][0]["frame_id"]
    if mutation == "wrong_source": data["cv_output"]["frames"][0]["source_id"] = "SRC02"
    if mutation == "wrong_timestamp": data["cv_output"]["frames"][0]["timestamp_sec"] = 999
    if mutation == "sequence": data["frames"][1]["frame_number"] = 0
    if mutation == "box": data["cv_output"]["frames"][0]["detections"][0]["bbox"] = [0, 0, 2000, 10]
    if mutation == "class": data["cv_output"]["frames"][0]["detections"][0]["class_name"] = "collapse"
    if mutation == "track_source": data["cv_output"]["tracks"][0]["source_id"] = "SRC06"
    if mutation == "short": data["frames"].pop()
    if mutation == "missing_detections": del data["cv_output"]["frames"][0]["detections"]
    if mutation == "timestamp_sequence":
        data["frames"][1]["timestamp_sec"] = 0
        data["cv_output"]["frames"][1]["timestamp_sec"] = 0
    result, calls = run_fake(adapter, data, context(tmp_path))
    assert not calls and not result["executed"]
    assert result["errors"][0]["category"] == "benchmark"


def test_actual_success_artifacts_usage_and_scope(adapter, tmp_path):
    data, ctx = model_input(6), context(tmp_path)
    result, calls = run_fake(adapter, data, ctx)
    assert len(calls) == 1 and result["status"] == "ok" and result["executed"]
    assert len(result["output"]["sources"]) == 6
    assert result["cost_usd"]["value"] == pytest.approx(.00024)
    assert result["cost_usd"]["basis"] == "usage_based_estimate"
    assert result["cost_usd"]["invoice_usd"] is None
    assert ctx["budget"].settled[0][-1] == "ok"
    assert result["metadata"]["images_sent"] == 0
    text = "".join(f.read_text() for f in tmp_path.glob("*.json"))
    assert "private-token-test" not in text and "private-account-test" not in text


@pytest.mark.parametrize("paid,blocked", [(False, False), (True, True)])
def test_disabled_and_exhausted_do_not_post(adapter, tmp_path, paid, blocked):
    ctx = context(tmp_path, paid, blocked)
    result, calls = run_fake(adapter, model_input(), ctx)
    assert not calls and not result["executed"]
    assert result["status"] == "blocked" and result["cost_usd"]["basis"] == "not_called"
    assert (tmp_path / "clef.request.json").is_file()


def test_missing_credentials_do_not_post(adapter, tmp_path):
    adapter._token = ""
    result, calls = run_fake(adapter, model_input(), context(tmp_path))
    assert not calls and result["errors"][0]["code"] == "credentials_missing_or_invalid"


@pytest.mark.parametrize("measured,confidence,incident,skip", [(False, .99, .1, False), (True, .9, .34, True),
    (True, .89, .1, False), (True, .99, .35, False), (True, .99, .0, True)])
def test_safe_skip_actual_route_not_proposal(adapter, measured, confidence, incident, skip):
    data = model_input(measured=measured)
    _, _, uncertainty = adapter._body(data)
    parsed = adapter._parse(response(data["sources"], "no_action", confidence, incident), uncertainty)["sources"][0]
    assert parsed["proposed_route"] == "no_action"
    assert parsed["invoke_vlm"] is not skip
    assert parsed["needs_human_review"] is not skip


@pytest.mark.parametrize("mutation", ["question_missing", "wrong_model", "wrong_type", "bad_sum", "wrong_winner", "nonfinite", "success_false"])
def test_malformed_typed_response_model_error(adapter, tmp_path, mutation):
    data, payload = model_input(), response(["SRC01"])
    answer = payload["result"]["answers"]["route.SRC01"]
    if mutation == "question_missing": del payload["result"]["answers"]["incident.SRC01"]
    if mutation == "wrong_model": payload["result"]["model"] = "invented"
    if mutation == "wrong_type": answer["type"] = "score"
    if mutation == "bad_sum": answer["probabilities"]["invoke_vlm"] = .5
    if mutation == "wrong_winner": answer["choice"] = "no_action"
    if mutation == "nonfinite": answer["confidence"] = "NaN"
    if mutation == "success_false": payload["success"] = False
    result, _ = run_fake(adapter, data, context(tmp_path), payload=payload)
    assert result["status"] == "error" and result["output"] is None
    assert result["errors"][0]["category"] == "model"
    assert (tmp_path / "clef.response.json").is_file()


def test_real_quota_error_fixture_preserved_without_secrets(adapter, tmp_path):
    payload = {"success": False, "errors": [{"code": 4006,
        "message": "Daily free allocation exhausted private-token-test private-account-test"}]}
    ctx = context(tmp_path)
    result, calls = run_fake(adapter, model_input(), ctx, 429, payload)
    assert len(calls) == 1 and result["executed"]
    assert result["metadata"]["http_status"] == 429
    assert result["errors"][0]["category"] == "execution"
    assert result["cost_usd"]["value"] is None
    assert result["cost_usd"]["invoice_usd"] is None
    raw = json.loads((tmp_path / "clef.response.json").read_text())
    assert raw["errors"][0]["code"] == 4006
    assert "[REDACTED]" in raw["errors"][0]["message"]
    assert ctx["budget"].settled[0][2] is None


def test_context_byte_limit_not_token_proxy(adapter):
    data = model_input()
    data["prompt"] = "x" * 45000
    _, encoded, _ = adapter._body(data)
    assert 65536 < len(encoded) < MAX_REQUEST_BYTES
    data["prompt"] = "x" * MAX_REQUEST_BYTES
    with pytest.raises(ValueError, match="request_body_limit"):
        adapter._body(data)


@pytest.mark.parametrize("text", ['{"value": NaN}', '{"value": Infinity}', 'not JSON'])
def test_http_parser_preserves_invalid_json_text(adapter, monkeypatch, text):
    import httpx
    class FakeResponse:
        status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def aiter_bytes(self): yield text.encode()
    class FakeClient:
        def __init__(self, **kwargs): assert kwargs["follow_redirects"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        def stream(self, method, url, **kwargs):
            assert method == "POST" and url.startswith("https://api.cloudflare.com/client/v4/")
            return FakeResponse()
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    status, raw = asyncio.run(adapter._post(b"{}"))
    assert status == 200 and raw["parse_error"] == "provider_invalid_json"
    assert raw["raw_text"] == text
    json.dumps(raw, allow_nan=False)


def test_transport_exception_never_leaks_exception_text(adapter, tmp_path):
    async def fail(_): raise RuntimeError("Bearer private-token-test private-account-test")
    adapter._post = fail
    ctx = context(tmp_path)
    result = asyncio.run(adapter.run(model_input(), ctx))
    assert result["executed"] and result["output"] is None
    text = json.dumps(result)
    assert "private-token-test" not in text and "private-account-test" not in text
    assert ctx["budget"].settled[0][2] is None

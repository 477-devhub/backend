import asyncio
import json
from pathlib import Path
import sys

import pytest

from app.models.adapters.yolo_benchmark import YoloBenchmarkAdapter
from app.models.adapters.yolo_benchmark_worker import (
    camera_profiles, posture_cue, profile_limitations, rgb_to_bgr, summarize_track,
)
from app.models.execution import execute_benchmark
from app.schemas.benchmark import BenchmarkInput, CanonicalFrame


@pytest.fixture(scope="module")
def rgb():
    return b"\xff\x00\x00" * (1920 * 1080)


@pytest.fixture
def request64(rgb):
    return BenchmarkInput(item_id="label-bearing-harness-id", task="single",
        prompt="frozen original prompt", schema_json="{}", fingerprint_json="{}",
        frames=tuple(CanonicalFrame("CAM_01", i/2, rgb) for i in range(64)),
        features_json=json.dumps({"annotations": {"answer": "never use this supplied label"}}))


@pytest.fixture
def adapter(tmp_path):
    weights = tmp_path / "yolo26s.pt"
    weights.write_bytes(b"unit-test-placeholder-not-model")
    return YoloBenchmarkAdapter(weights)


def response_for(header):
    frames = sorted(header["frames"], key=lambda row: row["frame_index"])
    return {"status": "ok", "features": {"compact_state": {},
        "frames": [{k: row[k] for k in ("frame_index", "camera", "timestamp_sec")} for row in frames],
        "consumption": {"frame_count": 64, "raw_rgb_bytes": 64*1920*1080*3, "frames": frames}}}


def test_rgb_conversion_preserves_red_as_bgr():
    array = rgb_to_bgr(b"\xff\x00\x00\x00\xff\x00", width=2, height=1)
    assert array.tolist() == [[[0, 0, 255], [0, 255, 0]]]


def test_worker_header_contains_only_pixels_and_neutral_metadata(adapter, request64):
    header = adapter._request_header(request64)
    encoded = json.dumps(header)
    for forbidden in ("label-bearing", "annotations", "answer", "prompt", "fingerprint", "single"):
        assert forbidden not in encoded
    assert len(header["frames"]) == 64
    assert header["frames"][1]["timestamp_sec"] == .5


def test_pose_off_preserves_all_detection_tracking_and_input_settings(adapter, request64, tmp_path):
    pose_weights = tmp_path / "yolo26s-pose.pt"
    pose_weights.write_bytes(b"unit-test-placeholder-not-model")
    pose_adapter = YoloBenchmarkAdapter(adapter.detector_weights, pose_weights)
    off_header = adapter._request_header(request64)
    on_header = pose_adapter._request_header(request64)
    assert off_header["config"]["pose_weights"] is None
    assert on_header["config"].pop("pose_weights") == str(pose_weights.resolve())
    off_header["config"].pop("pose_weights")
    assert off_header == on_header
    assert off_header["config"]["imgsz"] == 960
    assert off_header["config"]["conf"] == .10
    assert off_header["config"]["lost_seconds"] == 5.
    assert len(off_header["frames"]) == 64


def test_pose_off_limitations_distinguish_bbox_cues_from_unmeasured_keypoints():
    off = profile_limitations(False)
    on = profile_limitations(True)
    assert any("no pose model or keypoints measured" in text for text in off)
    assert any("do not diagnose collapse" in text for text in off)
    assert not any("no pose model" in text for text in on)
    cue = posture_cue([0, 0, 20, 10])
    assert cue["low_posture_candidate"]
    assert cue["torso_angle_from_vertical_deg"] is None
    assert "event_type" not in cue


def test_camera_specific_buffer_uses_real_timestamp_intervals():
    profiles = camera_profiles([{"camera": c, "timestamp_sec": t} for c, times in
        (("CAM_01", [0, .5, 1]), ("CAM_02", [0, 2, 4])) for t in times])
    assert profiles["CAM_01"]["lost_buffer_samples"] == 10
    assert profiles["CAM_02"]["lost_buffer_samples"] == 3
    assert profiles["CAM_02"]["lost_buffer_effective_sec"] == 6
    assert profiles["CAM_01"]["kalman_dt"] == "one_step_per_canonical_sample"


def test_duplicate_camera_times_rejected():
    with pytest.raises(ValueError):
        camera_profiles([{"camera": "CAM_01", "timestamp_sec": 0}] * 2)


def observations(times, class_id=0, low=False):
    return [{"frame_index": i, "timestamp_sec": t, "class_id": class_id,
             "bbox": [i, 0, i+10, 20], "low_posture_candidate": low} for i, t in enumerate(times)]


def test_dwell_uses_timestamps_and_does_not_bridge_missing_intervals():
    yes = summarize_track("CAM_01", "1", observations([0, 5, 10, 15]))
    missing = summarize_track("CAM_01", "1", observations([0, 1, 20]))
    assert yes["person_dwell_candidate"] and yes["interpolated_visible_sec"] == 15
    assert not missing["person_dwell_candidate"]
    assert missing["interpolated_visible_sec"] == 1 and missing["observed_span_sec"] == 20
    assert yes["evidence_frame_keys"][0] == {"frame_index": 0, "camera": "CAM_01", "timestamp_sec": 0}


def test_vehicle_or_changed_class_never_person_dwell():
    vehicle = summarize_track("CAM_02", "1", observations([0, 5, 10, 15], 2))
    switched = observations([0, 5, 10, 15])
    switched[2]["class_id"] = 2
    switched_result = summarize_track("CAM_01", "1", switched)
    assert not vehicle["person_dwell_candidate"]
    assert not switched_result["person_dwell_candidate"] and switched_result["class_changed"]


def test_low_posture_cue_requires_temporal_accumulation_and_has_no_event_output():
    assert posture_cue([0, 0, 20, 10])["low_posture_candidate"]
    assert not posture_cue([0, 0, 10, 20])["low_posture_candidate"]
    sustained = summarize_track("CAM_01", "1", observations([0, .5, 1], low=True))
    isolated = observations([0, .5, 1], low=True)
    isolated[1]["low_posture_candidate"] = False
    assert sustained["sustained_low_posture_candidate"]
    assert not summarize_track("CAM_01", "1", isolated)["sustained_low_posture_candidate"]
    assert "event_type" not in sustained


@pytest.mark.asyncio
async def test_output_is_observation_only_with_null_risk(adapter, request64, monkeypatch):
    async def worker(header, request):
        return response_for(header)
    monkeypatch.setattr(adapter, "_run_worker", worker)
    result = await execute_benchmark(adapter, request64, timeout_sec=5)
    assert result.status == "ok" and result.prediction is None
    assert all(v is None for v in result.metadata["risk_axes"].values())
    assert result.metadata["needs_human_review"]
    assert result.metadata["model_cold_start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pose_enabled", [False, True])
async def test_profile_reports_actual_models_versions_and_worker_configuration(
        adapter, request64, tmp_path, monkeypatch, pose_enabled):
    if pose_enabled:
        pose_weights = tmp_path / "yolo26s-pose.pt"
        pose_weights.write_bytes(b"unit-test-placeholder-not-model")
        adapter = YoloBenchmarkAdapter(adapter.detector_weights, pose_weights)
    tracker_config = {"CAM_01": {"track_high_thresh": .25, "track_low_thresh": .1,
        "new_track_thresh": .25, "track_buffer": 10, "match_thresh": .8, "fuse_score": True}}
    versions = {"ultralytics": "recorded-test-version", "torch": "recorded-test-version"}
    weight_hashes = {"detector_weights": "recorded-test-detector-hash"}
    if pose_enabled:
        weight_hashes["pose_weights"] = "recorded-test-pose-hash"

    async def worker(header, request):
        assert (header["config"]["pose_weights"] is not None) is pose_enabled
        result = response_for(header)
        result["features"]["tracker_config"] = tracker_config
        result["features"]["limitations"] = profile_limitations(pose_enabled)
        result["versions"] = versions
        result["weights_sha256"] = weight_hashes
        return result

    monkeypatch.setattr(adapter, "_run_worker", worker)
    result = await execute_benchmark(adapter, request64, timeout_sec=5)
    assert result.status == "ok"
    assert result.model == "yolo26s.pt+ByteTrack" + ("+yolo26s-pose.pt" if pose_enabled else "")
    assert result.metadata["models"] == {"detector": "yolo26s.pt", "tracker": "ByteTrack",
        "pose": "yolo26s-pose.pt" if pose_enabled else None}
    assert result.metadata["cv_profile"] == ("pose-always" if pose_enabled else "pose-off")
    assert result.metadata["pose_enabled"] is pose_enabled
    assert result.metadata["versions"] == versions
    assert result.metadata["weights_sha256"] == weight_hashes
    assert result.metadata["tracker_config"] == tracker_config
    assert result.metadata["config"]["imgsz"] == 960
    assert result.metadata["config"]["conf"] == .10
    assert not any(key.endswith("weights") for key in result.metadata["config"])
    assert result.metadata["limitations"] == profile_limitations(pose_enabled)
    assert not result.metadata["event_classifier_available"]
    assert result.metadata["needs_human_review"]
    assert all(value is None for value in result.metadata["risk_axes"].values())


@pytest.mark.asyncio
async def test_missing_consumed_frame_is_contract_failure(adapter, request64, monkeypatch):
    async def worker(header, request):
        result = response_for(header)
        result["features"]["consumption"]["frames"].pop()
        return result
    monkeypatch.setattr(adapter, "_run_worker", worker)
    result = await execute_benchmark(adapter, request64, timeout_sec=5)
    assert result.status == "error" and result.error_code == "provider_schema_error"
    assert result.prediction is None and result.metadata["needs_human_review"]


@pytest.mark.asyncio
async def test_worker_failure_is_sanitized(adapter, request64, monkeypatch):
    async def worker(header, request):
        return {"status": "error", "error_code": "worker_error", "raw_secret": "never surface"}
    monkeypatch.setattr(adapter, "_run_worker", worker)
    result = await execute_benchmark(adapter, request64, timeout_sec=5)
    assert result.status == "error" and result.error_code == "worker_error"
    assert "never surface" not in repr(result)


@pytest.mark.asyncio
async def test_admission_is_bounded_and_cancel_releases_waiter(adapter, request64, monkeypatch):
    active = asyncio.Event()
    async def worker(header, request):
        active.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(adapter, "_run_worker", worker)
    first = asyncio.create_task(adapter.evaluate_benchmark(request64))
    await active.wait()
    second = asyncio.create_task(adapter.evaluate_benchmark(request64))
    await asyncio.sleep(0)
    result = await execute_benchmark(adapter, request64, timeout_sec=5)
    assert result.error_code == "worker_error"
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert adapter._admitted == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("via_timeout", [False, True])
async def test_real_subprocess_is_killed_and_reaped_on_cancel_or_timeout(adapter, request64, monkeypatch, via_timeout):
    spawned = asyncio.Event()
    children = []
    async def spawn(environment):
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", "import time; time.sleep(60)",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        children.append(process)
        spawned.set()
        return process
    monkeypatch.setattr(adapter, "_spawn", spawn)
    adapter.worker_timeout = .3 if via_timeout else 60
    task = asyncio.create_task(execute_benchmark(adapter, request64, timeout_sec=10))
    await spawned.wait()
    if via_timeout:
        result = await task
        assert result.status == "error" and result.error_code == "timeout"
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert children[0].returncode is not None
    assert adapter._admitted == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_name,size", [("stdout", 1100000), ("stderr", 70000)])
async def test_subprocess_output_budget_stops_worker(adapter, request64, monkeypatch, stream_name, size):
    children = []
    async def spawn(environment):
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c",
            f"import sys,time; sys.{stream_name}.buffer.write(b'x'*{size}); sys.{stream_name}.flush(); time.sleep(60)",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        children.append(process)
        return process
    monkeypatch.setattr(adapter, "_spawn", spawn)
    result = await execute_benchmark(adapter, request64, timeout_sec=10)
    assert result.error_code == "payload_limit" and children[0].returncode is not None


def test_nan_timestamp_is_rejected_without_worker(rgb):
    # The shared canonical-frame boundary now rejects this before an adapter
    # can receive it; retain the stricter invariant instead of constructing NaN.
    with pytest.raises(ValueError, match="invalid canonical frame"):
        CanonicalFrame("CAM_01", float("nan"), rgb)

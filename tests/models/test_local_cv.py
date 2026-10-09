"""Synthetic technical checks, not CCTV accuracy or event validation."""
import asyncio
import base64
import json
import subprocess
import sys

import pytest
import pytest_asyncio

from app.models.adapters.ingestion import MediaIngestion
from app.models.adapters.local_cv import LocalCVAdapter, LocalCVError
from app.models.adapters.local_cv_worker import _associate, analyze
from app.models.execution import execute
from app.models.media import MediaResolver
from app.schemas.model import CameraContext, ModelInput, TemporalState, TimeWindow


@pytest.fixture(scope="module")
def synthetic_mp4():
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=black:s=640x360:r=4:d=2", "-c:v", "mpeg4", "-threads", "1",
        "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1",
    ], capture_output=True, check=True, timeout=15)
    return result.stdout


@pytest_asyncio.fixture
async def prepared(tmp_path, synthetic_mp4):
    resolver = MediaResolver(tmp_path, {}, assets={"clip_abcdef": synthetic_mp4})
    mi = ModelInput(sample_id="s_abcdef", camera=CameraContext(id="CCTV-001"),
                    clip_ref="clip_abcdef", window=TimeWindow(start_ms=0, end_ms=1750))
    return await MediaIngestion(resolver).prepare(mi)


@pytest.mark.asyncio
async def test_actual_hog_subprocess_is_uncertain_and_preserves_real_refs(prepared):
    adapter = LocalCVAdapter(prepared.resolver)
    result = await execute(adapter, prepared.model_input, timeout_sec=20)
    assert result.event_type == "uncertain"
    assert result.event_confidence == 0
    assert result.needs_human_review and not result.metadata.is_mock
    assert result.risk_axes.model_dump() == dict.fromkeys(
        ["severity", "imminence", "exposure", "persistence"])
    assert result.metadata.error_code is None
    assert result.evidence_refs == [e.frame_id for e in prepared.model_input.evidence]
    observation = adapter.last_observation
    assert observation.clip_sha256 == prepared.clip_sha256
    assert dict(observation.frame_sha256) == prepared.frame_sha256
    assert observation.preprocessing_ms > 0 and observation.worker_ms > 0
    assert dict(observation.versions)["opencv"].startswith("4.")
    assert dict(observation.versions)["device"] == "CPU"
    assert observation.temporal_state.person_count == 0
    assert observation.temporal_state.vehicle_count is None
    assert observation.temporal_state.events == []
    assert observation.temporal_state.feature_version == "opencv-hog-iou-v1"
    # Each access makes a fresh state; consumers cannot modify stored diagnostics.
    state = observation.temporal_state
    state.tracks.append({"invented": True})
    assert observation.temporal_state.tracks == []


@pytest.mark.asyncio
async def test_worker_input_excludes_labels_camera_paths_and_supplied_temporal(prepared, monkeypatch):
    adapter = LocalCVAdapter(prepared.resolver)
    actual_run, payloads = adapter._run_worker, []

    async def capture(request):
        payloads.append(json.loads(request))
        return await actual_run(request)

    monkeypatch.setattr(adapter, "_run_worker", capture)
    mi = prepared.model_input.model_copy(update={"temporal_state": TemporalState(
        person_count=999, tracks=[{"annotations": "GROUND_TRUTH_COLLAPSE"}],
        feature_version="GROUND_TRUTH")})
    result = await execute(adapter, mi, timeout_sec=20)
    assert result.metadata.error_code is None
    request = payloads[0]
    assert set(request) == {"frames"}
    assert all(set(frame) == {"frame_id", "timestamp_ms", "jpeg"} for frame in request["frames"])
    assert "GROUND_TRUTH" not in json.dumps(request)
    assert "CCTV-001" not in json.dumps(request)
    assert adapter.last_observation.temporal_state.person_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["id", "timestamp", "content", "missing_clip", "no_frames"])
async def test_invalid_media_or_provenance_goes_to_review(prepared, corruption):
    mi = prepared.model_input
    resolver = prepared.resolver
    if corruption == "id":
        frame = mi.evidence[0].model_copy(update={"frame_id": "frame_" + "0" * 64})
        mi = mi.model_copy(update={"evidence": [frame]})
    elif corruption == "timestamp":
        frame = mi.evidence[0].model_copy(update={"timestamp_ms": 1})
        mi = mi.model_copy(update={"evidence": [frame]})
    elif corruption == "content":
        assets = dict(resolver.assets)
        assets[mi.evidence[0].media_ref] = b"different-image"
        resolver = MediaResolver(resolver.root, {}, assets=assets)
    elif corruption == "missing_clip":
        mi = mi.model_copy(update={"clip_ref": "clip_unknown"})
    else:
        mi = mi.model_copy(update={"evidence": []})
    result = await execute(LocalCVAdapter(resolver), mi, timeout_sec=20)
    assert result.event_type == "uncertain" and result.needs_human_review
    assert not result.metadata.is_mock and result.metadata.error_code
    assert result.risk_axes is None
    # Common execution fallback preserves input refs for human inspection;
    # its error/null axes prevent these from becoming successful CV evidence.
    assert set(result.evidence_refs) <= {frame.frame_id for frame in mi.evidence}


@pytest.mark.asyncio
async def test_entire_ingestion_is_serial_and_queue_is_bounded(prepared, monkeypatch):
    import app.models.adapters.local_cv as module
    started, release = asyncio.Event(), asyncio.Event()
    active, peak = 0, 0

    class HeldIngestion:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, mi):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.set()
            try:
                await release.wait()
                return prepared
            finally:
                active -= 1

    monkeypatch.setattr(module, "MediaIngestion", HeldIngestion)
    adapter = LocalCVAdapter(prepared.resolver, timeout_sec=20)
    first = asyncio.create_task(adapter.extract_observations(prepared.model_input))
    await started.wait()
    second = asyncio.create_task(adapter.extract_observations(prepared.model_input))
    await asyncio.sleep(.01)
    with pytest.raises(LocalCVError, match="queue is full"):
        await adapter.extract_observations(prepared.model_input)
    assert adapter._admitted == 2 and peak == 1
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert adapter._admitted == 1
    release.set()
    await first
    assert adapter._admitted == 0
    await adapter.extract_observations(prepared.model_input)
    assert peak == 1 and adapter._admitted == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["timeout", "cancel", "overflow", "stderr"])
async def test_child_is_reaped_and_loop_keeps_running(tmp_path, monkeypatch, operation):
    actual_create = asyncio.create_subprocess_exec
    processes, entered = [], asyncio.Event()
    if operation == "overflow":
        code = "import sys,time;sys.stdout.buffer.write(b'x'*300000);sys.stdout.flush();time.sleep(60)"
    elif operation == "stderr":
        code = "import sys;sys.stderr.write('private/path/annotation');sys.exit(2)"
    else:
        code = "import time;time.sleep(60)"

    async def controlled(*args, **kwargs):
        process = await actual_create(sys.executable, "-c", code, **kwargs)
        processes.append(process)
        entered.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", controlled)
    adapter = LocalCVAdapter(MediaResolver(tmp_path, {}))
    ticks = 0

    async def tick():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(.005)

    ticker = asyncio.create_task(tick())
    task = asyncio.create_task(adapter._run_worker(b'{"frames":[]}'))
    await entered.wait()
    try:
        if operation == "cancel":
            await asyncio.sleep(.04)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif operation == "timeout":
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(task, .08)
        else:
            with pytest.raises(LocalCVError) as error:
                await asyncio.wait_for(task, 5)
            assert "private" not in str(error.value)
        assert processes[0].returncode is not None
        assert ticks > 0
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_total_timeout_releases_admission_and_cancels_ingestion(prepared, monkeypatch):
    import app.models.adapters.local_cv as module
    cleaned = asyncio.Event()

    class HeldIngestion:
        def __init__(self, *args, **kwargs):
            pass

        async def prepare(self, mi):
            try:
                await asyncio.sleep(60)
            finally:
                cleaned.set()

    monkeypatch.setattr(module, "MediaIngestion", HeldIngestion)
    adapter = LocalCVAdapter(prepared.resolver, timeout_sec=.05)
    result = await execute(adapter, prepared.model_input, timeout_sec=2)
    assert result.metadata.error_code and result.needs_human_review
    assert cleaned.is_set() and adapter._admitted == 0


def test_geometric_tracks_measure_motion_and_break_after_missing_detection():
    def frame(index, x=None):
        return {"frame_id": f"frame_{index:064d}", "timestamp_ms": index * 1000,
                "detections": [] if x is None else [{"bbox": [x, 20, x + 30, 80], "svm_margin": .4}]}

    tracks = _associate([frame(0, 10), frame(1, 20), frame(2), frame(3, 20)])
    assert len(tracks) == 2
    assert tracks[0]["sampled_path_length_px"] == 10
    assert tracks[0]["observed_duration_ms"] == 1000
    assert tracks[0]["sampled_speed_px_sec"] == 10
    assert tracks[1]["sampled_speed_px_sec"] is None


@pytest.mark.parametrize("changes", [{"timeout_sec": 0}, {"timeout_sec": float("inf")},
                                     {"max_frames": 0}, {"max_frame_bytes": True},
                                     {"max_waiters": 9}, {"max_waiters": -1}])
def test_invalid_resource_limits_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        LocalCVAdapter(MediaResolver(tmp_path, {}), **changes)


def test_worker_rejects_extra_annotation_input_and_invalid_bytes():
    with pytest.raises(ValueError):
        analyze({"frames": [], "annotations": {"event_class": "collapse"}})
    with pytest.raises(ValueError):
        analyze({"frames": [{"frame_id": "frame_" + "0" * 64, "timestamp_ms": 0,
                             "jpeg": base64.b64encode(b"notjpeg").decode()}]})

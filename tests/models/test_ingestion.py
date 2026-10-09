"""Synthetic video tests exercise the installed FFmpeg, not a dataset/model."""

import asyncio
import hashlib
import subprocess
import sys
import time

import pytest

from app.models.adapters.ingestion import IngestionError, MediaIngestion
from app.models.media import MediaResolver
from app.schemas.model import EvidenceFrame, TemporalState, TimeWindow


@pytest.fixture(scope="module")
def synthetic_clip():
    result = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=3:duration=2",
        "-c:v", "ffv1", "-threads:v", "1", "-f", "matroska", "pipe:1",
    ], capture_output=True, timeout=15, check=True)
    assert result.stdout
    return result.stdout


@pytest.fixture
def raw_input(mi):
    return mi.model_copy(update={
        "clip_ref": "clip_opaque", "window": TimeWindow(start_ms=0, end_ms=1700),
        "evidence": [], "temporal_state": TemporalState(),
    })


def resolver_for(tmp_path, clip):
    # Label-bearing local names remain confined to the trusted lookup layer.
    (tmp_path / "synthetic_normal_source.mkv").write_bytes(clip)
    return MediaResolver(tmp_path, {"clip_opaque": "synthetic_normal_source.mkv"})


def jpeg_dimensions(data):
    offset = 2
    while offset < len(data):
        assert data[offset] == 255
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2:offset + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return (int.from_bytes(data[offset + 7:offset + 9], "big"),
                    int.from_bytes(data[offset + 5:offset + 7], "big"))
        offset += 2 + length
    raise AssertionError("JPEG has no size marker")


async def test_real_decoder_actual_pts_resize_hashes_and_reproducible_refs(tmp_path, synthetic_clip, raw_input):
    resolver = resolver_for(tmp_path, synthetic_clip)
    ingestion = MediaIngestion(resolver)
    original = raw_input.model_dump()
    prepared = await ingestion.prepare(raw_input)
    again = await ingestion.prepare(raw_input)
    assert raw_input.model_dump() == original
    assert [f.timestamp_ms for f in prepared.model_input.evidence] == [0, 667, 1000, 1333]
    assert prepared.profile["targets_ms"] == [0, 425, 850, 1275]
    assert prepared.model_input.evidence == again.model_input.evidence
    assert prepared.clip_sha256 == hashlib.sha256(synthetic_clip).hexdigest()
    assert prepared.resolver.read("clip_opaque") == synthetic_clip
    assert prepared.ffmpeg_version and prepared.extractor_version == "ffmpeg-fixed-grid-v1"
    assert prepared.preprocessing_ms > 0
    assert prepared.profile["frame_count"] == prepared.profile["actual_frame_count"] == 4
    for frame in prepared.model_input.evidence:
        data = prepared.resolver.read(frame.media_ref)
        assert data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
        assert jpeg_dimensions(data) == (640, 360)
        assert prepared.frame_sha256[frame.frame_id] == hashlib.sha256(data).hexdigest()
    assert "synthetic_normal" not in prepared.model_input.model_dump_json()


async def test_annotations_do_not_drive_sampling_and_raw_features_reset(tmp_path, synthetic_clip, raw_input):
    ingestion = MediaIngestion(resolver_for(tmp_path, synthetic_clip))
    dirty = raw_input.model_copy(update={
        "evidence": [EvidenceFrame(frame_id="annotation", timestamp_ms=123, media_ref="unused")],
        "temporal_state": TemporalState(events=[{"label": "collapse", "timestamp_ms": 999}],
                                       feature_version="annotation-never-use"),
    })
    clean_result, dirty_result = await ingestion.prepare(raw_input), await ingestion.prepare(dirty)
    assert clean_result.model_input.evidence == dirty_result.model_input.evidence
    assert dirty_result.model_input.temporal_state == TemporalState()


async def test_sparse_targets_emit_actual_frame_once(tmp_path, synthetic_clip, raw_input):
    raw_input = raw_input.model_copy(update={"window": TimeWindow(start_ms=0, end_ms=100)})
    prepared = await MediaIngestion(resolver_for(tmp_path, synthetic_clip)).prepare(raw_input)
    assert [f.timestamp_ms for f in prepared.model_input.evidence] == [0]
    assert prepared.profile["frame_count"] == 4
    assert prepared.profile["actual_frame_count"] == 1 and prepared.profile["sparse_coverage"]


@pytest.mark.parametrize("failure", ["missing_ref", "unknown_ref", "empty", "corrupt", "no_frames", "bad_window", "escape"])
async def test_explicit_invalid_media_failures(tmp_path, synthetic_clip, raw_input, failure):
    resolver = resolver_for(tmp_path, synthetic_clip)
    if failure == "missing_ref":
        raw_input = raw_input.model_copy(update={"clip_ref": None})
    elif failure == "unknown_ref":
        raw_input = raw_input.model_copy(update={"clip_ref": "unknown"})
    elif failure in ("empty", "corrupt"):
        resolver = resolver.with_assets({"bad": b"" if failure == "empty" else b"not-video-secret"})
        raw_input = raw_input.model_copy(update={"clip_ref": "bad"})
    elif failure == "no_frames":
        raw_input = raw_input.model_copy(update={"window": TimeWindow(start_ms=3000, end_ms=4000)})
    elif failure == "bad_window":
        raw_input = raw_input.model_copy(update={"window": TimeWindow.model_construct(start_ms=5, end_ms=1)})
    elif failure == "escape":
        resolver = MediaResolver(tmp_path, {"clip_opaque": "../outside-secret.mkv"})
    with pytest.raises(IngestionError) as caught:
        await MediaIngestion(resolver).prepare(raw_input)
    assert "secret" not in str(caught.value) and str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("budget", ["clip", "frame"])
async def test_actual_byte_budgets(tmp_path, synthetic_clip, raw_input, budget):
    kwargs = {"max_clip_bytes": 32} if budget == "clip" else {"max_frame_bytes": 32}
    with pytest.raises(IngestionError):
        await MediaIngestion(resolver_for(tmp_path, synthetic_clip), **kwargs).prepare(raw_input)


@pytest.mark.parametrize("kwargs", [
    {"frame_count": 0}, {"frame_count": 17}, {"frame_count": True},
    {"width": 999999}, {"height": 0}, {"timeout_sec": float("nan")},
    {"timeout_sec": float("inf")}, {"timeout_sec": 0}, {"max_clip_bytes": 0},
])
def test_invalid_fixed_budgets(tmp_path, kwargs):
    with pytest.raises(ValueError):
        MediaIngestion(MediaResolver(tmp_path, {}), **kwargs)


async def test_read_and_decode_preserve_event_loop(tmp_path, synthetic_clip, raw_input):
    class SlowResolver(MediaResolver):
        def read(self, *args, **kwargs):
            time.sleep(.08)
            return super().read(*args, **kwargs)

    resolver = SlowResolver(tmp_path, {}, assets={"clip_opaque": synthetic_clip})
    ticks = 0
    task = asyncio.create_task(MediaIngestion(resolver).prepare(raw_input))
    while not task.done():
        await asyncio.sleep(.005)
        ticks += 1
    await task
    assert ticks >= 5


@pytest.mark.parametrize("action", ["timeout", "cancel"])
async def test_running_child_is_killed_and_reaped(tmp_path, raw_input, monkeypatch, action):
    actual_create = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    children, commands = [], []

    async def controlled_child(*args, **kwargs):
        commands.append(args)
        # An actual child process hangs after consuming input; no fabricated media.
        process = await actual_create(sys.executable, "-c", "import sys,time;sys.stdin.buffer.read();time.sleep(60)", **kwargs)
        children.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", controlled_child)
    resolver = MediaResolver(tmp_path, {}, assets={"clip_opaque": b"synthetic-control"})
    ingestion = MediaIngestion(resolver, timeout_sec=.4 if action == "timeout" else 15)
    task = asyncio.create_task(ingestion.prepare(raw_input))
    await asyncio.wait_for(spawned.wait(), 2)
    if action == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(IngestionError, match="timed out"):
            await task
    assert children[0].returncode is not None
    command = commands[0]
    assert command[command.index("-protocol_whitelist") + 1] == "pipe"
    assert command[command.index("-i") + 1] == "pipe:0"
    assert "synthetic_normal" not in " ".join(command)


async def test_decoder_stderr_is_sanitized(tmp_path, raw_input, monkeypatch):
    actual_create = asyncio.create_subprocess_exec

    async def failed_child(*args, **kwargs):
        return await actual_create(sys.executable, "-c", "import sys;sys.stderr.write('secret-label/path/key');sys.exit(1)", **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failed_child)
    resolver = MediaResolver(tmp_path, {}, assets={"clip_opaque": b"synthetic-control"})
    with pytest.raises(IngestionError) as caught:
        await MediaIngestion(resolver).prepare(raw_input)
    assert "secret" not in str(caught.value) and "key" not in str(caught.value)

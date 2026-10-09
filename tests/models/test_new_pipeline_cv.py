"""Pixel/mapping/worker boundary tests; never downloads or executes YOLO."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from app.models.adapters.new_pipeline_cv import Adapter


@pytest.fixture
def fixture_input(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    # Sentinel RGB [203, 41, 7]; OpenCV input is BGR.
    pixels = np.zeros((1080, 1920, 3), dtype=np.uint8)
    pixels[:] = [7, 41, 203]
    ok, encoded = cv2.imencode(".png", pixels)
    assert ok
    image = tmp_path / "neutral.png"
    image.write_bytes(encoded.tobytes())
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    frames = [{"frame_id": f"F{i:03d}", "source_id": "SRC01" if i < 32 else "SRC02",
               "frame_number": (i % 32) * 30, "timestamp_sec": float(i % 32),
               "width": 1920, "height": 1080, "image_path": str(image), "sha256": digest}
              for i in range(64)]
    weights = tmp_path / "models" / "yolo26s.pt"
    weights.parent.mkdir()
    weights.write_bytes(b"fixture-not-a-model")
    return {"sources": ["SRC01", "SRC02"], "frames": frames,
            "prompt": "No annotations", "output_schema": {}}, tmp_path


def context(root):
    def write(path, obj):
        path.write_text(json.dumps(obj, allow_nan=False), encoding="utf-8")
    return {"artifact_dir": root, "package_root": root, "write_json": write,
            "allow_paid": False, "budget": None}


def raw_response(frames):
    return {"status": "ok", "features": {
        "frames": [{"frame_index": i, "camera": f["source_id"],
                    "timestamp_sec": f["timestamp_sec"],
                    "detections": [{"class_id": 0, "class_name": "person", "bbox": [2., 3., 20., 30.],
                                    "confidence": .8, "track_id": 1}]} for i, f in enumerate(frames)],
        "tracks": [{"camera": s, "track_id": 1} for s in ["SRC01", "SRC02"]],
        "compact_state": {"quality": {"zone_configured": False}},
        "quality": {"zone_configured": False}, "limitations": ["Sparse samples"]},
        "weights_sha256": {"detector_weights": "abc"}, "versions": {"python": "test"},
        "timings_ms": {"detect": 100}, "memory": {"peak_rss_bytes": 10}}


@pytest.mark.parametrize("mutation", ["count", "duplicate", "source", "order", "hash", "resolution"])
def test_input_validation(fixture_input, mutation):
    inp, _ = fixture_input
    if mutation == "count":
        inp["frames"].pop()
    elif mutation == "duplicate":
        inp["frames"][1]["frame_id"] = inp["frames"][0]["frame_id"]
    elif mutation == "source":
        inp["frames"][1]["source_id"] = "SRC99"
    elif mutation == "order":
        inp["frames"][1]["timestamp_sec"] = 0
    elif mutation == "hash":
        inp["frames"][1]["sha256"] = "invalid"
    else:
        inp["frames"][1]["width"] = 640
    with pytest.raises(ValueError):
        Adapter({})._validate(inp)


def test_source_order_is_local_and_tracks_not_merged(fixture_input):
    inp, _ = fixture_input
    adapter = Adapter({})
    assert len(adapter._validate(inp)) == 64
    out = adapter._normalize(raw_response(inp["frames"]), inp["frames"])
    assert [(t["source_id"], t["track_id"]) for t in out["tracks"]] == [("SRC01", 1), ("SRC02", 1)]
    assert out["frames"][32]["timestamp_sec"] == 0
    assert out["frames"][32]["frame_id"] == "F032"


def test_png_bytes_decode_to_actual_rgb(fixture_input):
    inp, root = fixture_input
    adapter = Adapter({})
    stream, header = adapter._pack(inp["frames"][:1], adapter._worker_config(root))
    try:
        size = int.from_bytes(stream.read(4), "big")
        actual_header = json.loads(stream.read(size))
        assert actual_header == header
        pixels = stream.read()
        assert len(pixels) == 1920 * 1080 * 3
        assert pixels[:3] == bytes([203, 41, 7])
        assert pixels[-3:] == bytes([203, 41, 7])
        assert hashlib.sha256(pixels).hexdigest() == header["frames"][0]["sha256"]
        assert header["frames"][0]["camera"] == "SRC01"
        assert "image_path" not in json.dumps(header)
    finally:
        stream.close()


def test_corrupted_png_hash_refused_before_inference(fixture_input):
    inp, root = fixture_input
    inp["frames"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash/format"):
        Adapter({})._pack(inp["frames"][:1], Adapter({})._worker_config(root))


@pytest.mark.asyncio
async def test_valid_response_artifacts_no_gt_and_no_paid_calls(fixture_input, monkeypatch):
    inp, root = fixture_input
    inp["ground_truth"] = {"private": "FORBIDDEN_SENTINEL"}
    adapter = Adapter({})
    stream = tempfile.TemporaryFile()
    monkeypatch.setattr(adapter, "_pack", lambda *a: (stream, {"frames": []}))
    async def invoke(_):
        assert json.loads((root / "yolo.request.json").read_text())["phase"] == "ready"
        return json.dumps(raw_response(inp["frames"])).encode(), 0
    monkeypatch.setattr(adapter, "_invoke", invoke)
    out = await adapter.run(inp, context(root))
    assert out["status"] == "ok" and out["executed"] is True
    assert len(out["output"]["frames"]) == 64
    assert out["cost_usd"]["value"] == 0
    assert out["metadata"]["pose"] is False
    assert out["metadata"]["additional_frames"] == 0
    assert "FORBIDDEN_SENTINEL" not in (root / "yolo.request.json").read_text()
    assert "image_path" not in (root / "yolo.request.json").read_text()
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", b'{"status":"error","error_code":"worker_error"}'])
async def test_worker_failure_retains_raw_without_fake_model_output(fixture_input, monkeypatch, body):
    inp, root = fixture_input
    adapter = Adapter({})
    monkeypatch.setattr(adapter, "_pack", lambda *a: (tempfile.TemporaryFile(), {"frames": []}))
    async def invoke(_):
        return body, 0
    monkeypatch.setattr(adapter, "_invoke", invoke)
    out = await adapter.run(inp, context(root))
    assert out["status"] == "error" and out["output"] is None
    assert out["executed"] is None
    assert out["errors"][0]["category"] == "execution"
    assert json.loads((root / "yolo.response.json").read_text())["status"] == "error"


@pytest.mark.asyncio
async def test_malformed_worker_raw_survives_transport_error_record(fixture_input, monkeypatch):
    inp, root = fixture_input
    body = b"{ malformed ORIGINAL_WORKER_RESPONSE_SENTINEL"
    adapter = Adapter({})
    monkeypatch.setattr(adapter, "_pack", lambda *a: (tempfile.TemporaryFile(), {"frames": []}))
    async def invoke(_):
        return body, 0
    monkeypatch.setattr(adapter, "_invoke", invoke)
    out = await adapter.run(inp, context(root))
    assert out["status"] == "error" and out["output"] is None
    assert out["executed"] is None
    response = json.loads((root / "yolo.response.json").read_text())
    assert response["error_code"] == "invalid_worker_json"
    assert response["raw_text"] == body.decode("utf-8")
    transport = json.loads((root / "yolo.transport_error.json").read_text())
    assert transport["error_code"] == "worker_transport_error"


@pytest.mark.asyncio
async def test_invalid_worker_mapping_is_benchmark_conversion_error(fixture_input, monkeypatch):
    inp, root = fixture_input
    raw = raw_response(inp["frames"])
    raw["features"]["frames"][32]["camera"] = "SRC01"
    adapter = Adapter({})
    monkeypatch.setattr(adapter, "_pack", lambda *a: (tempfile.TemporaryFile(), {"frames": []}))
    async def invoke(_):
        return json.dumps(raw).encode(), 0
    monkeypatch.setattr(adapter, "_invoke", invoke)
    out = await adapter.run(inp, context(root))
    assert out["status"] == "error" and out["executed"] is True
    assert out["output"] is None
    assert out["errors"][0]["category"] == "benchmark"
    assert json.loads((root / "yolo.response.json").read_text()) == raw


@pytest.mark.asyncio
async def test_async_worker_stdin_is_file_and_stdout_bounded(tmp_path, monkeypatch):
    worker = tmp_path / "worker.py"
    worker.write_text("import sys,json\nx=sys.stdin.buffer.read()\nprint(json.dumps({'bytes':len(x)}))\n", encoding="utf-8")
    adapter = Adapter({})
    monkeypatch.setattr(adapter, "_worker_path", lambda: worker)
    with tempfile.TemporaryFile() as stream:
        stream.write(b"unused prefix+actual payload")
        stream.seek(len(b"unused prefix+"))
        body, code = await adapter._invoke(stream)
    assert code == 0
    assert json.loads(body) == {"bytes": len(b"actual payload")}


def test_alternate_local_checkpoint_allowed(fixture_input):
    _, root = fixture_input
    checkpoint = root / "models" / "another-coco-yolo.pt"
    checkpoint.write_bytes(b"not-a-real-model")
    assert Adapter({"weights": "models/another-coco-yolo.pt"})._worker_config(root)["detector_weights"] == str(checkpoint)

"""Offline boundary checks with real encoded pixels and an injected fake detector.

No model checkpoint, network, model inference, or accuracy claim is involved.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.models.adapters import annotation_detector as adapter


class FakeTensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return copy.deepcopy(self.values)


class FakeDetector:
    names = dict(adapter.COCO_CLASSES)

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses

    def predict(self, **kwargs):
        # Only pixel arrays are allowed across the inference boundary.
        import numpy as np
        assert isinstance(kwargs["source"], np.ndarray)
        self.calls.append({**kwargs, "source": kwargs["source"].copy()})
        if self.responses is not None:
            response = self.responses[len(self.calls) - 1]
            if isinstance(response, Exception):
                raise response
            return response
        shape = kwargs["source"].shape[:2]
        return [make_result(shape=shape)]


def make_result(*, shape=(480, 960), boxes=None, classes=None, scores=None):
    classes = list(adapter.COCO_CLASSES) if classes is None else classes
    if boxes is None:
        boxes = [[700.25 + i, 100.5, 900.75 + i, 300.5] for i in range(len(classes))]
    if scores is None:
        scores = [.081 + i * .1 for i in range(len(classes))]
    return SimpleNamespace(orig_shape=shape, boxes=SimpleNamespace(
        xyxy=FakeTensor(boxes), cls=FakeTensor(classes), conf=FakeTensor(scores)))


@pytest.fixture
def media(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    pixels = np.zeros((480, 960, 3), dtype=np.uint8)
    pixels[:] = [17, 41, 203]  # BGR sentinel verifies decode and channel order.
    frames = []
    for i, sid in enumerate(("SRC01", "SRC02")):
        image = pixels if i == 0 else np.zeros_like(pixels)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        path = tmp_path / f"{i + 1:03d}.png"
        path.write_bytes(encoded.tobytes())
        frames.append({"frame_id": f"{sid}-F000021", "source_id": sid,
                       "frame_number": 21, "timestamp_sec": .7, "width": 960,
                       "height": 480, "image_path": str(path),
                       "sha256": hashlib.sha256(encoded.tobytes()).hexdigest()})
    weights = tmp_path / "rtdetr-l.pt"
    weights.write_bytes(b"explicit test fixture, not model weights")
    return weights, frames


def run(media, detector=None, **kwargs):
    weights, frames = media
    detector = detector or FakeDetector()
    result = adapter.generate_candidates(weights, frames, detector_factory=lambda _: detector, **kwargs)
    return result, detector


def test_real_pixels_only_and_one_frame_memory_batch(media):
    result, detector = run(media)
    assert len(detector.calls) == 2
    assert detector.calls[0]["source"].shape == (480, 960, 3)
    assert detector.calls[0]["source"][0, 0].tolist() == [17, 41, 203]
    assert detector.calls[1]["source"].max() == 0
    for call in detector.calls:
        assert call["classes"] == [0, 1, 2, 3, 5, 7]
        assert call["batch"] == 1 and call["device"] == "cpu"
        assert call["imgsz"] == 640 and call["conf"] == .08
        assert call["save"] is False and call["stream"] is False
        assert not {"frame_id", "image_path", "source_id", "timestamp_sec"} & call.keys()
    assert result["settings"]["coordinates"] == "original_pixel_xyxy"


def test_all_six_classes_original_pixels_no_threshold_or_scale_rewrite(media):
    result, _ = run(media)
    for frame in result["frames"]:
        detections = frame["detections"]
        assert [(d["class_id"], d["class_name"]) for d in detections] == [
            (0, "person"), (1, "bicycle"), (2, "car"), (3, "motorcycle"), (5, "bus"), (7, "truck")]
        # Original x=900 exceeds inference imgsz=640: never normalize/rescale twice.
        assert detections[0]["bbox_xyxy"] == [700.25, 100.5, 900.75, 300.5]
        assert detections[0]["confidence"] == .081
        assert detections[0]["outside_image"] is False


def test_provenance_unreviewed_not_ground_truth_and_black_candidates_retained(media):
    weights, original = media
    before = copy.deepcopy(original)
    result, _ = run(media)
    assert original == before
    assert result["artifact_type"] == "annotation_candidates"
    assert result["reviewed"] is False and result["ground_truth_eligible"] is False
    assert result["inference_kind"] == "injected_test_detector"
    assert result["model"]["weights_sha256"] == hashlib.sha256(weights.read_bytes()).hexdigest()
    assert result["versions"]["python"]
    for saved, declared in zip(result["frames"], original):
        for field in adapter.FRAME_FIELDS:
            assert saved[field] == declared[field]
        assert saved["reviewed"] is False
        assert all(d["reviewed"] is False for d in saved["detections"])
        assert saved["timings_ms"]["predict"] >= 0
    assert result["frames"][0]["quality"]["black_frame"] is False
    assert result["frames"][1]["quality"]["black_frame"] is True
    assert len(result["frames"][1]["detections"]) == 6
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("weight_name", ["missing/rtdetr-l.pt", "yolo26s.pt", "rtdetr-l.yaml",
                                         "rtdetr-x.pt", "https://example.com/rtdetr-l.pt"])
def test_unknown_or_missing_model_never_reaches_constructor(media, weight_name):
    weights, frames = media
    path = weights.parent / weight_name
    if "/" not in weight_name:
        path.write_bytes(b"not a permitted model")
    calls = []
    with pytest.raises(ValueError, match="local rtdetr-l.pt"):
        adapter.generate_candidates(path, frames, detector_factory=lambda p: calls.append(p))
    assert calls == []


@pytest.mark.parametrize("mutation", ["annotation", "duplicate", "source", "number", "bool_number",
                                       "timestamp", "hash_format", "url", "missing"])
def test_invalid_or_label_bearing_manifest_rejected_before_detector(media, mutation):
    weights, frames = media
    frame = frames[0]
    if mutation == "annotation":
        frame["ground_truth"] = {"class": "person"}
    elif mutation == "duplicate":
        frames[1] = dict(frame)
    elif mutation == "source":
        frame["source_id"] = "injury"
    elif mutation == "number":
        frame["frame_number"] = 22
    elif mutation == "bool_number":
        frame["frame_number"] = True
    elif mutation == "timestamp":
        frame["timestamp_sec"] = float("nan")
    elif mutation == "hash_format":
        frame["sha256"] = "invalid"
    elif mutation == "url":
        frame["image_path"] = "https://example.com/001.png"
    else:
        frame["image_path"] = str(weights.parent / "absent.png")
    called = []
    with pytest.raises(ValueError):
        adapter.generate_candidates(weights, frames, detector_factory=lambda p: called.append(p))
    assert called == []


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("width", 640), ("height", 360)])
def test_declared_media_integrity_failure_never_predicts(media, field, value):
    media[1][0][field] = value
    detector = FakeDetector()
    with pytest.raises(ValueError, match="mismatch"):
        run(media, detector)
    assert detector.calls == []


@pytest.mark.parametrize("bad_result", [
    make_result(classes=[4]),
    make_result(classes=[.5]),
    make_result(classes=[0], scores=[float("nan")]),
    make_result(classes=[0], scores=[1.1]),
    make_result(classes=[0], boxes=[[0, 2, float("inf"), 4]]),
    make_result(classes=[0], boxes=[[4, 2, 1, 4]]),
    make_result(classes=[0], scores=[]),
    make_result(shape=(640, 640)),
])
def test_invalid_prediction_raises_no_fabricated_candidates(media, bad_result):
    with pytest.raises(ValueError):
        run(media, FakeDetector(responses=[[bad_result]]))


def test_outside_raw_box_preserved_and_flagged(media):
    raw = make_result(classes=[0], boxes=[[-1.25, 0, 970.5, 481]])
    result, _ = run(media, FakeDetector(responses=[[raw], [raw]]))
    detection = result["frames"][0]["detections"][0]
    assert detection["bbox_xyxy"] == [-1.25, 0., 970.5, 481.]
    assert detection["outside_image"] is True


def test_model_class_names_must_match_coco(media):
    detector = FakeDetector()
    detector.names = {**adapter.COCO_CLASSES, 0: "face"}
    with pytest.raises(ValueError, match="COCO"):
        run(media, detector)
    assert detector.calls == []


def test_production_loader_rejects_yolo_architecture_even_with_rtdetr_filename(media, monkeypatch):
    weights, frames = media
    constructed, threads = [], []
    class GenericDetectionModel:
        # YOLO and legacy official RT-DETR checkpoints share this base class.
        model = [object()]  # A non-RTDETR terminal head must not pass.
    class ExpectedRTDETRDecoder:
        pass
    def constructor(path):
        constructed.append(path)
        return SimpleNamespace(model=GenericDetectionModel())
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=threads.append))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(RTDETR=constructor))
    monkeypatch.setitem(sys.modules, "ultralytics.nn.tasks", SimpleNamespace(DetectionModel=GenericDetectionModel))
    monkeypatch.setitem(sys.modules, "ultralytics.nn.modules.head", SimpleNamespace(RTDETRDecoder=ExpectedRTDETRDecoder))
    with pytest.raises(ValueError, match="architecture"):
        adapter.generate_candidates(weights, frames)
    assert constructed == [str(weights.resolve())]
    assert threads == [1]


@pytest.mark.parametrize("specialized_class", [False, True])
def test_production_loader_accepts_official_generic_or_specialized_rtdetr_network(media, monkeypatch,
                                                                                 specialized_class):
    weights, frames = media
    class ExpectedRTDETRDecoder:
        pass
    class GenericDetectionModel:
        model = [object(), ExpectedRTDETRDecoder()]
    class SpecializedRTDETRDetectionModel(GenericDetectionModel):
        pass
    detector = FakeDetector()
    detector.model = (SpecializedRTDETRDetectionModel() if specialized_class
                      else GenericDetectionModel())
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(RTDETR=lambda _: detector))
    monkeypatch.setitem(sys.modules, "ultralytics.nn.tasks", SimpleNamespace(DetectionModel=GenericDetectionModel))
    monkeypatch.setitem(sys.modules, "ultralytics.nn.modules.head", SimpleNamespace(RTDETRDecoder=ExpectedRTDETRDecoder))
    result = adapter.generate_candidates(weights, frames)
    assert result["inference_kind"] == "local_rtdetr"
    assert len(detector.calls) == len(frames)
    assert result["reviewed"] is False


def test_zero_byte_checkpoint_rejected_before_constructor(media):
    weights, frames = media
    weights.write_bytes(b"")
    calls = []
    with pytest.raises(ValueError, match="empty checkpoint"):
        adapter.generate_candidates(weights, frames, detector_factory=lambda p: calls.append(p))
    assert calls == []


def test_empty_detection_frame_is_valid_but_prediction_exception_is_failure(media):
    empty = make_result(classes=[], boxes=[], scores=[])
    result, _ = run(media, FakeDetector(responses=[[empty], [empty]]))
    assert [f["detections"] for f in result["frames"]] == [[], []]
    with pytest.raises(RuntimeError, match="inference failed"):
        run(media, FakeDetector(responses=[RuntimeError("inference failed")]))


@pytest.mark.parametrize("response", [[], [make_result(), make_result()], None])
def test_wrong_prediction_frame_count_is_failure(media, response):
    with pytest.raises(ValueError, match="one prediction result"):
        run(media, FakeDetector(responses=[response]))


def test_jpeg_header_supported_and_invalid_encoded_frames_raise(media):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    weights, frames = media
    ok, encoded = cv2.imencode(".jpg", np.full((480, 960, 3), 50, dtype=np.uint8))
    assert ok
    image = weights.parent / "001.jpg"
    image.write_bytes(encoded.tobytes())
    frames[0]["image_path"] = str(image)
    frames[0]["sha256"] = hashlib.sha256(encoded.tobytes()).hexdigest()
    result, _ = run(media)
    assert result["frames"][0]["width"] == 960
    image.write_bytes(b"not an encoded image")
    frames[0].pop("sha256")
    with pytest.raises(ValueError, match="PNG or JPEG"):
        run(media)


def test_pixel_budget_checked_before_decode(media, monkeypatch):
    weights, frames = media
    path = Path(frames[0]["image_path"])
    oversized = b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR"
    oversized += (100_000).to_bytes(4, "big") + (100_000).to_bytes(4, "big")
    path.write_bytes(oversized)
    frames[0].pop("sha256")
    import cv2
    def forbidden_decode(*_):
        pytest.fail("compressed oversized image reached decoder")
    monkeypatch.setattr(cv2, "imdecode", forbidden_decode)
    with pytest.raises(ValueError, match="pixel budget"):
        run(media)


def test_cli_relative_manifest_and_no_output_on_failure(media, monkeypatch):
    weights, frames = media
    root = weights.parent
    for frame in frames:
        frame["image_path"] = Path(frame["image_path"]).name
    manifest = root / "frames.json"
    manifest.write_text(json.dumps(frames), encoding="utf-8")
    output = root / "candidates.json"
    detector = FakeDetector()
    monkeypatch.setattr(adapter, "_load_detector", lambda _: detector)
    assert adapter.main(["--weights", str(weights), "--frames", str(manifest),
                         "--output", str(output), "--device", "cpu", "--imgsz", "640", "--conf", ".08"]) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["frames"][1]["image_path"] == str(root / "002.png")
    assert saved["frames"][1]["frame_id"] == "SRC02-F000021"
    with pytest.raises(ValueError, match="new candidate"):
        adapter.main(["--weights", str(weights), "--frames", str(manifest), "--output", str(output)])
    failed_output = root / "failed.json"
    monkeypatch.setattr(adapter, "_load_detector", lambda _: FakeDetector(responses=[RuntimeError("failed")]))
    with pytest.raises(RuntimeError):
        adapter.main(["--weights", str(weights), "--frames", str(manifest), "--output", str(failed_output)])
    assert not failed_output.exists()


@pytest.mark.parametrize("settings", [{"device": "cuda"}, {"imgsz": 4096}, {"imgsz": 639}, {"conf": 0},
                                       {"conf": float("nan")}, {"conf": True}])
def test_bounded_cpu_settings(media, settings):
    with pytest.raises(ValueError, match="CPU device"):
        run(media, **settings)

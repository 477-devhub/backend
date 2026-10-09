"""Offline RT-DETR annotation candidates; never ground truth or runtime assessment.

Run this synchronous CLI in a disposable subprocess with a caller-owned timeout.
No registry integration is intended. MAIN supplies independently obtained weights
and reviews boxes visually before creating any ground-truth artifact.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path
import platform
import re
from time import perf_counter


COCO_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
MAX_FRAMES = 768
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 8_000_000
MAX_DETECTIONS = 300
FRAME_FIELDS = {"frame_id", "source_id", "frame_number", "image_path", "timestamp_sec",
                "width", "height", "sha256"}


def _local_weights(weights):
    path = Path(weights)
    # Check before importing/constructing Ultralytics, whose shorthand may download.
    if path.name != "rtdetr-l.pt" or not path.is_file():
        raise ValueError("explicit existing local rtdetr-l.pt checkpoint required; downloads disabled")
    path = path.resolve(strict=True)
    if not 0 < path.stat().st_size <= 1024 * 1024 * 1024:
        raise ValueError("checkpoint byte budget exceeded or empty checkpoint")
    return path


def _digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _encoded_dimensions(data):
    """Bound decoded allocation before OpenCV sees compressed image bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    elif data.startswith(b"\xff\xd8"):
        offset, dimensions = 2, None
        while offset < len(data):
            if data[offset] != 255:
                raise ValueError("invalid JPEG header")
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD9, 0xDA):
                break
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                raise ValueError("invalid JPEG segment")
            if marker in (0xC0, 0xC1, 0xC2):
                if length < 8:
                    raise ValueError("invalid JPEG dimensions")
                dimensions = (int.from_bytes(data[offset + 5:offset + 7], "big"),
                              int.from_bytes(data[offset + 3:offset + 5], "big"))
                break
            offset += length
        if dimensions is None:
            raise ValueError("JPEG dimensions unavailable")
        width, height = dimensions
    else:
        raise ValueError("PNG or JPEG frame required")
    if not 0 < width * height <= MAX_PIXELS or width <= 0 or height <= 0:
        raise ValueError("decoded pixel budget exceeded")
    return width, height


def _validate_frames(frames, base_dir):
    if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
        raise ValueError("frame list budget must be 1..768")
    validated, seen, locations = [], set(), set()
    for frame in frames:
        required = {"frame_id", "source_id", "frame_number", "image_path"}
        if not isinstance(frame, dict) or not required <= frame.keys() or frame.keys() - FRAME_FIELDS:
            raise ValueError("only declared frame provenance fields allowed; no annotations")
        source, fid, number = frame["source_id"], frame["frame_id"], frame["frame_number"]
        if (not isinstance(source, str) or not re.fullmatch(r"SRC\d{2}", source)
                or not isinstance(fid, str) or not re.fullmatch(re.escape(source) + r"-F\d+", fid)
                or type(number) is not int or number < 0
                or int(fid.rsplit("-F", 1)[1]) != number
                or fid in seen or (source, number) in locations):
            raise ValueError("invalid or duplicate neutral frame/source mapping")
        seen.add(fid)
        locations.add((source, number))
        raw_path = frame["image_path"]
        if not isinstance(raw_path, str) or not raw_path or "://" in raw_path:
            raise ValueError("declared local image path required")
        path = Path(raw_path)
        if not path.is_absolute():
            path = base_dir / path
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("image missing or image byte budget exceeded")
        for key in ("width", "height"):
            if key in frame and (type(frame[key]) is not int or frame[key] <= 0):
                raise ValueError("invalid declared image dimensions")
        if "timestamp_sec" in frame:
            stamp = frame["timestamp_sec"]
            if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0:
                raise ValueError("invalid timestamp")
        if "sha256" in frame and (not isinstance(frame["sha256"], str)
                                    or not re.fullmatch(r"[a-f0-9]{64}", frame["sha256"])):
            raise ValueError("invalid image SHA256")
        validated.append({**frame, "image_path": str(path.resolve(strict=True))})
    return validated


def _load_detector(weights):
    import torch
    from ultralytics import RTDETR
    from ultralytics.nn.tasks import DetectionModel
    from ultralytics.nn.modules.head import RTDETRDecoder

    torch.set_num_threads(1)
    model = RTDETR(str(weights))
    # Official pretrained checkpoints may deserialize as the generic DetectionModel
    # rather than RTDETRDetectionModel. The actual terminal decoder distinguishes
    # this architecture from a YOLO Detect head; a filename or wrapper cannot.
    network = model.model
    layers = getattr(network, "model", None)
    if (not isinstance(network, DetectionModel) or layers is None or not len(layers)
            or not isinstance(layers[-1], RTDETRDecoder)):
        raise ValueError("checkpoint architecture must be RT-DETR, independent of evaluated YOLO")
    return model


def _versions():
    result = {"python": platform.python_version()}
    for package in ("ultralytics", "torch", "numpy", "opencv-python", "opencv-python-headless"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = None
    return result


def _detections(result, width, height):
    if tuple(result.orig_shape) != (height, width):
        raise ValueError("detector original shape does not match decoded frame")
    boxes = result.boxes
    if boxes is None:
        raise ValueError("detector box output unavailable")
    xyxy = boxes.xyxy.cpu().tolist()
    classes = boxes.cls.cpu().tolist()
    scores = boxes.conf.cpu().tolist()
    if not len(xyxy) == len(classes) == len(scores) or len(xyxy) > MAX_DETECTIONS:
        raise ValueError("invalid detector output lengths or detection budget")
    detections = []
    for box, cls, confidence in zip(xyxy, classes, scores):
        if (type(cls) not in (int, float) or not math.isfinite(cls) or cls != int(cls)
                or int(cls) not in COCO_CLASSES):
            raise ValueError("unexpected detector class")
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("invalid detector confidence")
        if not isinstance(box, list) or len(box) != 4 or any(
                type(x) not in (int, float) or not math.isfinite(x) for x in box):
            raise ValueError("invalid detector box")
        x1, y1, x2, y2 = box
        if not x1 < x2 or not y1 < y2:
            raise ValueError("box must have positive original-pixel area")
        detections.append({"class_id": int(cls), "class_name": COCO_CLASSES[int(cls)],
                           "confidence": float(confidence), "bbox_xyxy": [float(x) for x in box],
                           "outside_image": not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height),
                           "reviewed": False})
    return detections


def generate_candidates(weights, frames, *, base_dir=None, device="cpu", imgsz=640,
                        conf=0.08, detector_factory=None):
    """Infer one decoded BGR frame at a time; injection is only for offline tests.

    All returned six-class predictions are retained, without additional confidence
    filtering, box correction, merging, tracking, or human-review promotion.
    """
    started = perf_counter()
    checkpoint = _local_weights(weights)
    frames = _validate_frames(frames, Path(base_dir or Path.cwd()).resolve())
    if (device != "cpu" or type(imgsz) is not int or not 32 <= imgsz <= 1280
            or imgsz % 32 or type(conf) not in (int, float)
            or not math.isfinite(conf) or not 0 < conf <= 1):
        raise ValueError("CPU device, bounded image size, and finite confidence required")
    import cv2
    import numpy as np

    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    weight_hash = _digest_file(checkpoint)
    load_started = perf_counter()
    detector = (detector_factory or _load_detector)(checkpoint)
    load_ms = (perf_counter() - load_started) * 1000
    names = detector.names
    for class_id, class_name in COCO_CLASSES.items():
        if names[class_id] != class_name:
            raise ValueError("checkpoint must use the declared COCO class mapping")
    output_frames, decode_ms, predict_ms = [], 0., 0.
    for frame in frames:
        frame_started = perf_counter()
        path = Path(frame["image_path"])
        with path.open("rb") as stream:
            encoded = stream.read(MAX_IMAGE_BYTES + 1)
        if len(encoded) > MAX_IMAGE_BYTES:
            raise ValueError("image byte budget exceeded")
        image_hash = hashlib.sha256(encoded).hexdigest()
        if "sha256" in frame and frame["sha256"] != image_hash:
            raise ValueError("declared image SHA256 mismatch")
        encoded_shape = _encoded_dimensions(encoded)
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image decode failed")
        height, width = image.shape[:2]
        if (width, height) != encoded_shape:
            raise ValueError("decoded image dimensions differ from header")
        if any(key in frame and frame[key] != value for key, value in (("width", width), ("height", height))):
            raise ValueError("declared image dimensions mismatch")
        mean_intensity = float(image.mean())
        dark_fraction = float(np.mean(np.max(image, axis=2) <= 10))
        frame_decode_ms = (perf_counter() - frame_started) * 1000
        prediction_started = perf_counter()
        results = detector.predict(source=image, device=device, imgsz=imgsz, conf=conf,
                                   classes=list(COCO_CLASSES), max_det=MAX_DETECTIONS,
                                   batch=1, stream=False, verbose=False, save=False)
        frame_predict_ms = (perf_counter() - prediction_started) * 1000
        if not isinstance(results, list) or len(results) != 1:
            raise ValueError("exactly one prediction result per declared frame required")
        detections = _detections(results[0], width, height)
        output_frames.append({**frame, "width": width, "height": height, "sha256": image_hash,
                              "reviewed": False, "detections": detections,
                              "quality": {"black_frame": mean_intensity <= 5 and dark_fraction >= .99,
                                          "mean_intensity": mean_intensity, "dark_fraction": dark_fraction},
                              "timings_ms": {"decode": frame_decode_ms, "predict": frame_predict_ms}})
        decode_ms += frame_decode_ms
        predict_ms += frame_predict_ms
        del image, results
    return {"artifact_type": "annotation_candidates", "reviewed": False,
            "ground_truth_eligible": False, "schema_version": "annotation-candidates-v1",
            "inference_kind": "injected_test_detector" if detector_factory else "local_rtdetr",
            "model": {"family": "RT-DETR", "checkpoint": "rtdetr-l.pt",
                      "weights_path": str(checkpoint), "weights_sha256": weight_hash,
                      "classes": {str(k): v for k, v in COCO_CLASSES.items()}},
            "settings": {"device": device, "imgsz": imgsz, "conf": conf, "batch": 1,
                         "max_det": MAX_DETECTIONS, "coordinates": "original_pixel_xyxy",
                         "black_rule": "mean_intensity<=5 and fraction(max_bgr<=10)>=0.99"},
            "versions": _versions(), "frames": output_frames,
            "timings_ms": {"model_load": load_ms, "decode": decode_ms, "predict": predict_ms,
                           "total": (perf_counter() - started) * 1000},
            "limitations": ["Candidates require independent visual review; never ground truth.",
                            "Predictions below conf or beyond max_det are not returned by the detector.",
                            "Sparse sampled frames cannot establish event or tracking truth."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--frames", required=True, help="JSON file containing only a frame list")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", choices=["cpu"], default="cpu")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=.08)
    args = parser.parse_args(argv)
    manifest, output = Path(args.frames).resolve(), Path(args.output).resolve()
    if output == manifest or output == Path(args.weights).resolve() or output.exists():
        raise ValueError("output must be a new candidate artifact path")
    with manifest.open("rb") as stream:
        payload = stream.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("frame manifest byte budget exceeded")
    frames = json.loads(payload)
    result = generate_candidates(args.weights, frames, base_dir=manifest.parent,
                                 device=args.device, imgsz=args.imgsz, conf=args.conf)
    # No output file is created on prediction/validation failure.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

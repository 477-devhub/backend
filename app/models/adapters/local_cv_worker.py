"""One disposable CPU process. Input is validated image bytes, never file paths."""
import base64
import json
import math
import platform
import sys
from time import perf_counter


def _jpeg_dimensions(data):
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG required")
    offset = 2
    while offset < len(data):
        if data[offset] != 255:
            raise ValueError("invalid JPEG header")
        while offset < len(data) and data[offset] == 255:
            offset += 1
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9, 0xDA):
            break
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid JPEG segment")
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:
                raise ValueError("invalid JPEG dimensions")
            return (int.from_bytes(data[offset + 5:offset + 7], "big"),
                    int.from_bytes(data[offset + 3:offset + 5], "big"))
        offset += length
    raise ValueError("JPEG dimensions unavailable")


def _iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, x1 - x0) * max(0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union else 0


def _associate(frames):
    """Greedy consecutive-frame IoU association; not identity recognition."""
    tracks, active, next_id = [], {}, 1
    for frame in frames:
        current, used = {}, set()
        for detection in frame["detections"]:
            bbox = detection["bbox"]
            matches = [(track_id, _iou(previous["bbox"], bbox))
                       for track_id, previous in active.items() if track_id not in used]
            match, score = max(matches, key=lambda pair: pair[1], default=(None, 0))
            if score < .15:
                match = next_id
                next_id += 1
                tracks.append({"track_id": str(match), "observations": []})
            used.add(match)
            observation = {"frame_id": frame["frame_id"], "timestamp_ms": frame["timestamp_ms"],
                           "bbox": bbox, "detector_svm_margin": detection["svm_margin"]}
            tracks[match - 1]["observations"].append(observation)
            current[match] = observation
        active = current
    for track in tracks:
        observations = track["observations"]
        centers = [((o["bbox"][0] + o["bbox"][2]) / 2,
                    (o["bbox"][1] + o["bbox"][3]) / 2) for o in observations]
        distance = sum(math.dist(a, b) for a, b in zip(centers, centers[1:]))
        duration = observations[-1]["timestamp_ms"] - observations[0]["timestamp_ms"]
        track.update(observed_duration_ms=duration, sampled_path_length_px=distance,
                     sampled_speed_px_sec=distance * 1000 / duration if duration else None)
    return tracks


def analyze(request):
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    cv2.ocl.setUseOpenCL(False)
    if not isinstance(request, dict) or set(request) != {"frames"}:
        raise ValueError("invalid CV request")
    raw_frames = request["frames"]
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= 16:
        raise ValueError("invalid frame budget")
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    frames, last_timestamp, seen_ids = [], -1, set()
    started = perf_counter()
    for frame in raw_frames:
        if set(frame) != {"frame_id", "timestamp_ms", "jpeg"}:
            raise ValueError("invalid frame request")
        frame_id, timestamp = frame["frame_id"], frame["timestamp_ms"]
        if (not isinstance(frame_id, str) or not frame_id.startswith("frame_") or len(frame_id) != 70
                or frame_id in seen_ids or type(timestamp) is not int or timestamp <= last_timestamp):
            raise ValueError("invalid frame provenance")
        seen_ids.add(frame_id)
        last_timestamp = timestamp
        if not isinstance(frame["jpeg"], str) or len(frame["jpeg"]) > 3 * 1024 * 1024:
            raise ValueError("image exceeds byte budget")
        data = base64.b64decode(frame["jpeg"], validate=True)
        if len(data) > 2 * 1024 * 1024 or _jpeg_dimensions(data) != (640, 360):
            raise ValueError("image dimensions/profile invalid")
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != (360, 640, 3):
            raise ValueError("invalid image")
        boxes, weights = hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.05)
        if len(boxes) > 100:
            raise ValueError("detection budget exceeded")
        detections = []
        for (x, y, width, height), weight in zip(boxes, weights):
            score = float(weight)
            if not math.isfinite(score):
                raise ValueError("invalid HOG margin")
            detections.append({"bbox": [max(0, int(x)), max(0, int(y)),
                                         min(640, int(x + width)), min(360, int(y + height))],
                               "svm_margin": score})
        frames.append({"frame_id": frame_id, "timestamp_ms": timestamp, "detections": detections})
    return {"temporal_state": {
        "person_count": max(len(frame["detections"]) for frame in frames),
        "vehicle_count": None, "tracks": _associate(frames), "events": [], "relations": [],
        "quality": {"sampled_frames": float(len(frames)), "detector_ms": (perf_counter() - started) * 1000},
        "feature_version": "opencv-hog-iou-v1",
    }, "versions": {"opencv": cv2.__version__, "numpy": np.__version__, "python": platform.python_version(),
                     "device": "CPU", "cv_threads": "1", "opencl": "disabled"}}


def main():
    try:
        payload = sys.stdin.buffer.read(45 * 1024 * 1024 + 1)
        if len(payload) > 45 * 1024 * 1024:
            raise ValueError("request exceeds budget")
        result = analyze(json.loads(payload))
        sys.stdout.write(json.dumps(result, allow_nan=False))
    except Exception:
        sys.stderr.write("local CV processing failed\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

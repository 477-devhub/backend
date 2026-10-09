"""Isolated YOLO/ByteTrack worker. Reads only canonical pixel observations."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import inspect
import json
import math
from pathlib import Path
import statistics
import sys
import threading
from time import perf_counter
from types import SimpleNamespace


COCO_CLASSES = [0, 1, 2, 3, 5, 7]  # person, bicycle, car, motorcycle, bus, truck
CLASS_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
LIMITATIONS = [
    "Sparse canonical samples: ByteTrack Kalman steps are samples, not decoded-video frames.",
    "Cross-camera identities are never matched; IDs are scoped to each camera.",
    "Observed track span and interpolated visibility do not establish continuous presence.",
    "15-second person dwell is a screen-presence candidate, not confirmed loitering.",
    "No configured restricted polygon: intrusion cannot be confirmed.",
    "Wide bounding boxes or horizontal torso are posture cues, not collapse diagnoses.",
    "Detection/pose confidence is not event confidence; no event/risk classifier is available.",
]


def profile_limitations(pose_enabled):
    """Describe available observations without treating cues as diagnoses."""
    limitations = list(LIMITATIONS)
    if not pose_enabled:
        limitations.append(
            "Pose-off: no pose model or keypoints measured; bounding-box posture cues alone do not diagnose collapse."
        )
    return limitations


def camera_profiles(frames, lost_seconds=5.):
    grouped = {}
    for frame in frames:
        grouped.setdefault(frame["camera"], []).append(frame["timestamp_sec"])
    profiles = {}
    for camera, times in grouped.items():
        times = sorted(times)
        deltas = [b-a for a, b in zip(times, times[1:])]
        if any(not math.isfinite(t) for t in times) or any(dt <= 0 for dt in deltas):
            raise ValueError("invalid timestamp sequence")
        median = statistics.median(deltas) if deltas else None
        buffer = max(1, math.ceil(lost_seconds / median)) if median else 1
        profiles[camera] = {"sample_count": len(times), "median_sample_interval_sec": median,
                            "min_sample_interval_sec": min(deltas) if deltas else None,
                            "max_sample_interval_sec": max(deltas) if deltas else None,
                            "lost_buffer_samples": buffer,
                            "lost_buffer_effective_sec": buffer * median if median else None,
                            "kalman_dt": "one_step_per_canonical_sample"}
    return profiles


def rgb_to_bgr(rgb, width=1920, height=1080):
    import numpy as np
    if len(rgb) != width * height * 3:
        raise ValueError("invalid RGB length")
    return np.frombuffer(rgb, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1].copy()


def posture_cue(bbox, keypoints=None, confidence=.4, ratio=1.2):
    width, height = bbox[2]-bbox[0], bbox[3]-bbox[1]
    wide = height > 0 and width / height >= ratio
    angle = None
    if keypoints and len(keypoints) == 17:
        selected = [keypoints[x] for x in (5, 6, 11, 12)]
        if all(point[2] >= confidence for point in selected):
            shoulder = [(selected[0][j]+selected[1][j])/2 for j in (0, 1)]
            hip = [(selected[2][j]+selected[3][j])/2 for j in (0, 1)]
            dx, dy = abs(shoulder[0]-hip[0]), abs(shoulder[1]-hip[1])
            if dx or dy:
                angle = math.degrees(math.atan2(dx, dy))
    return {"wide_box": wide, "torso_angle_from_vertical_deg": round(angle, 2) if angle is not None else None,
            "low_posture_candidate": bool(wide or (angle is not None and angle >= 60.))}


def bbox_iou(a, b):
    intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    union = max(0., a[2]-a[0])*max(0., a[3]-a[1]) + max(0., b[2]-b[0])*max(0., b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.


def summarize_track(camera, track_id, observations, lost_seconds=5., dwell_seconds=15., low_seconds=1.):
    points = sorted(observations, key=lambda x: x["timestamp_sec"])
    centers = [((p["bbox"][0]+p["bbox"][2])/2, (p["bbox"][1]+p["bbox"][3])/2) for p in points]
    deltas = [b["timestamp_sec"]-a["timestamp_sec"] for a, b in zip(points, points[1:])]
    visible = sum(dt for dt in deltas if 0 < dt <= lost_seconds)
    low_run = longest_low_run = 0.
    for previous, current, dt in zip(points, points[1:], deltas):
        if (0 < dt <= lost_seconds and previous.get("low_posture_candidate")
                and current.get("low_posture_candidate")):
            low_run += dt
            longest_low_run = max(longest_low_run, low_run)
        else:
            low_run = 0.
    classes = {point["class_id"] for point in points}
    person = classes == {0}
    return {"camera": camera, "track_id": track_id, "class_id": points[0]["class_id"],
            "class_name": CLASS_NAMES.get(points[0]["class_id"], "unknown"),
            "class_changed": len(classes) > 1,
            "first_timestamp_sec": points[0]["timestamp_sec"], "last_timestamp_sec": points[-1]["timestamp_sec"],
            "observations": len(points), "observed_span_sec": points[-1]["timestamp_sec"]-points[0]["timestamp_sec"],
            "interpolated_visible_sec": round(visible, 6), "max_observation_gap_sec": max(deltas) if deltas else None,
            "path_length_pixels": round(sum(math.dist(a, b) for a, b in zip(centers, centers[1:])), 2),
            "net_displacement_pixels": round(math.dist(centers[0], centers[-1]), 2),
            "person_dwell_candidate": person and len(points) >= 3 and visible >= dwell_seconds,
            "longest_low_posture_interval_sec": round(longest_low_run, 6),
            "sustained_low_posture_candidate": person and longest_low_run >= low_seconds,
            "evidence_frame_keys": [{"frame_index": p["frame_index"], "camera": camera,
                                      "timestamp_sec": p["timestamp_sec"]} for p in points]}


def read_exact(stream, length):
    chunks, remaining = [], length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ValueError("truncated canonical input")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def run(header, stream):
    worker_started = perf_counter()
    import numpy as np
    import psutil
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.trackers.byte_tracker import BYTETracker

    library_import_ms = (perf_counter()-worker_started)*1000

    process = psutil.Process()
    peak_rss, stopped = [process.memory_info().rss], threading.Event()

    def sample_memory():
        while not stopped.wait(.02):
            try:
                peak_rss[0] = max(peak_rss[0], process.memory_info().rss)
            except psutil.Error:
                return

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    try:
        torch.set_num_threads(4)
        config = header["config"]
        frame_headers = header["frames"]
        if header.get("version") != "yolo-canonical64-v1" or len(frame_headers) != 64:
            raise ValueError("invalid input version")
        if {f["frame_index"] for f in frame_headers} != set(range(64)):
            raise ValueError("invalid frame indices")
        profiles = camera_profiles(frame_headers, config["lost_seconds"])
        if set(profiles) - {"SRC01", "SRC02", "SRC03", "SRC04", "SRC05", "SRC06"}:
            raise ValueError("invalid camera")
        load_started = perf_counter()
        weights = {}
        for key in ("detector_weights", "pose_weights"):
            if config[key] is not None:
                path = Path(config[key])
                expected = "yolo26s.pt" if key == "detector_weights" else "yolo26s-pose.pt"
                if not path.is_absolute() or path.suffix != ".pt" or not path.is_file():
                    raise ValueError("weights must be explicit local files")
                weights[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        detector = YOLO(config["detector_weights"])
        pose = YOLO(config["pose_weights"]) if config["pose_weights"] is not None else None
        model_load_ms = (perf_counter()-load_started)*1000
        trackers, tracker_config = {}, {}
        for camera, profile in profiles.items():
            args = SimpleNamespace(track_high_thresh=.25, track_low_thresh=.1, new_track_thresh=.25,
                                   track_buffer=profile["lost_buffer_samples"], match_thresh=.8, fuse_score=True)
            kwargs = {"frame_rate": 30} if "frame_rate" in inspect.signature(BYTETracker).parameters else {}
            trackers[camera] = BYTETracker(args, **kwargs)
            tracker_config[camera] = {**vars(args), **kwargs}
        timing = {"library_import": library_import_ms, "model_load": model_load_ms,
                  "input_transfer_and_hash": 0., "rgb_to_bgr": 0., "detect": 0.,
                  "track": 0., "pose": 0., "rules": 0.}
        frame_rows, observations = [], {}
        raw_bytes = 0
        for frame in frame_headers:
            if frame["width"] != 1920 or frame["height"] != 1080:
                raise ValueError("invalid canonical resolution")
            started = perf_counter()
            payload = read_exact(stream, 1920*1080*3)
            raw_bytes += len(payload)
            if hashlib.sha256(payload).hexdigest() != frame["sha256"]:
                raise ValueError("input pixel hash mismatch")
            timing["input_transfer_and_hash"] += (perf_counter()-started)*1000
            started = perf_counter()
            bgr = rgb_to_bgr(payload)
            del payload
            timing["rgb_to_bgr"] += (perf_counter()-started)*1000
            started = perf_counter()
            result = detector.predict(bgr, imgsz=config["imgsz"], conf=config["conf"],
                                      classes=COCO_CLASSES, max_det=config["max_det"],
                                      device=config["device"], verbose=False)[0]
            timing["detect"] += (perf_counter()-started)*1000
            boxes = result.boxes.cpu().numpy()
            detection_rows = []
            for xyxy, confidence, class_id in zip(boxes.xyxy, boxes.conf, boxes.cls):
                cid = int(class_id)
                detection_rows.append({"bbox": [round(float(v), 2) for v in xyxy],
                                       "confidence": round(float(confidence), 5), "class_id": cid,
                                       "class_name": CLASS_NAMES.get(cid, "unknown"), "track_id": None})
            started = perf_counter()
            tracked = trackers[frame["camera"]].update(boxes, bgr)
            timing["track"] += (perf_counter()-started)*1000
            for track in tracked:
                index = int(track[-1])
                if 0 <= index < len(detection_rows):
                    detection_rows[index]["track_id"] = str(int(track[4]))
            pose_rows = []
            if pose is not None:
                started = perf_counter()
                pose_result = pose.predict(bgr, imgsz=config["imgsz"], conf=config["conf"],
                                           max_det=config["max_det"], device=config["device"], verbose=False)[0]
                timing["pose"] += (perf_counter()-started)*1000
                if pose_result.keypoints is not None:
                    for bbox, confidence, keypoints in zip(pose_result.boxes.xyxy.cpu().numpy(),
                            pose_result.boxes.conf.cpu().numpy(), pose_result.keypoints.data.cpu().numpy()):
                        pose_rows.append({"bbox": [round(float(v), 2) for v in bbox],
                                          "confidence": round(float(confidence), 5),
                                          "keypoints": [[round(float(p[0]), 2), round(float(p[1]), 2),
                                                         round(float(p[2]), 4)] for p in keypoints]})
            started = perf_counter()
            for detection in detection_rows:
                if detection["class_id"] == 0:
                    best = max(pose_rows, key=lambda p: bbox_iou(detection["bbox"], p["bbox"]), default=None)
                    keypoints = best["keypoints"] if best is not None and bbox_iou(detection["bbox"], best["bbox"]) >= .3 else None
                    detection["posture"] = posture_cue(detection["bbox"], keypoints,
                                                       config["pose_conf"], config["low_posture_ratio"])
                if detection["track_id"] is not None:
                    key = (frame["camera"], detection["track_id"])
                    observations.setdefault(key, []).append({"frame_index": frame["frame_index"],
                        "timestamp_sec": frame["timestamp_sec"], "bbox": detection["bbox"],
                        "class_id": detection["class_id"],
                        "low_posture_candidate": detection.get("posture", {}).get("low_posture_candidate", False)})
            timing["rules"] += (perf_counter()-started)*1000
            frame_rows.append({"frame_index": frame["frame_index"], "camera": frame["camera"],
                               "timestamp_sec": frame["timestamp_sec"], "detections": detection_rows,
                               "pose": pose_rows, "detector_speed_ms": result.speed})
        if stream.read(1):
            raise ValueError("extra noncanonical pixels")
        started = perf_counter()
        tracks = [summarize_track(camera, track_id, points, config["lost_seconds"],
                                  config["dwell_seconds"], config["low_posture_seconds"])
                  for (camera, track_id), points in sorted(observations.items())]
        timing["rules"] += (perf_counter()-started)*1000
        frame_rows.sort(key=lambda row: row["frame_index"])
        consumption = {"frame_count": 64, "raw_rgb_bytes": raw_bytes,
                       "frames": sorted(frame_headers, key=lambda row: row["frame_index"]),
                       "additional_frames": 0, "external_crops": 0,
                       "pose_frame_count": 64 if pose is not None else 0,
                       "model_resize": {"imgsz": config["imgsz"], "operation": "Ultralytics predict letterbox"}}
        compact_frames = []
        for row in frame_rows:
            counts = {name: sum(d["class_name"] == name for d in row["detections"]) for name in CLASS_NAMES.values()}
            compact_frames.append({"frame_index": row["frame_index"], "camera": row["camera"],
                "timestamp_sec": row["timestamp_sec"], "counts": counts,
                "people": [{"bbox": d["bbox"], "track_id": d["track_id"], "confidence": d["confidence"],
                            "posture": d["posture"]} for d in row["detections"] if d["class_id"] == 0]})
        quality = {"frames_without_person_detection": sum(not any(d["class_id"] == 0 for d in r["detections"]) for r in frame_rows),
                   "untracked_detections": sum(d["track_id"] is None for r in frame_rows for d in r["detections"]),
                   "total_detections": sum(len(r["detections"]) for r in frame_rows),
                   "detector_confidence_is_not_event_confidence": True,
                   "zone_configured": False, "pose_enabled": pose is not None}
        config_public = {k: v for k, v in config.items() if not k.endswith("weights")}
        limitations = profile_limitations(pose is not None)
        features = {"feature_version": "yolo-canonical64-v1", "frames": frame_rows, "tracks": tracks,
                    "camera_sampling": profiles, "consumption": consumption, "quality": quality,
                    "config": config_public, "tracker_config": tracker_config, "limitations": limitations,
                    "compact_state": {"source": "CV-derived canonical 64-frame observations",
                        "frames": compact_frames, "tracks": tracks, "camera_sampling": profiles,
                        "quality": quality, "limitations": limitations,
                        "rule_policy": {"dwell_candidate_seconds": 15, "intrusion_supported": False,
                                        "loitering_confirmed_supported": False, "event_classifier_available": False}}}
        timing["worker"] = (perf_counter()-worker_started)*1000
        peak_rss[0] = max(peak_rss[0], process.memory_info().rss)
        memory = {"process_peak_rss_bytes_sampled": peak_rss[0], "sampling_interval_ms": 20,
                  "process_peak_rss_bytes_os": getattr(process.memory_info(), "peak_wset", None),
                  "includes_model_and_one_frame": True, "peak_vram_allocated_bytes": None}
        if torch.cuda.is_available() and str(config["device"]) != "cpu":
            memory["peak_vram_allocated_bytes"] = torch.cuda.max_memory_allocated()
        return {"status": "ok", "features": features, "timings_ms": timing, "memory": memory,
                "versions": {"ultralytics": ultralytics.__version__, "torch": torch.__version__,
                             "numpy": np.__version__, "python": sys.version.split()[0]},
                "weights_sha256": weights}
    finally:
        stopped.set()
        sampler.join(timeout=.2)


def main():
    try:
        stream = sys.stdin.buffer
        length = int.from_bytes(read_exact(stream, 4), "big")
        if not 0 < length <= 65536:
            raise ValueError("header budget")
        header = json.loads(read_exact(stream, length))
        # All third-party stdout is captured on bounded stderr, never mixed with JSON.
        with redirect_stdout(sys.stderr):
            output = run(header, stream)
        encoded = json.dumps(output, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 1024*1024:
            encoded = b'{"status":"error","error_code":"payload_limit"}'
    except Exception:
        # Never expose input, local paths, environment or library exception messages.
        encoded = b'{"status":"error","error_code":"worker_error"}'
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()

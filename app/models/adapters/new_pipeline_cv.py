"""Portable canonical-64 YOLO/ByteTrack adapter; no annotation access."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter


class Adapter:
    def __init__(self, config):
        self.config = dict(config)

    def _validate(self, model_input):
        frames = model_input.get("frames", [])
        if not isinstance(frames, list) or len(frames) != 64:
            raise ValueError("exactly 64 frames required")
        sources = model_input.get("sources", [])
        ids = [s["source_id"] if isinstance(s, dict) else s for s in sources]
        if not 1 <= len(ids) <= 6 or len(set(ids)) != len(ids):
            raise ValueError("one to six distinct sources required")
        if any(s not in {f"SRC{i:02d}" for i in range(1, 7)} for s in ids):
            raise ValueError("neutral source IDs required")
        seen, last, counts = set(), {}, dict.fromkeys(ids, 0)
        for frame in frames:
            fid, sid = frame["frame_id"], frame["source_id"]
            if not isinstance(fid, str) or not fid or fid in seen or sid not in counts:
                raise ValueError("invalid frame/source mapping")
            seen.add(fid)
            number, stamp = frame["frame_number"], frame["timestamp_sec"]
            if type(number) is not int or number < 0 or isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < 0:
                raise ValueError("invalid original frame/time")
            if sid in last and (number <= last[sid][0] or stamp <= last[sid][1]):
                raise ValueError("source frame order must strictly increase")
            last[sid] = (number, stamp)
            counts[sid] += 1
            if frame["width"] != 1920 or frame["height"] != 1080:
                raise ValueError("canonical image dimensions must be 1920x1080")
            path = Path(frame["image_path"])
            if not path.is_absolute() or not path.is_file():
                raise ValueError("explicit existing PNG reference required")
            digest = frame["sha256"]
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("invalid PNG hash")
        if any(n == 0 for n in counts.values()):
            raise ValueError("every declared source requires frames")
        return frames

    def _worker_config(self, package_root):
        weights = Path(self.config.get("weights", self.config.get("detector_weights", "models/yolo26s.pt")))
        if not weights.is_absolute():
            weights = package_root / weights
        weights = weights.resolve()
        if not weights.is_file() or weights.suffix.lower() != ".pt":
            raise ValueError("existing local detector .pt checkpoint required")
        device = self.config.get("device", "cpu")
        conf = float(self.config.get("conf", .1))
        imgsz = int(self.config.get("imgsz", 960))
        if not math.isfinite(conf) or not 0 < conf <= 1 or not 32 <= imgsz <= 4096:
            raise ValueError("invalid detector settings")
        return {"detector_weights": str(weights), "pose_weights": None,
                "device": device, "imgsz": imgsz, "conf": conf,
                "max_det": 100, "lost_seconds": 5., "dwell_seconds": 15.,
                "pose_conf": .4, "low_posture_ratio": 1.2,
                "low_posture_seconds": 1., "max_output_bytes": 1024 * 1024}

    @staticmethod
    def _manifest(frames):
        return [{k: f[k] for k in ("frame_id", "source_id", "frame_number", "timestamp_sec", "width", "height", "sha256")} for f in frames]

    def _pack(self, frames, config):
        import cv2
        import numpy as np

        stream = tempfile.TemporaryFile(mode="w+b")
        try:
            stream.write(b"\0" * 65540)
            headers = []
            for index, frame in enumerate(frames):
                encoded = Path(frame["image_path"]).read_bytes()
                if not encoded.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(encoded).hexdigest() != frame["sha256"]:
                    raise ValueError("canonical PNG hash/format mismatch")
                bgr = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
                if bgr is None or bgr.shape != (1080, 1920, 3):
                    raise ValueError("decoded dimensions mismatch")
                payload = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).tobytes()
                headers.append({"frame_index": index, "camera": frame["source_id"],
                                "timestamp_sec": frame["timestamp_sec"], "width": 1920,
                                "height": 1080, "sha256": hashlib.sha256(payload).hexdigest()})
                stream.write(payload)
            header = {"version": "yolo-canonical64-v1", "config": config, "frames": headers}
            encoded_header = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
            if len(encoded_header) > 65536:
                raise ValueError("worker header budget")
            offset = 65540 - len(encoded_header) - 4
            stream.seek(offset)
            stream.write(len(encoded_header).to_bytes(4, "big"))
            stream.write(encoded_header)
            stream.flush()
            stream.seek(offset)
            return stream, header
        except BaseException:
            stream.close()
            raise

    def _worker_path(self):
        neighbor = Path(__file__).with_name("yolo_worker.py")
        return neighbor if neighbor.is_file() else Path(__file__).with_name("yolo_benchmark_worker.py")

    async def _invoke(self, stream):
        python = str(self.config.get("python_executable", sys.executable))
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process = await asyncio.create_subprocess_exec(
            python, "-B", str(self._worker_path()), stdin=stream,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        output_limit = 1024 * 1024

        async def read_stdout():
            chunks, size = [], 0
            while chunk := await process.stdout.read(65536):
                size += len(chunk)
                if size > output_limit:
                    raise ValueError("worker output budget exceeded")
                chunks.append(chunk)
            return b"".join(chunks)

        async def discard_stderr():
            # Third-party logs are intentionally not retained: may contain local paths.
            while await process.stderr.read(65536):
                pass

        tasks = [asyncio.create_task(read_stdout()), asyncio.create_task(discard_stderr()),
                 asyncio.create_task(process.wait())]
        try:
            result = await asyncio.wait_for(asyncio.gather(*tasks),
                                           timeout=float(self.config.get("timeout_sec", 600)))
            return result[0], process.returncode
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _normalize(raw, frames):
        features = raw.get("features")
        if not isinstance(features, dict) or not isinstance(features.get("frames"), list) or len(features["frames"]) != 64:
            raise ValueError("worker output lacks canonical frame results")
        rows, seen = [], set()
        for row in features["frames"]:
            index = row.get("frame_index")
            if type(index) is not int or not 0 <= index < 64 or index in seen:
                raise ValueError("worker frame index mismatch")
            seen.add(index)
            frame = frames[index]
            if row.get("camera") != frame["source_id"] or row.get("timestamp_sec") != frame["timestamp_sec"]:
                raise ValueError("worker source/time mismatch")
            detections = row.get("detections")
            if not isinstance(detections, list):
                raise ValueError("invalid detection array")
            for detection in detections:
                bbox, confidence = detection.get("bbox"), detection.get("confidence")
                if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in bbox):
                    raise ValueError("invalid detection box")
                if not 0 <= bbox[0] < bbox[2] <= 1920 or not 0 <= bbox[1] < bbox[3] <= 1080:
                    raise ValueError("detection box outside canonical frame")
                if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError("invalid detection confidence")
                if type(detection.get("class_id")) is not int or not isinstance(detection.get("class_name"), str):
                    raise ValueError("invalid detection class")
            rows.append({"frame_id": frame["frame_id"], "source_id": frame["source_id"],
                         "frame_number": frame["frame_number"], "timestamp_sec": frame["timestamp_sec"],
                         "detections": detections})
        tracks = features.get("tracks", [])
        valid_sources = {f["source_id"] for f in frames}
        if not isinstance(tracks, list) or any(t.get("camera") not in valid_sources for t in tracks):
            raise ValueError("worker track source mismatch")
        normalized_tracks = [{**t, "source_id": t["camera"]} for t in tracks]
        # Every track remains source scoped; shared numeric IDs are not identities.
        return {"frames": sorted(rows, key=lambda r: next(i for i, f in enumerate(frames) if f["frame_id"] == r["frame_id"])),
                "tracks": normalized_tracks, "compact_state": features.get("compact_state", {}),
                "quality": features.get("quality", {}), "limitations": features.get("limitations", []),
                "camera_sampling": features.get("camera_sampling", {})}

    async def run(self, model_input, context):
        started = perf_counter()
        write = context["write_json"]
        artifacts = Path(context["artifact_dir"])
        package_root = Path(context["package_root"])
        result = {"status": "error", "executed": False, "output": None,
                  "metadata": {"model": "YOLO+ByteTrack", "frame_count": 64,
                               "additional_frames": 0, "crops": 0, "pose": False},
                  "errors": [], "cost_usd": {"value": 0, "basis": "local_no_api",
                              "invoice_usd": 0, "infrastructure_usd": None}}
        stream, phase = None, "input_validation"
        try:
            frames = self._validate(model_input)
            config = self._worker_config(package_root)
            request = {"phase": "planned", "input_type": "canonical_png_to_rgb_bytes",
                       "frames": self._manifest(frames), "frame_count": 64,
                       "config": {k: v for k, v in config.items() if not k.endswith("weights")},
                       "detector_file": Path(config["detector_weights"]).name,
                       "annotations_in_input": False}
            write(artifacts / "yolo.request.json", request)
            phase = "pixel_conversion"
            conversion_started = perf_counter()
            stream, header = await asyncio.to_thread(self._pack, frames, config)
            conversion_ms = (perf_counter() - conversion_started) * 1000
            request.update({"phase": "ready", "worker_frames": header["frames"], "conversion_ms": conversion_ms})
            write(artifacts / "yolo.request.json", request)
            phase = "worker_execution"
            result["executed"] = None  # Actual model invocation cannot be inferred until worker reports.
            worker_started = perf_counter()
            body, exit_code = await self._invoke(stream)
            worker_ms = (perf_counter() - worker_started) * 1000
            try:
                raw = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                write(artifacts / "yolo.response.json", {"status": "error", "error_code": "invalid_worker_json", "raw_text": body.decode("utf-8", errors="replace")})
                raise ValueError("worker returned invalid JSON")
            write(artifacts / "yolo.response.json", raw)
            if exit_code != 0 or not isinstance(raw, dict) or raw.get("status") != "ok":
                result["errors"].append({"category": "execution", "stage": "yolo", "code": "worker_error", "detail": raw.get("error_code", "nonzero_worker_exit") if isinstance(raw, dict) else "invalid_worker_shape", "cause_confirmed": False})
                return result
            result["executed"] = True
            phase = "output_conversion"
            result["output"] = self._normalize(raw, frames)
            result.update(status="ok", executed=True)
            result["metadata"].update({"model": Path(config["detector_weights"]).name + "+ByteTrack",
                "weights_sha256": raw.get("weights_sha256"), "versions": raw.get("versions"),
                "device": config["device"], "config": request["config"],
                "timings_ms": raw.get("timings_ms", {}), "conversion_ms": conversion_ms,
                "worker_ms": worker_ms, "memory": raw.get("memory"),
                "class_mapping": "COCO: person=0, bicycle=1, car=2, motorcycle=3, bus=5, truck=7; worker class filter"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            category = "benchmark" if phase in {"input_validation", "pixel_conversion", "output_conversion"} else "execution"
            # No exception contents: resolver/library errors can include secret-bearing paths.
            result["errors"].append({"category": category, "stage": "yolo", "code": phase,
                                     "detail": type(exc).__name__, "cause_confirmed": phase != "worker_execution"})
            if phase == "worker_execution":
                write(artifacts / "yolo.transport_error.json", {"status": "error", "error_code": "worker_transport_error", "exception_type": type(exc).__name__})
        finally:
            if stream is not None:
                stream.close()
            result["metadata"]["total_ms"] = (perf_counter() - started) * 1000
        return result

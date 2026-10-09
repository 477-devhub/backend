"""Sparse canonical-frame YOLO observations, never a trained event classifier."""
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

from app.schemas.benchmark import BenchmarkError, BenchmarkInput, BenchmarkOutcome


class YoloBenchmarkAdapter:
    name = "yolo26_benchmark"
    model = "yolo26s.pt+ByteTrack"

    def __init__(self, detector_weights: Path, pose_weights: Path | None = None,
                 device: str = "cpu", imgsz: int = 960, conf: float = .10,
                 worker_timeout: float = 1800., worker_python: Path | None = None):
        if not 0 < conf < 1 or imgsz < 32 or not math.isfinite(worker_timeout) or worker_timeout <= 0:
            raise ValueError("invalid worker configuration")
        self.detector_weights = Path(detector_weights).resolve()
        self.pose_weights = Path(pose_weights).resolve() if pose_weights is not None else None
        self.model = self.detector_weights.name + "+ByteTrack"
        if self.pose_weights is not None:
            self.model += "+" + self.pose_weights.name
        self.device, self.imgsz, self.conf = device, imgsz, conf
        self.worker_timeout = worker_timeout
        self.worker_python = str(worker_python or sys.executable)
        self._gate = asyncio.Lock()
        self._admitted = 0

    def _request_header(self, request: BenchmarkInput) -> dict:
        """Exclude harness IDs, label-bearing paths, prompts and supplied features."""
        if len(request.frames) != 64 or self.detector_weights.name != "yolo26s.pt":
            raise BenchmarkError("input_contract")
        if not self.detector_weights.is_file() or (self.pose_weights is not None and
                (self.pose_weights.name != "yolo26s-pose.pt" or not self.pose_weights.is_file())):
            raise BenchmarkError("worker_error")
        frames = []
        for index, frame in enumerate(request.frames):
            if not math.isfinite(frame.timestamp_sec) or frame.timestamp_sec < 0:
                raise BenchmarkError("input_contract")
            if frame.width != 1920 or frame.height != 1080 or len(frame.rgb24) != 1920 * 1080 * 3:
                raise BenchmarkError("input_contract")
            frames.append({"frame_index": index, "camera": frame.camera,
                           "timestamp_sec": frame.timestamp_sec, "width": frame.width,
                           "height": frame.height, "sha256": hashlib.sha256(frame.rgb24).hexdigest()})
        frames.sort(key=lambda f: (f["camera"], f["timestamp_sec"]))
        return {"version": "yolo-canonical64-v1", "frames": frames,
                "config": {"detector_weights": str(self.detector_weights),
                           "pose_weights": str(self.pose_weights) if self.pose_weights else None,
                           "device": self.device, "imgsz": self.imgsz, "conf": self.conf,
                           "max_det": 100, "lost_seconds": 5., "dwell_seconds": 15.,
                           "pose_conf": .4, "low_posture_ratio": 1.2,
                           "low_posture_seconds": 1., "max_output_bytes": 1024 * 1024}}

    async def evaluate_benchmark(self, request: BenchmarkInput) -> BenchmarkOutcome:
        # One active worker and at most one waiter. No unbounded 398-MB input queue.
        if self._admitted >= 2:
            raise BenchmarkError("worker_error")
        self._admitted += 1
        try:
            async with self._gate:
                started = perf_counter()
                header = await asyncio.to_thread(self._request_header, request)
                prepare_ms = (perf_counter() - started) * 1000
                result = await asyncio.wait_for(self._run_worker(header, request), self.worker_timeout)
                if result.get("status") != "ok":
                    raise BenchmarkError(result.get("error_code", "worker_error"))
                features = result.get("features")
                if not isinstance(features, dict) or not isinstance(features.get("compact_state"), dict):
                    raise BenchmarkError("provider_schema_error")
                expected = sorted(header["frames"], key=lambda f: f["frame_index"])
                consumption = features.get("consumption", {})
                if (consumption.get("frame_count") != 64 or
                        consumption.get("frames") != expected or
                        consumption.get("raw_rgb_bytes") != 64 * 1920 * 1080 * 3):
                    raise BenchmarkError("provider_schema_error")
                frame_rows = features.get("frames", [])
                if len(frame_rows) != 64 or [(x.get("frame_index"), x.get("camera"), x.get("timestamp_sec"))
                        for x in frame_rows] != [(x["frame_index"], x["camera"], x["timestamp_sec"])
                                                for x in expected]:
                    raise BenchmarkError("provider_schema_error")
                return BenchmarkOutcome(adapter=self.name, model=self.model, features=features,
                    raw_response=result, prediction=None,
                    metadata={"needs_human_review": True,
                              "risk_axes": {k: None for k in ("severity", "imminence", "exposure", "persistence")},
                              "model_cold_start": True, "pose_enabled": self.pose_weights is not None,
                              "cv_profile": "pose-always" if self.pose_weights is not None else "pose-off",
                              "models": {"detector": self.detector_weights.name, "tracker": "ByteTrack",
                                         "pose": self.pose_weights.name if self.pose_weights is not None else None},
                              "config": {k: v for k, v in header["config"].items()
                                         if not k.endswith("weights")},
                              "tracker_config": features.get("tracker_config", {}),
                              "limitations": features.get("limitations", []),
                              "input_header_preparation_ms": prepare_ms,
                              "timings_ms": result.get("timings_ms", {}),
                              "memory": result.get("memory", {}),
                              "versions": result.get("versions", {}),
                              "weights_sha256": result.get("weights_sha256", {}),
                              "device": self.device,
                              "event_classifier_available": False})
        finally:
            self._admitted -= 1

    async def _spawn(self, environment: dict):
        return await asyncio.create_subprocess_exec(
            self.worker_python, "-B", "-m", "app.models.adapters.yolo_benchmark_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=environment,
        )

    async def _run_worker(self, header: dict, request: BenchmarkInput) -> dict:
        # Ultralytics settings and caches live outside all protected data folders.
        with tempfile.TemporaryDirectory(prefix="477-yolo-worker-") as temporary:
            environment = {k: v for k, v in os.environ.items()
                           if not any(token in k.upper() for token in ("API_KEY", "AUTH_TOKEN", "CLEF_"))}
            environment.update({"PYTHONDONTWRITEBYTECODE": "1", "YOLO_AUTOINSTALL": "false",
                                "YOLO_CONFIG_DIR": str(Path(temporary) / "ultralytics"),
                                "MPLCONFIGDIR": str(Path(temporary) / "matplotlib"),
                                "TORCH_HOME": str(Path(temporary) / "torch"),
                                "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4"})
            process = await self._spawn(environment)

            async def send():
                encoded = json.dumps(header, separators=(",", ":"), allow_nan=False).encode()
                process.stdin.write(len(encoded).to_bytes(4, "big") + encoded)
                await process.stdin.drain()
                for frame in header["frames"]:
                    process.stdin.write(request.frames[frame["frame_index"]].rgb24)
                    await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()

            async def bounded_read(stream, limit):
                chunks, size = [], 0
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        return b"".join(chunks)
                    size += len(chunk)
                    if size > limit:
                        raise BenchmarkError("payload_limit")
                    chunks.append(chunk)

            tasks = [asyncio.create_task(send()),
                     asyncio.create_task(bounded_read(process.stdout, 1024 * 1024)),
                     asyncio.create_task(bounded_read(process.stderr, 64 * 1024)),
                     asyncio.create_task(process.wait())]
            try:
                outputs = await asyncio.gather(*tasks)
                if process.returncode != 0:
                    raise BenchmarkError("worker_error")
                try:
                    return json.loads(outputs[1])
                except (ValueError, UnicodeDecodeError):
                    raise BenchmarkError("provider_schema_error") from None
            finally:
                if process.returncode is None:
                    process.kill()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Retrieve the Proactor pipe-close future too: Windows otherwise
                # reports a BrokenPipeError after cancellation despite reaping.
                if not process.stdin.is_closing():
                    process.stdin.close()
                try:
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    pass

                async def discard(stream):
                    while await stream.read(65536):
                        pass

                # Resume paused read transports before waiting for child exit.
                await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())

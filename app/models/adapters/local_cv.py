"""Real CPU HOG observations; calibrated event classification remains unavailable.

Evidence must come from the default MediaIngestion profile. Re-decoding validates
its provenance; no caller temporal_state or annotation enters the worker.
"""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import math
import sys
from time import perf_counter

from app.models.base import ModelAdapter
from app.models.media import MediaResolver
from app.models.adapters.ingestion import MediaIngestion
from app.schemas.model import ModelAssessment, ModelInput, ModelMetadata, RiskAxes, TemporalState


class LocalCVError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalCVObservation:
    # Serialized observations avoid sharing mutable lists/dicts with callers.
    temporal_json: bytes
    evidence_refs: tuple[str, ...]
    clip_sha256: str
    frame_sha256: tuple[tuple[str, str], ...]
    preprocessing_ms: float
    worker_ms: float
    versions: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...] = (
        "HOG detections are uncalibrated and may miss CCTV subjects",
        "IoU tracks are geometric associations, not person identity",
        "pose, configured zones, and all six event classes are unimplemented",
        "risk axes are unmeasured; sparse sampling cannot establish event absence",
    )

    @property
    def temporal_state(self) -> TemporalState:
        return TemporalState.model_validate_json(self.temporal_json)


class LocalCVAdapter(ModelAdapter):
    name = "local_cv"

    def __init__(self, resolver: MediaResolver, *, timeout_sec: float = 15.0,
                 max_clip_bytes: int = 64 * 1024 * 1024,
                 max_frame_bytes: int = 2 * 1024 * 1024,
                 max_frames: int = 16, max_waiters: int = 1):
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError("timeout_sec must be finite and positive")
        for value in (max_clip_bytes, max_frame_bytes, max_frames):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("budgets must be positive integers")
        if isinstance(max_waiters, bool) or not isinstance(max_waiters, int) or not 0 <= max_waiters <= 8:
            raise ValueError("max_waiters must be in 0..8")
        self.resolver = resolver
        self.timeout_sec = timeout_sec
        self.max_clip_bytes = max_clip_bytes
        self.max_frame_bytes = max_frame_bytes
        self.max_frames = max_frames
        self.max_waiters = max_waiters
        self._gate = asyncio.Semaphore(1)
        self._admitted = 0
        self.last_observation: LocalCVObservation | None = None

    async def evaluate(self, model_input: ModelInput) -> ModelAssessment:
        observation = await self.extract_observations(model_input)
        versions = dict(observation.versions)
        return ModelAssessment(
            event_type="uncertain", event_confidence=0.0, risk_axes=RiskAxes(),
            needs_human_review=True,
            uncertainty_reason="CV observations measured; event classifier and risk axes are unvalidated",
            evidence_refs=list(observation.evidence_refs),
            metadata=ModelMetadata(adapter=self.name,
                                   model="opencv-hog-default-people-detector/" + versions["opencv"],
                                   is_mock=False, latency_ms=observation.preprocessing_ms + observation.worker_ms),
        )

    async def extract_observations(self, model_input: ModelInput) -> LocalCVObservation:
        # The gate covers resolver reads, FFmpeg and OpenCV, not just the CV child.
        # Admission count changes without an await, so concurrent tasks cannot race.
        if self._admitted >= 1 + self.max_waiters:
            raise LocalCVError("local CV queue is full")
        self._admitted += 1
        try:
            return await asyncio.wait_for(self._admitted_extract(model_input), self.timeout_sec)
        except asyncio.TimeoutError:
            raise LocalCVError("local CV timed out") from None
        except (KeyError, OSError, ValueError, TypeError) as exc:
            raise LocalCVError("invalid or unavailable CV media") from None
        finally:
            self._admitted -= 1

    async def _admitted_extract(self, model_input):
        async with self._gate:
            self.last_observation = None
            started = perf_counter()
            mi = ModelInput.model_validate(model_input.model_dump(mode="python"))
            if not mi.clip_ref or not mi.evidence or len(mi.evidence) > self.max_frames:
                raise LocalCVError("clip and bounded decoded evidence are required")
            prepared = await MediaIngestion(
                self.resolver, timeout_sec=self.timeout_sec,
                max_clip_bytes=self.max_clip_bytes, max_frame_bytes=self.max_frame_bytes,
            ).prepare(mi)
            actual = {frame.frame_id: frame for frame in prepared.model_input.evidence}
            frames, hashes = [], []
            for frame in sorted(mi.evidence, key=lambda value: value.timestamp_ms):
                if actual.get(frame.frame_id) != frame:
                    raise LocalCVError("evidence does not match default decoded clip profile")
                content = await asyncio.to_thread(
                    self.resolver.read, frame.media_ref, max_bytes=self.max_frame_bytes)
                digest = (await asyncio.to_thread(hashlib.sha256, content)).hexdigest()
                if prepared.frame_sha256[frame.frame_id] != digest:
                    raise LocalCVError("evidence bytes do not match decoded clip")
                hashes.append((frame.frame_id, digest))
                frames.append({"frame_id": frame.frame_id, "timestamp_ms": frame.timestamp_ms,
                               "jpeg": base64.b64encode(content).decode("ascii")})
            preprocessing_ms = (perf_counter() - started) * 1000
            worker_started = perf_counter()
            result = await self._run_worker(json.dumps({"frames": frames}).encode("utf8"))
            # A child response is validated before becoming observable diagnostics.
            state = TemporalState.model_validate(result["temporal_state"])
            if state.feature_version != "opencv-hog-iou-v1":
                raise LocalCVError("invalid CV feature version")
            valid_ids = {frame.frame_id for frame in mi.evidence}
            if any(obs.get("frame_id") not in valid_ids
                   for track in state.tracks for obs in track.get("observations", [])):
                raise LocalCVError("CV references an unknown input frame")
            observation = LocalCVObservation(
                state.model_dump_json().encode("utf8"), tuple(frame["frame_id"] for frame in frames),
                prepared.clip_sha256, tuple(hashes), preprocessing_ms,
                (perf_counter() - worker_started) * 1000,
                tuple(sorted({**result["versions"], "ffmpeg": prepared.ffmpeg_version}.items())),
            )
            self.last_observation = observation
            return observation

    async def _run_worker(self, request: bytes) -> dict:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "app.models.adapters.local_cv_worker",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_bounded(stream, budget):
            chunks, size = [], 0
            while chunk := await stream.read(min(65536, budget - size + 1)):
                size += len(chunk)
                if size > budget:
                    raise LocalCVError("CV worker output exceeds budget")
                chunks.append(chunk)
            return b"".join(chunks)

        async def send():
            process.stdin.write(request)
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

        tasks = [asyncio.create_task(send()),
                 asyncio.create_task(read_bounded(process.stdout, 256 * 1024)),
                 asyncio.create_task(read_bounded(process.stderr, 32 * 1024)),
                 asyncio.create_task(process.wait())]
        try:
            _, output, _, code = await asyncio.gather(*tasks)
            if code:
                # Never expose raw child stderr, filenames, or input payloads.
                raise LocalCVError("CV worker failed")
            return json.loads(output)
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

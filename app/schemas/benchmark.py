"""Harness-only canonical inputs; never replace the frozen public schemas."""
from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Protocol


@dataclass(frozen=True)
class CanonicalFrame:
    camera: str
    timestamp_sec: float
    rgb24: bytes = field(repr=False)
    width: int = 1920
    height: int = 1080

    def __post_init__(self):
        if self.camera not in {"CAM_01", "CAM_02", "CAM_03"}:
            raise ValueError("invalid camera")
        if not isinstance(self.rgb24, bytes) or len(self.rgb24) != self.width * self.height * 3:
            raise ValueError("invalid RGB payload")
        if (self.width != 1920 or self.height != 1080
                or not math.isfinite(self.timestamp_sec) or self.timestamp_sec < 0):
            raise ValueError("invalid canonical frame")

    @property
    def sha256(self):
        return hashlib.sha256(self.rgb24).hexdigest()


@dataclass(frozen=True)
class BenchmarkInput:
    item_id: str  # harness only; adapters must not serialize it to a provider
    task: str
    prompt: str
    schema_json: str
    fingerprint_json: str
    frames: tuple[CanonicalFrame, ...] = field(repr=False)
    features_json: str | None = None  # only CV-derived state for Clef, never VLM

    def __post_init__(self):
        if self.task not in {"single", "attention", "multi_camera"} or len(self.frames) != 64:
            raise ValueError("canonical input requires 64 total frames")
        if not self.prompt or not isinstance(json.loads(self.schema_json), dict):
            raise ValueError("missing frozen prompt/schema")
        if len({(f.camera, f.timestamp_sec) for f in self.frames}) != 64:
            raise ValueError("duplicate canonical frame")
        if self.features_json is not None and not isinstance(json.loads(self.features_json), dict):
            raise ValueError("invalid CV features")

    @property
    def input_digest(self):
        h = hashlib.sha256()
        for value in (self.task, self.prompt, self.schema_json, self.fingerprint_json):
            h.update(value.encode("utf-8"))
        for frame in self.frames:
            h.update(f"{frame.camera}:{frame.timestamp_sec:.12f}:".encode())
            h.update(frame.rgb24)
        h.update((self.features_json or "").encode())
        return h.hexdigest()


@dataclass
class BenchmarkOutcome:
    adapter: str
    model: str
    status: str = "ok"
    error_code: str | None = None
    raw_response: Any = None
    prediction: dict | None = None
    features: dict | None = None
    decision: dict | None = None
    usage: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    latency_ms: float | None = None


class BenchmarkAdapter(Protocol):
    name: str
    model: str

    async def evaluate_benchmark(self, request: BenchmarkInput) -> BenchmarkOutcome: ...


class BenchmarkError(Exception):
    """Only a stable code may cross the execution boundary, never request details."""
    def __init__(self, code: str):
        self.code = code if code in {
            "budget_exhausted", "provider_http_error", "provider_transport_error",
            "payload_limit", "credentials_missing", "provider_schema_error",
            "unsupported_model", "worker_error", "input_contract", "schema_or_contract",
        } else "provider_error"
        super().__init__(self.code)

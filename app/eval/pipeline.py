"""Label-free evaluation preparation and execution with phase-level accounting."""
import hashlib
import json
import math
from time import perf_counter

from app.models.adapters.ingestion import MediaIngestion
from app.models.execution import execute, failure_assessment
from app.models.media import MediaResolver
from app.models.registry import get_adapter


def input_sha256(model_input):
    canonical = json.dumps(model_input.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def evaluate_input(adapter_name, model_input, timeout_sec=5, *, resolver=None,
                         expected_media_sha256=None):
    if not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise ValueError("timeout_sec must be finite and positive")
    started = perf_counter()
    source_hash = input_sha256(model_input)
    mi = model_input
    preparation = None
    phase_error = None
    timings = {"preprocessing_ms": None, "execution_wall_ms": None,
               "adapter_cv_preprocessing_ms": None, "adapter_cv_worker_ms": None,
               "provider_ms": None, "end_to_end_ms": None}
    versions = {}
    if resolver is not None:
        preprocessing_started = perf_counter()
        try:
            prepared = await MediaIngestion(resolver).prepare(mi)
            if expected_media_sha256 is not None and prepared.clip_sha256 != expected_media_sha256:
                raise ValueError("resolved clip does not match manifest media")
            mi, resolver = prepared.model_input, prepared.resolver
            preparation = {"clip_sha256": prepared.clip_sha256,
                           "frame_sha256": prepared.frame_sha256, "profile": prepared.profile}
            versions = {"extractor": prepared.extractor_version, "ffmpeg": prepared.ffmpeg_version}
        except Exception:
            phase_error = "preprocessing"
            assessment = failure_assessment(adapter_name, model_input, "preprocessing_error")
        timings["preprocessing_ms"] = (perf_counter() - preprocessing_started) * 1000
    if phase_error is None:
        adapter = get_adapter(adapter_name, resolver=resolver)
        execution_started = perf_counter()
        assessment = await execute(adapter, mi, timeout_sec)
        timings["execution_wall_ms"] = (perf_counter() - execution_started) * 1000
        # Real slots cannot contribute mock measurements to real dataset metrics.
        if not adapter_name.startswith("mock_") and assessment.metadata.is_mock:
            assessment = failure_assessment(adapter_name, mi, "schema_or_contract",
                                            timings["execution_wall_ms"])
        if assessment.metadata.error_code:
            phase_error = "execution"
        observation = getattr(adapter, "last_observation", None)
        if observation is not None and not assessment.metadata.error_code:
            timings["adapter_cv_preprocessing_ms"] = observation.preprocessing_ms
            timings["adapter_cv_worker_ms"] = observation.worker_ms
            versions.update(dict(observation.versions))
    timings["end_to_end_ms"] = (perf_counter() - started) * 1000
    return {"sample_id": mi.sample_id, "adapter": adapter_name,
            "source_input_sha256": source_hash, "input_sha256": input_sha256(mi),
            "input_stage": "prepared" if preparation is not None else "supplied",
            "preparation": preparation, "versions": versions, "timings": timings,
            "error_phase": phase_error, "prediction": assessment.model_dump(mode="json")}


def load_resolver(asset_map=None, asset_root=None):
    if asset_root is not None and asset_map is None:
        raise ValueError("asset_root requires asset_map")
    return MediaResolver.from_asset_map(asset_map, root=asset_root) if asset_map is not None else None

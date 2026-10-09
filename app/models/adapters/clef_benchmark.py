"""Real, text-state Clef routing for CV-derived canonical benchmark features."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
from time import perf_counter
from typing import Any

import httpx

from app.models.budget import PaidBudget
from app.schemas.benchmark import BenchmarkError, BenchmarkInput, BenchmarkOutcome


RESERVATION_USD = 0.03145728
MAX_REQUEST_BYTES = 196608  # Conservative local bound, below hosted body limits.
MAX_RESPONSE_BYTES = 1024 * 1024
SOURCE = "CV-derived canonical 64-frame observations"
_ALLOWED_KEYS = frozenset("""
source frames tracks camera_sampling quality limitations rule_policy
frame_index camera timestamp_sec counts people bbox track_id confidence posture
person bicycle car motorcycle bus truck wide_box torso_angle_from_vertical_deg
low_posture_candidate class_id class_name class_changed first_timestamp_sec
last_timestamp_sec observations observed_span_sec interpolated_visible_sec
max_observation_gap_sec path_length_pixels net_displacement_pixels
person_dwell_candidate longest_low_posture_interval_sec sustained_low_posture_candidate
evidence_frame_keys sample_count median_sample_interval_sec min_sample_interval_sec
max_sample_interval_sec lost_buffer_samples lost_buffer_effective_sec kalman_dt
frames_without_person_detection untracked_detections total_detections
detector_confidence_is_not_event_confidence zone_configured pose_enabled
dwell_candidate_seconds intrusion_supported loitering_confirmed_supported
event_classifier_available severity imminence exposure persistence risk_axes
CAM_01 CAM_02 CAM_03
""".split())


def _checked_tree(value: Any) -> Any:
    """Exclude unknown, label-bearing or private fields rather than serializing them."""
    if isinstance(value, dict):
        if any(key not in _ALLOWED_KEYS for key in value):
            raise BenchmarkError("input_contract")
        return {key: _checked_tree(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_checked_tree(child) for child in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise BenchmarkError("input_contract")


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError("provider_schema_error")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise BenchmarkError("provider_schema_error")
    return float(value)


class ClefBenchmarkAdapter:
    name = "clef_benchmark"

    def __init__(self, budget: PaidBudget, *, token: str | None = None,
                 account: str | None = None, model: str | None = None,
                 client: httpx.AsyncClient | None = None, timeout_sec: float = 120):
        self.budget = budget
        self._token = (token if token is not None else os.getenv("CLEF_API_TOKEN", "")).strip()
        self._account = (account if account is not None else os.getenv("CLEF_ACCOUNT", "")).strip()
        self.model = (model if model is not None else os.getenv("CLEF_MODEL", "clef")).strip()
        self._client = client
        self.timeout_sec = timeout_sec
        # These values are never included in metadata, exception messages or files.
        self._secrets = tuple(value for value in (
            self._token, self._account, os.getenv("VLM_API_KEY", ""),
            os.getenv("CLOUDFLARE_AUTH_TOKEN", "")) if value)

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                safe_key = self._redact(str(key))
                sensitive = bool(re.fullmatch(
                    r"(?:token|(?:access|auth|api|clef)_?token|api_?key|vlm_api_key|authorization|account(?:_id)?)",
                    str(key), re.I))
                result[safe_key] = "[REDACTED]" if sensitive else self._redact(child)
            return result
        if isinstance(value, list):
            return [self._redact(child) for child in value]
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, float) and not math.isfinite(value):
            return "[INVALID_NONFINITE]"
        return value

    def _body(self, request: BenchmarkInput) -> tuple[bytes, bool]:
        if request.features_json is None:
            raise BenchmarkError("input_contract")
        try:
            features = json.loads(request.features_json)
            compact = features["compact_state"]
            if not isinstance(compact, dict) or compact.get("source") != SOURCE:
                raise BenchmarkError("input_contract")
            state = _checked_tree(compact)
            rows = state.get("frames")
            if not isinstance(rows, list) or len(rows) != 64:
                raise BenchmarkError("input_contract")
            indices = set()
            for row in rows:
                index = row.get("frame_index")
                if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 64:
                    raise BenchmarkError("input_contract")
                frame = request.frames[index]
                timestamp = row.get("timestamp_sec")
                if (row.get("camera") != frame.camera or isinstance(timestamp, bool)
                        or not isinstance(timestamp, (int, float))
                        or abs(timestamp - frame.timestamp_sec) > 1e-6):
                    raise BenchmarkError("input_contract")
                indices.add(index)
            if len(indices) != 64:
                raise BenchmarkError("input_contract")
            # Evidence references in CV tracks must refer to actual consumed frames.
            for track in state.get("tracks", []):
                for ref in track.get("evidence_frame_keys", []):
                    index = ref.get("frame_index")
                    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 64:
                        raise BenchmarkError("input_contract")
                    frame = request.frames[index]
                    if (ref.get("camera") != frame.camera
                            or ref.get("timestamp_sec") != frame.timestamp_sec):
                        raise BenchmarkError("input_contract")
            policy = state.get("rule_policy", {})
            axes = state.get("risk_axes", {})
            uncertain = (not policy.get("event_classifier_available", False)
                         or not state.get("quality", {}).get("zone_configured", False)
                         or any(axes.get(axis) is None for axis in
                                ("severity", "imminence", "exposure", "persistence")))
            body = {"model": self.model, "state": state, "questions": {
                "incident": {"type": "noul", "instructions": request.prompt +
                    "\nAssess whether these CV observations provide evidence of an incident. "
                    "Detection confidence is not event confidence; absent evidence is not normality."},
                "route": {"type": "choice", "instructions": request.prompt +
                    "\nChoose the next review route from only these CV observations. "
                    "Missing zones, risk axes or event classifiers require further review.",
                    "criteria": {"invoke_vlm": "Visual analysis is needed to evaluate a possible incident.",
                        "no_action": "Explicit normality is established with sufficient measured evidence.",
                        "human_review": "Evidence is uncertain or insufficient for an automatic decision."}}}}
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            if len(encoded) > MAX_REQUEST_BYTES:
                raise BenchmarkError("payload_limit")
            # Clef's context limit is measured in tokens, not UTF-8 bytes.
            # Preserve the bounded request body; observe provider token usage below.
            return encoded, uncertain
        except BenchmarkError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise BenchmarkError("input_contract") from None

    @staticmethod
    def _parse_decision(payload: Any, uncertain: bool) -> dict:
        try:
            result = payload["result"]
            if payload.get("success") is not True:
                raise BenchmarkError("provider_schema_error")
            incident, route = result["answers"]["incident"], result["answers"]["route"]
            if incident.get("type") != "noul" or route.get("type") != "choice":
                raise BenchmarkError("provider_schema_error")
            probability = _number(incident["noul"])
            confidence = _number(route["confidence"])
            choice = route["choice"]
            probabilities = route["probabilities"]
            if (choice not in {"invoke_vlm", "no_action", "human_review"}
                    or not isinstance(probabilities, dict)
                    or set(probabilities) != {"invoke_vlm", "no_action", "human_review"}):
                raise BenchmarkError("provider_schema_error")
            values = {key: _number(value) for key, value in probabilities.items()}
            if abs(sum(values.values()) - 1) > 1e-3 or values[choice] < max(values.values()) - 1e-6:
                raise BenchmarkError("provider_schema_error")
            skip = choice == "no_action" and confidence >= .90 and probability < .35 and not uncertain
            reason = ("cv_information_incomplete" if uncertain else "incident_probability_threshold"
                      if probability >= .35 else "explicit_no_action" if skip else "further_review_required")
            return {"invoke_vlm": not skip, "needs_human_review": not skip,
                    "reason": reason, "incident_probability": probability,
                    "proposed_route": choice, "route_confidence": confidence,
                    "cv_uncertain": uncertain}
        except BenchmarkError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise BenchmarkError("provider_schema_error") from None

    async def _post(self, body: bytes) -> tuple[int, Any]:
        async def send(client):
            url = f"https://api.cloudflare.com/client/v4/accounts/{self._account}/ai/run/@cf/cloudflare/{self.model}"
            async with client.stream("POST", url, content=body,
                    headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
                    timeout=self.timeout_sec) as response:
                chunks, length = [], 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise BenchmarkError("payload_limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    payload = {"unparsed_response": raw.decode("utf-8", errors="replace")}
                return response.status_code, self._redact(payload)
        if self._client is not None:
            return await send(self._client)
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            return await send(client)

    async def evaluate_benchmark(self, request: BenchmarkInput) -> BenchmarkOutcome:
        if not self._token or not self._account:
            raise BenchmarkError("credentials_missing")
        if self.model not in {"clef", "clef-flash"}:
            raise BenchmarkError("unsupported_model")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self._account):
            raise BenchmarkError("credentials_missing")
        started = perf_counter()
        body, uncertain = await asyncio.to_thread(self._body, request)
        preprocessing_ms = (perf_counter() - started) * 1000
        reservation = await asyncio.to_thread(self.budget.reserve, "clef", RESERVATION_USD)
        metadata = {"input_mode": "cv_feature_state", "frame_count": 64,
                    "images_sent": 0, "request_bytes": len(body), "preprocessing_ms": preprocessing_ms,
                    "conversion_profile": "canonical64_cv_feature_state_v2",
                    "request_size_policy": {"max_request_bytes": MAX_REQUEST_BYTES,
                        "provider_context_tokens": 65536, "byte_token_proxy": False},
                    "context_truncation_status": "unknown",
                    "reservation_usd": RESERVATION_USD, "actual_invoice_cost_usd": None,
                    "retry_count": 0, "risk_axes": {key: None for key in
                        ("severity", "imminence", "exposure", "persistence")}}
        raw, usage, cost, code = None, {}, None, None
        request_started = perf_counter()
        try:
            status, raw = await self._post(body)
            metadata["http_status"] = status
            if isinstance(raw, dict) and isinstance(raw.get("result"), dict):
                candidate = raw["result"].get("usage", {})
                if isinstance(candidate, dict):
                    for key in ("input_tokens", "output_tokens"):
                        value = candidate.get(key)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            usage[key] = value
                    if "input_tokens" in usage:
                        cost = usage["input_tokens"] * .24 / 1_000_000
            if not 200 <= status < 300:
                raise BenchmarkError("provider_http_error")
            decision = self._parse_decision(raw, uncertain)
            if raw["result"].get("model") not in {None, self.model, f"@cf/cloudflare/{self.model}"}:
                raise BenchmarkError("provider_schema_error")
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self.budget.settle, reservation, {}, None, "cancelled_billing_unknown"))
            raise
        except httpx.HTTPError:
            code = "provider_transport_error"
        except BenchmarkError as error:
            code = error.code
        metadata["request_ms"] = (perf_counter() - request_started) * 1000
        metadata["input_tokens_reported"] = usage.get("input_tokens")
        metadata["usage_cost_estimate_usd"] = cost
        metadata["cost_estimate_method"] = "input_tokens * published $0.24 per million; invoice unavailable"
        await asyncio.to_thread(self.budget.settle, reservation, usage, cost,
                                "error_billing_unknown" if code else "response_received")
        if code:
            decision = {"invoke_vlm": True, "needs_human_review": True,
                        "reason": code, "cv_uncertain": uncertain}
        return BenchmarkOutcome(adapter=self.name, model=self.model,
            status="error" if code else "ok", error_code=code, raw_response=raw,
            decision=decision, usage=usage, metadata=metadata)

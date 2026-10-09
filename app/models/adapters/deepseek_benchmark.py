"""DeepSeek vision API adapter for the unchanged canonical 64-frame benchmark."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

import httpx

from app.models.budget import PaidBudget
from app.schemas.benchmark import BenchmarkError, BenchmarkInput, BenchmarkOutcome


ENDPOINT = "https://api.deepseek.com/chat/completions"
RESERVATION_USD = 0.0685824
MAX_REQUEST_BYTES = 48 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 16000
MAX_INPUT_TOKENS = 64 * 1024 + MAX_TEXT_BYTES
MAX_OUTPUT_TOKENS = 8192
JPEG_QUALITY = 80
TRANSPORT_PROFILE = "deepseek_timestamp_copy_v2"
JSON_LABELS_PROFILE = "deepseek_json_labels_v3"
JSON_LABELS_MAX_OUTPUT_TOKENS = 4096
JSON_LABELS_RESERVATION_USD = 0.058752
TIMESTAMP_COPY_INSTRUCTION = (
    "Image transport labels identify the actual input frames. For every observation, "
    "copy camera and timestamp_sec exactly from the label of the image used as evidence. "
    "Do not round, truncate, interpolate, or reconstruct timestamp_sec. "
    "Do not use a timestamp from a different camera. frame_index is a neutral transport "
    "reference only, not an additional output field; preserve the supplied JSON schema."
)
JSON_LABELS_COPY_INSTRUCTION = (
    "Image transport labels are valid JSON objects identifying the actual input frames. "
    "For every observation, copy camera and timestamp_sec exactly from the JSON label "
    "of the image used as evidence. Use quoted JSON field names and colons in the output. "
    "Preserve the complete canonical timestamp_sec numeric value; do not round, truncate, "
    "interpolate, or reconstruct it. Do not use a timestamp from a different camera. "
    "frame_index is a neutral transport reference only, not an additional output field; "
    "preserve the supplied JSON schema."
)


class DeepSeekBenchmarkAdapter:
    name = "deepseek_benchmark"

    def __init__(self, budget: PaidBudget, *, api_key: str | None = None,
                 model: str | None = None, client: httpx.AsyncClient | None = None,
                 timeout_sec: float = 180, transport_profile: str = TRANSPORT_PROFILE):
        if transport_profile not in (TRANSPORT_PROFILE, JSON_LABELS_PROFILE):
            raise ValueError("unsupported DeepSeek transport profile")
        self._transport_profile = transport_profile
        self.budget = budget
        self._api_key = (api_key if api_key is not None else os.getenv("VLM_API_KEY", "")).strip()
        self.model = (model if model is not None else os.getenv("VLM_MODEL", "deepseek-flash")).strip()
        self._client = client
        self.timeout_sec = timeout_sec
        self._secrets = tuple(sorted({value for value in (
            self._api_key, os.getenv("CLEF_API_TOKEN", ""), os.getenv("CLEF_ACCOUNT", ""),
            os.getenv("CLOUDFLARE_AUTH_TOKEN", "")) if value}, key=len, reverse=True))

    @property
    def transport_profile(self) -> str:
        return self._transport_profile

    @property
    def max_output_tokens(self) -> int:
        return (JSON_LABELS_MAX_OUTPUT_TOKENS if self.transport_profile == JSON_LABELS_PROFILE
                else MAX_OUTPUT_TOKENS)

    @property
    def reservation_upper_usd(self) -> float:
        return (JSON_LABELS_RESERVATION_USD if self.transport_profile == JSON_LABELS_PROFILE
                else RESERVATION_USD)

    @property
    def timestamp_copy_instruction(self) -> str:
        return (JSON_LABELS_COPY_INSTRUCTION if self.transport_profile == JSON_LABELS_PROFILE
                else TIMESTAMP_COPY_INSTRUCTION)

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            output = {}
            for key, child in value.items():
                safe_key = self._redact(str(key))
                normalized = str(key).lower().replace("-", "_")
                if normalized in {"token", "account", "credentials"} or any(part in normalized for part in (
                    "api_key", "authorization", "auth_token", "account_id", "clef_account",
                    "clef_api_token", "access_token", "secret", "password")):
                    output[safe_key] = "[REDACTED]"
                else:
                    output[safe_key] = self._redact(child)
            return output
        if isinstance(value, list):
            return [self._redact(child) for child in value]
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return value
        return value

    def _body(self, request: BenchmarkInput) -> tuple[bytes, dict]:
        """CPU-heavy conversion runs in a worker thread; no media paths leave the process."""
        if request.features_json is not None:
            raise BenchmarkError("input_contract")
        if len(request.frames) != 64:
            raise BenchmarkError("input_contract")
        schema = json.loads(request.schema_json)
        branch = {"single": "single", "attention": "attention", "multi_camera": "multi"}[request.task]
        # Preserve the entire frozen schema, selecting its existing branch by task text.
        texts = [request.prompt, "Task: " + request.task + "; schema branch: " + branch +
                 "\nOutput JSON schema:\n" + request.schema_json,
                 self.timestamp_copy_instruction]
        if not isinstance(schema, dict):
            raise BenchmarkError("input_contract")
        # repr(float) round-trips the canonical timestamp without decimal quantization.
        # These labels change only the transport; the frozen prompt/schema stay intact.
        if self.transport_profile == JSON_LABELS_PROFILE:
            labels = [json.dumps({"frame_index": index, "camera": frame.camera,
                                  "timestamp_sec": frame.timestamp_sec}, ensure_ascii=False,
                                 allow_nan=False, separators=(",", ":"))
                      for index, frame in enumerate(request.frames)]
        else:
            labels = [f"frame_index={index}; camera={frame.camera}; "
                      f"timestamp_sec={frame.timestamp_sec!r}"
                      for index, frame in enumerate(request.frames)]
        text_bytes = sum(len(text.encode("utf-8")) for text in texts + labels)
        if text_bytes > MAX_TEXT_BYTES:
            raise BenchmarkError("payload_limit")
        import cv2
        import numpy as np

        content: list[dict] = [{"type": "text", "text": text} for text in texts]
        images = []
        for index, (frame, label) in enumerate(zip(request.frames, labels)):
            rgb = np.frombuffer(frame.rgb24, dtype=np.uint8).reshape(frame.height, frame.width, 3)
            ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                                     [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise BenchmarkError("input_contract")
            jpeg = encoded.tobytes()
            content.extend([{"type": "text", "text": label},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}])
            images.append({"frame_index": index, "camera": frame.camera,
                "timestamp_sec": frame.timestamp_sec, "width": frame.width, "height": frame.height,
                "transport_label": label,
                "source_rgb_sha256": hashlib.sha256(frame.rgb24).hexdigest(),
                "sent_jpeg_sha256": hashlib.sha256(jpeg).hexdigest(), "jpeg_bytes": len(jpeg)})
        payload = {"model": self.model, "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
            "max_tokens": self.max_output_tokens, "temperature": 0}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise BenchmarkError("payload_limit")
        return body, {"input_mode": "canonical_64_jpeg_images", "frame_count": 64,
            "images_sent": 64, "jpeg_quality": JPEG_QUALITY, "resize": False, "crop": False,
            "text_utf8_bytes": text_bytes, "request_bytes": len(body), "images": images,
            "transport_profile": self.transport_profile,
            "input_token_limit": MAX_INPUT_TOKENS, "output_token_limit": self.max_output_tokens,
            "request_byte_limit": MAX_REQUEST_BYTES, "text_byte_limit": MAX_TEXT_BYTES,
            "reservation_upper_usd": self.reservation_upper_usd,
            "source_prompt_sha256": hashlib.sha256(request.prompt.encode("utf-8")).hexdigest(),
            "source_schema_sha256": hashlib.sha256(request.schema_json.encode("utf-8")).hexdigest(),
            "timestamp_copy_instruction_sha256": hashlib.sha256(
                self.timestamp_copy_instruction.encode("utf-8")).hexdigest(),
            "frame_labels_sha256": hashlib.sha256(
                json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "timestamp_label_format": "python_float_repr_exact_round_trip",
            "provider_timestamp_postprocessing": False,
            "server_resize": "provider automatic resize; final dimensions not returned",
            "server_resize_policy": "544^2 minimum / 1300^2 maximum area, aspect ratio preserved",
            "task_schema_branch": branch, "cv_features_sent": False,
            "provider_cache_state": "unknown before request", "provider_cold_start": None}

    async def _post(self, body: bytes) -> tuple[int, Any]:
        async def send(client: httpx.AsyncClient):
            async with client.stream("POST", ENDPOINT, content=body,
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    timeout=self.timeout_sec, follow_redirects=False) as response:
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

    async def get_balance(self) -> dict:
        """Read only numeric account balances; never persist arbitrary account responses."""
        if not self._api_key:
            return {"status": "error", "error_code": "credentials_missing"}
        async def send(client):
            async with client.stream("GET", "https://api.deepseek.com/user/balance",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self.timeout_sec, follow_redirects=False) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise BenchmarkError("payload_limit")
                if not 200 <= response.status_code < 300:
                    return {"status": "error", "error_code": "provider_http_error",
                            "http_status": response.status_code}
                try:
                    data = json.loads(raw)
                    if not isinstance(data.get("is_available"), bool) or not isinstance(data.get("balance_infos"), list):
                        raise ValueError()
                    rows = []
                    for row in data["balance_infos"]:
                        if row.get("currency") not in {"CNY", "USD"}:
                            raise ValueError()
                        result = {"currency": row["currency"]}
                        for key in ("total_balance", "granted_balance", "topped_up_balance"):
                            value = Decimal(str(row[key]))
                            if not value.is_finite():
                                raise ValueError()
                            result[key] = str(value)
                        rows.append(result)
                    return {"status": "ok", "http_status": response.status_code,
                            "is_available": data["is_available"], "balance_infos": rows}
                except (ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
                    return {"status": "error", "error_code": "provider_schema_error",
                            "http_status": response.status_code}
        try:
            if self._client is not None:
                return await send(self._client)
            async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
                return await send(client)
        except httpx.HTTPError:
            return {"status": "error", "error_code": "provider_transport_error"}
        except BenchmarkError as error:
            return {"status": "error", "error_code": error.code}

    @staticmethod
    def _usage(payload: Any) -> tuple[dict, float | None]:
        if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
            return {}, None
        raw = payload["usage"]
        usage = {}
        for key in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            if key in raw:
                value = raw[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise BenchmarkError("provider_schema_error")
                usage[key] = value
        if "prompt_tokens" not in usage or "completion_tokens" not in usage:
            raise BenchmarkError("provider_schema_error")
        prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
        cached = usage.get("prompt_cache_hit_tokens", 0)
        if cached > prompt:
            raise BenchmarkError("provider_schema_error")
        if "prompt_cache_miss_tokens" in usage and usage["prompt_cache_miss_tokens"] + cached != prompt:
            raise BenchmarkError("provider_schema_error")
        usage.update(input_tokens=prompt, output_tokens=output)
        cost = ((prompt - cached) * .30 + cached * .006 + output * 1.20) / 1_000_000
        if not math.isfinite(cost):
            raise BenchmarkError("provider_schema_error")
        return usage, cost

    @staticmethod
    def _prediction(payload: Any) -> dict:
        try:
            choice = payload["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise BenchmarkError("provider_schema_error")
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise BenchmarkError("provider_schema_error")
            prediction = json.loads(content, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(prediction, dict):
                raise BenchmarkError("provider_schema_error")
            return prediction
        except BenchmarkError:
            raise
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise BenchmarkError("provider_schema_error") from None

    async def evaluate_benchmark(self, request: BenchmarkInput) -> BenchmarkOutcome:
        if not self._api_key:
            raise BenchmarkError("credentials_missing")
        if self.model != "deepseek-flash":
            raise BenchmarkError("unsupported_model")
        started = perf_counter()
        body, metadata = await asyncio.to_thread(self._body, request)
        metadata["preprocessing_ms"] = (perf_counter() - started) * 1000
        reservation = await asyncio.to_thread(self.budget.reserve, "deepseek", self.reservation_upper_usd)
        metadata.update(reservation_usd=self.reservation_upper_usd, actual_invoice_cost_usd=None, retry_count=0,
            needs_human_review=True, schema_validation="pending MAIN benchmark validator")
        raw, usage, cost, code, prediction = None, {}, None, None, None
        request_started = perf_counter()
        try:
            status, raw = await self._post(body)
            metadata["http_status"] = status
            if self.transport_profile == JSON_LABELS_PROFILE and isinstance(raw, dict):
                choices = raw.get("choices")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                    if choices[0].get("finish_reason") == "length":
                        metadata["truncation_reason"] = "provider_finish_reason_length"
            usage, cost = self._usage(raw)
            if not 200 <= status < 300:
                raise BenchmarkError("provider_http_error")
            if (usage.get("input_tokens", 0) > MAX_INPUT_TOKENS
                    or usage.get("output_tokens", 0) > self.max_output_tokens):
                raise BenchmarkError("provider_schema_error")
            returned_model = raw.get("model") if isinstance(raw, dict) else None
            if (not isinstance(raw, dict) or (returned_model is not None
                    and (not isinstance(returned_model, str) or not returned_model.strip()))):
                raise BenchmarkError("provider_schema_error")
            metadata["returned_model"] = returned_model
            prediction = self._prediction(raw)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self.budget.settle, reservation, {}, None,
                                                  "cancelled_billing_unknown"))
            raise
        except httpx.HTTPError:
            code = "provider_transport_error"
        except BenchmarkError as error:
            code = error.code
        metadata["request_ms"] = (perf_counter() - request_started) * 1000
        metadata["usage_cost_estimate_usd"] = cost
        metadata["cost_estimate_method"] = "peak USD/M: uncached input 0.30, cached input 0.006, output 1.20; invoice unavailable"
        metadata["off_peak_cost_estimate_usd"] = cost / 2 if cost is not None else None
        await asyncio.to_thread(self.budget.settle, reservation, usage, cost,
                                "error_billing_unknown" if code else "response_received")
        return BenchmarkOutcome(adapter=self.name, model=self.model, status="error" if code else "ok",
            error_code=code, raw_response=raw, prediction=None if code else prediction,
            usage=usage, metadata=metadata)

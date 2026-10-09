"""Portable DeepSeek image adapter. Format validity never means event correctness."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
from time import perf_counter

ENDPOINT = "https://api.deepseek.com/chat/completions"
MAX_REQUEST_BYTES = 48 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024
JPEG_QUALITY = 80


def strict_json(text):
    def reject(value):
        raise ValueError("nonfinite_json")
    return json.loads(text, parse_constant=reject)


def encoded_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def number(value):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_numeric_config")
    return float(value)


class Adapter:
    def __init__(self, config):
        self.config = dict(config)
        self.model = str(config.get("model") or os.environ.get("VLM_MODEL", "deepseek-flash")).strip()
        self._token = os.environ.get("VLM_API_KEY", "").strip()
        self.max_tokens = config.get("max_tokens", config.get("max_output_tokens", 4096))

    def _scrub(self, value):
        if isinstance(value, str):
            return value.replace(self._token, "[REDACTED]") if self._token else value
        if isinstance(value, dict):
            return {self._scrub(k): self._scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._scrub(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    def _body(self, data):
        from jsonschema import Draft202012Validator
        if self.config.get("base_url", "https://api.deepseek.com").rstrip("/") != "https://api.deepseek.com":
            raise ValueError("unsupported_endpoint")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.model):
            raise ValueError("invalid_model")
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 8192:
            raise ValueError("invalid_output_limit")
        for key, default in (("input_price_per_million", .30), ("cached_input_price_per_million", .006),
                             ("output_price_per_million", 1.20), ("reservation_upper_usd", .058752)):
            number(self.config.get(key, default))
        if any(k in data for k in ("ground_truth", "annotations", "reference_label", "features_json")):
            raise ValueError("label_or_feature_leakage")
        sources, frames = data["sources"], data["frames"]
        active = data.get("active_sources", sources)
        if not isinstance(sources, list) or not 1 <= len(sources) <= 6 or len(set(sources)) != len(sources):
            raise ValueError("invalid_sources")
        if any(not isinstance(s, str) or not re.fullmatch(r"SRC0[1-6]", s) for s in sources):
            raise ValueError("nonneutral_sources")
        if not isinstance(active, list) or not active or len(set(active)) != len(active) or not set(active) <= set(sources):
            raise ValueError("invalid_active_sources")
        if not isinstance(frames, list) or len(frames) != 64 or len({f["frame_id"] for f in frames}) != 64:
            raise ValueError("64_unique_frames_required")
        expected_order = []
        for index, source in enumerate(sources):
            expected_order.extend([source] * (64 // len(sources) + (index < 64 % len(sources))))
        if [f["source_id"] for f in frames] != expected_order:
            raise ValueError("allocation_or_order_invalid")
        prompt, schema = data["prompt"], data["output_schema"]
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(schema, dict):
            raise ValueError("prompt_schema_invalid")
        Draft202012Validator.check_schema(schema)
        schema_bytes = encoded_json(schema)
        texts = [prompt, "Active sources and output JSON schema:\n" + encoded_json(
            {"active_sources": active, "output_schema": schema}).decode()]
        labels, last = [], {}
        for frame in frames:
            if any(k in frame for k in ("annotation", "annotations", "bbox", "ground_truth", "caption", "answer")):
                raise ValueError("frame_label_leakage")
            source, fid, n, timestamp = frame["source_id"], frame["frame_id"], frame["frame_number"], frame["timestamp_sec"]
            if type(n) is not int or n < 0 or not isinstance(fid, str) or not re.fullmatch(source + r"[-_]F[0-9]{6,}", fid):
                raise ValueError("invalid_frame_mapping")
            if int(re.split(r"[-_]F", fid)[1]) != n:
                raise ValueError("frame_number_mismatch")
            if type(timestamp) not in {int, float} or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("invalid_timestamp")
            if source in last and (n <= last[source][0] or timestamp <= last[source][1]):
                raise ValueError("source_order_invalid")
            last[source] = (n, timestamp)
            if frame["width"] != 1920 or frame["height"] != 1080:
                raise ValueError("canonical_dimensions_invalid")
            labels.append(encoded_json({k: frame[k] for k in ("frame_id", "source_id", "frame_number", "timestamp_sec")}).decode())
        text_bytes = sum(len(t.encode()) for t in texts + labels)
        if text_bytes > MAX_TEXT_BYTES:
            raise ValueError("text_size_limit_exceeded")
        import cv2
        import numpy as np
        content = [{"type": "text", "text": t} for t in texts]
        images = []
        for frame, label in zip(frames, labels):
            path = Path(frame["image_path"])
            if not path.is_absolute():
                raise ValueError("absolute_resolved_image_required")
            png = path.read_bytes()
            png_digest = hashlib.sha256(png).hexdigest()
            if png_digest != frame["sha256"] or not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("image_checksum_invalid")
            pixels = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
            if pixels is None or pixels.shape != (1080, 1920, 3) or pixels.dtype != np.uint8:
                raise ValueError("decoded_dimensions_or_channels_invalid")
            rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
            ok, jpeg_array = cv2.imencode(".jpg", pixels, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                raise ValueError("jpeg_conversion_failed")
            jpeg = jpeg_array.tobytes()
            content.extend([{"type": "text", "text": label}, {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}}])
            images.append({**{k: frame[k] for k in ("frame_id", "source_id", "frame_number", "timestamp_sec", "width", "height")},
                "png_sha256": png_digest, "source_rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                "sent_jpeg_sha256": hashlib.sha256(jpeg).hexdigest(), "jpeg_bytes": len(jpeg), "transport_label": label})
        body = {"model": self.model, "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"},
            "temperature": 0, "max_tokens": self.max_tokens}
        encoded = encoded_json(body)
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("request_size_limit_exceeded")
        return body, encoded, {"images_sent": 64, "images": images, "active_sources": active,
            "jpeg_quality": JPEG_QUALITY, "resize": False, "crop": False, "cv_features_sent": False,
            "request_bytes": len(encoded), "text_utf8_bytes": text_bytes, "max_tokens": self.max_tokens,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
            "frame_labels_sha256": hashlib.sha256(encoded_json(labels)).hexdigest(),
            "server_resize": "provider automatic; final dimensions not returned", "cloud_environment": "unknown"}

    async def _post(self, encoded):
        import httpx
        async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", ENDPOINT, headers={"Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json"}, content=encoded) as response:
                chunks, length = [], 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise ValueError("response_size_limit_exceeded")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8", errors="replace")
                try:
                    raw = strict_json(text)
                except (ValueError, json.JSONDecodeError):
                    raw = {"raw_text": text, "parse_error": "provider_invalid_json"}
                return response.status_code, self._scrub(raw)

    def _usage(self, raw):
        reported = raw.get("usage", {}) if isinstance(raw, dict) else {}
        keys = {"prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"}
        usage = {k: v for k, v in reported.items() if k in keys and type(v) is int and v >= 0} if isinstance(reported, dict) else {}
        price = number(self.config.get("input_price_per_million", .30))
        cache_price = number(self.config.get("cached_input_price_per_million", .006))
        output_price = number(self.config.get("output_price_per_million", 1.20))
        if not isinstance(reported, dict) or any(k in reported and k not in usage for k in keys):
            return usage, None
        if not {"prompt_tokens", "completion_tokens"} <= set(usage):
            return usage, None
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", usage["prompt_tokens"] - hit)
        if hit > usage["prompt_tokens"] or miss < 0 or hit + miss != usage["prompt_tokens"]:
            return usage, None
        return usage, (hit * cache_price + miss * price + usage["completion_tokens"] * output_price) / 1_000_000

    def _parse(self, raw, data):
        from jsonschema import Draft202012Validator
        if not isinstance(raw, dict) or not isinstance(raw.get("choices"), list) or not raw["choices"]:
            raise ValueError("provider_envelope_invalid")
        text = raw["choices"][0]["message"]["content"]
        if not isinstance(text, str) or len(text.encode()) > MAX_RESPONSE_BYTES:
            raise ValueError("provider_content_invalid")
        parsed = strict_json(text)
        errors = list(Draft202012Validator(data["output_schema"]).iter_errors(parsed))
        if errors:
            return parsed, False, "provider_schema_invalid"
        assessments = parsed["assessments"]
        sources = [a["source_id"] for a in assessments]
        active = data.get("active_sources", data["sources"])
        if len(sources) != len(active) or set(sources) != set(active):
            return parsed, False, "active_source_coverage_invalid"
        frame_sources = {f["frame_id"]: f["source_id"] for f in data["frames"]}
        for assessment in assessments:
            if any(frame_sources.get(ref) != assessment["source_id"] for ref in assessment["evidence_refs"]):
                return parsed, False, "evidence_reference_invalid"
            review_required = (assessment["event_type"] == "uncertain" or assessment["event_confidence"] < .90
                or any(value is None for value in assessment["risk_axes"].values()))
            if review_required and not assessment["needs_human_review"]:
                return parsed, False, "human_review_contract_invalid"
        return parsed, True, None

    async def run(self, model_input, context):
        started, request_started = perf_counter(), None
        result = {"status": "error", "executed": False, "output": None, "errors": [],
            "cost_usd": {"value": 0, "basis": "not_called", "invoice_usd": 0},
            "metadata": {"model": self.model, "retry_count": 0, "format_valid": None,
                "request_body_limit_bytes": MAX_REQUEST_BYTES, "response_body_limit_bytes": MAX_RESPONSE_BYTES}}
        phase, reservation, usage, cost = "input", None, {}, None
        directory, write = Path(context["artifact_dir"]), context["write_json"]
        try:
            body, encoded, metadata = await asyncio.to_thread(self._body, model_input)
            write(directory / "vlm.request.json", self._scrub(body))
            result["metadata"].update(metadata, preprocessing_ms=(perf_counter() - started) * 1000)
            if not context.get("allow_paid", False):
                result["status"] = "blocked"
                result["errors"].append({"category": "execution", "code": "paid_execution_disabled", "detail": "No API call was made."})
                return result
            phase = "credentials"
            if not self._token:
                raise ValueError("credentials_missing")
            phase = "budget"
            reservation = context["budget"].reserve("deepseek", number(self.config.get("reservation_upper_usd", .058752)))
            result["metadata"]["reservation_id"] = reservation
            phase = "request"
            result["executed"] = True
            result["cost_usd"] = {"value": None, "basis": "unknown", "invoice_usd": None}
            request_started = perf_counter()
            status, raw = await self._post(encoded)
            result["metadata"]["request_ms"] = (perf_counter() - request_started) * 1000
            result["metadata"]["http_status"] = status
            raw = self._scrub(raw)
            write(directory / "vlm.response.json", raw)
            usage, cost = self._usage(raw)
            result["cost_usd"] = {"value": cost, "basis": "usage_based_estimate" if cost is not None else "unknown", "invoice_usd": None}
            result["metadata"].update(usage=usage, reported_model=raw.get("model") if isinstance(raw, dict) else None,
                input_price_per_million=self.config.get("input_price_per_million", .30),
                cached_input_price_per_million=self.config.get("cached_input_price_per_million", .006),
                output_price_per_million=self.config.get("output_price_per_million", 1.20))
            if not 200 <= status < 300:
                result["errors"].append({"category": "execution", "code": "provider_http_error",
                    "detail": f"DeepSeek HTTP {status}; inspect vlm.response.json."})
                return result
            phase = "parse"
            parsed, valid, code = self._parse(raw, model_input)
            result["output"] = parsed
            result["metadata"]["format_valid"] = valid
            write(directory / "vlm.converted.json", parsed)
            if valid:
                result["status"] = "ok"
            else:
                result["invalid_output"] = parsed
                result["errors"].append({"category": "model", "code": code,
                    "detail": "Provider output was preserved without repair; event correctness is evaluated separately."})
        except asyncio.CancelledError:
            if reservation:
                context["budget"].settle(reservation, usage, cost, "cancelled_unknown")
                reservation = None
            raise
        except Exception:
            category = "benchmark" if phase == "input" else "model" if phase == "parse" else "execution"
            code = {"input": "input_contract_invalid", "credentials": "credentials_missing_or_invalid", "budget": "budget_exhausted",
                "request": "provider_transport_or_response_error", "parse": "provider_content_invalid"}[phase]
            result["status"] = "blocked" if phase in {"credentials", "budget"} else "error"
            if phase == "parse":
                result["metadata"]["format_valid"] = False
            result["errors"].append({"category": category, "code": code,
                "detail": "Inspect preserved artifacts and configuration; exception text is withheld to protect credentials."})
        finally:
            if request_started is not None and "request_ms" not in result["metadata"]:
                result["metadata"]["request_ms"] = (perf_counter() - request_started) * 1000
            result["latency_ms"] = (perf_counter() - started) * 1000
            if reservation:
                context["budget"].settle(reservation, usage, cost, result["status"])
        return result

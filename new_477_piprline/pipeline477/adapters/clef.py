"""Standalone, source-scoped Clef routing over label-free CV observations."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
from pathlib import Path
from time import perf_counter

MAX_REQUEST_BYTES = 196608
MAX_RESPONSE_BYTES = 1024 * 1024
ROUTES = {"invoke_vlm", "no_action", "human_review"}
CLASSES = {"person", "bicycle", "car", "motorcycle", "bus", "truck"}
AXES = ("severity", "imminence", "exposure", "persistence")


def number(value, low=0, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid numeric observation")
    if value < low or (high is not None and value > high):
        raise ValueError("numeric observation outside range")
    return value


def identifier(value):
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value):
        return value
    raise ValueError("invalid local track identifier")


class Adapter:
    def __init__(self, config):
        self.config = dict(config)
        self.model = os.environ.get("CLEF_MODEL", self.config.get("model", "clef")).strip()
        self._token = os.environ.get("CLEF_API_TOKEN") or os.environ.get("CLOUDFLARE_AUTH_TOKEN", "")
        self._account = os.environ.get("CLEF_ACCOUNT", "").strip()

    def _body(self, model_input):
        ids = [s["source_id"] if isinstance(s, dict) else s for s in model_input["sources"]]
        if not 1 <= len(ids) <= 6 or len(set(ids)) != len(ids) or any(
            not isinstance(s, str) or not re.fullmatch(r"SRC0[1-6]", s) for s in ids
        ):
            raise ValueError("one to six neutral distinct sources required")
        frames = model_input["frames"]
        cv = model_input["cv_output"]
        if not isinstance(frames, list) or len(frames) != 64 or not isinstance(cv, dict):
            raise ValueError("exactly 64 frames and normalized CV output required")
        cv_frames = cv.get("frames")
        if not isinstance(cv_frames, list) or len(cv_frames) != 64:
            raise ValueError("CV output must cover every input frame")
        mapped = {f["frame_id"]: f for f in cv_frames}
        if len(mapped) != 64:
            raise ValueError("duplicate CV frame reference")
        observations = {sid: [] for sid in ids}
        previous, previous_time = {}, {}
        seen = set()
        for frame in frames:
            fid, sid = frame["frame_id"], frame["source_id"]
            if not isinstance(fid, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", fid):
                raise ValueError("invalid neutral frame reference")
            if sid not in observations or fid in seen or fid not in mapped:
                raise ValueError("input frame mapping invalid")
            seen.add(fid)
            timestamp = number(frame["timestamp_sec"])
            if timestamp <= previous_time.get(sid, -1):
                raise ValueError("source timestamp sequence invalid")
            previous_time[sid] = timestamp
            original = frame["frame_number"]
            if type(original) is not int or original < 0 or original <= previous.get(sid, -1):
                raise ValueError("original frame sequence invalid")
            previous[sid] = original
            row = mapped[fid]
            if row.get("source_id") != sid or row.get("frame_number") != original or row.get("timestamp_sec") != timestamp:
                raise ValueError("CV frame mapping disagrees with input")
            if not isinstance(row.get("detections"), list):
                raise ValueError("CV detection list missing or invalid")
            detections = []
            for detection in row["detections"]:
                label = detection["class_name"]
                if label not in CLASSES:
                    raise ValueError("unsupported CV class")
                box = detection["bbox"]
                if not isinstance(box, list) or len(box) != 4:
                    raise ValueError("invalid CV box")
                box = [number(v) for v in box]
                if not box[0] < box[2] <= frame["width"] or not box[1] < box[3] <= frame["height"]:
                    raise ValueError("CV box outside input image")
                detections.append({"class_name": label, "bbox": box,
                    "confidence": number(detection["confidence"], high=1),
                    "track_id": identifier(detection.get("track_id"))})
            observations[sid].append({"frame_id": fid, "frame_number": original,
                "timestamp_sec": timestamp, "detections": detections})
        if any(not rows for rows in observations.values()):
            raise ValueError("source without input frames")
        compact = cv.get("compact_state", {})
        quality = cv.get("quality", compact.get("quality", {}))
        policy = compact.get("rule_policy", {})
        axes = compact.get("risk_axes", {})
        if not all(isinstance(v, dict) for v in (compact, quality, policy, axes)):
            raise ValueError("invalid CV quality or policy")
        measured = {axis: None if axes.get(axis) is None else number(axes[axis], high=1) for axis in AXES}
        flags = {"zone_configured": quality.get("zone_configured") is True,
                 "event_classifier_available": policy.get("event_classifier_available") is True,
                 "detector_confidence_is_not_event_confidence": True}
        uncertain = not flags["zone_configured"] or not flags["event_classifier_available"] or any(v is None for v in measured.values())
        tracks = {sid: [] for sid in ids}
        numeric_keys = ("first_timestamp_sec", "last_timestamp_sec", "observations", "observed_span_sec",
            "interpolated_visible_sec", "max_observation_gap_sec", "path_length_pixels", "net_displacement_pixels")
        for track in cv.get("tracks", []):
            sid = track.get("source_id", track.get("camera"))
            if sid not in tracks or track.get("class_name") not in CLASSES:
                raise ValueError("invalid CV track source or class")
            safe = {"track_id": identifier(track.get("track_id")), "class_name": track["class_name"]}
            for key in numeric_keys:
                if key in track:
                    # The CV worker reports no inter-observation gap for a
                    # single observation. Preserve this unknown, never invent 0.
                    if key == "max_observation_gap_sec" and track[key] is None:
                        if track.get("observations") != 1:
                            raise ValueError("null track gap requires one observation")
                        safe[key] = None
                    else:
                        safe[key] = number(track[key])
            if "person_dwell_candidate" in track:
                if type(track["person_dwell_candidate"]) is not bool:
                    raise ValueError("invalid dwell observation")
                safe["person_dwell_candidate"] = track["person_dwell_candidate"]
            tracks[sid].append(safe)
        prompt = model_input.get("prompt", "")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be text")
        state = {"sources": [{"source_id": sid, "frames": observations[sid], "tracks": tracks[sid],
                "quality": flags, "risk_axes": measured, "cv_uncertain": uncertain} for sid in ids],
            "limitations": ["Sparse uniformly sampled frames, not continuous video tracking.",
                "Track IDs are independent per source; no cross-source identity matching.",
                "Screen dwell alone does not establish loitering; missing zones cannot establish intrusion."],
            "frame_count": 64}
        questions = {}
        for sid in ids:
            questions[f"incident.{sid}"] = {"type": "noul", "instructions": prompt +
                f"\nFor source {sid} only, assess whether CV observations support a possible incident. "
                "Detection confidence is not event confidence; absent detections do not establish normality."}
            questions[f"route.{sid}"] = {"type": "choice", "instructions": prompt +
                f"\nFor source {sid} only, choose further processing. Missing zones, measured risk axes, "
                "or an event classifier require further review.", "criteria": {
                    "invoke_vlm": "Visual analysis is needed to evaluate a possible incident.",
                    "no_action": "Explicit normality is established with sufficient measured evidence.",
                    "human_review": "Evidence is uncertain or insufficient for an automatic decision."}}
        body = {"model": self.model, "state": state, "questions": questions}
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("request_body_limit_exceeded")
        return body, encoded, {sid: uncertain for sid in ids}

    def _parse(self, raw, uncertainty):
        if not isinstance(raw, dict) or raw.get("success") is not True or not isinstance(raw.get("result"), dict):
            raise ValueError("invalid provider envelope")
        data = raw["result"]
        if data.get("model") not in {self.model, f"@cf/cloudflare/{self.model}"}:
            raise ValueError("unexpected or missing reported model")
        answers = data.get("answers")
        expected = {f"{q}.{sid}" for sid in uncertainty for q in ("incident", "route")}
        if not isinstance(answers, dict) or set(answers) != expected:
            raise ValueError("provider questions incomplete or unexpected")
        decisions = []
        for sid, uncertain in uncertainty.items():
            incident, route = answers[f"incident.{sid}"], answers[f"route.{sid}"]
            if not isinstance(incident, dict) or not isinstance(route, dict) or incident.get("type") != "noul" or route.get("type") != "choice":
                raise ValueError("provider answer type invalid")
            probability = number(incident["noul"], high=1)
            confidence = number(route["confidence"], high=1)
            choice, distribution = route["choice"], route["probabilities"]
            if choice not in ROUTES or not isinstance(distribution, dict) or set(distribution) != ROUTES:
                raise ValueError("provider route options invalid")
            values = {k: number(v, high=1) for k, v in distribution.items()}
            if abs(sum(values.values()) - 1) > .001 or values[choice] < max(values.values()) - .000001:
                raise ValueError("provider route probabilities invalid")
            skip = choice == "no_action" and confidence >= .9 and probability < .35 and not uncertain
            reason = "cv_information_incomplete" if uncertain else "explicit_no_action" if skip else "further_review_required"
            decisions.append({"source_id": sid, "invoke_vlm": not skip, "proposed_route": choice,
                "route_confidence": confidence, "incident_probability": probability, "cv_uncertain": uncertain,
                "needs_human_review": not skip, "reason": reason})
        return {"sources": decisions}

    def _scrub(self, value):
        if isinstance(value, str):
            for secret in (self._token, self._account):
                if secret:
                    value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self._scrub(v) for v in value]
        if isinstance(value, dict):
            return {self._scrub(k): self._scrub(v) for k, v in value.items()}
        return value

    async def _post(self, body):
        import httpx
        url = f"https://api.cloudflare.com/client/v4/accounts/{self._account}/ai/run/@cf/cloudflare/{self.model}"
        async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}, content=body) as response:
                chunks, length = [], 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise ValueError("response_size_limit_exceeded")
                    chunks.append(chunk)
                text = b"".join(chunks).decode("utf-8", errors="replace")
                try:
                    def invalid_constant(_):
                        raise ValueError("non-finite JSON value")
                    raw = json.loads(text, parse_constant=invalid_constant)
                except (ValueError, json.JSONDecodeError):
                    raw = {"raw_text": text, "parse_error": "provider_invalid_json"}
                return response.status_code, self._scrub(raw)

    def _usage(self, raw):
        usage = raw.get("result", {}).get("usage", {}) if isinstance(raw, dict) and isinstance(raw.get("result"), dict) else {}
        valid = {k: v for k, v in usage.items() if k in {"input_tokens", "output_tokens"} and type(v) is int and v >= 0} if isinstance(usage, dict) else {}
        price = number(self.config.get("input_price_per_million", .24))
        output_price = number(self.config.get("output_price_per_million", 0))
        cost = None
        if "input_tokens" in valid and (not output_price or "output_tokens" in valid):
            cost = (valid["input_tokens"] * price + valid.get("output_tokens", 0) * output_price) / 1_000_000
        return valid, cost

    async def run(self, model_input, context):
        started, request_started = perf_counter(), None
        result = {"status": "error", "executed": False, "output": None, "errors": [],
            "cost_usd": {"value": 0, "basis": "not_called", "invoice_usd": 0},
            "metadata": {"model": self.model, "images_sent": 0, "feature_frames": 64,
                "retry_count": 0, "context_truncation_status": "unknown", "byte_token_proxy": False,
                "request_body_limit_bytes": MAX_REQUEST_BYTES}}
        phase, reservation, usage, cost = "input", None, {}, None
        write, directory = context["write_json"], Path(context["artifact_dir"])
        try:
            if self.model not in {"clef", "clef-flash"}:
                raise ValueError("unsupported_model")
            if self.config.get("base_url", "https://api.cloudflare.com").rstrip("/") != "https://api.cloudflare.com":
                raise ValueError("unsupported_endpoint")
            body, encoded, uncertainty = self._body(model_input)
            write(directory / "clef.request.json", self._scrub(body))
            result["metadata"].update(request_bytes=len(encoded), preprocessing_ms=(perf_counter()-started)*1000,
                sources=list(uncertainty), prompt_in_request=True)
            if not context.get("allow_paid", False):
                result["status"] = "blocked"
                result["errors"].append({"category": "execution", "code": "paid_execution_disabled", "detail": "No API call was made."})
                return result
            phase = "credentials"
            if not self._token or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self._account):
                raise ValueError("credentials_missing_or_invalid")
            phase = "budget"
            reservation = context["budget"].reserve("clef", number(self.config.get("reservation_upper_usd", .03145728)))
            result["metadata"]["reservation_id"] = reservation
            phase = "request"
            result["executed"] = True
            result["cost_usd"] = {"value": None, "basis": "unknown", "invoice_usd": None}
            request_started = perf_counter()
            status, raw = await self._post(encoded)
            result["metadata"]["http_status"] = status
            raw = self._scrub(raw)
            write(directory / "clef.response.json", raw)
            usage, cost = self._usage(raw)
            result["cost_usd"] = {"value": cost, "basis": "usage_based_estimate" if cost is not None else "unknown", "invoice_usd": None}
            result["metadata"].update(usage=usage, input_price_per_million=self.config.get("input_price_per_million", .24),
                output_price_per_million=self.config.get("output_price_per_million", 0))
            if not 200 <= status < 300:
                result["errors"].append({"category": "execution", "code": "provider_http_error",
                    "detail": f"Clef HTTP {status}; inspect clef.response.json for provider details."})
                return result
            phase = "parse"
            result["output"] = self._parse(raw, uncertainty)
            result["metadata"]["reported_model"] = raw["result"]["model"]
            result["status"] = "ok"
        except asyncio.CancelledError:
            if reservation:
                context["budget"].settle(reservation, usage, cost, "cancelled_unknown")
                reservation = None
            raise
        except Exception:
            category = "benchmark" if phase == "input" else "model" if phase == "parse" else "execution"
            code = {"input": "input_contract_invalid", "credentials": "credentials_missing_or_invalid",
                "budget": "budget_exhausted", "request": "provider_transport_or_response_error", "parse": "provider_schema_invalid"}[phase]
            result["status"] = "blocked" if phase in {"credentials", "budget"} else "error"
            result["errors"].append({"category": category, "code": code,
                "detail": "Inspect the planned request, response if available, and configuration; exception text is withheld to protect credentials."})
        finally:
            result["metadata"]["request_ms"] = (perf_counter()-request_started)*1000 if request_started is not None else 0
            result["latency_ms"] = (perf_counter()-started)*1000
            if reservation:
                context["budget"].settle(reservation, usage, cost, result["status"])
        return result

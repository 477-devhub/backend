"""OpenAI Responses API client for P4 (official SDK 3.26.0, same call pattern as P3): one user message with text +
images, reasoning.effort=high, strict json_schema, no tools, store=false, default service tier.
Retries only network/429/5xx (max 2). Classifies ok | refusal | incomplete | parse_failure. Never invents output.
"""
import json
import random
import time

import httpx2
import openai
from openai import OpenAI

from .utils import load_api_key_env, redact

MODEL = 'gpt-6.1-sol'
REASONING_EFFORT = 'high'
MAX_OUTPUT_TOKENS = 32000
CONNECT_TIMEOUT_SEC = 10.0
READ_WRITE_TIMEOUT_SEC = 900.0
MAX_RETRIES = 2
BACKOFF_BASE_SEC = 1.0
JITTER_SEC = 0.25
RETRYABLE = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)


def classify(body):
    if body.get('status') == 'incomplete':
        return 'incomplete', None, None
    texts, refusals = [], []
    for item in body.get('output') or []:
        if item.get('type') != 'message':
            continue
        for c in item.get('content') or []:
            if c.get('type') == 'refusal':
                refusals.append(c.get('refusal') or '')
            elif c.get('type') == 'output_text':
                texts.append(c.get('text') or '')
    if refusals:
        return 'refusal', None, ' '.join(refusals)[:1000]
    try:
        return 'ok', json.loads(''.join(texts)), None
    except Exception:
        return 'parse_failure', None, None


class ResponsesClient:
    def __init__(self):
        if not load_api_key_env():
            raise RuntimeError('OPENAI_API_KEY not available in environment or experiments/.env')
        self.client = OpenAI(max_retries=0, timeout=httpx2.Timeout(READ_WRITE_TIMEOUT_SEC, connect=CONNECT_TIMEOUT_SEC))
        self.sdk_version = openai.__version__

    def decide(self, content, text_format, model=MODEL):
        attempts, errors = 0, []
        t_total = time.perf_counter()
        while True:
            attempts += 1
            t0 = time.perf_counter()
            try:
                raw = self.client.responses.with_raw_response.create(
                    model=model, input=[{'role': 'user', 'content': content}],
                    reasoning={'effort': REASONING_EFFORT}, text={'format': text_format},
                    max_output_tokens=MAX_OUTPUT_TOKENS, store=False)
                elapsed = (time.perf_counter() - t0) * 1000
                body = raw.http_response.json()
                kind, parsed, refusal = classify(body)
                return {
                    'status': kind, 'http_status': raw.http_response.status_code,
                    'request_id': raw.headers.get('x-request-id'), 'openai_processing_ms': raw.headers.get('openai-processing-ms'),
                    'model': body.get('model'), 'response_status': body.get('status'), 'incomplete_details': body.get('incomplete_details'),
                    'service_tier': body.get('service_tier'), 'parsed': parsed, 'refusal': refusal, 'usage': body.get('usage'),
                    'reasoning_effort_returned': (body.get('reasoning') or {}).get('effort'), 'tools_returned': body.get('tools'),
                    'response_body': body,
                    'timing': {'last_attempt_ms': round(elapsed, 2), 'total_including_retries_ms': round((time.perf_counter() - t_total) * 1000, 2)},
                    'retry_count': attempts - 1, 'errors_before_success': errors,
                }
            except RETRYABLE as e:
                errors.append({'attempt': attempts, 'error_type': type(e).__name__, 'status': getattr(e, 'status_code', None), 'message': redact(str(e))[:300]})
                if attempts > MAX_RETRIES:
                    return self._failed(errors, attempts, t_total)
                time.sleep(BACKOFF_BASE_SEC * 2 ** (attempts - 1) + random.uniform(0, JITTER_SEC))
            except openai.APIStatusError as e:
                errors.append({'attempt': attempts, 'error_type': type(e).__name__, 'status': e.status_code, 'message': redact(str(e))[:800],
                               'request_id': e.response.headers.get('x-request-id') if e.response is not None else None})
                return self._failed(errors, attempts, t_total)

    @staticmethod
    def _failed(errors, attempts, t_total):
        return {'status': 'FAILED', 'errors': errors, 'retry_count': attempts - 1,
                'timing': {'total_including_retries_ms': round((time.perf_counter() - t_total) * 1000, 2)}}

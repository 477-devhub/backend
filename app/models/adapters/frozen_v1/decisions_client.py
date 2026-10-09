"""OpenAI Decisions API client (official SDK `client.decisions.create`), text input only.

- API key only from the environment (loaded from experiments/.env); never stored or logged.
- Explicit connect/read timeouts. Retries (max 2, exponential backoff + jitter) only for network errors, 429, 5xx.
  400/401/403/404/422 are never retried.
- Returns a JSON-safe record with answers, model, usage, timing, retry count, HTTP status and request id.
"""
import random
import time

import httpx2
import openai
from openai import OpenAI

from .utils import load_api_key_env

MODEL = 'gpt-6-luna'
CONNECT_TIMEOUT_SEC = 10.0
READ_TIMEOUT_SEC = 120.0
MAX_RETRIES = 2
BACKOFF_BASE_SEC = 1.0
JITTER_SEC = 0.25
RETRYABLE = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)  # APITimeoutError ⊂ APIConnectionError


def build_questions(task, cameras, qcfg):
    """Deterministic question list for one item (1 item = 1 request). Names are unique, [a-z0-9_]."""
    pol = qcfg['policy']

    def q(base, scope, prefix=''):
        out = {'type': base['type'], 'name': prefix + base['key'], 'instructions': f"{scope} {base['instructions']} {pol}"}
        if base['type'] == 'choice':
            out['choices'] = [dict(c) for c in base['choices']]
        if base['type'] == 'score':
            out['levels'] = [dict(l) for l in base['levels']]
        return out

    qs = []
    if task == 'single':
        qs = [q(b, qcfg['scope']['single']) for b in qcfg['per_assessment_questions']]
    elif task == 'attention':
        for cam in cameras:
            scope = qcfg['scope']['camera'].format(camera=cam)
            qs += [q(b, scope, cam.lower().replace('_', '') + '_') for b in qcfg['per_assessment_questions']]
        allowed = set(cameras) | {'no_clear_priority'}
        for b in qcfg['attention_questions']:
            b = dict(b, choices=[c for c in b['choices'] if c['value'] in allowed])
            qs.append(q(b, ''))
    elif task == 'multi_camera':
        scope = qcfg['scope']['multi_camera']
        qs = [q(b, scope) for b in qcfg['per_assessment_questions'] + qcfg['multi_camera_questions']]
    else:
        raise ValueError(task)
    for x in qs:
        x['instructions'] = x['instructions'].strip()
    return qs


class DecisionsClient:
    def __init__(self):
        if not load_api_key_env():
            raise RuntimeError('OPENAI_API_KEY not available in environment or experiments/.env')
        self.client = OpenAI(max_retries=0, timeout=httpx2.Timeout(READ_TIMEOUT_SEC, connect=CONNECT_TIMEOUT_SEC))
        self.sdk_version = openai.__version__
        self.http_client_version = f'httpx2 {httpx2.__version__}'

    def decide(self, input_text, questions, model=MODEL):
        attempts, errors = 0, []
        t_total = time.perf_counter()
        while True:
            attempts += 1
            t0 = time.perf_counter()
            try:
                raw = self.client.decisions.with_raw_response.create(model=model, input=input_text, questions=questions)
                elapsed = (time.perf_counter() - t0) * 1000
                parsed = raw.parse()
                return {
                    'status': 'ok',
                    'http_status': raw.http_response.status_code,
                    'request_id': raw.headers.get('x-request-id'),
                    'openai_processing_ms': raw.headers.get('openai-processing-ms'),
                    'model': parsed.model,
                    'answers': [a.model_dump(mode='json') for a in parsed.answers],
                    'usage': parsed.usage.model_dump(mode='json'),
                    'response_body': raw.http_response.json(),
                    'timing': {'last_attempt_ms': round(elapsed, 2), 'total_including_retries_ms': round((time.perf_counter() - t_total) * 1000, 2)},
                    'retry_count': attempts - 1,
                    'errors_before_success': errors,
                }
            except RETRYABLE as e:
                errors.append({'attempt': attempts, 'error_type': type(e).__name__, 'status': getattr(e, 'status_code', None), 'message': type(e).__name__})
                if attempts > MAX_RETRIES:
                    return self._failed(errors, attempts, t_total)
                time.sleep(BACKOFF_BASE_SEC * 2 ** (attempts - 1) + random.uniform(0, JITTER_SEC))
            except openai.APIStatusError as e:   # 400/401/403/404/422 etc.: never retried
                errors.append({'attempt': attempts, 'error_type': type(e).__name__, 'status': e.status_code, 'message': type(e).__name__,
                               'request_id': e.response.headers.get('x-request-id') if e.response is not None else None})
                return self._failed(errors, attempts, t_total)

    @staticmethod
    def _failed(errors, attempts, t_total):
        return {'status': 'FAILED', 'errors': errors, 'retry_count': attempts - 1,
                'timing': {'total_including_retries_ms': round((time.perf_counter() - t_total) * 1000, 2)}}

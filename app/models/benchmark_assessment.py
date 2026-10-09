"""Map validated benchmark predictions to the existing backend contract."""
from app.schemas.benchmark import BenchmarkInput, BenchmarkOutcome
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes
from app.services.risk import risk_level, risk_score

EVENTS = {'normal', 'collapse', 'conflict', 'intrusion', 'loitering', 'uncertain'}


def common_assessments(request: BenchmarkInput, outcome: BenchmarkOutcome,
                       *, validated: bool, force_review: bool = False) -> list[dict]:
    """No repairs or invented scores; free-form unknown event labels go to review."""
    prediction = outcome.prediction if validated and outcome.status == 'ok' else None
    error_code = outcome.error_code or ('invalid_benchmark_contract'
        if outcome.prediction is not None and not validated else None)
    rows = ([(r['camera'], r['assessment']) for r in prediction['assessments']]
        if prediction and request.task == 'attention' else [(None, prediction)])
    results = []
    for camera, row in rows:
        event = row.get('event_type', '').strip().lower() if row else 'uncertain'
        unknown_label = event not in EVENTS
        if unknown_label:
            event = 'uncertain'
        refs = []
        if row:
            for obs in row.get('observations', []):
                candidates = [(i, f) for i, f in enumerate(request.frames)
                    if f.camera == obs['camera']]
                index, nearest = min(candidates,
                    key=lambda pair: abs(pair[1].timestamp_sec-obs['timestamp_sec']))
                if abs(nearest.timestamp_sec-obs['timestamp_sec']) <= 1/30 + 1e-9:
                    ref = f'{nearest.camera}:{index}'
                    if ref not in refs:
                        refs.append(ref)
        uncertainties = row.get('uncertainties', []) if row else []
        reason = '; '.join(uncertainties) or None
        if unknown_label:
            reason = 'Provider event label does not match the common event enumeration.'
        if not row:
            reason = error_code or 'Model did not produce a validated event assessment.'
        review = bool(force_review or not row or unknown_label or uncertainties
            or row.get('human_review_required', False)
            or row.get('confidence', 0) < .9 or not refs)
        assessment = ModelAssessment(event_type=event,
            event_confidence=row['confidence'] if row else 0,
            risk_axes=RiskAxes(**row['risk']) if row else RiskAxes(),
            evidence_refs=refs, needs_human_review=review,
            uncertainty_reason=reason, ai_opinion=row.get('reason') if row else None,
            metadata=ModelMetadata(adapter=outcome.adapter, model=outcome.model,
                latency_ms=outcome.latency_ms, error_code=error_code,
                estimated_cost_usd=outcome.metadata.get('usage_cost_estimate_usd',
                    outcome.metadata.get('estimated_cost_usd'))))
        score = risk_score(assessment.risk_axes)
        results.append({'camera': camera, 'assessment': assessment.model_dump(mode='json'),
            'backend_risk_score': score, 'backend_risk_level': risk_level(score),
            'provider_event_label': row.get('event_type') if row else None})
    return results

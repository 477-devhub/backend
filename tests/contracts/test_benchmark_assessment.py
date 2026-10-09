from app.models.benchmark_assessment import common_assessments
from app.schemas.benchmark import BenchmarkInput, BenchmarkOutcome, CanonicalFrame


def request():
    pixels = bytes(1920*1080*3)
    return BenchmarkInput('synthetic-fixture', 'single', 'frozen prompt', '{}', '{}',
        tuple(CanonicalFrame('CAM_01', i, pixels) for i in range(64)))


def test_failure_keeps_null_axes_and_backend_unknown():
    result = common_assessments(request(), BenchmarkOutcome('cv', 'cv'), validated=False)[0]
    assert result['backend_risk_score'] is None
    assert result['backend_risk_level'] == 'UNKNOWN'
    assert result['assessment']['needs_human_review']
    assert all(v is None for v in result['assessment']['risk_axes'].values())


def test_common_risk_is_backend_weighted_and_not_confidence_multiplied():
    prediction = {'event_type': 'collapse', 'confidence': .4,
        'observations': [{'camera': 'CAM_01', 'timestamp_sec': 12}],
        'risk': dict(severity=1, imminence=1, exposure=1, persistence=1),
        'uncertainties': [], 'human_review_required': False, 'reason': 'visible posture'}
    result = common_assessments(request(),
        BenchmarkOutcome('vlm', 'vlm', prediction=prediction), validated=True)[0]
    assert result['backend_risk_score'] == 100
    assert result['assessment']['evidence_refs'] == ['CAM_01:12']
    assert result['assessment']['needs_human_review']


def test_unrecognized_provider_event_is_preserved_and_reviewed():
    prediction = {'event_type': 'unsupported diagnosis', 'confidence': .99,
        'observations': [{'camera': 'CAM_01', 'timestamp_sec': 12}],
        'risk': dict(severity=0, imminence=0, exposure=0, persistence=0),
        'uncertainties': [], 'human_review_required': False}
    result = common_assessments(request(),
        BenchmarkOutcome('vlm', 'vlm', prediction=prediction), validated=True)[0]
    assert result['provider_event_label'] == 'unsupported diagnosis'
    assert result['assessment']['event_type'] == 'uncertain'
    assert result['assessment']['needs_human_review']


def test_exact_source_frame_period_boundary_survives_float_rounding():
    from dataclasses import replace
    original = request()
    adjusted = replace(original, frames=(
        CanonicalFrame('CAM_01', 2/30, original.frames[0].rgb24),
        *original.frames[1:]))
    prediction = {'event_type': 'collapse', 'confidence': .95,
        'observations': [{'camera': 'CAM_01', 'timestamp_sec': .1}],
        'risk': dict(severity=1, imminence=1, exposure=1, persistence=1),
        'uncertainties': [], 'human_review_required': True}
    result = common_assessments(adjusted,
        BenchmarkOutcome('vlm', 'vlm', prediction=prediction), validated=True)[0]
    assert result['assessment']['evidence_refs'] == ['CAM_01:0']


def test_invalid_contract_is_recorded_as_error_without_repairing_prediction():
    outcome = BenchmarkOutcome('vlm', 'vlm', prediction={'event_type': 'collapse'})
    result = common_assessments(request(), outcome, validated=False)[0]
    assert result['assessment']['metadata']['error_code'] == 'invalid_benchmark_contract'
    assert result['backend_risk_score'] is None
    assert outcome.prediction == {'event_type': 'collapse'}

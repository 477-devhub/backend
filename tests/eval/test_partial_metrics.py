import pytest

from app.eval.metrics import summarize
from app.schemas.model import ModelAssessment, ModelMetadata, RiskAxes


def record(*,gt_axes=None,pred_axes=None,critical=None,review=None,error=None):
    assessment=ModelAssessment(
        event_type='uncertain',event_confidence=0.0,
        risk_axes=RiskAxes.model_validate(pred_axes) if pred_axes is not None else None,
        evidence_refs=[],needs_human_review=True,uncertainty_reason='contract test',
        metadata=ModelMetadata(adapter='local_cv',model='contract-only',error_code=error),
    )
    return {'ground_truth':{
        'event_type':'collapse','critical':critical,'needs_human_review':review,
        'risk_axes':gt_axes,
    },'prediction':assessment.model_dump(mode='json')}


def test_partial_axis_mae_uses_only_matching_measurements():
    records=[
        record(gt_axes={'severity':0.8,'imminence':None,'exposure':0.4},
               pred_axes={'severity':0.5,'imminence':1.0,'persistence':0.2}),
        record(gt_axes={'severity':0.0,'imminence':0.0,'exposure':0.0,'persistence':0.0},
               pred_axes={'severity':0.1,'imminence':0.2,'exposure':0.3,'persistence':0.4}),
        record(error='provider_error'),
    ]
    metrics=summarize(records)
    assert metrics['risk_axis_scalar_pair_count']==5
    assert metrics['risk_axis_mae_measured']==pytest.approx(1.3/5)
    assert metrics['risk_axis_pair_count']==1
    assert metrics['risk_axis_pair_coverage']==pytest.approx(1/3)
    assert metrics['risk_axis_scalar_coverage']==pytest.approx(5/12)
    axes=metrics['risk_axis_metrics']
    assert axes['severity']['pair_count']==2
    assert axes['severity']['mae_measured']==pytest.approx(0.2)
    assert axes['severity']['pair_coverage']==pytest.approx(2/3)
    assert axes['imminence']['pair_count']==1
    assert axes['imminence']['ground_truth_count']==1
    assert axes['imminence']['prediction_count']==2
    assert axes['exposure']['ground_truth_count']==2
    assert axes['exposure']['prediction_count']==1
    assert axes['persistence']['ground_truth_coverage']==pytest.approx(1/3)
    assert axes['persistence']['prediction_coverage']==pytest.approx(2/3)
    assert metrics['n']==3 and metrics['error_rate']==pytest.approx(1/3)
    assert metrics['cost_usd_mean_measured'] is None and metrics['cost_coverage']==0


def test_four_single_axis_samples_do_not_count_as_one_complete_pair():
    records=[record(gt_axes={axis:0.6},pred_axes={axis:0.4})
             for axis in ['severity','imminence','exposure','persistence']]
    metrics=summarize(records)
    assert metrics['risk_axis_scalar_pair_count']==4
    assert metrics['risk_axis_pair_count']==0
    assert metrics['risk_axis_mae_measured']==pytest.approx(0.2)


def test_missing_and_disjoint_measurements_have_null_mae():
    metrics=summarize([
        record(gt_axes={'severity':1.0},pred_axes={'imminence':0.0}),
        record(gt_axes={'severity':None},pred_axes={}),
        record(),
    ])
    assert metrics['risk_axis_mae_measured'] is None
    assert metrics['risk_axis_pair_count']==0
    assert metrics['risk_axis_scalar_pair_count']==0
    assert metrics['risk_axis_scalar_coverage']==0
    assert all(axis['mae_measured'] is None for axis in metrics['risk_axis_metrics'].values())
    assert metrics['risk_axis_metrics']['severity']['ground_truth_count']==1
    assert metrics['risk_axis_metrics']['imminence']['prediction_count']==1


def test_annotation_coverage_distinguishes_false_missing_and_positive():
    metrics=summarize([
        record(critical=True,review=True,error='timeout'),
        record(critical=False,review=False),
        record(),
        {'ground_truth':{'event_type':'collapse'},'prediction':record()['prediction']},
    ])
    assert metrics['critical_annotation_count']==2
    assert metrics['critical_annotation_coverage']==0.5
    assert metrics['critical_positive_count']==1
    assert metrics['critical_event_recall']==0
    assert metrics['critical_escalation_recall']==1
    assert metrics['human_review_annotation_count']==2
    assert metrics['human_review_annotation_coverage']==0.5
    assert metrics['human_review_positive_count']==1
    assert metrics['human_review_recall']==1
    assert metrics['macro_f1']==0 and metrics['error_rate']==0.25


@pytest.mark.parametrize('annotation',[None,False])
def test_no_positive_annotations_give_null_recall(annotation):
    metrics=summarize([record(critical=annotation,review=annotation)])
    assert metrics['critical_event_recall'] is None
    assert metrics['critical_escalation_recall'] is None
    assert metrics['human_review_recall'] is None
    assert metrics['critical_annotation_coverage']==(0 if annotation is None else 1)
    assert metrics['human_review_annotation_coverage']==(0 if annotation is None else 1)

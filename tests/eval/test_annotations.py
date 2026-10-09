"""Synthetic companion annotations test the GT boundary, never model accuracy."""
import pytest

from app.eval.annotations import parse_annotations


@pytest.fixture
def companion():
    return {"videos":[{"filename":"lo_e1015_c1.mp4","view":"c1","width":1920},
                      {"filename":"lo_e1015_c2.mp4","view":"c2","width":1920}],
            "annotations":{"event_class":"특정 구역 내 지속 배회",
                "question":"GT question", "answer":"GT answer",
                "caption":{"c1":{"caption_text":"GT", "cot":{"1단계":"GT"}}},
                "evidence":{"c1":{"frame_id":[412],"obj_bbox":[[1,2,3,4]]}}}}


def test_mapping_is_explicit_and_no_inference_input_is_generated(companion):
    parsed=parse_annotations(companion,event_mapping={"특정 구역 내 지속 배회":"loitering"})
    assert parsed.ground_truth=={"event_type":"loitering","critical":None,
                                "needs_human_review":None,"risk_axes":None}
    assert len(parsed.videos)==2
    assert parsed.evaluation_only_annotations['evidence']['c1']['frame_id']==[412]
    assert not hasattr(parsed,'model_input') and not hasattr(parsed,'window')
    companion['annotations']['evidence']['c1']['frame_id'].append(999)
    assert parsed.evaluation_only_annotations['evidence']['c1']['frame_id']==[412]


@pytest.mark.parametrize('mapping',[{}, {'특정 구역 내 지속 배회':'danger'}])
def test_unknown_mapping_fails(companion,mapping):
    with pytest.raises(ValueError,match='mapping|mapped'):
        parse_annotations(companion,event_mapping=mapping)


def test_duplicate_view_rejected(companion):
    companion['videos'][1]['view']='c1'
    with pytest.raises(ValueError,match='duplicate'):
        parse_annotations(companion,event_mapping={'특정 구역 내 지속 배회':'loitering'})


def test_explicit_partial_labels_remain_partial(companion):
    companion['annotations'].update(critical=True,needs_human_review=False,risk_axes={'severity':.4})
    parsed=parse_annotations(companion,event_mapping={'특정 구역 내 지속 배회':'loitering'})
    assert parsed.ground_truth['critical'] is True
    assert parsed.ground_truth['needs_human_review'] is False
    assert parsed.ground_truth['risk_axes']['severity']==.4
    assert parsed.ground_truth['risk_axes']['imminence'] is None


def test_boolean_labels_are_not_coerced(companion):
    companion['annotations']['critical']='true'
    with pytest.raises(ValueError,match='boolean'):
        parse_annotations(companion,event_mapping={'특정 구역 내 지속 배회':'loitering'})

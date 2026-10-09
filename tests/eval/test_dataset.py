import hashlib,json
from pathlib import Path
import pytest
from app.eval.dataset import validate_manifest, load_input, ManifestRow
from app.eval.batch import run_batch

@pytest.fixture
def dataset(tmp_path,mi):
    (tmp_path/'video.mp4').write_bytes(b'fake-data-for-contract-only')
    mi=mi.model_copy(update={'sample_id':'s_000001'})
    (tmp_path/'input.json').write_text(mi.model_dump_json(),encoding='utf-8')
    row={'sample_id':'s_000001','split':'validation','scenario_group':'scene1','source_video_id':'source1',
        'video_path':'video.mp4','media_sha256':hashlib.sha256((tmp_path/'video.mp4').read_bytes()).hexdigest(),
        'input_path':'input.json','camera_id':mi.camera.id,'start_ms':0,'end_ms':10000,
        'event_type':'collapse','critical':True,'needs_human_review':False}
    manifest=tmp_path/'manifest.jsonl';manifest.write_text(json.dumps(row)+'\n',encoding='utf-8')
    return manifest,row

def test_valid_and_gt_removed(dataset):
    p,row=dataset;rows=validate_manifest(p);mi=load_input(rows[0],p.parent)
    assert 'collapse' not in mi.sample_id and 'event_type' not in mi.model_dump()

def test_source_leak(dataset):
    p,row=dataset;b={**row,'sample_id':'s_000002','split':'test'}
    p.write_text(json.dumps(row)+'\n'+json.dumps(b)+'\n')
    with pytest.raises(ValueError,match='cross-split'):validate_manifest(p)

def test_path_and_hash(dataset):
    p,row=dataset;p.write_text(json.dumps({**row,'video_path':'../escape.mp4'}))
    with pytest.raises(ValueError,match='escapes'):validate_manifest(p)
    p.write_text(json.dumps({**row,'media_sha256':'0'*64}))
    with pytest.raises(ValueError,match='hash mismatch'):validate_manifest(p)

def test_observation_leak(dataset):
    p,_=dataset;inp=p.parent/'input.json';data=json.loads(inp.read_text());data['temporal_state']['events'][0]['label']='collapse';inp.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='label-like'):validate_manifest(p)

async def test_mocks_rejected(dataset,tmp_path):
    p,_=dataset
    with pytest.raises(ValueError,match='mock'):await run_batch(p,'mock_local_cv','validation',tmp_path/'out')
async def test_real_errors_in_denominator(dataset,tmp_path):
    p,_=dataset;m=await run_batch(p,'local_cv','validation',tmp_path/'out')
    assert m['error_rate']==1 and m['critical_event_recall']==0 and m['critical_escalation_recall']==1
    assert m['cost_usd_mean_measured'] is None
async def test_test_requires_lock(dataset,tmp_path):
    p,row=dataset;p.write_text(json.dumps({**row,'split':'test'}))
    with pytest.raises(ValueError,match='requires'):await run_batch(p,'local_cv','test',tmp_path/'out')
async def test_frozen_change_rejected(dataset,tmp_path):
    p,row=dataset;p.write_text(json.dumps({**row,'split':'test'}))
    c=tmp_path/'config.json';c.write_text('{"adapters":["local_cv"],"timeout_sec":5}')
    lock=tmp_path/'lock.json';lock.write_text(json.dumps({'manifest_sha256':'0'*64,'run_config_sha256':hashlib.sha256(c.read_bytes()).hexdigest()}))
    with pytest.raises(ValueError,match='changed'):await run_batch(p,'local_cv','test',tmp_path/'out',lock,c,True)

def test_missing_review_and_critical_annotations_remain_null(dataset):
    p,row=dataset
    row.pop('critical')
    row.pop('needs_human_review')
    p.write_text(json.dumps(row),encoding='utf-8')
    parsed=validate_manifest(p)[0]
    assert parsed.critical is None and parsed.needs_human_review is None
    assert parsed.model_dump()['critical'] is None

def test_raw_frames_allow_empty_temporal_state(dataset):
    p,_=dataset
    inp=p.parent/'input.json'
    data=json.loads(inp.read_text(encoding='utf-8'))
    data['temporal_state']={}
    data['evidence'][0]['media_ref']='media_'+'a'*64
    inp.write_text(json.dumps(data),encoding='utf-8')
    parsed=load_input(validate_manifest(p)[0],p.parent)
    assert parsed.temporal_state.feature_version is None
    assert parsed.evidence[0].media_ref=='media_'+'a'*64

@pytest.mark.parametrize('observations',[
    {'person_count':0},{'vehicle_count':0},
    {'tracks':[{'track_id':'track_1','frame_id':'frame_1','bbox':[1,2,3,4]}]},
    {'events':[{'timestamp_ms':10,'motion_speed':0.5}]},
    {'relations':[{'track_ids':['track_1','track_2'],'distance':4}]},
    {'quality':{'blur_score':0.0}},
])
def test_every_observation_category_requires_extractor_version(dataset,observations):
    p,_=dataset
    inp=p.parent/'input.json'
    data=json.loads(inp.read_text(encoding='utf-8'))
    data['temporal_state']=observations
    inp.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='feature_version required'):
        validate_manifest(p)
    data['temporal_state']['feature_version']='cv-test-1'
    inp.write_text(json.dumps(data),encoding='utf-8')
    validate_manifest(p)

@pytest.mark.parametrize('annotation_key',[
    'annotations','caption','caption_text','cot','answer','question','event_class',
    'evidence_text','obj_bbox','obj_id','obj_label',
])
def test_annotation_keys_rejected_at_nested_observation_depth(dataset,annotation_key):
    p,_=dataset
    inp=p.parent/'input.json'
    data=json.loads(inp.read_text(encoding='utf-8'))
    data['temporal_state']['tracks']=[{'measurements':[{'details':{annotation_key:'GT'}}]}]
    inp.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='label-like'):
        validate_manifest(p)

@pytest.mark.parametrize('media_ref',['lo_e1015_c1.mp4','media_loitering','media_'+'a'*63])
def test_media_tokens_reject_original_paths_and_invalid_digest(dataset,media_ref):
    p,_=dataset
    inp=p.parent/'input.json'
    data=json.loads(inp.read_text(encoding='utf-8'))
    data['evidence'][0]['media_ref']=media_ref
    inp.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='opaque frame token'):
        validate_manifest(p)

async def test_unconfigured_real_batch_preserves_missing_annotations(dataset,tmp_path):
    p,row=dataset
    row.pop('critical')
    row.pop('needs_human_review')
    p.write_text(json.dumps(row),encoding='utf-8')
    metrics=await run_batch(p,'local_cv','validation',tmp_path/'partial-out')
    assert metrics['n']==1 and metrics['error_rate']==1
    assert metrics['critical_event_recall'] is None
    assert metrics['human_review_recall'] is None
    assert metrics['critical_annotation_coverage']==0
    assert metrics['human_review_annotation_coverage']==0
    record=json.loads((tmp_path/'partial-out'/'predictions.jsonl').read_text(encoding='utf-8'))
    assert record['ground_truth']['critical'] is None
    assert record['ground_truth']['needs_human_review'] is None
    assert record['prediction']['needs_human_review'] is True

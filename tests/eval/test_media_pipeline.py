"""Real FFmpeg over SYNTHETIC media; results here are not CCTV model metrics."""
import hashlib
import json
import shutil
import subprocess

import pytest

from app.eval.batch import run_batch
from app.eval.pipeline import evaluate_input, input_sha256, load_resolver
from app.eval.runner import run
from app.models.media import MediaResolver
from app.schemas.model import TimeWindow, TemporalState, ModelAssessment, ModelMetadata


@pytest.fixture
def synthetic_dataset(tmp_path,mi):
    ffmpeg=shutil.which('ffmpeg')
    if ffmpeg is None:
        pytest.skip('FFmpeg executable required for synthetic media integration')
    content=subprocess.run([ffmpeg,'-nostdin','-v','error','-f','lavfi','-i',
        'testsrc=size=64x48:rate=4:duration=2','-threads','1','-c:v','mpeg4',
        '-movflags','frag_keyframe+empty_moov','-f','mp4','pipe:1'],
        check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10).stdout
    video=tmp_path/'lo_e1015_c1.mp4';video.write_bytes(content)
    raw=mi.model_copy(update={'sample_id':'s_000001','clip_ref':'clip_000001',
        'window':TimeWindow(start_ms=0,end_ms=1700),'evidence':[], 'temporal_state':TemporalState()})
    inp=tmp_path/'input.json';inp.write_text(raw.model_dump_json(),encoding='utf-8')
    row={'sample_id':raw.sample_id,'split':'validation','scenario_group':'scene-0001',
        'source_video_id':'source-0001','video_path':video.name,'input_path':inp.name,
        'media_sha256':hashlib.sha256(content).hexdigest(),'camera_id':raw.camera.id,
        'start_ms':0,'end_ms':1700,'event_type':'loitering'}
    manifest=tmp_path/'manifest.jsonl';manifest.write_text(json.dumps(row)+'\n',encoding='utf-8')
    asset_map=tmp_path/'assets.json';asset_map.write_text(json.dumps({'clip_000001':video.name}),encoding='utf-8')
    return raw,manifest,asset_map,row


async def test_real_slots_get_identical_prepared_input_and_phases(synthetic_dataset,tmp_path):
    raw,manifest,asset_map,_=synthetic_dataset
    records=[]
    for name in ('local_cv','clef_direct','general_vlm'):
        out=tmp_path/name
        metrics=await run_batch(manifest,name,'validation',out,asset_map=asset_map)
        record=json.loads((out/'predictions.jsonl').read_text(encoding='utf-8'))
        records.append(record)
        assert metrics['n']==1 and metrics['mock_count']==0
        assert record['preparation']['profile']['actual_frame_count']==4
        assert record['input_stage']=='prepared'
        assert record['timings']['preprocessing_ms']>0
        assert record['timings']['execution_wall_ms']>0
        assert record['timings']['end_to_end_ms']>=record['timings']['execution_wall_ms']
        assert record['timings']['provider_ms'] is None
        assert metrics['cost_coverage']==0
        assert record['ground_truth']['critical'] is None
    assert len({r['input_sha256'] for r in records})==1
    assert len({json.dumps(r['preparation'],sort_keys=True) for r in records})==1
    assert records[0]['prediction']['event_type']=='uncertain'
    assert records[0]['timings']['adapter_cv_preprocessing_ms']>0
    assert records[0]['timings']['adapter_cv_worker_ms']>0
    assert records[0]['versions']['opencv']
    assert all(r['prediction']['metadata']['error_code']=='provider_error' for r in records[1:])
    single=await run('clef_direct',manifest.parent/'input.json',output=tmp_path/'single.json',asset_map=asset_map)
    assert single['input_sha256']==records[1]['input_sha256']
    assert single['source_input_sha256']==input_sha256(raw)


async def test_resolver_hash_mismatch_is_retained(synthetic_dataset,tmp_path):
    _,manifest,asset_map,_=synthetic_dataset
    # Another valid clip container, same decodable video, different actual bytes.
    wrong=manifest.parent/'wrong.mp4'
    wrong.write_bytes((manifest.parent/'lo_e1015_c1.mp4').read_bytes()+b'synthetic-other-source')
    asset_map.write_text(json.dumps({'clip_000001':wrong.name}),encoding='utf-8')
    out=tmp_path/'mismatch'
    metrics=await run_batch(manifest,'clef_direct','validation',out,asset_map=asset_map)
    record=json.loads((out/'predictions.jsonl').read_text(encoding='utf-8'))
    assert metrics['n']==1 and metrics['error_rate']==1
    assert metrics['error_phase_counts']=={'preprocessing':1,'execution':0}
    assert record['prediction']['metadata']['error_code']=='preprocessing_error'
    assert record['prediction']['evidence_refs']==[]
    assert record['prediction']['risk_axes'] is None
    assert record['prediction']['metadata']['latency_ms'] is None
    assert record['timings']['execution_wall_ms'] is None
    assert record['timings']['preprocessing_ms']>0
    assert metrics['timing_metrics']['execution_wall_ms']['coverage']==0


async def test_missing_clip_and_invalid_video_do_not_drop_samples(synthetic_dataset,tmp_path):
    _,manifest,asset_map,row=synthetic_dataset
    broken=manifest.parent/'broken.mp4';broken.write_bytes(b'SYNTHETIC invalid media')
    row.update(video_path=broken.name,media_sha256=hashlib.sha256(broken.read_bytes()).hexdigest(),critical=True)
    manifest.write_text(json.dumps(row),encoding='utf-8')
    asset_map.write_text(json.dumps({'clip_000001':broken.name}),encoding='utf-8')
    for i,mapping in enumerate(({'clip_000001':broken.name},{})):
        asset_map.write_text(json.dumps(mapping),encoding='utf-8')
        out=tmp_path/f'broken{i}'
        metrics=await run_batch(manifest,'general_vlm','validation',out,asset_map=asset_map)
        assert metrics['n']==1 and metrics['critical_event_recall']==0
        assert metrics['critical_escalation_recall']==1 and metrics['error_rate']==1


async def test_preparation_discards_supplied_annotation_observations(synthetic_dataset,monkeypatch):
    raw,_,asset_map,_=synthetic_dataset
    raw=raw.model_copy(update={'temporal_state':TemporalState(events=[{'caption':'GT'}])})
    captured=[]
    class SyntheticProbe:
        name='clef_direct'
        async def evaluate(self,mi):
            captured.append(mi.model_dump(mode='json'))
            return ModelAssessment(event_type='uncertain',event_confidence=0,risk_axes=None,
                needs_human_review=True,uncertainty_reason='synthetic contract probe',
                evidence_refs=[],metadata=ModelMetadata(adapter=self.name,model='synthetic-test-probe'))
    monkeypatch.setattr('app.eval.pipeline.get_adapter',lambda name,**kw:SyntheticProbe())
    result=await evaluate_input('clef_direct',raw,resolver=load_resolver(asset_map))
    assert result['error_phase'] is None
    assert captured[0]['temporal_state']==TemporalState().model_dump(mode='json')
    text=json.dumps(captured)
    assert 'GT' not in text and 'lo_e1015' not in text and 'loitering' not in text
    assert all(e['timestamp_ms'] in (0,500,1000,1500) for e in captured[0]['evidence'])


async def test_mock_result_in_real_slot_becomes_error(mi,monkeypatch):
    class SyntheticBadProbe:
        name='clef_direct'
        async def evaluate(self,mi):
            return ModelAssessment(event_type='uncertain',event_confidence=0,risk_axes=None,
                needs_human_review=True,uncertainty_reason='synthetic test',evidence_refs=[],
                metadata=ModelMetadata(adapter=self.name,model='mock',is_mock=True))
    monkeypatch.setattr('app.eval.pipeline.get_adapter',lambda name,**kw:SyntheticBadProbe())
    result=await evaluate_input('clef_direct',mi)
    assert result['prediction']['metadata']['error_code']=='schema_or_contract'
    assert result['prediction']['metadata']['is_mock'] is False


def test_asset_root_requires_mapping(tmp_path):
    with pytest.raises(ValueError,match='requires'):
        load_resolver(asset_root=tmp_path)


async def test_multiview_scenario_cannot_cross_split(synthetic_dataset,tmp_path):
    raw,manifest,_,row=synthetic_dataset
    second=raw.model_copy(update={'sample_id':'s_000002'})
    (tmp_path/'second.json').write_text(second.model_dump_json(),encoding='utf-8')
    other={**row,'sample_id':'s_000002','split':'test','source_video_id':'source-0002','input_path':'second.json'}
    manifest.write_text(json.dumps(row)+'\n'+json.dumps(other),encoding='utf-8')
    with pytest.raises(ValueError,match='cross-split leakage: scenario'):
        await run_batch(manifest,'local_cv','validation',tmp_path/'leak')


@pytest.mark.parametrize('missing_field',['asset_map_sha256','preprocessing_version'])
async def test_frozen_test_requires_asset_and_preprocessor_pin(synthetic_dataset,tmp_path,missing_field):
    # Only synthetic metadata is exercised; no real held-out test set is opened.
    _,manifest,asset_map,row=synthetic_dataset
    row['split']='test'
    manifest.write_text(json.dumps(row),encoding='utf-8')
    config={'adapters':['clef_direct'],'timeout_sec':5,
        'asset_map_sha256':hashlib.sha256(asset_map.read_bytes()).hexdigest(),
        'preprocessing_version':'ffmpeg-fixed-grid-v1'}
    config.pop(missing_field)
    config_path=tmp_path/'config.json';config_path.write_text(json.dumps(config),encoding='utf-8')
    lock=tmp_path/'lock.json';lock.write_text(json.dumps({
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'run_config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest()}),encoding='utf-8')
    out=tmp_path/'guard'
    with pytest.raises(ValueError,match='asset map|preprocessing version'):
        await run_batch(manifest,'clef_direct','test',out,lock,config_path,True,asset_map=asset_map)
    assert not out.exists()


@pytest.mark.parametrize('mode',[
    'prepared_map_omitted','supplied_map_added','version_only_map_omitted','map_only_map_omitted',
])
async def test_frozen_mode_cannot_change_with_cli_asset_map(synthetic_dataset,tmp_path,mode):
    # Regression: omitting the CLI map previously skipped the frozen-mode guard.
    _,manifest,asset_map,row=synthetic_dataset
    row['split']='test'
    manifest.write_text(json.dumps(row),encoding='utf-8')
    config={'adapters':['clef_direct'],'timeout_sec':5}
    if mode in ('prepared_map_omitted','map_only_map_omitted'):
        config['asset_map_sha256']=hashlib.sha256(asset_map.read_bytes()).hexdigest()
    if mode in ('prepared_map_omitted','version_only_map_omitted'):
        config['preprocessing_version']='ffmpeg-fixed-grid-v1'
    config_path=tmp_path/'mode_config.json';config_path.write_text(json.dumps(config),encoding='utf-8')
    lock=tmp_path/'mode_lock.json';lock.write_text(json.dumps({
        'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'run_config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest()}),encoding='utf-8')
    out=tmp_path/'mode_guard'
    cli_map=asset_map if mode=='supplied_map_added' else None
    with pytest.raises(ValueError,match='asset map|preprocessing version'):
        await run_batch(manifest,'clef_direct','test',out,lock,config_path,True,asset_map=cli_map)
    assert not out.exists()


async def test_frozen_supplied_mode_accepts_absent_or_null_pins(synthetic_dataset,tmp_path):
    _,manifest,_,row=synthetic_dataset
    row['split']='test'
    manifest.write_text(json.dumps(row),encoding='utf-8')
    for explicit_null in (False,True):
        config={'adapters':['clef_direct'],'timeout_sec':5}
        if explicit_null:
            config.update(asset_map_sha256=None,preprocessing_version=None)
        config_path=tmp_path/'supplied_config.json';config_path.write_text(json.dumps(config),encoding='utf-8')
        lock=tmp_path/'supplied_lock.json';lock.write_text(json.dumps({
            'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'run_config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest()}),encoding='utf-8')
        out=tmp_path/f'supplied_{explicit_null}'
        metrics=await run_batch(manifest,'clef_direct','test',out,lock,config_path,True)
        assert metrics['n']==1 and metrics['error_rate']==1
        record=json.loads((out/'predictions.jsonl').read_text(encoding='utf-8'))
        assert record['input_stage']=='supplied' and record['preparation'] is None

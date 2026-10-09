import asyncio,json
from pathlib import Path
import pytest
from app.schemas.model import ModelInput,CameraContext,TimeWindow,EvidenceFrame
from app.models.media import MediaResolver
from app.models.adapters.cascade_v1 import CascadeV1Adapter
from app.models.adapters.assessment_mapper import decision_from_answers,axes_for,guards
from app.models.adapters.frozen_v1.visual_prompt_builder import VisualPromptBuilder

def answers(p=.001,cat='no_clear_incident',risk=0):
 return [{'name':'incident','type':'predicate','probability':p},{'name':'incident_category','type':'choice','choice':cat,'confidence':.99,'probabilities':None},*({'name':k,'type':'score','score':risk,'confidence':.9} for k in ('severity','imminence','exposure','persistence')),{'name':'human_review','type':'predicate','probability':.01}]
def mi():return ModelInput(sample_id='NEUTRAL_01',camera=CameraContext(id='CAM_02'),window=TimeWindow(start_ms=1000,end_ms=65000),evidence=[EvidenceFrame(frame_id=f'F{i+1:03d}',timestamp_ms=1000+i*1000,media_ref=f'FRAME_{i}') for i in range(64)])
def visual(cat='possible_fall_or_person_down'):
 return {'incident':{'probability':.98},'incident_category':{'value':cat,'confidence':.98},**{k:{'score':.7} for k in ('severity','imminence','exposure','persistence')},'human_review':{'probability':.1},'evidence':[{'frame_ref':'F002','description':'A person is lying on the ground.'}],'temporal_summary':'A person moves then lies down.','reason':'Possible fall requires operator review.','uncertainties':['Cause cannot be determined.']}
def run_adapter(mode='shadow',p1=None,p4=None,fail=None):
 called=[];original=mi();snapshot=original.model_dump()
 async def runner(stage,payload,**kwargs):
  called.append(stage)
  if stage==fail:raise ValueError('private path token should not leak')
  if stage=='cv':return {'state':{}}
  if stage=='p1':return {'status':'ok','answers':p1 if p1 is not None else answers()}
  return {'status':'ok','parsed':p4 or visual(),'usage':{'input_tokens':100,'output_tokens':30}}
 resolver=MediaResolver(Path('.'),{},assets={**{f'FRAME_{i}':b'image' for i in range(64)},'NEUTRAL_01:AI_PROFILE':json.dumps({'frame_numbers':list(range(64))}).encode()})
 adapter=CascadeV1Adapter(resolver,weights_path='trusted.pt',mode=mode,stage_runner=runner)
 result=asyncio.run(adapter.evaluate(original));assert original.model_dump()==snapshot
 return result,called

def test_shadow_always_calls_visual_with_guarded_normal():
 result,called=run_adapter();assert called==['cv','p1','p4'];assert result.event_type=='collapse';assert result.routing.frozen_guard_passed;assert result.evidence_descriptions['F002'].startswith('A person')
def test_frozen_suppression_has_no_fabricated_frame_citation():
 result,called=run_adapter('frozen_cascade_v1');assert called==['cv','p1'];assert result.event_type=='normal';assert result.evidence_refs==[];assert result.routing.evidence_scope=='window_observations';assert result.metadata.stage_trace[-1].status=='skipped'
def test_backend_guard_overrides_frozen_guard_high_axes():
 result,called=run_adapter('frozen_cascade_v1',p1=answers(risk=4));assert called[-1]=='p4';assert result.routing.frozen_guard_passed;assert not result.routing.backend_guard_passed
@pytest.mark.parametrize('stage',['cv','p4'])
def test_failures_are_unknown_review_and_sanitized(stage):
 result,called=run_adapter(fail=stage);assert result.event_type=='uncertain';assert result.risk_axes is None;assert result.needs_human_review;assert 'private' not in result.model_dump_json()
 if stage=='cv':assert called==['cv']
def test_p1_failure_continues_to_visual():
 result,called=run_adapter(fail='p1');assert called==['cv','p1','p4'];assert result.event_type=='collapse'
@pytest.mark.parametrize('cat',['no_clear_incident','possible_scene_or_boundary_entry'])
def test_no_clear_and_boundary_never_become_normal_or_intrusion(cat):
 result,called=run_adapter(p4=visual(cat));assert result.event_type=='uncertain';assert result.needs_human_review

def test_bad_citation_produces_review_failure():
 v=visual();v['evidence'][0]['frame_ref']='F999';result,_=run_adapter(p4=v);assert result.metadata.error_code=='p4_error'
def test_refused_axis_is_null_in_backend():
 a=answers();a[2]={'name':'severity','type':'refusal'};d=decision_from_answers(a);assert d['risk']['severity']==.5;assert axes_for(d)['severity'] is None;assert guards(d)==(False,False)
def test_invalid_numeric_answer_rejected():
 a=answers();a[0]['probability']=float('nan')
 with pytest.raises(ValueError):decision_from_answers(a)
def test_frozen_prompt_uses_actual_frame_ids():
 frames=[{'ref':'F001','camera':'CAM_01','timestamp_sec':0.123}];b=VisualPromptBuilder();assert b.frame_label(frames[0])=='F001 | CAM_01 | t=0.123s';assert b.output_schema('single',['CAM_01'],frames)['properties']['evidence']['items']['properties']['frame_ref']['enum']==['F001']

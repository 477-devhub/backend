"""Explicit semantic bridge from frozen Decisions values to backend assessment."""
import json,math
from pathlib import Path
from app.schemas.model import ModelAssessment,ModelMetadata,RiskAxes,RoutingAssessment
from .frozen_v1.decision_adapter import DecisionAdapter,index_answers
from .frozen_v1.common_adapter_v2 import CommonAdapterV2
from .frozen_v1.raw_visual_adapter import RawVisualAdapter
Q=json.loads((Path(__file__).parent/'frozen_v1/decisions_questions_v1.json').read_text(encoding='utf-8'))
AXES=('severity','imminence','exposure','persistence')
def finite01(v):
 if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('invalid_probability')
 return v

def decision_from_answers(answers):
 if not isinstance(answers,list):raise ValueError('invalid_answers')
 names=[a.get('name') for a in answers]
 if len(set(names))!=len(names):raise ValueError('duplicate_answers')
 indexed=index_answers(answers);levels={q['key']:len(q['levels']) for q in Q['per_assessment_questions'] if q['type']=='score'}
 for key in ('incident','human_review'):
  a=indexed.get(key)
  if a and a.get('type')!='refusal':
   if a.get('type')!='predicate':raise ValueError('answer_type')
   finite01(a['probability'])
 a=indexed.get('incident_category')
 if a and a.get('type')!='refusal':
  if a.get('type')!='choice' or a.get('choice') not in Q['adapter']['event_type_map']:raise ValueError('category')
  finite01(a['confidence'])
 for key in AXES:
  a=indexed.get(key)
  if a and a.get('type')!='refusal':
   if a.get('type')!='score':raise ValueError('answer_type')
   finite01(a['score']/(levels[key]-1))
 return DecisionAdapter(Q).assessment(indexed)

def guards(d):
 p=d.get('p_incident')
 frozen=(p is not None and p<=.01 and not d['refused_questions'] and not d['human_review_required'] and d['category']=='no_clear_incident' and d['confidence']>=.90)
 axes=axes_for(d)
 score=round(100*sum(w*axes[k] for k,w in zip(AXES,(.35,.30,.20,.15)))) if all(v is not None for v in axes.values()) else None
 return bool(frozen),bool(frozen and score is not None and score<20)

def axes_for(d):return {k:None if d['risk_raw'][k].get('refused') else d['risk'][k] for k in AXES}

def map_decision(d,*,mode,stage,trace,visual=None,p1_decision=None,latency_ms=None):
 raw_route=p1_decision or (d if stage=='p1' else None);frozen,backend=guards(raw_route) if raw_route else (False,False)
 normalized=CommonAdapterV2().reconcile(d)['normalized_decision']
 category=d['category'];event='uncertain'
 if normalized['is_incident'] and category=='possible_fall_or_person_down':event='collapse'
 if normalized['is_incident'] and category=='possible_physical_conflict':event='conflict'
 if stage=='p1':event='normal'
 axes=RiskAxes(**axes_for(d));review=bool(d['human_review_required'] or event=='uncertain' or not axes.is_complete or d['confidence']<.70)
 refs=[];descriptions={};opinion=None;uncertainty=None
 if visual:
  refs=list(dict.fromkeys(e['frame_ref'] for e in visual['evidence']))
  descriptions={e['frame_ref']:e['description'] for e in visual['evidence']}
  opinion=visual['temporal_summary']+' '+visual['reason'];uncertainty='; '.join(visual['uncertainties']) or None
 if event=='uncertain':uncertainty=uncertainty or '사건 여부 또는 경계의 의미를 확인할 수 없어 검토가 필요합니다.'
 costs=[s.estimated_cost_usd for s in trace if s.estimated_cost_usd is not None]
 return ModelAssessment(event_type=event,event_confidence=d['confidence'],risk_axes=axes,needs_human_review=review,uncertainty_reason=uncertainty,evidence_refs=refs,evidence_descriptions=descriptions,ai_opinion=opinion,metadata=ModelMetadata(adapter='cascade_v1',model='cheap-cv + gpt-6-luna + gpt-6.1-sol',prompt_version='frozen-v1',latency_ms=latency_ms,estimated_cost_usd=sum(costs) if costs else None,stage_trace=trace),routing=RoutingAssessment(mode=mode,selected_stage=stage,p_incident=raw_route['p_incident'] if raw_route else None,frozen_guard_passed=frozen,backend_guard_passed=backend,evidence_scope='window_observations' if stage=='p1' else 'cited_frames'))

def visual_decision(parsed,frames):
 answers,raw,vis=RawVisualAdapter(Q).convert('single',parsed,['CAM_01'],{f['ref']:f for f in frames})
 return decision_from_answers(answers),vis['single']

import asyncio
import pytest
from app.models.base import ModelAdapter
from app.models.execution import execute
from app.models.registry import get_adapter
from app.schemas.model import ModelAssessment, RiskAxes, ModelMetadata
from app.services.policy import decide
from app.services.incidents import make_incident

class Adapter(ModelAdapter):
    name='unit'
    def __init__(self,behavior):self.behavior=behavior
    async def evaluate(self,mi):
        if self.behavior=='timeout':await asyncio.sleep(.1)
        if self.behavior=='exception':raise RuntimeError('secret_key=DO_NOT_EXPOSE')
        if self.behavior=='schema':return {'event_type':'invented'}
        if self.behavior=='mutate':mi.temporal_state.events.append({'x':1})
        refs=['not_a_frame'] if self.behavior=='bad_ref' else [mi.evidence[0].frame_id]
        if self.behavior=='no_ref':refs=[]
        return ModelAssessment(event_type='collapse',event_confidence=.60,risk_axes=RiskAxes(severity=1,imminence=1,exposure=1,persistence=1),
            evidence_refs=refs,metadata=ModelMetadata(adapter=self.name,model='test'))

@pytest.mark.parametrize('behavior,code',[('timeout','timeout'),('exception','provider_error'),('schema','schema_or_contract'),
 ('bad_ref','schema_or_contract'),('mutate','schema_or_contract'),('no_ref','schema_or_contract')])
async def test_failures_review(mi,behavior,code):
    before=mi.model_dump();r=await execute(Adapter(behavior),mi,.01)
    assert r.metadata.error_code==code and r.risk_axes is None and r.needs_human_review
    assert decide(r).disposition=='review' and mi.model_dump()==before
    assert 'DO_NOT_EXPOSE' not in r.model_dump_json()
    incident=make_incident(mi,r)
    assert incident.level=='UNKNOWN' and incident.risk is None and incident.needs_human_review

async def test_confidence_not_risk(mi):
    r=await execute(Adapter('ok'),mi)
    d=decide(r);assert d.risk==100 and d.disposition=='review'

@pytest.mark.parametrize('name',['mock_local_cv','mock_clef','mock_vlm'])
async def test_mock_explicit(mi,name):
    r=await execute(get_adapter(name),mi)
    assert r.metadata.is_mock and r.metadata.adapter==name and decide(r).disposition=='review'
@pytest.mark.parametrize('name',['local_cv','clef_direct','general_vlm'])
async def test_real_not_mock(mi,name):
    r=await execute(get_adapter(name),mi)
    assert r.metadata.error_code=='provider_error' and not r.metadata.is_mock

def test_suppression_only_strong_normal():
    a=ModelAssessment(event_type='normal',event_confidence=.99,risk_axes=RiskAxes(severity=0,imminence=0,exposure=0,persistence=0),
        evidence_refs=['f'],metadata=ModelMetadata(adapter='x',model='x'))
    assert decide(a).disposition=='suppressed'
    assert decide(a.model_copy(update={'event_confidence':.8})).disposition=='incident'

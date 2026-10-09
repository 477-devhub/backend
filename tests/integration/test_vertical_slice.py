from app.models.execution import execute
from app.models.registry import get_adapter
from app.services.incidents import make_incident

async def test_fixture_to_api(mi,client):
    result=await execute(get_adapter('mock_local_cv'),mi)
    incident=make_incident(mi,result)
    client.app.state.store.put(incident)
    response=client.get('/api/incidents/'+incident.id)
    assert response.status_code==200 and response.json()['needs_human_review']
    assert response.json()['evidence'][0]['frame_id']=='f001'

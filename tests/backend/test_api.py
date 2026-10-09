from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings

def post(client,path,body,key):
    return client.post(path,json=body,headers={'Idempotency-Key':key})

def test_scenarios(client):
    for step,count in [(1,0),(2,0),(3,1),(4,2),(5,3),(6,3)]:
        assert post(client,'/api/demo/step',{'step':step},f'step-{step}').status_code==200
        assert client.get('/api/status').json()['active_count']==count
    x=client.get('/api/incidents/INC-032').json();assert x['risk']==89 and x['rank']==1
    assert x['next_incident_id']=='INC-033'
    assert client.get('/api/cameras').json()[2]['status']=='review'
    assert client.get('/api/pipeline/stats').json()['needs_review']==1

def test_ack_idempotency(client):
    post(client,'/api/demo/step',{'step':3},'step')
    url='/api/incidents/INC-032/ack'
    a=post(client,url,{'action':'verify'},'ack');b=post(client,url,{'action':'verify'},'ack')
    assert a.json()==b.json() and a.status_code==200
    assert client.get('/api/status').json()['active_count']==0
    assert client.get('/api/incidents/INC-032').json()['status']=='acked'
    assert len(client.app.state.store.audit)==1
    assert post(client,url,{'action':'dismiss'},'ack').status_code==409
    assert client.post(url,json={'action':'verify'}).status_code==400
    assert post(client,url,{'action':'nonsense'},'bad').status_code==422

def test_actions_and_terminal_state(client):
    post(client,'/api/demo/step',{'step':5},'step')
    url='/api/incidents/INC-034/ack'
    assert post(client,url,{'action':'handover'},'invalid').status_code==409
    assert post(client,url,{'action':'handover','to_operator':'operator2'},'handover').json()['incident']['assigned_operator']=='operator2'
    assert post(client,url,{'action':'request_dispatch'},'dispatch').json()['incident']['dispatch_requested']
    assert post(client,url,{'action':'confirm_review'},'confirm').json()['incident']['needs_human_review'] is False
    assert post(client,url,{'action':'needs_review'},'review').json()['incident']['needs_human_review']
    assert post(client,url,{'action':'dismiss'},'dismiss').status_code==200
    assert post(client,url,{'action':'verify'},'terminal').status_code==409

def test_restore(client):
    post(client,'/api/demo/step',{'step':2},'step')
    assert client.get('/api/suppressed').json()[0]['id']=='SUP-001'
    for key in ['restore','restore','restore2']:
        assert post(client,'/api/suppressed/SUP-001/restore',{},key).status_code==200
    assert client.get('/api/status').json()['active_count']==1
    x=client.get('/api/incidents/RESTORED-SUP-001').json()
    assert x['risk'] is None and x['level']=='UNKNOWN' and x['needs_human_review']
    assert len(client.app.state.store.incidents)==1

def test_unknown_and_media(client):
    assert client.get('/api/incidents/unknown/clip').status_code==404
    assert client.get('/stream/unknown').status_code==404
    assert client.get('/stream/CAM_01').status_code==503
    post(client,'/api/demo/step',{'step':3},'step')
    x=client.get('/api/incidents/INC-032/clip').json()
    assert not x['available'] and x['clip_url']=='/stream/CAM_08' and isinstance(x['bbox_track'],list)
    (client.app.state.settings.media_root/'CAM_08.mp4').write_bytes(b'unit-media')
    assert client.get('/stream/CAM_08').content==b'unit-media'

def test_demo_disabled(tmp_path):
    with TestClient(create_app(Settings(mode='development',media_root=tmp_path))) as c:
        assert post(c,'/api/demo/step',{'step':3},'step').status_code==404

def test_ws_push_and_reconnect(client):
    with client.websocket_connect('/ws/attention') as ws:
        initial=ws.receive_json();assert initial['active_count']==0
        post(client,'/api/demo/step',{'step':5},'step')
        update=ws.receive_json();assert update['revision']>initial['revision'] and update['active_count']==3
        assert update['level_counts']=={'critical':1,'high':1,'medium':0,'low':0,'review':1,'unknown':0}
        assert update['cameras'][2]['status']=='review'
        post(client,'/api/incidents/INC-032/ack',{'action':'verify'},'ack')
        assert ws.receive_json()['active_count']==2
    with client.websocket_connect('/ws/attention') as ws:
        assert ws.receive_json()['active_count']==2
    assert not client.app.state.hub.clients

def test_same_key_across_routes(client):
    post(client,'/api/demo/step',{'step':3},'same')
    assert post(client,'/api/incidents/INC-032/ack',{'action':'verify'},'same').status_code==409

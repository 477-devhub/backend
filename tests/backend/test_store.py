from datetime import datetime,timezone
from app.repositories.memory import MemoryStore
from app.schemas.incident import Incident
from app.services.events import SnapshotHub

def test_unknown_visible_and_ordered():
    s=MemoryStore();s.demo(3)
    s.put(Incident(id='unknown',sample_id='unknown',type='uncertain',title='unknown',primary_cam='CAM_01',
        risk=None,level='UNKNOWN',risk_axes=None,confidence=0,needs_human_review=True,created_at=datetime.now(timezone.utc)))
    assert [i.id for i in s.ordered()]==['unknown','INC-032']

def test_hub_coalesces():
    hub=SnapshotHub();q=hub.subscribe()
    for rev in range(100):hub.publish({'revision':rev})
    assert q.qsize()==1 and q.get_nowait()['revision']==99

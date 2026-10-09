import asyncio
class SnapshotHub:
    """One pending snapshot/client: slow consumers converge without unbounded queues."""
    def __init__(self):
        self.clients: set[asyncio.Queue] = set()
    def subscribe(self):
        q = asyncio.Queue(maxsize=1); self.clients.add(q); return q
    def unsubscribe(self, q):
        self.clients.discard(q)
    def publish(self, snapshot):
        for q in tuple(self.clients):
            if q.full(): q.get_nowait()
            q.put_nowait(snapshot)

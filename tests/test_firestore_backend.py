from types import SimpleNamespace
from datetime import datetime, timezone
from app.firestore_database import FirestoreQuery
from app.models import Job, Application

class FakeSnapshot:
    def __init__(self, data): self.data=data
    def to_dict(self): return self.data
class FakeCollection:
    def __init__(self, rows): self.rows=rows
    def stream(self): return [FakeSnapshot(x) for x in self.rows]
class FakeClient:
    def __init__(self, data): self.data=data
    def collection(self, name): return FakeCollection(self.data.get(name, []))

class FakeSession:
    def __init__(self, data):
        self.client=FakeClient(data); self.pending=[]; self._tracked=[]; self._snapshots={}; self._models=[]


def test_firestore_query_filters_and_orders_job_documents():
    session=FakeSession({'opportunities':[
        {'id':1,'title':'Product Manager','company':'A','score':80,'active':True,'discovered_at':datetime.now(timezone.utc)},
        {'id':2,'title':'Designer','company':'B','score':50,'active':True,'discovered_at':datetime.now(timezone.utc)},
        {'id':3,'title':'Growth Product Lead','company':'C','score':90,'active':False,'discovered_at':datetime.now(timezone.utc)},
    ]})
    rows=FirestoreQuery(session,Job).filter(Job.active.is_(True)).order_by(Job.score.desc()).all()
    assert [r.id for r in rows] == [1,2]


def test_firestore_relationship_has_predicate_checks_application_collection():
    session=FakeSession({'applications':[{'id':7,'job_id':1,'status':'draft'}]})
    query=FirestoreQuery(session,Job)
    job=Job(); job.id=1
    assert query._matches(job, Job.application.has()) is True
    job.id=2
    assert query._matches(job, Job.application.has()) is False


def test_firestore_collection_names_are_domain_oriented():
    from app.firestore_database import _collection
    assert _collection(Job)=='opportunities'
    assert _collection(Application)=='applications'


def test_firestore_query_reuses_session_collection_snapshot():
    class CachedSession(FakeSession):
        def __init__(self, data):
            super().__init__(data)
            self.reads = {}
            self.cache = {}
        def _documents(self, model):
            from app.firestore_database import _collection
            name = _collection(model)
            if name not in self.cache:
                self.reads[name] = self.reads.get(name, 0) + 1
                self.cache[name] = [x.to_dict() for x in self.client.collection(name).stream()]
            return self.cache[name]

    session = CachedSession({'opportunities': [
        {'id': 1, 'title': 'Product Manager', 'company': 'A', 'score': 80, 'active': True}
    ]})
    FirestoreQuery(session, Job).filter_by(active=True).all()
    FirestoreQuery(session, Job).filter_by(active=True).count()
    assert session.reads == {'opportunities': 1, 'applications': 1}

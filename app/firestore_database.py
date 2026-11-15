"""Firestore-backed compatibility session for the application's existing query surface.

Firestore is the source of truth in this mode. Queries are evaluated against documents
loaded from a collection; this deliberately favours correctness/compatibility over scale.
High-volume deployments should progressively replace scans with indexed repository queries.
"""
from __future__ import annotations
import os, threading
from datetime import datetime, date
from typing import Any
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList, UnaryExpression, BindParameter
from sqlalchemy.sql import operators

_lock = threading.RLock()
_client = None

def _firestore():
    global _client
    if _client is None:
        import firebase_admin
        from firebase_admin import credentials, firestore
        if not firebase_admin._apps:
            project = os.getenv('FIREBASE_PROJECT_ID') or None
            cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if cred_path:
                firebase_admin.initialize_app(credentials.Certificate(cred_path), {'projectId': project} if project else {})
            else:
                firebase_admin.initialize_app(options={'projectId': project} if project else None)
        _client = firestore.client()
    return _client

def _collection(model):
    explicit = getattr(model, '__firestore_collection__', None)
    if explicit: return explicit
    return {'Job':'opportunities','CompanyWatch':'company_watches','DiscoveryRun':'discovery_runs','CandidateDocument':'documents','Application':'applications','GmailConnection':'gmail_connections','EmailSendRecord':'email_send_records'}.get(model.__name__, model.__tablename__)

def _apply_defaults(obj):
    for col in _columns(type(obj)):
        if getattr(obj, col.name, None) is None and col.default is not None:
            try:
                value=col.default.arg
                setattr(obj,col.name,value() if callable(value) else value)
            except Exception: pass
    return obj

def _columns(model):
    return list(model.__table__.columns)

def _serialise(obj):
    out = {}
    for col in _columns(type(obj)):
        value = getattr(obj, col.name, None)
        if isinstance(value, (datetime, date)):
            value = value
        out[col.name] = value
    return out

def _restore(model, data):
    obj = _apply_defaults(model())
    for col in _columns(model):
        if col.name in data:
            setattr(obj, col.name, data[col.name])
    return obj

class FirestoreSession:
    def __init__(self):
        self.client = _firestore(); self.pending=[]; self.deleted=[]; self._tracked=[]; self._snapshots={}; self._models=[]
        # Reuse collection snapshots within one request/session. The old adapter
        # streamed the same Firestore collections repeatedly for every query.
        self._collection_cache = {}
    def _documents(self, model):
        name = _collection(model)
        if name not in self._collection_cache:
            self._collection_cache[name] = [snap.to_dict() or {} for snap in self.client.collection(name).stream()]
        return self._collection_cache[name]
    def query(self, model):
        if model not in self._models: self._models.append(model)
        return FirestoreQuery(self, model)
    def add(self, obj):
        _apply_defaults(obj)
        self.pending.append(obj)
    def delete(self, obj): self.deleted.append(obj)
    def commit(self):
        with _lock:
            writes=[]
            for obj in self.pending:
                model=type(obj); coll=self.client.collection(_collection(model))
                ident=getattr(obj,'id',None)
                if not ident:
                    counter=self.client.collection('_system').document(_collection(model))
                    from google.cloud import firestore as gcf
                    @gcf.transactional
                    def allocate(transaction, ref):
                        snap=ref.get(transaction=transaction); current=(snap.to_dict() or {}).get('next_id',0)+1
                        transaction.set(ref, {'next_id':current}); return current
                    ident=allocate(self.client.transaction(), counter); obj.id=ident
                writes.append(('set',coll.document(str(ident)),_serialise(obj)))
            for obj in self.deleted:
                model=type(obj); ident=getattr(obj,'id',None)
                if ident is not None: writes.append(('delete',self.client.collection(_collection(model)).document(str(ident)),None))
            for obj in self._tracked:
                if getattr(obj,'id',None) is not None:
                    current=_serialise(obj); before=self._snapshots.get((type(obj),obj.id))
                    if before is not None and current != before:
                        writes.append(('set',self.client.collection(_collection(type(obj))).document(str(obj.id)),current))
            # Firestore write batches are limited to 500 operations; keep headroom.
            for offset in range(0,len(writes),400):
                batch=self.client.batch()
                for action,ref,data in writes[offset:offset+400]:
                    if action=='set': batch.set(ref,data)
                    else: batch.delete(ref)
                batch.commit()
            self.pending.clear(); self.deleted.clear(); self._tracked.clear(); self._snapshots.clear(); self._collection_cache.clear()
    def refresh(self,obj):
        snap=self.client.collection(_collection(type(obj))).document(str(obj.id)).get()
        if snap.exists:
            for k,v in (snap.to_dict() or {}).items(): setattr(obj,k,v)
    def rollback(self): self.pending.clear(); self.deleted.clear(); self._tracked.clear(); self._snapshots.clear(); self._collection_cache.clear()
    def close(self): pass

class FirestoreQuery:
    def __init__(self, session, model): self.session=session; self.model=model; self.predicates=[]; self.sorts=[]; self._limit=None
    def _documents(self, model):
        if hasattr(self.session, '_documents'):
            return self.session._documents(model)
        return [snap.to_dict() or {} for snap in self.session.client.collection(_collection(model)).stream()]
    def filter_by(self, **kwargs):
        self.predicates.extend([('eq',k,v) for k,v in kwargs.items()]); return self
    def filter(self,*criteria): self.predicates.extend(criteria); return self
    def order_by(self,*orders): self.sorts.extend(orders); return self
    def limit(self,n): self._limit=n; return self
    def _all(self, with_relationships=True):
        rows=[_restore(self.model,data) for data in self._documents(self.model)]
        rows.extend(x for x in self.session.pending if isinstance(x,self.model))
        # Rehydrate the two application/job relationships used by the UI and workflow.
        if with_relationships and self.model.__name__ == 'Job':
            from app.models import Application
            apps=[_restore(Application,data) for data in self._documents(Application)]
            by_job={a.job_id:a for a in apps}
            for row in rows: row.application=by_job.get(row.id)
        elif with_relationships and self.model.__name__ == 'Application':
            from app.models import Job
            jobs=[_restore(Job,data) for data in self._documents(Job)]
            by_id={j.id:j for j in jobs}
            for row in rows: row.job=by_id.get(row.job_id)
        rows=[x for x in rows if all(self._matches(x,p) for p in self.predicates)]
        for order in reversed(self.sorts):
            desc=isinstance(order,UnaryExpression) and order.modifier is operators.desc_op
            expr=order.element if isinstance(order,UnaryExpression) else order
            key=getattr(expr,'key',None)
            if key: rows.sort(key=lambda x:(getattr(x,key,None) is None,getattr(x,key,None)),reverse=desc)
        if self._limit is not None: rows=rows[:self._limit]
        for row in rows:
            if row not in self.session._tracked:
                self.session._tracked.append(row)
                self.session._snapshots[(type(row),getattr(row,'id',None))]=_serialise(row)
        return rows
    def _value(self,obj,expr):
        if isinstance(expr,BindParameter): return expr.value
        key=getattr(expr,'key',None)
        if key and hasattr(obj,key): return getattr(obj,key)
        return expr
    def _matches(self,obj,p):
        if p.__class__.__name__ == 'Grouping': return self._matches(obj,p.element)
        if p.__class__.__name__ == 'Exists':
            # SQLAlchemy relationship .has() used by the stale-job sweep.
            from app.models import Application
            apps=[_restore(Application,data) for data in self._documents(Application)]
            return any(a.job_id == getattr(obj,'id',None) for a in apps)
        if isinstance(p,tuple): return getattr(obj,p[1],None)==p[2]
        if isinstance(p,BooleanClauseList):
            vals=[self._matches(obj,c) for c in p.clauses]
            return all(vals) if p.operator is operators.and_ else any(vals)
        if isinstance(p,UnaryExpression):
            if p.operator is operators.inv:
                return not self._matches(obj,p.element)
            return self._value(obj,p.element) is None
        if isinstance(p,BinaryExpression):
            # Relationship EXISTS predicates are handled by checking related documents.
            if getattr(p.left, 'key', None) == 'application' and getattr(p.operator, '__name__', '') == 'has_op':
                from app.models import Application
                apps=[_restore(Application,data) for data in self._documents(Application)]
                return any(a.job_id == getattr(obj,'id',None) for a in apps)
            left=self._value(obj,p.left); right=self._value(obj,p.right); op=p.operator
            try:
                if op is operators.eq: return left==right
                if op is operators.ne: return left!=right
                if op is operators.lt: return left is not None and left<right
                if op is operators.le: return left is not None and left<=right
                if op is operators.gt: return left is not None and left>right
                if op is operators.ge: return left is not None and left>=right
                if op is operators.in_op: return left in right
                if op is operators.not_in_op: return left not in right
                if op is operators.is_: return left is right or left==right
                if op is operators.is_not: return left is not right and left!=right
                if op is operators.ilike_op:
                    import re
                    pattern=str(right).replace('%','.*').replace('_','.')
                    return re.search(pattern,str(left or ''),re.I) is not None
                if op is operators.like_op:
                    import re
                    pattern=str(right).replace('%','.*').replace('_','.')
                    return re.search(pattern,str(left or '')) is not None
            except (TypeError,ValueError): return False
        # Relationship .has() is only used for Job.application; resolve via application docs.
        if hasattr(p,'prop') and getattr(p,'prop',None) is not None:
            return True
        return True
    def all(self): return self._all()
    def first(self):
        rows=self._all(); return rows[0] if rows else None
    def count(self): return len(self._all(with_relationships=False))
    def update(self,values,synchronize_session=False):
        rows=self._all()
        for row in rows:
            for key,val in values.items(): setattr(row,getattr(key,"key",key),val)
            if row not in self.session._tracked: self.session._tracked.append(row)
        return len(rows)

def get_workspace_document(collection: str, document_id: str, default):
    snap=_firestore().collection(collection).document(document_id).get()
    return snap.to_dict() if snap.exists else default

def set_workspace_document(collection: str, document_id: str, value):
    _firestore().collection(collection).document(document_id).set(value)
    return value

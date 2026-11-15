"""One-way migration from SQLite/PostgreSQL to Firestore; preserves numeric IDs.
Run with DATABASE_URL pointing at the source relational database and Firebase env configured.
"""
import os, json
from datetime import date, datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.models import Job, Application, CompanyWatch, DiscoveryRun, CandidateDocument, GmailConnection, EmailSendRecord
from app.firestore_database import _firestore, _collection, _serialise

MODELS=[Job,Application,CompanyWatch,DiscoveryRun,CandidateDocument,GmailConnection,EmailSendRecord]

def clean(value):
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,dict): return {k:clean(v) for k,v in value.items()}
    if isinstance(value,list): return [clean(v) for v in value]
    return value

def main():
    url=os.environ.get('SOURCE_DATABASE_URL') or os.environ.get('DATABASE_URL')
    if not url: raise SystemExit('Set SOURCE_DATABASE_URL or DATABASE_URL to the source relational database.')
    if not os.getenv('FIREBASE_PROJECT_ID'): raise SystemExit('FIREBASE_PROJECT_ID is required.')
    engine=create_engine(url,pool_pre_ping=True); client=_firestore(); total=0
    for model in MODELS:
        with Session(engine) as session:
            rows=session.scalars(select(model)).all()
            coll=client.collection(_collection(model))
            for offset in range(0,len(rows),400):
                batch=client.batch()
                for row in rows[offset:offset+400]:
                    data=clean(_serialise(row)); batch.set(coll.document(str(row.id)),data); total+=1
                batch.commit()
            # Preserve the next ID sequence to avoid collisions after migration.
            if rows:
                client.collection('_system').document(_collection(model)).set({'next_id':max(r.id for r in rows)})
        print(f'{model.__name__}: migrated {len(rows)} records')
    print(f'Complete. Migrated {total} records. Source database was not modified.')

if __name__=='__main__': main()

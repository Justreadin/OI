"""Backend selection: SQLite for development, Firestore for production, PostgreSQL optional."""
from app.config import settings

backend = (settings.database_backend or ("firestore" if settings.app_env == "production" else "sqlite")).lower()
if backend == "firestore":
    from app.firestore_database import FirestoreSession
    SessionLocal = FirestoreSession
    engine = None
    Base = None
    def get_db():
        db = SessionLocal()
        try: yield db
        finally: db.close()
elif backend in {"sqlite", "postgresql"}:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, DeclarativeBase
    args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=args, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    class Base(DeclarativeBase): pass
    def get_db():
        db=SessionLocal()
        try: yield db
        finally: db.close()
else:
    raise RuntimeError(f"Unsupported DATABASE_BACKEND: {backend}")

from datetime import datetime,timezone
from sqlalchemy import String,Text,DateTime,Float,Boolean,ForeignKey,Index
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.database import Base
def now(): return datetime.now(timezone.utc)
class Job(Base):
    __tablename__="jobs"
    __table_args__ = (
        Index("ix_jobs_active_score_discovered", "active", "score", "discovered_at"),
        Index("ix_jobs_active_track_type", "active", "track", "opportunity_type"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    source:Mapped[str]=mapped_column(String(80),default="")
    source_id:Mapped[str]=mapped_column(String(300),default="")
    company:Mapped[str]=mapped_column(String(300),default="Unknown")
    title:Mapped[str]=mapped_column(String(500),index=True)
    location:Mapped[str]=mapped_column(String(500),default="Not specified")
    description:Mapped[str]=mapped_column(Text,default="")
    url:Mapped[str]=mapped_column(String(2000),unique=True)
    published_at:Mapped[str]=mapped_column(String(100),default="")
    discovered_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    last_seen_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
    eligibility:Mapped[str]=mapped_column(String(30),default="unknown")
    score:Mapped[float]=mapped_column(Float,default=0)
    track:Mapped[str]=mapped_column(String(100),default="")
    opportunity_type:Mapped[str]=mapped_column(String(60),default="Other",index=True)
    reasons:Mapped[str]=mapped_column(Text,default="")
    eligibility_evidence:Mapped[str]=mapped_column(Text,default="[]")
    qualification:Mapped[str]=mapped_column(String(30),default="review")
    application_method:Mapped[str]=mapped_column(String(40),default="unknown")
    application_method_confidence:Mapped[str]=mapped_column(String(20),default="low")
    application_email:Mapped[str]=mapped_column(String(320),default="")
    application_method_evidence:Mapped[str]=mapped_column(Text,default="")
    application:Mapped["Application"]=relationship(back_populates="job",uselist=False)
class CompanyWatch(Base):
    __tablename__="company_watches"
    id:Mapped[int]=mapped_column(primary_key=True)
    name:Mapped[str]=mapped_column(String(300),default="")
    career_url:Mapped[str]=mapped_column(String(2000),unique=True)
    enabled:Mapped[bool]=mapped_column(Boolean,default=True)
    last_scanned_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    last_error:Mapped[str]=mapped_column(Text,default="")
class DiscoveryRun(Base):
    __tablename__="discovery_runs"
    id:Mapped[int]=mapped_column(primary_key=True)
    started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    status:Mapped[str]=mapped_column(String(30),default="running")
    source_results:Mapped[str]=mapped_column(Text,default="{}")
    total_new:Mapped[int]=mapped_column(default=0)
    total_indexed:Mapped[int]=mapped_column(default=0)
    error:Mapped[str]=mapped_column(Text,default="")
class CandidateDocument(Base):
    __tablename__="candidate_documents"
    id:Mapped[int]=mapped_column(primary_key=True)
    category:Mapped[str]=mapped_column(String(60),default="supporting")
    original_name:Mapped[str]=mapped_column(String(500),default="")
    stored_path:Mapped[str]=mapped_column(String(2000),default="")
    mime_type:Mapped[str]=mapped_column(String(160),default="")
    size_bytes:Mapped[int]=mapped_column(default=0)
    extracted_text:Mapped[str]=mapped_column(Text,default="")
    uploaded_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    active:Mapped[bool]=mapped_column(Boolean,default=True)
class Application(Base):
    __tablename__="applications"
    __table_args__ = (
        Index("ix_applications_status_updated", "status", "updated_at"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    job_id:Mapped[int]=mapped_column(ForeignKey("jobs.id"),unique=True)
    status:Mapped[str]=mapped_column(String(40),default="draft")
    cv_text:Mapped[str]=mapped_column(Text,default="")
    cover_letter:Mapped[str]=mapped_column(Text,default="")
    match_report:Mapped[str]=mapped_column(Text,default="")
    approved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    submitted_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    confirmation:Mapped[str]=mapped_column(Text,default="")
    workflow_json:Mapped[str]=mapped_column(Text,default="{}")
    audit_json:Mapped[str]=mapped_column(Text,default="{}")
    missing_info_json:Mapped[str]=mapped_column(Text,default="[]")
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)
    job:Mapped[Job]=relationship(back_populates="application")


class GmailConnection(Base):
    __tablename__="gmail_connections"
    id:Mapped[int]=mapped_column(primary_key=True)
    email:Mapped[str]=mapped_column(String(320),default="")
    encrypted_token:Mapped[str]=mapped_column(Text,default="")
    connected_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,onupdate=now)

class EmailSendRecord(Base):
    __tablename__="email_send_records"
    id:Mapped[int]=mapped_column(primary_key=True)
    application_id:Mapped[int]=mapped_column(ForeignKey("applications.id"),index=True)
    recipient:Mapped[str]=mapped_column(String(320),default="")
    subject:Mapped[str]=mapped_column(String(500),default="")
    gmail_message_id:Mapped[str]=mapped_column(String(300),default="")
    status:Mapped[str]=mapped_column(String(40),default="sent")
    sent_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    inbox_copy:Mapped[bool]=mapped_column(Boolean,default=True)

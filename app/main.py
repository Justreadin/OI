from datetime import datetime, timezone
import asyncio
import base64, csv, json, mimetypes, os, secrets, shutil, tempfile, uuid, logging, time
from email.message import EmailMessage
from io import BytesIO, StringIO
from urllib.parse import urlparse
from pydantic import BaseModel, Field
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect, text as sql_text

from app.config import settings
from app.database import Base, engine, get_db, SessionLocal
from app.models import Job, Application, CompanyWatch, DiscoveryRun, CandidateDocument, GmailConnection, EmailSendRecord
from app.sources import discover, _assert_public_https
from app.generator import create_draft, create_screening_answers
from app.profile import PROFILE
from app.assets import ASSETS, select_assets
from app.browser_assistant import inspect_form, fill_form, run
from app.orchestration import infer_stage, evidence_audit, dump

# Relational schema creation/migrations are used only by SQLite and PostgreSQL.
if engine is not None:
    Base.metadata.create_all(bind=engine)
    for table, additions in {
        "applications": {"workflow_json": "TEXT DEFAULT '{}'", "audit_json": "TEXT DEFAULT '{}'", "missing_info_json": "TEXT DEFAULT '[]'", "updated_at": "TIMESTAMP"},
        "company_watches": {"last_scanned_at": "TIMESTAMP", "last_error": "TEXT DEFAULT ''"},
        "jobs": {"last_seen_at": "TIMESTAMP", "eligibility_evidence": "TEXT DEFAULT '[]'", "qualification": "VARCHAR(30) DEFAULT 'review'", "application_method": "VARCHAR(40) DEFAULT 'unknown'", "application_method_confidence": "VARCHAR(20) DEFAULT 'low'", "application_email": "VARCHAR(320) DEFAULT ''", "application_method_evidence": "TEXT DEFAULT ''", "opportunity_type": "VARCHAR(60) DEFAULT 'Other'"}
    }.items():
        existing = {c["name"] for c in sa_inspect(engine).get_columns(table)}
        for column, ddl in additions.items():
            if column not in existing:
                with engine.begin() as conn:
                    conn.execute(sql_text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                    if table == "jobs" and column == "last_seen_at":
                        conn.execute(sql_text("UPDATE jobs SET last_seen_at=discovered_at WHERE last_seen_at IS NULL"))

_seed = SessionLocal()
try:
    for url in settings.csv(settings.company_seed_urls):
        if not _seed.query(CompanyWatch).filter_by(career_url=url).first():
            _seed.add(CompanyWatch(name=url.split("//")[-1].split("/")[0], career_url=url))
    _seed.commit()
finally:
    _seed.close()

app = FastAPI(title="Opportunity Intelligence", version="13.4.5")
_scan_task = None
_scan_lock = asyncio.Lock()

async def _run_discovery_background():
    """Run discovery with its own DB session, never the request session."""
    db = SessionLocal()
    try:
        await discover(db, force=True)
    except Exception:
        db.rollback()
        logging.getLogger("oi.discovery").exception("Background discovery failed")
        try:
            failed_db = SessionLocal()
            latest = failed_db.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).first()
            if latest and latest.status == "running":
                latest.status = "failed"
                latest.finished_at = datetime.now(timezone.utc)
                failed_db.commit()
        except Exception:
            logging.getLogger("oi.discovery").exception("Could not persist failed scan status")
        finally:
            try:
                failed_db.close()
            except Exception:
                pass
    finally:
        db.close()

_perf_log = logging.getLogger("oi.performance")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = lambda value: json.loads(value or "[]")

@app.middleware("http")
async def request_performance_metrics(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        return response
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms >= 750:
            _perf_log.warning(
                "slow_request method=%s path=%s duration_ms=%.1f",
                request.method, request.url.path, elapsed_ms
            )


@app.middleware("http")
async def same_origin_state_change_guard(request: Request, call_next):
    # Lightweight protection against cross-site HTML form submissions.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.netloc.lower() != request.url.netloc.lower() or parsed.scheme not in {"http", "https"}:
                return JSONResponse({"detail": "Cross-origin state changes are not permitted."}, status_code=403)
    return await call_next(request)

@app.middleware("http")
async def optional_private_workspace_auth(request, call_next):
    if settings.enable_basic_auth and not settings.app_password:
        if request.url.path != "/health":
            return JSONResponse({"detail":"Basic authentication is enabled but APP_PASSWORD is not configured."},status_code=503)
    if settings.enable_basic_auth and settings.app_password:
        if request.url.path != "/health" and not request.url.path.startswith("/static/"):
            auth = request.headers.get("authorization", "")
            valid = False
            if auth.startswith("Basic "):
                try:
                    raw = base64.b64decode(auth.split(" ", 1)[1]).decode()
                    _, password = raw.split(":", 1)
                    valid = secrets.compare_digest(password, settings.app_password)
                except Exception:
                    valid = False
            if not valid:
                return JSONResponse({"detail": "Authentication required"}, status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Opportunity Intelligence"'})
    return await call_next(request)

class FormInspectionRequest(BaseModel):
    url: str
class FormFillRequest(BaseModel):
    url: str
    field_values: list[dict] = Field(default_factory=list)
    advance_button_text: str | None = None
    final_submit_button_text: str | None = None
    authorization_phrase: str | None = None
class ProgressRequest(BaseModel):
    progress: dict = Field(default_factory=dict)
class ScreeningRequest(BaseModel):
    questions: list[str] = Field(default_factory=list)

def _application_or_404(aid: int, db: Session):
    a = db.get(Application, aid)
    if not a:
        raise HTTPException(404, "Application not found")
    if a.status not in ("draft", "approved", "submitted", "submission_pending_verification"):
        raise HTTPException(409, "Application package unavailable")
    return a

def _remaining_application_fields(a: Application, db: Session, incoming_values=None):
    wf = json.loads(a.workflow_json or "{}")
    progress = wf.get("progress", {})
    incoming = incoming_values or []
    remaining = []
    all_fields=[]
    for stage in wf.get("stages", []): all_fields.extend(stage.get("fields", []))
    all_fields.extend(wf.get("fields", []))
    seen=set()
    for field in all_fields:
        key=field.get("selector_key","")
        if key in seen: continue
        seen.add(key)
        if not field.get("required") or field.get("disabled"):
            continue
        key = field.get("selector_key", "")
        value = progress.get(key, "")
        for item in incoming:
            if item.get("selector_key") == key:
                value = item.get("value", value)
        if str(value or "").strip():
            continue
        if (field.get("type") or "").lower() == "file":
            label = " ".join([field.get("label", ""), field.get("name", ""), field.get("id", "")]).lower()
            if ("resume" in label or "curriculum" in label or label.startswith("cv") or " cv " in f" {label} ") and a.cv_text.strip():
                continue
            if any(x in label for x in ("cover", "motivation")) and a.cover_letter.strip():
                continue
            categories = {
                "portfolio": ("portfolio",), "transcript": ("transcript",),
                "writing_sample": ("writing_sample",), "certificate": ("certificate",),
                "reference": ("reference",)
            }
            matched = [cat for cat, words in categories.items() if any(w in label for w in words)]
            if matched and db.query(CandidateDocument).filter(CandidateDocument.active.is_(True), CandidateDocument.category.in_(matched)).first():
                continue
        remaining.append(field)
    return remaining

def _csv_response(rows, filename):
    out = StringIO()
    writer = csv.writer(out)
    for row in rows:
        writer.writerow(row)
    return StreamingResponse(BytesIO(out.getvalue().encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/health")
def health():
    # Readiness check: report database reachability without exposing secrets.
    try:
        if engine is not None:
            with engine.connect() as connection:
                connection.execute(sql_text("SELECT 1"))
        else:
            from app.firestore_database import _firestore
            _firestore().collection("_system").document("health").get()
        database = "ok"
    except Exception:
        database = "error"
    if database != "ok":
        return JSONResponse({"status": "degraded", "database": database, "backend": settings.database_backend, "version": "13.4.5"}, status_code=503)
    return {"status": "ok", "database": database, "backend": settings.database_backend, "version": "13.4.5"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, track: str = "", status: str = "", qtext: str = "", opportunity_type: str = "", view: str = "shortlist", page: int = 1, per_page: int = 15, db: Session = Depends(get_db)):
    from datetime import timedelta
    from app.preferences import get_preferences
    prefs=get_preferences(); allq=db.query(Job).filter_by(active=True)
    if track: allq=allq.filter_by(track=track)
    if opportunity_type: allq=allq.filter_by(opportunity_type=opportunity_type)
    if qtext:
        like=f"%{qtext}%"; allq=allq.filter((Job.title.ilike(like))|(Job.company.ilike(like))|(Job.description.ilike(like)))
    # Bound the dashboard working set. The shortlist only renders 60 records,
    # while the full-index view renders at most 300. A separate paginated
    # opportunity index should replace this cap as the dataset grows.
    all_jobs=allq.order_by(Job.score.desc(),Job.discovered_at.desc()).limit(1000).all()
    if status: all_jobs=[j for j in all_jobs if (j.application.status if j.application else "new")==status]
    cutoff=datetime.now(timezone.utc)-timedelta(days=14)
    def recent(j):
        d=j.discovered_at
        if d and d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
        return bool(d and d>=cutoff)
    def preference_eligible(j):
        ev=json.loads(j.eligibility_evidence or '[]')
        quotes=' '.join(x.get('quote','').lower() for x in ev)
        if j.eligibility=='restricted' and not prefs.get('include_location_restricted_roles',False): return False
        if 'visa sponsorship' in quotes and not prefs.get('include_visa_sponsorship',True): return False
        if any(x in quotes for x in ['eligible to work in','authorized to work in','authorised to work in']) and not prefs.get('include_roles_requiring_local_work_authorisation',False): return False
        if any(x in quotes for x in ['on-site','onsite','in-office','hybrid']) and not prefs.get('include_hybrid_onsite_outside_nigeria',False) and 'nigeria' not in quotes: return False
        mode=prefs.get('work_authorisation_mode','any')
        role_text=f"{j.location or ''} {j.description or ''}".lower()
        auth_terms=['eligible to work in','authorized to work in','authorised to work in','must have the right to work','right to work in']
        requires_local=any(term in role_text for term in auth_terms)
        authorised=[x.strip().lower() for x in prefs.get('authorised_countries','').split(',') if x.strip()]
        sponsorship=[x.strip().lower() for x in prefs.get('sponsorship_countries','').split(',') if x.strip()]
        if mode=='authorised_only' and requires_local and authorised and not any(country in role_text for country in authorised): return False
        if mode=='sponsorship_or_authorised' and requires_local and authorised and sponsorship and not any(country in role_text for country in authorised+sponsorship) and not any(x in role_text for x in ['visa sponsorship','sponsorship available','work permit sponsorship']): return False
        if prefs.get('relocation_willingness')=='remote_only' and any(x in role_text for x in ['on-site','onsite','in-office','hybrid']): return False
        return True
    shortlisted=[j for j in all_jobs if j.score>=int(prefs.get('minimum_fit_score',65)) and (j.eligibility!='ineligible' and (j.eligibility!='restricted' or prefs.get('include_location_restricted_roles',False))) and j.application is None and recent(j) and j.track in prefs.get('tracks',[]) and (j.eligibility!='verify' or prefs.get('include_unverified_geography',True)) and preference_eligible(j)]
    if prefs.get('auto_shortlist',True): result_set=shortlisted if view!='all' else all_jobs
    else: result_set=all_jobs
    total_results=len(result_set)
    per_page=max(5,min(int(per_page or 15),50))
    total_pages=max(1,(total_results+per_page-1)//per_page)
    page=max(1,min(int(page or 1),total_pages))
    jobs=result_set[(page-1)*per_page:page*per_page]
    drafts=db.query(Application).filter_by(status='draft').count(); approved=db.query(Application).filter_by(status='approved').count()
    pending=db.query(Application).filter_by(status='submission_pending_verification').count()
    active_apps=db.query(Application).filter(Application.status.in_(['draft','approved','submission_pending_verification'])).order_by(Application.updated_at.desc()).limit(8).all()
    stats={'jobs':db.query(Job).count(),'shortlist':len(shortlisted),'drafts':drafts,'approved':approved,'pending':pending,
      'submitted':db.query(Application).filter_by(status='submitted').count(),'stale':db.query(Job).filter(Job.last_seen_at < cutoff).count()}
    watches=db.query(CompanyWatch).order_by(CompanyWatch.name).all()
    docs=db.query(CandidateDocument).filter_by(active=True).order_by(CandidateDocument.uploaded_at.desc()).all()
    last_run=db.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).first()
    return templates.TemplateResponse(request, 'dashboard.html', {'jobs':jobs,'stats':stats,'tracks':list(PROFILE['tracks']),
      'selected_track':track,'selected_status':status,'selected_opportunity_type':opportunity_type,'opportunity_types':['Internship','Fellowship','Graduate Programme','Research Opportunity','Early-Career Programme','Part-Time Employment','Full-Time Employment','Other'],'watches':watches,'assets':ASSETS,'query':qtext,'documents':docs,
      'last_run':last_run,'preferences':prefs,'active_apps':active_apps,'view':view,'page':page,'per_page':per_page,'total_results':total_results,'total_pages':total_pages})


@app.get('/candidate-profile', response_class=HTMLResponse)
def candidate_profile_page(request: Request):
    from app.candidate_profile import get_candidate_profile
    return templates.TemplateResponse(request, 'candidate_profile.html', {'candidate': get_candidate_profile()['candidate_details']})

@app.post('/candidate-profile')
def update_candidate_profile(
    name: str = Form(''), headline: str = Form(''), email: str = Form(''), phone: str = Form(''),
    location: str = Form(''), website: str = Form(''), linkedin: str = Form(''), github: str = Form(''),
    summary: str = Form(''), skills: str = Form(''), education_notes: str = Form(''),
    experience_notes: str = Form(''), project_notes: str = Form(''), achievements: str = Form(''),
    career_interests: str = Form(''), languages: str = Form(''), additional_context: str = Form('')):
    from app.candidate_profile import save_candidate_profile
    save_candidate_profile(locals())
    return RedirectResponse('/candidate-profile?saved=1', 303)

@app.get('/settings',response_class=HTMLResponse)
def settings_page(request:Request):
    from app.preferences import get_preferences
    return templates.TemplateResponse(request, 'settings.html', {'preferences':get_preferences(),'tracks':list(PROFILE['tracks'])})

@app.post('/settings')
def save_settings(request:Request, minimum_fit_score:int=Form(65), display_mode:str=Form('auto'), default_submit_mode:str=Form('manual'),
    residence_country:str=Form('Nigeria'), citizenship:str=Form(''), immigration_status:str=Form('not_specified'), work_authorisation_mode:str=Form('any'), authorised_countries:str=Form(''), sponsorship_countries:str=Form(''), relocation_willingness:str=Form('open'),
    include_visa_sponsorship:bool=Form(False), include_roles_requiring_local_work_authorisation:bool=Form(False),
    include_location_restricted_roles:bool=Form(False), include_hybrid_onsite_outside_nigeria:bool=Form(False),
    include_unverified_geography:bool=Form(False), show_stale:bool=Form(False), auto_shortlist:bool=Form(False),
    tracks:list[str]=Form([])):
    from app.preferences import get_preferences,save_preferences
    p=get_preferences(); p.update({'minimum_fit_score':max(0,min(100,minimum_fit_score)),'display_mode':display_mode if display_mode in ('auto','mobile','desktop') else 'auto',
      'default_submit_mode':default_submit_mode if default_submit_mode in ('manual','assisted') else 'manual',
      'residence_country':residence_country.strip()[:100], 'citizenship':citizenship.strip()[:200],
      'immigration_status':immigration_status if immigration_status in ('not_specified','citizen','permanent_resident','work_permit','temporary_visa','student_visa','no_work_authorisation','other') else 'not_specified',
      'work_authorisation_mode':work_authorisation_mode if work_authorisation_mode in ('any','authorised_only','sponsorship_or_authorised') else 'any',
      'authorised_countries':authorised_countries.strip()[:1000], 'sponsorship_countries':sponsorship_countries.strip()[:1000],
      'relocation_willingness':relocation_willingness if relocation_willingness in ('open','remote_only','case_by_case') else 'open',
      'include_visa_sponsorship':include_visa_sponsorship,'include_roles_requiring_local_work_authorisation':include_roles_requiring_local_work_authorisation,
      'include_location_restricted_roles':include_location_restricted_roles,'include_hybrid_onsite_outside_nigeria':include_hybrid_onsite_outside_nigeria,
      'include_unverified_geography':include_unverified_geography,'show_stale':show_stale,'auto_shortlist':auto_shortlist,
      'tracks':[t for t in tracks if t in PROFILE['tracks']]})
    save_preferences(p)
    return RedirectResponse('/settings?saved=1',303)

@app.post("/api/scan")
async def start_scan():
    """Start discovery without blocking or navigating away from the dashboard."""
    global _scan_task
    async with _scan_lock:
        if _scan_task is not None and not _scan_task.done():
            return JSONResponse({"status": "running", "message": "A discovery scan is already running."}, status_code=202)
        _scan_task = asyncio.create_task(_run_discovery_background())
    return JSONResponse({"status": "started", "message": "Discovery started."}, status_code=202)

@app.get("/api/scan/status")
def scan_status(db: Session = Depends(get_db)):
    if _scan_task is not None and not _scan_task.done():
        return {"status": "running", "new": 0, "finished_at": None, "sources": {}}
    run = db.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).first()
    if not run:
        return {"status": "idle", "new": 0, "finished_at": None, "sources": {}}
    try:
        sources = json.loads(run.source_results or "{}")
    except Exception:
        sources = {}
    status = run.status or "unknown"
    if status == "complete":
        status = "completed"
    return {"status": status, "new": run.total_new or 0, "finished_at": run.finished_at.isoformat() if run.finished_at else None, "sources": sources}

@app.post("/scan")
async def legacy_scan():
    """Backward-compatible form endpoint; now starts an async scan."""
    await start_scan()
    return RedirectResponse("/", 303)

@app.post("/watch")
def watch(name: str = Form(...), career_url: str = Form(...), db: Session = Depends(get_db)):
    try:
        _assert_public_https(career_url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not db.query(CompanyWatch).filter_by(career_url=career_url).first():
        db.add(CompanyWatch(name=name.strip()[:300], career_url=career_url))
        db.commit()
    return RedirectResponse("/", 303)

@app.post("/watch/{watch_id}/toggle")
def toggle_watch(watch_id: int, db: Session = Depends(get_db)):
    item = db.get(CompanyWatch, watch_id)
    if not item:
        raise HTTPException(404, "Watchlist item not found")
    item.enabled = not item.enabled
    db.commit()
    return RedirectResponse("/", 303)

@app.get("/job/{jid}", response_class=HTMLResponse)
def job_page(jid: int, request: Request, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404)
    from app.candidate_profile import get_candidate_profile
    candidate_profile = get_candidate_profile()
    profile_json = json.dumps({
        "name": candidate_profile["name"], "email": candidate_profile["contact"]["email"],
        "phone": candidate_profile["contact"].get("phone", ""), "portfolio": candidate_profile["links"]["portfolio"],
        "github": candidate_profile["links"]["github"], "linkedin": candidate_profile["links"].get("linkedin", "")
    })
    workflow = json.loads(j.application.workflow_json or "{}") if j.application else {}
    return templates.TemplateResponse(request, "job.html", {
        "job": j, "application": j.application,
        "selected_assets": select_assets(j.track, j.title, j.description),
        "profile_json": profile_json, "workflow_url": workflow.get("url", j.url),
        "gmail_connection": db.query(GmailConnection).first()
    })

@app.post("/job/{jid}/draft")
def draft(jid: int, db: Session = Depends(get_db)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404)
    if not j.application:
        source_doc = db.query(CandidateDocument).filter_by(category="resume", active=True).order_by(CandidateDocument.uploaded_at.desc()).first()
        source_cv = source_doc.extracted_text if source_doc else ""
        cv, letter, report = create_draft(j, source_cv=source_cv)
        if source_doc and not source_cv:
            report += " Uploaded source CV has no extractable text; review the original file and upload a text-readable PDF/DOCX if needed."
        db.add(Application(job_id=j.id, cv_text=cv, cover_letter=letter, match_report=report))
        db.commit()
    return RedirectResponse(f"/job/{jid}", 303)

@app.post("/application/{aid}/save")
def save_application(aid: int, cv_text: str = Form(""), cover_letter: str = Form(""), db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if not a or a.status != "draft":
        raise HTTPException(409, "Only draft applications can be edited")
    a.cv_text = cv_text
    a.cover_letter = cover_letter
    db.commit()
    return RedirectResponse(f"/job/{a.job_id}", 303)

@app.post("/application/{aid}/approve")
def approve(aid: int, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if not a or a.status != "draft":
        raise HTTPException(409, "Only a draft can be approved")
    job = db.get(Job, a.job_id)
    remaining = _remaining_application_fields(a, db)
    audit = evidence_audit(job, a, remaining)
    a.audit_json = dump(audit)
    a.missing_info_json = dump(audit["required_fields_missing"])
    if not audit["ready_for_human_review"]:
        db.commit()
        raise HTTPException(409, "Application audit has blockers: " + " ".join(audit["blockers"]))
    a.status = "approved"
    a.approved_at = datetime.now(timezone.utc)
    a.confirmation = "Approved by user for final human review. No external submission has occurred."
    db.commit()
    return RedirectResponse(f"/job/{a.job_id}", 303)

@app.post("/application/{aid}/submitted")
def submitted(aid: int, confirmation: str = Form(""), db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if not a or a.status != "approved":
        raise HTTPException(409, "Approve the application package first")
    if confirmation.strip() != "I CONFIRM I SUBMITTED THIS APPLICATION":
        raise HTTPException(400, "Submit on the employer's website first, then enter the exact confirmation phrase.")
    a.status = "submitted"
    a.submitted_at = datetime.now(timezone.utc)
    a.confirmation = "Candidate explicitly confirmed external submission. This system did not click the employer's final Submit button."
    db.commit()
    return RedirectResponse(f"/job/{a.job_id}", 303)

@app.get("/application/{aid}/cv.docx")
def download_cv_docx(aid: int, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db)
    job = db.get(Job, a.job_id)
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Inches(.65); sec.bottom_margin = Inches(.65)
    normal = doc.styles["Normal"]; normal.font.name = "Aptos"; normal.font.size = Pt(9.5)
    normal.font.color.rgb = RGBColor(42, 48, 40)
    for i, raw in enumerate(a.cv_text.splitlines()):
        line = raw.strip()
        if not line: continue
        if i == 0: doc.add_heading(line, 0)
        elif line.isupper() and len(line) < 65: doc.add_heading(line, 2)
        elif line.startswith("• "): doc.add_paragraph(line[2:], style="List Bullet")
        else: doc.add_paragraph(line)
    doc.core_properties.title = f"CV  -  {job.title if job else 'Application'}"
    buf = BytesIO(); doc.save(buf); buf.seek(0)
    company = (job.company if job else "Application").replace(" ", "_")
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="Favour_Akintoye_CV_{company}.docx"'})

@app.get("/application/{aid}/cv.pdf")
def download_cv_pdf(aid: int, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import mm
    from xml.sax.saxutils import escape
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=19*mm, leftMargin=19*mm, topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CVName", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19, leading=22, textColor=colors.HexColor("#253126"), alignment=TA_LEFT, spaceAfter=8))
    styles.add(ParagraphStyle(name="CVHead", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#8b693b"), spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="CVBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.7, leading=12, textColor=colors.HexColor("#293128"), spaceAfter=3))
    story = []
    for i, raw in enumerate(a.cv_text.splitlines()):
        line = raw.strip()
        if not line: story.append(Spacer(1, 3)); continue
        if i == 0: story.append(Paragraph(escape(line), styles["CVName"]))
        elif line.isupper() and len(line) < 65: story.append(Paragraph(escape(line), styles["CVHead"]))
        else: story.append(Paragraph(escape(line.lstrip("• ")), styles["CVBody"]))
    doc.build(story); buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition":'attachment; filename="Favour_Akintoye_Tailored_CV.pdf"'})

@app.get("/application/{aid}/email.eml")
def download_email_eml(aid: int, to: str = "", db: Session = Depends(get_db)):
    a = _application_or_404(aid, db); job = db.get(Job, a.job_id)
    msg = EmailMessage()
    msg["To"] = to or ""
    msg["Subject"] = f"Application: {job.title}  -  Favour Akintoye"
    from app.candidate_profile import get_candidate_profile
    candidate_profile = get_candidate_profile()
    msg["From"] = candidate_profile["contact"]["email"]
    msg.set_content(a.cover_letter)
    return StreamingResponse(BytesIO(msg.as_bytes()), media_type="message/rfc822",
        headers={"Content-Disposition":'attachment; filename="application_email.eml"'})


# Gmail OAuth: one private workspace connection. The OAuth client secret and token-encryption key
# are environment secrets and must never be committed to source control.
@app.get("/gmail", response_class=HTMLResponse)
def gmail_settings_page(request: Request, db: Session = Depends(get_db)):
    connection = db.query(GmailConnection).first()
    history = db.query(EmailSendRecord).order_by(EmailSendRecord.sent_at.desc()).limit(20).all()
    message = request.query_params.get("message", "")
    return templates.TemplateResponse(request, "gmail.html", {"connection":connection,"history":history,"message":message})

@app.get("/gmail/connect")
def gmail_connect(request: Request):
    from itsdangerous import URLSafeTimedSerializer
    from app.gmail_service import authorization_url
    serializer=URLSafeTimedSerializer(settings.secret_key, salt="oi-gmail-oauth")
    redirect_uri=os.getenv("GMAIL_REDIRECT_URI", "").strip() or str(request.url_for("gmail_oauth_callback"))
    auth_url,state,verifier=authorization_url(redirect_uri)
    signed=serializer.dumps({"state":state,"verifier":verifier,"redirect_uri":redirect_uri})
    response=RedirectResponse(auth_url,303)
    response.set_cookie("oi_gmail_oauth",signed,httponly=True,secure=(redirect_uri.startswith("https://")),samesite="lax",max_age=600)
    return response

@app.get("/gmail/oauth/callback",name="gmail_oauth_callback")
def gmail_oauth_callback(request: Request, db: Session = Depends(get_db)):
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    from app.gmail_service import exchange_code, encrypt_token, GmailNotConfigured
    signed=request.cookies.get("oi_gmail_oauth","")
    serializer=URLSafeTimedSerializer(settings.secret_key,salt="oi-gmail-oauth")
    try: payload=serializer.loads(signed,max_age=600)
    except (BadSignature,SignatureExpired): raise HTTPException(400,"Gmail authorization expired. Start the connection again.")
    if request.query_params.get("state") != payload.get("state"):
        raise HTTPException(400,"OAuth state verification failed.")
    if request.query_params.get("error"):
        return RedirectResponse("/gmail?message=Gmail+connection+cancelled",303)
    try:
        token,email=exchange_code(request.query_params.get("code",""),payload["redirect_uri"],payload["verifier"])
        row=db.query(GmailConnection).first()
        if row is None: row=GmailConnection(); db.add(row)
        row.email=email; row.encrypted_token=encrypt_token(token); db.commit()
    except GmailNotConfigured as e: raise HTTPException(503,str(e))
    except Exception as e: raise HTTPException(400,"Could not complete Gmail authorization: "+str(e)[:240])
    response=RedirectResponse("/gmail?message=Gmail+connected+successfully",303); response.delete_cookie("oi_gmail_oauth"); return response

@app.post("/gmail/disconnect")
def gmail_disconnect(db: Session = Depends(get_db)):
    row=db.query(GmailConnection).first()
    if row: db.delete(row); db.commit()
    return RedirectResponse("/gmail?message=Gmail+disconnected",303)

@app.post("/application/{aid}/send-email")
def send_application_email(aid: int, recipient: str=Form(...), subject: str=Form(...), body: str=Form(...), authorization: str=Form(...), bcc_self: str=Form("yes"), db: Session=Depends(get_db)):
    import re
    from app.gmail_service import decrypt_token, encrypt_token, send_raw_message, GmailNotConfigured
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from xml.sax.saxutils import escape
    from email.utils import parseaddr
    a=db.get(Application,aid)
    if not a or a.status!="approved": raise HTTPException(409,"Approve and audit this application package before sending an email.")
    if authorization.strip()!="I APPROVE THIS EMAIL TO BE SENT": raise HTTPException(400,"Exact email approval phrase is required.")
    address=parseaddr(recipient.strip())[1]
    if not address or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",address): raise HTTPException(400,"Enter a valid employer email address.")
    if not subject.strip() or not body.strip(): raise HTTPException(400,"Subject and email body are required.")
    connection=db.query(GmailConnection).first()
    if not connection: raise HTTPException(409,"Connect Gmail before sending.")
    job=db.get(Job,a.job_id)
    try:
        token=decrypt_token(connection.encrypted_token)
        # Tailored CV PDF
        cvbuf=BytesIO(); styles=getSampleStyleSheet(); story=[]
        for idx,line in enumerate(a.cv_text.splitlines()):
            line=line.strip()
            if not line: story.append(Spacer(1,3)); continue
            if idx==0: story.append(Paragraph(escape(line),styles['Title']))
            elif line.isupper() and len(line)<65: story.append(Paragraph(escape(line),styles['Heading2']))
            else: story.append(Paragraph(escape(line.lstrip('• ')),styles['BodyText']))
        SimpleDocTemplate(cvbuf,pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=16*mm,bottomMargin=16*mm).build(story)
        # Cover letter PDF
        letterbuf=BytesIO(); letter_story=[]
        for para in a.cover_letter.splitlines():
            if para.strip(): letter_story.append(Paragraph(escape(para),styles['BodyText'])); letter_story.append(Spacer(1,5))
        SimpleDocTemplate(letterbuf,pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=20*mm,bottomMargin=20*mm).build(letter_story)
        # Send CV and cover letter as separate PDFs. Gmail also stores a copy in Sent;
        # optional BCC creates a separate copy in the connected account's Inbox.
        from email.message import EmailMessage
        from email import encoders
        import base64
        msg=EmailMessage(); msg['To']=address; msg['Subject']=subject.strip()
        if bcc_self=="yes": msg['Bcc']=connection.email
        msg.set_content(body)
        msg.add_attachment(cvbuf.getvalue(),maintype='application',subtype='pdf',filename=f"{(job.company or 'Company').replace(' ','_')}_Tailored_CV.pdf")
        msg.add_attachment(letterbuf.getvalue(),maintype='application',subtype='pdf',filename=f"{(job.company or 'Company').replace(' ','_')}_Cover_Letter.pdf")
        # Persist a send intent before the external side effect. If Gmail accepts
        # the message but the response times out, retain an UNKNOWN record so the
        # candidate checks Gmail Sent before retrying and creating a duplicate.
        record=EmailSendRecord(application_id=aid,recipient=address,subject=subject.strip(),status='sending',inbox_copy=(bcc_self=="yes"))
        db.add(record); db.commit(); db.refresh(record)
        try:
            result,token=send_raw_message(token,msg.as_bytes())
            connection.encrypted_token=encrypt_token(token)
            record.gmail_message_id=result.get('id','')
            record.status='sent'
            db.commit()
        except Exception:
            db.rollback()
            uncertain=db.get(EmailSendRecord,record.id)
            if uncertain:
                uncertain.status='unknown'
                db.commit()
            raise
        return RedirectResponse(f"/job/{job.id}?email_sent=1",303)
    except GmailNotConfigured as e: raise HTTPException(503,str(e))
    except Exception as e:
        raise HTTPException(502,"Gmail did not return a confirmed result. Check Gmail Sent and the email activity record before retrying; the message may have been accepted. Details: "+str(e)[:220])

@app.post("/application/{aid}/form-pack")
def form_pack(aid: int, questions: str = Form(""), db: Session = Depends(get_db)):
    a = _application_or_404(aid, db); job = db.get(Job, a.job_id)
    from app.candidate_profile import get_candidate_profile
    candidate_profile = get_candidate_profile()
    lines = [f"APPLICATION RESPONSE PACK  -  {job.company}", "", f"Role: {job.title}",
        f"Candidate: {candidate_profile['name']}", f"Email: {candidate_profile['contact']['email']}",
        f"Portfolio: {candidate_profile['links']['portfolio']}", "", "CV EVIDENCE", a.cv_text,
        "", "COVER LETTER / EMAIL", a.cover_letter, "", "SCREENING QUESTIONS / GOOGLE FORM"]
    qs = [q.strip() for q in questions.splitlines() if q.strip()]
    if qs:
        answers, warnings, ai_used = create_screening_answers(job, qs)
        lines += ["", "QUESTION-SPECIFIC DRAFT ANSWERS",
            f"Generation mode: {'AI-assisted' if ai_used else 'evidence suggestions only'}", answers]
        if warnings: lines += ["", "VERIFY BEFORE SUBMISSION", *warnings]
    else:
        lines.append("Paste screening questions into the application workspace to generate a response pack.")
    return StreamingResponse(BytesIO("\n".join(lines).encode("utf-8")),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition":'attachment; filename="application_response_pack.txt"'})

@app.post("/application/{aid}/screening-answers")
def screening_answers_api(aid: int, payload: ScreeningRequest, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db); job = db.get(Job, a.job_id)
    answers, warnings, ai_used = create_screening_answers(job, payload.questions)
    return {"answers": answers, "warnings": warnings, "ai_used": ai_used,
        "evidence_policy": "Unknown personal, eligibility and sensitive answers require direct candidate input."}

@app.post("/application/{aid}/inspect-form")
def inspect_application_form(aid: int, payload: FormInspectionRequest, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db)
    try:
        result = run(inspect_form(payload.url), payload.url)
        workflow = infer_stage(result.get("title", ""), result.get("url", ""), result.get("fields", []), result.get("buttons", []))
        result["workflow"] = workflow
        previous = json.loads(a.workflow_json or "{}")
        result["saved_progress"] = previous.get("progress", {})
        stages = previous.get("stages", [])
        snapshot = {"url":result.get("url"),"ats":result.get("ats"),"fields":result.get("fields",[]),
                    "workflow":workflow,"inspected_at":datetime.now(timezone.utc).isoformat()}
        signature=tuple(sorted(f.get("selector_key","") for f in snapshot["fields"]))
        if not any(tuple(sorted(f.get("selector_key","") for f in old.get("fields",[])))==signature for old in stages):
            stages.append(snapshot)
        a.workflow_json = dump({
            "url": result.get("url"), "ats": result.get("ats"), "fields": result.get("fields", []),
            "buttons": result.get("buttons", []), "frames": result.get("frames", []),
            "workflow": workflow, "progress": previous.get("progress", {}),"stages":stages,
            "inspected_at": datetime.now(timezone.utc).isoformat()
        })
        a.missing_info_json = dump([x for x in result.get("fields", []) if x.get("required")])
        db.commit()
        return result
    except ValueError as e: raise HTTPException(400, str(e))
    except ImportError: raise HTTPException(503, "Playwright is not installed.")
    except Exception as e: raise HTTPException(502, f"Could not inspect application page: {str(e)[:240]}")

@app.post("/application/{aid}/fill-form")
def fill_application_form(aid: int, payload: FormFillRequest, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db)
    if a.status not in ("draft", "approved"):
        raise HTTPException(409, "Only active applications can be prepared.")
    try:
        with tempfile.TemporaryDirectory() as td:
            cv_path = os.path.join(td, "Favour_Akintoye_Tailored_CV.docx")
            from docx import Document
            doc = Document()
            for i, line in enumerate(a.cv_text.splitlines()):
                line = line.strip()
                if not line: continue
                if i == 0: doc.add_heading(line, 0)
                elif line.isupper() and len(line) < 65: doc.add_heading(line, 2)
                elif line.startswith("• "): doc.add_paragraph(line[2:], style="List Bullet")
                else: doc.add_paragraph(line)
            doc.save(cv_path)
            cover_path = os.path.join(td, "Favour_Akintoye_Cover_Letter.docx")
            cover_doc = Document()
            for paragraph in a.cover_letter.split("\n\n"):
                cover_doc.add_paragraph(paragraph)
            cover_doc.save(cover_path)
            document_paths = {}
            for d in db.query(CandidateDocument).filter_by(active=True).order_by(CandidateDocument.uploaded_at.desc()).all():
                if d.category in {"portfolio", "transcript", "writing_sample", "certificate", "reference"} and d.category not in document_paths and os.path.exists(d.stored_path):
                    target = os.path.join(td, f"{d.category}_{os.path.basename(d.stored_path)}")
                    shutil.copyfile(d.stored_path, target); document_paths[d.category] = target
            result = run(fill_form(payload.url, payload.field_values, cv_path, cover_path, document_paths, payload.advance_button_text), payload.url)
            wf = json.loads(a.workflow_json or "{}")
            wf["last_fill"] = {"filled":result.get("filled",[]),"unfilled":result.get("unfilled",[]),
                "url":result.get("url"),"advanced":result.get("advanced_to_next_step",False),
                "saved_at":datetime.now(timezone.utc).isoformat()}
            if result.get("next_page"):
                next_data=result["next_page"]
                next_workflow=infer_stage(next_data.get("title",""),next_data.get("url",""),next_data.get("fields",[]),next_data.get("buttons",[]))
                wf.update({"url":next_data.get("url"),"ats":next_data.get("ats"),
                    "fields":next_data.get("fields",[]),"buttons":next_data.get("buttons",[]),
                    "frames":next_data.get("frames",[]),"workflow":next_workflow})
                stages=wf.get("stages",[])
                signature=tuple(sorted(f.get("selector_key","") for f in next_data.get("fields",[])))
                if not any(tuple(sorted(f.get("selector_key","") for f in old.get("fields",[])))==signature for old in stages):
                    stages.append({"url":next_data.get("url"),"ats":next_data.get("ats"),
                        "fields":next_data.get("fields",[]),"workflow":next_workflow,
                        "inspected_at":datetime.now(timezone.utc).isoformat()})
                wf["stages"]=stages
                result["next_page"]["workflow"]=next_workflow
            a.workflow_json=dump(wf);db.commit()
            return result
    except ValueError as e: raise HTTPException(400, str(e))
    except ImportError: raise HTTPException(503, "Playwright is not installed.")
    except Exception as e: raise HTTPException(502, f"Could not prepare the form: {str(e)[:240]}")


@app.post("/application/{aid}/submit-external")
def submit_external_application(aid: int, payload: FormFillRequest, db: Session = Depends(get_db)):
    a = db.get(Application, aid)
    if not a or a.status != "approved":
        raise HTTPException(409, "Only an approved application can be submitted.")
    if payload.authorization_phrase != "I AUTHORIZE THIS APPLICATION TO BE SUBMITTED":
        raise HTTPException(400, "Explicit submission authorization is required.")
    if not payload.final_submit_button_text:
        raise HTTPException(400, "No final submission control was selected.")
    wf_snapshot=json.loads(a.workflow_json or "{}")
    if not wf_snapshot.get("buttons"):
        raise HTTPException(409, "Inspect the employer form before requesting submission.")
    observed_labels={str(x.get("text","")).strip() for x in wf_snapshot.get("buttons",[])}
    if payload.final_submit_button_text.strip() not in observed_labels:
        raise HTTPException(409, "The selected final control was not present in the latest inspection. Inspect the form again.")
    observed_url=wf_snapshot.get("url","")
    if observed_url and urlparse(observed_url).hostname != urlparse(payload.url).hostname:
        raise HTTPException(409, "The application host changed. Inspect the new page before submission.")
    remaining = _remaining_application_fields(a, db, payload.field_values)
    audit = evidence_audit(db.get(Job, a.job_id), a, remaining)
    if not audit["ready_for_human_review"]:
        a.audit_json = dump(audit); db.commit()
        raise HTTPException(409, "Submission blocked by the completeness audit: " + " ".join(audit["blockers"]))
    try:
        with tempfile.TemporaryDirectory() as td:
            from docx import Document
            doc = Document()
            for i, line in enumerate(a.cv_text.splitlines()):
                line=line.strip()
                if not line:continue
                if i==0:doc.add_heading(line,0)
                elif line.isupper() and len(line)<65:doc.add_heading(line,2)
                elif line.startswith("• "):doc.add_paragraph(line[2:],style="List Bullet")
                else:doc.add_paragraph(line)
            cv_path=os.path.join(td,"Favour_Akintoye_Tailored_CV.docx");doc.save(cv_path)
            cover_path=os.path.join(td,"Favour_Akintoye_Cover_Letter.docx")
            cover_doc=Document()
            for paragraph in a.cover_letter.split("\n\n"):cover_doc.add_paragraph(paragraph)
            cover_doc.save(cover_path)
            document_paths={}
            for d in db.query(CandidateDocument).filter_by(active=True).order_by(CandidateDocument.uploaded_at.desc()).all():
                if d.category in {"portfolio","transcript","writing_sample","certificate","reference"} and d.category not in document_paths and os.path.exists(d.stored_path):
                    target=os.path.join(td,f"{d.category}_{os.path.basename(d.stored_path)}")
                    shutil.copyfile(d.stored_path,target);document_paths[d.category]=target
            result=run(fill_form(payload.url,payload.field_values,cv_path,cover_path,document_paths,
                final_submit_button_text=payload.final_submit_button_text),payload.url)
        if result.get("submission_confirmed"):
            a.status="submitted";a.submitted_at=datetime.now(timezone.utc)
            a.confirmation="Employer confirmation detected after explicit candidate authorization: "+result.get("confirmation_text","")[:1000]
        elif result.get("submission_attempted"):
            a.status="submission_pending_verification"
            a.confirmation="Final control was clicked after explicit authorization, but the employer's success state could not be verified. Check the employer site/email before retrying."
        a.workflow_json=dump({**json.loads(a.workflow_json or "{}"),"last_submission_result":result,
            "submission_checked_at":datetime.now(timezone.utc).isoformat()})
        db.commit()
        return {"application_status":a.status,**result}
    except ValueError as e:raise HTTPException(400,str(e))
    except Exception as e:raise HTTPException(502,f"Submission handoff failed: {str(e)[:240]}")

@app.post("/application/{aid}/progress")
def save_application_progress(aid: int, payload: ProgressRequest, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db)
    if a.status == "submitted": raise HTTPException(409, "Submitted applications are read-only.")
    prior = json.loads(a.workflow_json or "{}")
    merged_progress = prior.get("progress", {})
    merged_progress.update(payload.progress)
    prior["progress"] = merged_progress
    prior["saved_at"] = datetime.now(timezone.utc).isoformat()
    a.workflow_json = dump(prior); db.commit()
    return {"saved": True, "application_id": aid, "saved_at": prior["saved_at"]}

@app.get("/application/{aid}/audit")
def application_audit(aid: int, db: Session = Depends(get_db)):
    a = _application_or_404(aid, db); job = db.get(Job, a.job_id)
    remaining = _remaining_application_fields(a, db)
    audit = evidence_audit(job, a, remaining)
    a.audit_json = dump(audit); a.missing_info_json = dump(audit["required_fields_missing"])
    db.commit()
    return audit

@app.get("/exports/opportunities.csv")
def export_opportunities(db: Session = Depends(get_db)):
    rows = [["job_id","company","role","location","track","opportunity_type","source","source_url","published_at","discovered_at","last_seen_at","active","eligibility","fit_score","opportunity_status","application_id","application_status","approved_at","submitted_at","confirmation"]]
    for j in db.query(Job).order_by(Job.discovered_at.desc()).all():
        a = j.application
        rows.append([j.id,j.company,j.title,j.location,j.track,j.opportunity_type,j.source,j.url,j.published_at,
            j.discovered_at.isoformat() if j.discovered_at else "",j.last_seen_at.isoformat() if j.last_seen_at else "",j.active,j.eligibility,j.score,
            "applied" if a and a.status=="submitted" else ("in_progress" if a else ("found" if j.active else "stale")),
            a.id if a else "",a.status if a else "not_started",
            a.approved_at.isoformat() if a and a.approved_at else "",
            a.submitted_at.isoformat() if a and a.submitted_at else "",a.confirmation if a else ""])
    return _csv_response(rows, "opportunity_tracker.csv")

@app.get("/exports/applications.csv")
def export_applications(db: Session = Depends(get_db)):
    rows = [["application_id","company","role","location","track","opportunity_type","source_url","status","discovered_at","updated_at","approved_at","submitted_at","confirmation","workflow_stage","ats","audit_ready","audit_blockers"]]
    for a in db.query(Application).order_by(Application.id.desc()).all():
        j = db.get(Job, a.job_id); wf = json.loads(a.workflow_json or "{}"); audit = json.loads(a.audit_json or "{}")
        rows.append([a.id,j.company if j else "",j.title if j else "",j.location if j else "",
            j.track if j else "",j.opportunity_type if j else "Other",j.url if j else "",a.status,
            j.discovered_at.isoformat() if j and j.discovered_at else "",
            a.updated_at.isoformat() if a.updated_at else "",
            a.approved_at.isoformat() if a.approved_at else "",
            a.submitted_at.isoformat() if a.submitted_at else "",a.confirmation,
            wf.get("workflow",{}).get("stage",""),wf.get("ats",""),
            audit.get("ready_for_human_review","")," | ".join(audit.get("blockers",[]))])
    return _csv_response(rows, "application_tracker.csv")

@app.get("/exports/opportunity-intelligence.xlsx")
def export_workbook(db: Session = Depends(get_db)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook(); ws = wb.active; ws.title = "Opportunities"
    ws.append(["ID","Company","Role","Location","Track","Source","Original URL","Published","Discovered","Last seen","Active","Eligibility","Fit score","Opportunity state","Application status"])
    for j in db.query(Job).order_by(Job.score.desc(), Job.discovered_at.desc()).all():
        a = j.application
        ws.append([j.id,j.company,j.title,j.location,j.track,j.opportunity_type,j.source,j.url,j.published_at,
            j.discovered_at.isoformat() if j.discovered_at else "",j.last_seen_at.isoformat() if j.last_seen_at else "",j.active,j.eligibility,j.score,
            "applied" if a and a.status=="submitted" else ("in progress" if a else ("found" if j.active else "stale")),
            a.status if a else "not started"])
    appws = wb.create_sheet("Applications")
    appws.append(["Application ID","Company","Role","Status","Discovered","Updated","Approved","Submitted","ATS","Workflow stage","Audit ready","Audit blockers","Confirmation"])
    for a in db.query(Application).order_by(Application.id.desc()).all():
        j = db.get(Job, a.job_id); wf = json.loads(a.workflow_json or "{}"); audit = json.loads(a.audit_json or "{}")
        appws.append([a.id,j.company if j else "",j.title if j else "",a.status,
            j.discovered_at.isoformat() if j and j.discovered_at else "",a.updated_at.isoformat() if a.updated_at else "",
            a.approved_at.isoformat() if a.approved_at else "",a.submitted_at.isoformat() if a.submitted_at else "",
            wf.get("ats",""),wf.get("workflow",{}).get("stage",""),audit.get("ready_for_human_review",""),
            " | ".join(audit.get("blockers",[])),a.confirmation])
    docws = wb.create_sheet("Candidate Documents")
    docws.append(["Document ID","Category","Original filename","Size bytes","MIME type","Uploaded at","Extracted text available","Active"])
    for d in db.query(CandidateDocument).order_by(CandidateDocument.uploaded_at.desc()).all():
        docws.append([d.id,d.category,d.original_name,d.size_bytes,d.mime_type,
            d.uploaded_at.isoformat() if d.uploaded_at else "",bool(d.extracted_text),d.active])
    watchws = wb.create_sheet("Employer Watchlist")
    watchws.append(["Watch ID","Organisation","Career URL","Enabled","Last scanned","Last error"])
    for item in db.query(CompanyWatch).order_by(CompanyWatch.name).all():
        watchws.append([item.id,item.name,item.career_url,item.enabled,
            item.last_scanned_at.isoformat() if item.last_scanned_at else "",item.last_error])
    runws = wb.create_sheet("Discovery Runs")
    runws.append(["Run ID","Started","Finished","Status","New records","Total indexed","Source results","Error"])
    for r in db.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).limit(200).all():
        runws.append([r.id,r.started_at.isoformat() if r.started_at else "",r.finished_at.isoformat() if r.finished_at else "",
            r.status,r.total_new,r.total_indexed,r.source_results,r.error])
    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="26342A")
            cell.alignment = Alignment(wrap_text=True)
        for col in sheet.columns:
            letter = get_column_letter(col[0].column)
            width = min(58, max(13, max((len(str(c.value or "")) for c in col[:100]), default=12)+2))
            sheet.column_dimensions[letter].width = width
        for row in sheet.iter_rows(min_row=2):
            for cell in row: cell.alignment = Alignment(vertical="top", wrap_text=True)
    buf = BytesIO(); wb.save(buf); buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":'attachment; filename="opportunity_intelligence.xlsx"'})

@app.get("/exports/documents.csv")
def export_documents(db: Session = Depends(get_db)):
    rows=[["document_id","category","filename","size_bytes","mime_type","uploaded_at","extracted_text_available","active"]]
    for d in db.query(CandidateDocument).order_by(CandidateDocument.uploaded_at.desc()).all():
        rows.append([d.id,d.category,d.original_name,d.size_bytes,d.mime_type,
            d.uploaded_at.isoformat() if d.uploaded_at else "",bool(d.extracted_text),d.active])
    return _csv_response(rows,"candidate_documents.csv")

@app.get("/exports/watchlist.csv")
def export_watchlist(db: Session = Depends(get_db)):
    rows=[["watch_id","organisation","career_url","enabled","last_scanned_at","last_error"]]
    for item in db.query(CompanyWatch).order_by(CompanyWatch.name).all():
        rows.append([item.id,item.name,item.career_url,item.enabled,
            item.last_scanned_at.isoformat() if item.last_scanned_at else "",item.last_error])
    return _csv_response(rows,"employer_watchlist.csv")

@app.get("/api/discovery-runs")
def discovery_runs(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(DiscoveryRun).order_by(DiscoveryRun.id.desc()).limit(max(1,min(limit,100))).all()
    return [{"id":r.id,"started_at":r.started_at,"finished_at":r.finished_at,"status":r.status,
        "new":r.total_new,"total":r.total_indexed,"sources":json.loads(r.source_results or "{}"),"error":r.error} for r in rows]

def _extract_document_text(path, extension):
    try:
        if extension == ".pdf":
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)[:100000]
        if extension == ".docx":
            from docx import Document
            return "\n".join(p.text for p in Document(path).paragraphs)[:100000]
        if extension in (".txt", ".md"):
            with open(path, encoding="utf-8", errors="ignore") as fh: return fh.read(100000)
    except Exception:
        return ""
    return ""

@app.post("/documents/upload")
async def upload_candidate_document(category: str = Form("supporting"), file: UploadFile = File(...), db: Session = Depends(get_db)):
    allowed = {".pdf",".docx",".txt",".md",".rtf"}
    name = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed: raise HTTPException(400, "Upload PDF, DOCX, DOC, TXT, Markdown or RTF files only.")
    if category not in {"resume","cover_letter","portfolio","transcript","writing_sample","certificate","reference","supporting"}:
        raise HTTPException(400, "Unsupported document category.")
    data = await file.read(12*1024*1024+1)
    if len(data) > 12*1024*1024: raise HTTPException(413, "Maximum file size is 12 MB.")
    if not data: raise HTTPException(400, "Empty file.")
    base = os.getenv("CANDIDATE_ASSET_DIR", "./candidate_assets")
    os.makedirs(base, exist_ok=True)
    stored = os.path.join(base, uuid.uuid4().hex + ext)
    with open(stored, "wb") as fh: fh.write(data)
    extracted = _extract_document_text(stored, ext)
    db.add(CandidateDocument(category=category, original_name=name[:500], stored_path=stored,
        mime_type=file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
        size_bytes=len(data), extracted_text=extracted))
    db.commit()
    return RedirectResponse("/", 303)

@app.get("/api/documents")
def list_candidate_documents(db: Session = Depends(get_db)):
    return [{"id":d.id,"category":d.category,"filename":d.original_name,"size_bytes":d.size_bytes,
        "uploaded_at":d.uploaded_at,"has_extracted_text":bool(d.extracted_text)}
        for d in db.query(CandidateDocument).filter_by(active=True).order_by(CandidateDocument.uploaded_at.desc()).all()]

@app.post("/documents/{document_id}/deactivate")
def deactivate_document(document_id: int, db: Session = Depends(get_db)):
    d = db.get(CandidateDocument, document_id)
    if not d: raise HTTPException(404, "Document not found")
    d.active = False; db.commit()
    return RedirectResponse("/", 303)

@app.get("/api/profile")
def profile():
    from app.candidate_profile import get_candidate_profile
    return {**get_candidate_profile(), "assets": ASSETS}

@app.get("/api/assets")
def assets():
    return {"assets": ASSETS}

## Release 13.4.5 notes

- Added MyJobMag public listing ingestion for the Nigeria jobs feed, internships, graduate trainee and internship-position listings.
- Collector checks robots.txt, preserves original listing URLs, extracts listing excerpts and basic date/location metadata, and routes records through existing deduplication, eligibility and fit scoring.
- MyJobMag refreshes on a 24-hour cooldown. It is a best-effort HTML integration, not an official API; site markup or access-policy changes may require maintenance.

# Opportunity Intelligence  -  Full Test Release

A private job-discovery, qualification and application-preparation workspace for Favour Akintoye. It is designed around broad sourcing, evidence-grounded application materials, resumable employer-form preparation and auditable records.

## Release 13.4.4 notes

This package includes the v13.4.2 performance and diagnostics work, global Brave discovery enrichment, and the non-blocking dashboard scan flow. It also fixes the current Starlette/FastAPI template-rendering convention across the dashboard, candidate profile, settings, job detail and Gmail pages. The scan starts through the API and the page polls for completion without a full-page reload.

## Included in this release

### Discovery and source coverage

Opportunity Intelligence classifies each listing as Internship, Fellowship, Graduate Programme, Research Opportunity, Early-Career Programme, Part-Time Employment, Full-Time Employment or Other. Classification is based primarily on explicit title language. An analyst or junior role is not automatically labelled an internship. The dashboard supports filtering by opportunity type, and CSV/XLSX exports include the classification. Discovery queries include targeted internship, research internship, policy internship, graduate programme and fellowship searches through configured sources. Source coverage is not exhaustive; specialist programmes may require adding employer or programme career pages to the watchlist.
- Remote OK, Remotive (six-hour cooldown), Arbeitnow, Jobicy, Himalayas (Nigeria/worldwide keyword searches with a 24-hour refresh cooldown) and We Work Remotely RSS.
- Adzuna Nigeria search when API credentials are configured.
- Public Greenhouse, Ashby and Lever job boards when board identifiers are configured.
- Brave web discovery across product, technical product, growth, GTM, strategy, VC, investment research, policy, government and development roles when an API key is configured.
- Brave LLM Context ingestion of pre-extracted page chunks, plus experimental recruitment-filtered Brave News Search. Each Brave endpoint has its own configurable cooldown (24 hours by default).
- Employer career-page watchlist, with robots.txt checks, public-host validation, redirect revalidation, same-domain/ATS link discovery and a six-hour per-company scan cooldown.
- URL deduplication, last-seen timestamps, preliminary fit scoring and career-track classification. Unrefreshed vacancies older than 60 days are marked stale in exports, but existing application records are retained.
- Per-source results, run history and durable scan telemetry.
- Separate Railway worker process; manual scan remains available in the web UI.

Source limits are respected where known. Remotive is throttled to no more than one request per six hours by the persisted discovery-run history. Himalayas is refreshed once daily; its public API caps each response at 20 records and warns that request rates are limited. Public search indexes are discovery aids, not authoritative proof that a vacancy remains open. Always verify the original employer listing and Nigeria eligibility.

### Candidate intelligence and applications
- Structured candidate evidence with claim statuses (`user_reported`, `verify_before_use`, `constraint`).
- Role-aware CV and cover-letter drafting; screening-answer API with evidence warnings.
- Editable application packages and DOCX/PDF/email exports.
- Per-application form inspection, ATS identification, field suggestions and selected-field filling.
- Persistent per-employer browser profiles and saved field progress.
- Workflow stage inference, required-field inventory, missing-information prompts and evidence consistency audit.
- Conservative file upload matching. The system does not upload a random portfolio/transcript/reference file into an ambiguous upload control.
- Final submission is a separate, explicit candidate-authorized action. The candidate must approve the package, inspect the live form, enter the exact authorization phrase and confirm a second prompt. The browser then clicks only one uniquely identified final Submit/Apply control. The system records "submitted" only when a recognised employer confirmation state appears; if the button was clicked but success cannot be verified, it records `submission_pending_verification` and warns against retrying until the employer status is checked.

### Ledgers and exports
- `GET /exports/opportunities.csv`: every indexed vacancy, with source, URL, dates, score, track and status.
- `GET /exports/applications.csv`: application status, approval/submission dates, ATS/workflow and audit results.
- `GET /exports/documents.csv`: uploaded candidate-document inventory (metadata only; never file contents).
- `GET /exports/watchlist.csv`: employer career-page watchlist, enabled state and latest scan result.
- `GET /exports/opportunity-intelligence.xlsx`: multi-sheet workbook with Opportunities, Applications, Candidate Documents, Employer Watchlist and Discovery Runs.
- `GET /api/discovery-runs`: latest scan results by source.
All exports are generated from the database at request time and include new records automatically.

## Run locally (Windows PowerShell)

Quick start on Windows: double-click `start_windows.bat`. It creates the virtual environment, installs dependencies and Chromium, creates `.env` from the example if needed, and starts the web app.

Manual PowerShell setup:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open http://127.0.0.1:8000. The first discovery scan can take time because it queries multiple independent sources. Without API keys, the public-feed and configured ATS-board connectors still run.

## Run tests

Windows: double-click `run_tests_windows.bat`.

```powershell
python -m pytest -q
```

## Railway deployment

Recommended two-service deployment:
1. Add Railway PostgreSQL.
2. Deploy the Dockerfile as the web service.
3. Create a second service from the same repo with start command `python -m app.worker`.
4. Set `ENABLE_SCHEDULER=false` on the web service and `ENABLE_SCHEDULER=true` on the worker.
5. Set `DATABASE_URL` to Railway's PostgreSQL connection URL on both services.
6. Mount persistent storage and set `BROWSER_DATA_DIR=/data/browser_sessions` and `CANDIDATE_ASSET_DIR=/data/candidate_assets`. Keep both directories private; they contain cookies and uploaded personal documents.
7. Set `OPENAI_API_KEY` only when you want AI-assisted application drafting. Optional ambiguous-opportunity classification is disabled by default; set `ENABLE_AI_CLASSIFICATION=true` to opt in. Set optional discovery API credentials separately.
8. If the instance is accessible over the public internet, set `ENABLE_BASIC_AUTH=true` and a long unique `APP_PASSWORD`. Do not use the example password or commit `.env`.

Web start command:
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Worker start command:
`python -m app.worker`

`SCAN_INTERVAL_MINUTES` is clamped to at least 30 minutes. Remotive is separately rate-limited to a six-hour cooldown. Avoid running multiple worker replicas against the same database unless you add a distributed scheduler lock.

## ATS capability boundaries

The ATS label is a routing hint, not a guarantee of universal automation:
- Greenhouse public GET job-board endpoints do not require auth; application POST requires an employer API key and job-specific field mapping.
- Himalayas API data must be attributed to Himalayas and must not be republished to third-party job boards; this system is a private personal research workspace and preserves the provider as the source.
- Lever exposes public postings and a separate application API; application creation is rate-limited and requires the proper posting/site key and form field payload.
- Ashby's public job-posting API retrieves published jobs. Submission endpoints require employer-side permissions/credentials.
- Workday, SmartRecruiters, iCIMS, Taleo, SuccessFactors, Workable, Recruitee, BambooHR, JazzHR and Google Forms currently use the generic accessible-DOM browser assistant with platform identification, not a fully maintained private integration for every platform.
- Multi-step forms are resumable: inspect a page, fill selected fields, and optionally use the separately labelled Fill + Continue action to activate an exact, allowlisted Next/Continue button. The next page is inspected and saved. The final Submit/Apply action is a separate endpoint and requires explicit authorization.
- CAPTCHA, MFA, anti-bot controls, unsupported custom widgets and inaccessible iframes are manual checkpoints. The system detects common CAPTCHA signals and pauses before clicking Submit. Never bypass them.

## Security and privacy

- Basic auth is optional and disabled by default for local development. Enable it for hosted private use. A same-origin request guard is present, but this is not a full CSRF-token/session implementation; the service remains single-user and non-multi-tenant.
- Use HTTPS in production and keep the hosted service private where possible.
- The browser assistant only accepts public HTTPS application URLs and revalidates requested HTTPS destinations. Employer watchlist URLs are also checked against private-address ranges. Do not treat this as a substitute for a hardened outbound proxy or network-level egress policy.
- Persistent browser profiles contain employer-site cookies. Protect the Railway volume and never include it in shared ZIPs.
- Database, exports, CVs and application drafts contain sensitive personal data. Restrict access and backups.
- Do not commit `.env`, API keys, database files or browser profiles.
- LinkedIn, Wellfound and other job platforms have their own terms and anti-automation policies. The system uses search-index discovery and original links rather than logging in and scraping private content.
- No system can truthfully guarantee 50 suitable applications per day. The product prioritises eligibility and role fit; vacancy supply and quality vary by day.

## Candidate-data verification checklist

Before using the system to submit any application, verify:
- Email, phone and contact details.
- Current university status, dates and expected graduation.
- Work authorisation and sponsorship answers for each country.
- Historical user, campaign and performance metrics.
- Exact responsibilities and personal attribution for team/company results.
- Any salary, notice period, demographic or other sensitive answers.

Unknown claims are not to be fabricated. The application audit is a review aid, not a guarantee that the employer's application is complete or accurate.

## Research references

- Arbeitnow Job Board API: https://www.arbeitnow.com/blog/job-board-api
- Jobicy Remote Jobs API: https://jobicy.com/jobs-rss-feed
- Himalayas Remote Jobs API: https://himalayas.app/api
- We Work Remotely RSS: https://weworkremotely.com/remote-job-rss-feed
- Greenhouse Job Board API: https://docs.greenhouse.io/job-board
- Lever Postings API: https://github.com/lever/postings-api
- Ashby Public Job Posting API: https://developers.ashbyhq.com/docs/public-job-posting-api
- Remote OK API guidance: https://remoteok.com/faq
- Remotive API: https://github.com/remotive-com/remote-jobs-api
- Adzuna API: https://developer.adzuna.com/activedocs
- Playwright Python: https://playwright.dev/python/docs/intro
- FastAPI: https://fastapi.tiangolo.com/
- Railway: https://docs.railway.com/

---

# Version 8  -  Intelligence dashboard and qualification settings

## Operating philosophy

The home screen is now a briefing, not a database dump. It prioritises the three queues that require action: high-confidence opportunities to review, drafts awaiting approval, and submissions that need verification. The opportunity index, detailed evidence, documents, watchlist and exports remain available behind the primary briefing.

## Automatic qualification

Every discovered role receives a preliminary fit score, career-track classification and a location/eligibility signal. The default shortlist includes opportunities that:

1. Meet the configured minimum fit score (default 65/100).
2. Match one of the selected career tracks.
3. Are not already attached to an application.
4. Were discovered within the last 14 days.
5. Are not explicitly classified as ineligible under the default location rules.
6. Have a location signal allowed by the candidate's preferences.

The settings page lets the candidate choose whether to include visa-sponsorship roles, roles requiring local work authorisation, geographically restricted roles, hybrid/on-site roles outside Nigeria, and roles whose geography is unclear. The default keeps ambiguous geography in a review queue rather than pretending that remote means worldwide.

The system extracts short evidence snippets from vacancy text for Nigeria, Africa, worldwide, country restrictions and sponsorship language. These are clues, not legal conclusions. Job descriptions are often incomplete, outdated or ambiguous. The system must never claim that a person has work authorisation, decide a legal immigration question, or answer an employer's personal eligibility question without candidate input.

Ambiguous opportunity descriptions can optionally use the configured OpenAI classifier model for track and opportunity-type interpretation. This is disabled by default (`ENABLE_AI_CLASSIFICATION=false`) so discovery does not consume OpenAI credits. Set `ENABLE_AI_CLASSIFICATION=true` to opt in. Deterministic rules remain the first pass, and the classifier result is cached in-process. AI application drafting remains a separate feature controlled by `OPENAI_API_KEY`. The model does not decide geographic eligibility or assign the fit score.

Fit score is a transparent heuristic, not a hiring probability. The score and eligibility labels should be reviewed periodically against real outcomes. A candidate can widen or narrow the shortlist in Settings without losing the underlying opportunity records.

## Settings

Open **Settings** from the top navigation. Configure:

- Minimum fit score and automatic shortlist behaviour.
- Career tracks to include.
- Visa sponsorship preference.
- Local work-authorisation preference.
- Geographically restricted role preference.
- Hybrid/on-site relocation preference.
- Whether unclear geography remains visible for manual review.
- Whether stale listings should be shown.
- Adaptive, mobile or desktop workspace mode.
- Default application mode: manual apply pack or assisted browser workflow.

Adaptive mode uses a responsive layout based on viewport width. Mobile and desktop settings are presentation preferences; they do not change candidate data or application permissions.

## Database architecture (v13)

The application now selects a primary persistence backend through `DATABASE_BACKEND`. SQLite is the development default, Firestore is the production default when `APP_ENV=production`, and PostgreSQL remains an optional supported relational backend. The web process and discovery worker must use identical backend and credential configuration. There is no silent fallback: a Firestore outage makes readiness fail rather than redirecting writes to a local SQLite file.

### Development: SQLite

```env
APP_ENV=development
DATABASE_BACKEND=sqlite
DATABASE_URL=sqlite:///./opportunities.db
```

### Production: Firestore (recommended/default)

```env
APP_ENV=production
DATABASE_BACKEND=firestore
FIREBASE_PROJECT_ID=your-firebase-project-id
GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/firebase-service-account.json
```

The service account file must be mounted as a deployment secret and must never be committed. Application Default Credentials may be used where the runtime identity is configured securely. Firestore is the primary source of truth in this mode. The principal collections are `opportunities`, `applications`, `company_watches`, `discovery_runs`, `documents`, `gmail_connections`, and `email_send_records`; candidate profile and preferences are stored as singleton documents in `candidates/primary` and `preferences/primary`. Numeric record IDs are allocated using `_system` counter documents.

Candidate profile and preferences are read from and written to Firestore in Firestore mode. Uploaded document binaries and browser session state are not Firestore documents: keep them on a persistent private volume or migrate document binaries to Firebase Storage before using ephemeral hosting. Firestore records retain document metadata and stored paths.

### Alternative: PostgreSQL

```env
APP_ENV=production
DATABASE_BACKEND=postgresql
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME
```

PostgreSQL remains available as a selectable alternative; it is not used as a Firestore mirror. SQLite and PostgreSQL use the existing SQLAlchemy relational implementation.

### Migration from an existing relational database

1. Back up the source database and candidate document directory.
2. Configure `SOURCE_DATABASE_URL` to the SQLite or PostgreSQL source.
3. Configure `FIREBASE_PROJECT_ID` and Google credentials.
4. Run `python scripts/migrate_relational_to_firestore.py`.
5. Verify the reported record counts and inspect representative opportunities, applications, Gmail records and watchlists in Firestore.
6. Deploy both web and worker with `APP_ENV=production` and `DATABASE_BACKEND=firestore`.

The migration script preserves existing numeric IDs and does not modify the source database. Run it once against a backed-up source; do not run concurrent migrations while the source is changing. Candidate profile/preferences JSON can be imported by saving them through their profile/settings screens after switching, or copied to the corresponding singleton documents.

### Firestore rules, indexes and scaling note

`firebase/firestore.rules` denies direct client SDK access. The application uses the Firebase Admin SDK server-side, which bypasses client security rules; protect the service account and keep the app private behind authentication. `firebase/firestore.indexes.json` is the deployment index manifest. The current compatibility query adapter reads collection documents and applies some legacy SQLAlchemy-style predicates in application code to preserve existing route behaviour. This is a functional migration bridge, not the final high-scale query optimisation: large collections should be moved to explicit indexed repository methods with cursor pagination before broad multi-user or high-volume deployment. Review Firestore read costs and query behaviour under realistic data volumes.

### Health and failure behaviour

`GET /health` checks the configured primary backend. In Firestore mode it attempts a Firestore health document read and returns HTTP 503 if Firestore is unreachable. It does not silently switch to SQLite or PostgreSQL. The worker uses the same backend selection and fails its scan if the primary store is unavailable.

### Backups and security

Enable scheduled Firestore exports to a protected Cloud Storage bucket and test restore procedures. Back up document binaries separately. Restrict service-account IAM permissions to the required Firestore and Storage resources. Do not expose Admin credentials to the browser. The included deny-all client rules are intentional until Firebase Authentication and per-user ownership rules are implemented. This release remains designed for a private, single-candidate workspace, not an unauthenticated public multi-tenant service.

## Version 8 dashboard sections

- **Briefing:** last scan, indexed/stale context and three action cards.
- **Radar:** default shortlist, filters, fit score, track, location signal and expandable eligibility reasoning/evidence.
- **Workspace:** active application pipeline, candidate asset library and employer watchlist.
- **Portable records:** Excel and CSV exports.

The full index remains available through **All opportunities**. It is intentionally not the default landing view.


## Candidate Intelligence Profile

Open `/candidate-profile` to maintain the structured candidate record used by matching and application drafting. It stores editable identity/contact details, professional summary, skills, education, employment history, projects, achievements, languages and career interests in `data/candidate_profile.json` (override with `CANDIDATE_PROFILE_PATH`). The factual project/evidence catalogue in `app/profile.py` remains a separate reference. User-entered details are not independently verified; review them before use. This JSON file must live on persistent storage and be backed up. On multi-replica deployments, mount shared storage or move this profile store to a shared database before running multiple web replicas.

## Gmail direct application email (v11.1)

The `/gmail` integration sends a reviewed application message through the candidate's connected Gmail account. OAuth uses PKCE and requests `openid`, `email`, and `https://www.googleapis.com/auth/gmail.send`; it does not request mailbox read access. The application password is never requested. OAuth tokens are encrypted with Fernet before storage in `gmail_connections`.

### Google Cloud setup

1. Create/select a Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen. While in Testing, add the connecting Google account as a test user. Complete Google's verification requirements before broad public distribution.
3. Create an OAuth Client ID of type **Web application**.
4. Register the exact callback URI `https://YOUR_PUBLIC_HOST/gmail/oauth/callback` as an authorised redirect URI. Set `GMAIL_REDIRECT_URI` to the same exact URI when behind a reverse proxy.
5. Store the downloaded OAuth client JSON outside the repository and set `GOOGLE_OAUTH_CLIENT_FILE`, or provide its JSON through the `GOOGLE_OAUTH_CLIENT_CONFIG` secret.
6. Generate a Fernet key using `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` and set `GMAIL_TOKEN_ENCRYPTION_KEY`.
7. Set a long random `SECRET_KEY`, enable HTTPS, configure private workspace authentication, and preserve both secrets across deployments. Losing the Fernet key makes existing stored tokens unreadable; reconnect Gmail after key rotation.
8. Deploy, visit `/gmail`, and connect the account.

### Email workflow and safety

- An application must be audited and approved before the direct-email form is available.
- The candidate reviews recipient, subject, body, and attachments, then enters `I APPROVE THIS EMAIL TO BE SENT` for that message.
- The system attaches the tailored CV and cover letter as PDFs and sends through Gmail.
- Gmail retains the message in **Sent**. BCC-to-self is enabled by default and requests a separate copy in the sender's Inbox; the user can disable it per message. Inbox placement is subject to Gmail filtering and cannot be guaranteed.
- A send-intent record is committed before calling Gmail. Confirmed sends are marked `sent`; ambiguous network/API outcomes are marked `unknown`. **Check Gmail Sent and the activity ledger before retrying an `unknown` send**, because Gmail may have accepted it before the connection failed.
- Sending is never automatic. Each email requires an individual explicit approval.

## Technical architecture and data flow

- **FastAPI** (`app/main.py`) serves the dashboard, candidate profile, settings, opportunity/application workspace, exports and Gmail integration.
- **Backend selector** (`app/database.py`) selects SQLite, Firestore or PostgreSQL from `DATABASE_BACKEND`.
- **Firestore adapter** (`app/firestore_database.py`) is the primary production persistence implementation. It maps the existing model/query surface to Firestore collections and rehydrates application/job relationships used by the UI.
- **Relational models** (`app/models.py`) continue to define the shared record shape for SQLite/PostgreSQL and the Firestore compatibility adapter.
- **Discovery worker** (`app/worker.py`) uses the same configured backend as the web service.
- **Candidate profile/preferences** are persisted in Firestore singleton documents when Firestore is selected; in relational modes they remain local JSON files.
- **Candidate document binaries and browser sessions** remain in private file storage. They are not automatically moved into Firestore; use persistent volumes or migrate binaries to Firebase Storage before ephemeral production hosting.

### End-to-end system flow

1. **Discover:** the worker queries enabled public sources and employer watchlists.
2. **Normalize and persist:** source records are normalized and deduplicated by canonical posting URL, then stored in the selected primary database with source and discovery metadata.
3. **Qualify:** scoring assigns a heuristic fit score and career track. Location/work-authorisation clues are extracted as evidence, then candidate preferences determine shortlist visibility. These are review signals, not legal determinations or hiring probabilities.
4. **Review:** the dashboard presents a concise shortlist and action queues. The full opportunity index remains accessible.
5. **Prepare:** the candidate starts an application. The generator drafts a tailored CV and cover letter using the candidate profile and uploaded CV/evidence where available.
6. **Audit:** required information, evidence and unsupported claims are checked. The candidate edits and approves the package.
7. **Execute:** use the manual application pack, supported assisted browser workflow, or direct Gmail email channel. CAPTCHA, MFA and unsupported forms remain manual checkpoints.
8. **Confirm:** external submission is not inferred from a click. The candidate records portal confirmation; Gmail sends are logged with the Gmail message ID and status.
9. **Export:** CSV/XLSX ledgers are generated from the configured primary database.

### Database configuration

See [Database architecture (v13)](#database-architecture-v13) for SQLite development, Firestore production and PostgreSQL alternative configuration. The same `APP_ENV`, `DATABASE_BACKEND`, Firebase project and credential settings must be configured for both web and worker services.

### Deployment topology

1. Provision a Firebase project and enable Cloud Firestore (or provision PostgreSQL only if selecting the relational alternative).
2. Deploy the Dockerfile as the web service.
3. Deploy a second service from the same image with command `python -m app.worker`.
4. Set the same `APP_ENV`, `DATABASE_BACKEND`, Firebase credentials (or `DATABASE_URL` for relational mode), `SECRET_KEY` and asset-volume paths for both services.
5. Set `ENABLE_SCHEDULER=false` on web and `ENABLE_SCHEDULER=true` on worker.
6. Mount persistent private storage for candidate uploads, browser sessions and JSON profile/preferences. Do not assume container-local files survive redeploys.
7. Configure optional AI/source API keys and Gmail OAuth secrets.
8. Enable HTTPS and `ENABLE_BASIC_AUTH=true` with a long unique `APP_PASSWORD` for the private single-user deployment.

### Health and operational checks

`GET /health` checks the selected primary backend and returns HTTP 503 when it cannot be reached. It does not certify that Gmail OAuth, external job feeds or browser automation are operational. Those integrations must be tested separately in the deployed environment.

## Security and production boundaries

- This is a private, single-candidate workspace, not a multi-tenant SaaS. Basic authentication is optional and must be enabled for an internet-accessible private deployment.
- State-changing browser requests reject an explicitly cross-origin `Origin`; this is a lightweight same-origin guard, not a replacement for a full CSRF-token/session framework.
- Use HTTPS. Keep OAuth client secrets, Fernet key, `SECRET_KEY`, Firebase credentials and API keys outside source control.
- Gmail tokens are encrypted at rest, but anyone with database access plus the encryption key can decrypt them. Restrict both.
- Firestore is the primary database when `DATABASE_BACKEND=firestore`; it is not a best-effort mirror. PostgreSQL is an optional alternative.
- In Firestore mode, profile/preferences are Firestore documents; uploaded document binaries and Playwright browser profiles remain separate and need persistent storage and backups.
- Do not expose this build as a public multi-user service without account isolation, a full authentication/session system, CSRF tokens, per-user data ownership and stronger secret management.
- Browser automation is constrained by site design, CAPTCHA, MFA, bot controls and legal terms. Never bypass those controls.

## Version 13.2 implementation notes

- Added explicit opportunity-type classification for internships, fellowships, graduate programmes, research opportunities, early-career programmes, part-time employment and full-time employment.
- Added targeted internship and early-career discovery terms to Himalayas, Adzuna and Brave Search queries. These run only when the corresponding source is enabled and configured.
- Added opportunity-type filtering to the dashboard and classification to CSV/XLSX exports.
- Internship and early-career classification is based on explicit listing language. It does not infer that every junior or analyst vacancy is an internship.

## Version 13.0 implementation notes

- Firestore is the primary production persistence backend; SQLite remains the development default and PostgreSQL remains selectable.
- Added backend-aware `/health` readiness response for SQLite, Firestore and PostgreSQL.
- Added same-origin checks for browser state-changing requests.
- Added pre-send email intent records and an `unknown` state for ambiguous Gmail outcomes to reduce accidental duplicate sends.
- Added Gmail activity status display and aligned navigation between dashboard, settings, candidate profile and Gmail.
- Hardened narrow-screen layouts, horizontal overflow, nav scrolling, opportunity rows and Gmail activity table.
- Existing unit tests and route smoke checks should be run after deployment; live Gmail delivery, production PostgreSQL, Firestore credentials and external source APIs require environment-specific verification.

## Application quality standard (v13.1)

Opportunity Intelligence is designed to prioritise application quality over application volume. It should not optimise for the number of drafts produced or applications sent. The objective is to prepare a smaller number of convincing, accurate, role-specific applications.

### Drafting principles

- Every application is generated against the actual vacancy, not from a universal cover-letter template. The drafting prompt identifies the role's important responsibilities and selects candidate evidence that best supports those requirements.
- The narrative emphasis should change by role. Product, growth, GTM, strategy, investment research and policy applications should not all tell the same story or lead with the same project.
- CVs preserve factual chronology, employers, dates and qualifications from the source CV. Tailoring may prioritise and reorganise relevant evidence, but must not fabricate or silently remove material experience.
- Cover letters should make a concise argument for fit, supported by specific candidate examples. Generic enthusiasm, corporate filler, repeated job-description language and unsupported claims are discouraged.
- Screening answers are generated question by question. Each answer should respond to the question's actual purpose, use a relevant example, and respect requested length and format. Unknown personal, sensitive and eligibility questions are returned for candidate input, never guessed.
- The CV, cover letter and screening answers should complement one another rather than repeat the same paragraphs.
- Plain punctuation is used. Em dashes and en dashes are not used in generated application materials.

### Editorial quality gate

Draft generation includes a deterministic editorial review for cover-letter length, generic phrasing, named candidate evidence, vacancy-language alignment and verification warnings. The result is a review signal, not a measure of hiring probability and not proof of quality. The application approval audit also checks for generic language, missing concrete evidence, excessive or insufficient length, and prohibited dash punctuation. These issues block approval until the candidate edits the draft.

The AI drafting mode uses a role-specific editorial prompt and structured candidate evidence. If AI drafting is unavailable, the application falls back to a clearly labelled starting draft. The fallback is not represented as a finished bespoke application. It must be edited and reviewed before approval.

### Quality over volume operating rule

A role should be skipped when the evidence does not support a credible application, the eligibility position is unclear, or the vacancy is too poorly described to tailor responsibly. Do not lower the standard merely to increase daily application counts. The candidate reviews every CV, letter, screening answer, employer form field, recipient and attachment. External submission and email sending remain individually authorised actions.

### Known limitations

Automated quality checks cannot reliably judge originality, persuasiveness, factual nuance, employer culture or whether a candidate's motivation is genuine. AI-generated content can still be wrong or generic. The candidate must read every answer in full and correct it. The product does not guarantee an interview or application outcome.

## Application-channel intelligence (v12)
Each discovered opportunity is classified as `direct_email`, `ats`, `employer_portal`, `external_form`, or `unknown`. The classifier uses explicit wording in the listing and the application destination host. It extracts a recipient only when application-specific instructions identify an email address. A generic contact address is not enough. The job workspace displays the method, confidence and evidence; extracted email addresses are prefilled but must be verified by the candidate. Unknown or low-confidence cases remain reviewable rather than being guessed. Gmail sending still requires an approved application package and the exact per-message authorisation phrase.

**Database status:** v13 selects Firestore as the primary production persistence backend, SQLite for development and PostgreSQL as an optional relational alternative. Firestore currently uses a compatibility session adapter for legacy query patterns; optimise collection scans into indexed repository queries before scaling to large multi-user workloads. Live Firestore credentials/emulator integration and production data restore must be verified in the deployment environment.

## Brave Search configuration

Set `BRAVE_SEARCH_API_KEY` on the server. The platform uses three separate Brave endpoints: Web Search for broad URL discovery, LLM Context for pre-extracted page content, and News Search as an experimental source for recruitment announcements. The latter is filtered by recruitment-related signals and should be monitored for false positives.

`BRAVE_SCAN_INTERVAL_HOURS` defaults to `24` and is applied independently to each Brave endpoint. A normal scheduled scan therefore does not repeatedly spend Brave requests every 30 minutes. A forced discovery run bypasses these Brave cooldowns, so use it sparingly.

LLM Context returns query-relevant extracted snippets, not a guaranteed complete copy of every job page. The original employer or application URL remains the source of truth. The existing OpenAI classifier continues to interpret listing evidence; Brave Answers is not used to decide eligibility or fit.



## v13.4.2 performance notes

This update adds per-session Firestore collection snapshot reuse, reduces relationship hydration for count queries, bounds dashboard opportunity loading, adds slow-request timing logs, and creates relational indexes for common dashboard filters/orderings.

The Firestore compatibility adapter still scans each relevant collection once per request/session and filters most predicates in Python. For larger datasets, replace compatibility queries with native indexed Firestore repository methods or use PostgreSQL for the query-heavy application workload.

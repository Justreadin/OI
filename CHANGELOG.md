## 13.4.5 - MyJobMag source integration

- Added MyJobMag Nigeria discovery across jobs, internships and graduate/internship keyword listings.
- Added robots.txt checks, conservative same-site listing extraction, original URL retention and daily cooldown.
- Added parser and metadata regression tests.
- Preserved the v13.4.4 TemplateResponse compatibility fix and performance improvements.

## 13.4.4 - Template compatibility and asynchronous scan release

- Corrected all five Jinja2 template responses to use the current Starlette/FastAPI `TemplateResponse(request, name, context)` calling convention. Removed `request` from the template context dictionaries to prevent `TypeError: unhashable type: 'dict'`.
- Preserved the performance and diagnostics work from 13.4.2, including per-request Firestore snapshot reuse, cheaper count operations, bounded dashboard working sets, slow-request logging and relational indexes.
- Preserved global Brave discovery (`country=ALL`) across web, LLM Context and news endpoints, with per-source cooldowns.
- Preserved the non-blocking scan interface: scans start through `/api/scan`, run outside the request handler, expose status through `/api/scan/status`, and update the dashboard without a full-page navigation.
- This release is verified by Python compilation, ZIP integrity checks and the automated test suite where dependencies permit. Live Firestore, Brave API and multi-process scan coordination are not claimed as tested.

## 13.4.1 - Discovery resilience and classifier opt-out

- Disabled optional OpenAI opportunity classification by default. It can be explicitly enabled with `ENABLE_AI_CLASSIFICATION=true`; AI application drafting remains independently configurable with `OPENAI_API_KEY`.
- Corrected Brave country targeting to use the documented uppercase `NG` country code across web, news and LLM Context requests.
- Expanded Brave API error logging to include response validation details, making future 4xx parameter errors diagnosable.
- Added regression tests for disabled-by-default classification and Brave country parameter casing.

## 13.4.0 - Brave discovery enrichment

- Added Brave LLM Context ingestion using pre-extracted page snippets and source metadata.
- Retained standard Brave Web Search for broad opportunity discovery.
- Added experimental Brave News Search with recruitment-signal filtering.
- Added independent per-source cooldowns, defaulting to 24 hours, to control request usage.
- Added Nigeria-targeted search locale, bounded result/context sizes, and graceful API failure handling.
- Kept OpenAI classification and evidence-based candidate scoring separate from Brave retrieval.

## 13.3.0 - Hybrid opportunity intelligence
- Added optional GPT-6 Luna interpretation for ambiguous opportunity classifications, with deterministic rules retained as the first pass.
- Added structured output validation, taxonomy checks, bounded in-process result caching, short timeouts and graceful fallback when the API is unavailable.
- Kept geographic eligibility and candidate-fit scoring deterministic. Remote or Africa-wide wording alone no longer confirms Nigerian eligibility; explicit country restrictions take precedence.
- Separated opportunity classification from candidate-fit scoring. AI classification never assigns a fixed fit score.
- Added candidate track preference weighting and retained evidence snippets for review.
- Added tests for ambiguous classification, strict geographic cases, structured output validation and API request construction.

# Changelog

## 13.2.0
- Added opportunity-type classification for internships, fellowships, graduate programmes, research opportunities, early-career programmes, part-time employment and full-time employment.
- Added internship and early-career search terms to configured discovery providers.
- Added opportunity-type filtering to the dashboard.
- Added opportunity type to opportunity/application CSV and Excel exports.
- Added regression tests to prevent junior analyst roles being incorrectly labelled as internships.

# Changelog

## 8.0.0  -  Intelligence briefing and candidate-controlled qualification

- Replaced the database-first home screen with a briefing-first dashboard: action queue, shortlist radar, application workspace, asset library, watchlist and portable exports.
- Added a dedicated Settings page for minimum fit score, career tracks, geography, visa sponsorship, local work-authorisation, relocation/hybrid willingness, unverified location handling, stale listing visibility, workspace mode and default application submission mode.
- Added evidence snippets extracted from vacancy text for Nigeria/Africa/worldwide location signals, country restrictions and visa sponsorship. The job detail/radar can show the source wording behind the eligibility signal.
- Added automatic shortlist qualification: fit threshold, selected tracks, recency, application state and location preferences are applied before roles reach the default radar.
- Added responsive mobile/desktop/adaptive presentation preference. Adaptive is the default.
- Added optional Firestore production change mirror, activated only when APP_ENV=production and Firebase credentials/project are configured. SQLite remains the transactional query database in this release; Firestore is a mirror, not yet a drop-in replacement for the SQL repository.
- Preserved explicit human review and final-submission authorization gates.

## 7.0.0
- Added multi-source discovery, ATS-aware form inspection/filling, multi-page progress, application audits, exports, candidate document vault and worker deployment support.

## 9.0.0  -  Candidate eligibility controls and responsive hardening
- Added optional candidate settings for country of residence, citizenship, immigration/residence status, countries with existing work authorisation, countries where sponsorship is needed, work-authorisation filtering approach, and relocation preference.
- Kept all immigration/work-permission details user-controlled and optional. The system does not infer legal eligibility or complete legal declarations.
- Applied configured authorisation-country and relocation preferences to shortlist filtering where the listing provides matching text signals.
- Hardened dashboard and settings layouts for narrow phones, tablets, desktop widths, long labels, navigation overflow, form controls, and reduced-motion preferences.
- Preserved manual application submission as the default and explicit approval as a hard gate.

## 11.0.0  -  Gmail application email
- Added Google OAuth 2.0 authorization with PKCE and minimal send-only Gmail access plus verified account identity.
- Added encrypted-at-rest OAuth token storage and refresh-token handling.
- Added Gmail connection management and recent send history.
- Added per-application direct email composition for approved applications, with tailored CV and cover letter PDF attachments.
- Added mandatory per-message approval phrase; no background or automatic sending.
- Added default BCC-to-self so a separate copy arrives in the connected Gmail Inbox; Gmail also retains the original in Sent.
- Added delivery records with Gmail message ID and timestamp.
- Documented Google Cloud OAuth setup, deployment secrets, HTTPS and private-workspace security requirements.

## 10.0.0  -  Candidate Intelligence Profile
- Added a persistent, editable candidate profile for identity, contact details, professional summary, skills, education, experience, projects, achievements, languages and career interests.
- Added `/candidate-profile` editor and linked it from Settings.
- Application drafting now consumes the saved candidate details alongside the existing evidence catalogue; existing verification warnings and constraints remain intact.
- `/api/profile`, application form packs and downloadable email drafts use the editable candidate contact details.
- Documented the distinction between an email draft export and actual Gmail sending. Gmail OAuth sending is implemented in v11.0.0.


## 11.1.0  -  Final alignment and operational hardening
- Added SQL database readiness check to `/health`.
- Added same-origin guard for state-changing browser requests.
- Added pre-send email intent persistence and `unknown` status for uncertain Gmail outcomes.
- Added Gmail send status to activity history.
- Aligned dashboard/settings/profile/Gmail navigation and responsive layouts.
- Rewrote deployment, architecture, data-flow, Gmail and database documentation to accurately describe production boundaries.


## 12.0.0 - Application-channel intelligence
- Added evidence-based application-channel classification: direct email, ATS, employer portal, external form, or unknown.
- Extracts an employer email only when the listing contains an explicit application instruction; generic contact addresses are not treated as application recipients.
- Stores channel, confidence, extracted recipient, and evidence on each opportunity and refreshes those fields on rediscovery.
- Displays the detected application method and evidence in the opportunity workspace; pre-fills Gmail recipient when extracted and warns when the method is not confidently direct email.
- Added focused classifier tests. Firestore-primary database migration is not included in this release; v11.1's SQLAlchemy database remains authoritative until the repository/data-access refactor is completed and validated.

## 13.0.0  -  Firestore-primary production backend
- Added explicit backend selection: SQLite for development, Firestore for production, PostgreSQL as an optional alternative.
- Added Firestore-backed session/query compatibility layer and primary Firestore collections for opportunities, applications, watchlists, discovery runs, documents and Gmail records.
- Moved candidate profile and preferences persistence to Firestore when Firestore is selected.
- Updated web startup, health checks and discovery worker to use the selected primary backend without silent fallback.
- Added relational-to-Firestore migration utility, deny-by-default Firestore rules and index manifest.
- Documented Firestore migration, deployment, backup, security and query-scaling limitations.

## 13.1.0 - Application quality controls

- Reworked application drafting to prioritise vacancy-specific reasoning and relevant candidate evidence over generic template copy.
- Added differentiated drafting instructions for CVs and cover letters, with strict factual preservation and attribution rules.
- Reworked screening-answer generation so each question receives an independent, evidence-grounded response or an explicit candidate-input request.
- Added editorial quality signals and approval blockers for generic language, missing concrete evidence, weak cover-letter length and prohibited dash punctuation.
- Clearly labels deterministic fallback drafts as starting points rather than finished bespoke applications.
- Standardised user-facing project copy to avoid em dashes and en dashes.


## v13.4.2 Performance and diagnostics

- Added per-request Firestore collection snapshot reuse to avoid repeatedly streaming the same collections for each query in a single request.
- Firestore count operations no longer hydrate Job/Application relationships that are not needed for counts.
- Bounded the dashboard working set to the top 1,000 matching opportunities before applying the shortlist presentation rules.
- Added slow-request logging for requests taking at least 750 ms, including method, path, and duration.
- Added relational indexes for active opportunity ordering/filtering and application status/update ordering.
- Corrected the Brave LLM Context test expectation to require global `country=ALL`, not unsupported Nigeria `NG`.
- Made Brave response handling compatible with successful lightweight transports/test doubles that do not expose an HTTP status attribute.

### Known limitation

The Firestore compatibility query layer still reads complete collections once per session/request and applies most filters in Python. This release reduces duplicate reads within a request but does not replace the compatibility layer with fully indexed Firestore repository queries. A larger dataset will still benefit from native Firestore query translation or a relational query backend such as PostgreSQL.

## 13.5.0 - UI refresh
- Reworked the visual system to a restrained black, white and neutral-grey product interface.
- Standardized navigation, typography, cards, forms, tables, detail pages and responsive layouts.
- Added server-rendered opportunity pagination with selectable page sizes and preserved filters.
- Kept existing backend workflows and application safeguards intact.

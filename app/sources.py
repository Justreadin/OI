"""Respectful, deduplicated vacancy ingestion from public feeds and employer ATS job boards."""
import asyncio, json, logging, re, urllib.parse, urllib.robotparser, socket, ipaddress, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import httpx
from sqlalchemy import text as sql_text
from bs4 import BeautifulSoup
from app.config import settings
from app.models import Job, CompanyWatch, DiscoveryRun

log=logging.getLogger(__name__)
UA="OpportunityIntelligence/1.0 (+personal job research; contact configured operator)"
TIMEOUT=httpx.Timeout(25.0,connect=10.0)
LIMIT=max(50,min(settings.max_jobs_per_source,500))
_PENDING_URLS=set()

def upsert(db,source,sid,company,title,location,description,url,published=""):
    if not title or not url: return 0
    try:
        p=urllib.parse.urlparse(str(url))
        if p.scheme not in ("http","https") or not p.netloc:return 0
    except Exception:return 0
    url=str(url).split("#")[0][:2000]
    if url in _PENDING_URLS:return 0
    old=db.query(Job).filter_by(url=url).first()
    _PENDING_URLS.add(url)
    from app.scoring import score_job_detailed, classify_opportunity_type
    from app.application_channels import classify_application_channel
    channel=classify_application_channel(str(description or ""), url)
    prefs={}
    try:
        from app.preferences import get_preferences
        prefs=get_preferences()
    except Exception: pass
    score,track,eligibility,reasons,evidence=score_job_detailed(str(title),str(location or ""),str(description or ""),prefs)
    opportunity_type=classify_opportunity_type(str(title),str(description or ""),str(location or ""))
    qualification="excluded" if eligibility=="ineligible" else "qualified" if score >= int(prefs.get("minimum_fit_score",65)) and eligibility!="verify" else "review"
    if old:
        old.score,old.track,old.eligibility,old.reasons=score,track,eligibility,reasons
        old.opportunity_type=opportunity_type
        old.eligibility_evidence=json.dumps(evidence); old.qualification=qualification
        if description:old.description=str(description)[:40000]
        if published and (not old.published_at or str(published)>old.published_at):old.published_at=str(published)[:100]
        old.application_method=channel["method"]; old.application_method_confidence=channel["confidence"]
        old.application_email=channel["recipient"]; old.application_method_evidence=channel["evidence"]
        old.active=True
        old.last_seen_at=datetime.now(timezone.utc)
        return 0
    db.add(Job(source=str(source)[:80],source_id=str(sid or url)[:300],company=str(company or "Unknown")[:300],
      title=str(title)[:500],location=str(location or "Not specified")[:500],
      description=str(description or "")[:40000],url=url,published_at=str(published or "")[:100],
      score=score,track=track,opportunity_type=opportunity_type,eligibility=eligibility,reasons=reasons,eligibility_evidence=json.dumps(evidence),qualification=qualification,application_method=channel["method"],application_method_confidence=channel["confidence"],application_email=channel["recipient"],application_method_evidence=channel["evidence"]))
    return 1

async def _get_json(client,url,params=None):
    r=await client.get(url,params=params);r.raise_for_status()
    return r.json()

async def _client():
    return httpx.AsyncClient(timeout=TIMEOUT,headers={"User-Agent":UA,"Accept":"application/json, text/html;q=0.9,*/*;q=0.8"},follow_redirects=True,
      limits=httpx.Limits(max_connections=12,max_keepalive_connections=6))

MYJOBMAG_BASE = "https://www.myjobmag.com"
MYJOBMAG_LISTING_PATHS = (
    "/jobs",
    "/internship/",
    "/jobs-by-title/graduate-trainee",
    "/jobs-by-title/internship-positions",
)


def _myjobmag_listing_cards(soup, page_url):
    """Extract job cards conservatively from MyJobMag listing pages.

    The site has changed its markup over time, so this uses semantic anchors and
    nearby card containers rather than relying on one generated CSS class.
    Only same-site job-detail links are accepted.
    """
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(page_url, anchor.get("href", ""))
        parsed = urllib.parse.urlparse(href)
        path = parsed.path.rstrip("/")
        label = anchor.get_text(" ", strip=True)
        if parsed.scheme != "https" or parsed.netloc.lower() not in {"www.myjobmag.com", "myjobmag.com"}:
            continue
        if not label or len(label) < 8 or len(label) > 240:
            continue
        # Exclude navigation, search and category pages. Detail URLs on MyJobMag
        # generally have a descriptive slug and are not the known listing routes.
        if path in {"", "/jobs", "/internship"} or path.startswith(("/jobs-by-title/", "/category/", "/tag/", "/company/")):
            continue
        if path in seen:
            continue
        parent = anchor
        for _ in range(5):
            if parent.parent is None:
                break
            parent = parent.parent
            if getattr(parent, "name", None) in ("article", "li"):
                break
            classes = " ".join(parent.get("class", [])) if getattr(parent, "attrs", None) else ""
            if any(token in classes.lower() for token in ("job", "listing", "vacancy", "result", "card")):
                break
        text = parent.get_text(" ", strip=True)
        if len(text) < len(label):
            text = label
        # Avoid collecting general editorial/resource links as vacancies.
        if not any(word in (label + " " + text).lower() for word in (
            "intern", "graduate", "trainee", "analyst", "associate", "officer",
            "manager", "engineer", "assistant", "coordinator", "specialist",
            "research", "programme", "program", "executive", "consultant", "job",
        )):
            continue
        seen.add(path)
        yield {"url": href, "title": label, "card_text": text[:12000]}


def _myjobmag_metadata(card_text, title):
    text = re.sub(r"\s+", " ", card_text or "").strip()
    company = "Unknown"
    match = re.search(r"\s+at\s+(.+?)(?:\s+(?:Date Posted|Posted|Location|Featured|₦)|$)", title, re.I)
    if match:
        company = match.group(1).strip(" -|·")[:300] or company
    published = ""
    date_match = re.search(r"(?:Date Posted\s*:?\s*)?(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?)", text, re.I)
    if date_match:
        published = date_match.group(1)
    location = "Nigeria / see listing"
    loc_match = re.search(r"(?:location icon\s*)?\b(Lagos|Abuja|Oyo|Ondo|Remote|All|Nigeria|Ibadan|Port Harcourt|Ogun|Enugu|Kano|Rivers|FCT)\b(?:\s+and\s+\d+\s+other locations)?", text, re.I)
    if loc_match:
        location = loc_match.group(0).strip()
    return company, location, published


async def myjobmag(db):
    """Ingest public MyJobMag Nigeria job listings, respecting robots.txt.

    This is a conservative HTML listing integration, not an official API. It
    stores the source listing URL and a short listing excerpt; users should open
    the original listing for full requirements and application instructions.
    """
    n = 0
    visited_pages = set()
    async with await _client() as client:
        for path in MYJOBMAG_LISTING_PATHS:
            page_url = urllib.parse.urljoin(MYJOBMAG_BASE, path)
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)
            try:
                if not await robots_ok(page_url):
                    log.info("MyJobMag skipped: robots.txt disallows or cannot be checked for %s", page_url)
                    continue
                response = await client.get(page_url)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                for card in _myjobmag_listing_cards(soup, str(response.url)):
                    title = card["title"]
                    company, location, published = _myjobmag_metadata(card["card_text"], title)
                    # Keep the excerpt as provenance/context, not as a substitute
                    # for the employer's full job description.
                    description = "MyJobMag listing excerpt: " + card["card_text"]
                    n += upsert(db, "MyJobMag", card["url"], company, title,
                                location, description, card["url"], published)
                # Follow only a small number of same-site pagination links from
                # this page, with a strict per-category page cap.
                page_links = []
                for link in soup.find_all("a", href=True):
                    candidate = urllib.parse.urljoin(str(response.url), link["href"])
                    parsed = urllib.parse.urlparse(candidate)
                    if parsed.netloc.lower() not in {"www.myjobmag.com", "myjobmag.com"}:
                        continue
                    if re.search(r"(?:page|pg)[=/_-]?\d+", parsed.path + "?" + parsed.query, re.I):
                        if candidate not in visited_pages:
                            page_links.append(candidate)
                for candidate in page_links[:2]:
                    if candidate in visited_pages:
                        continue
                    visited_pages.add(candidate)
                    try:
                        if not await robots_ok(candidate):
                            continue
                        page_response = await client.get(candidate)
                        page_response.raise_for_status()
                        page_soup = BeautifulSoup(page_response.text, "html.parser")
                        for card in _myjobmag_listing_cards(page_soup, str(page_response.url)):
                            company, location, published = _myjobmag_metadata(card["card_text"], card["title"])
                            description = "MyJobMag listing excerpt: " + card["card_text"]
                            n += upsert(db, "MyJobMag", card["url"], company, card["title"],
                                        location, description, card["url"], published)
                    except Exception as exc:
                        log.warning("MyJobMag pagination failed for %s: %s", candidate, str(exc)[:180])
            except Exception as exc:
                log.warning("MyJobMag listing failed for %s: %s", page_url, str(exc)[:180])
    return n


async def remoteok(db):
    n=0
    async with await _client() as c:
        data=await _get_json(c,"https://remoteok.com/api")
    for j in data:
        if isinstance(j,dict) and j.get("position"):
            n+=upsert(db,"Remote OK",j.get("id"),j.get("company"),j.get("position"),j.get("location") or "Remote",j.get("description"),j.get("url") or j.get("apply_url"),j.get("date"))
            if n>=LIMIT:break
    return n

async def remotive(db):
    # Remotive recommends no more than four requests per day. Worker enforces a 6-hour cooldown.
    n=0
    async with await _client() as c:data=await _get_json(c,"https://remotive.com/api/remote-jobs",{"limit":min(100,LIMIT)})
    for j in data.get("jobs",[]):
        n+=upsert(db,"Remotive",j.get("id"),j.get("company_name"),j.get("title"),j.get("candidate_required_location") or "Remote",j.get("description"),j.get("url"),j.get("publication_date"))
    return n

async def arbeitnow(db):
    n=0
    async with await _client() as c:data=await _get_json(c,"https://www.arbeitnow.com/api/job-board-api")
    for j in data.get("data",[])[:LIMIT]:
        n+=upsert(db,"Arbeitnow",j.get("slug") or j.get("url"),j.get("company_name"),j.get("title"),j.get("location"),j.get("description"),j.get("url"),j.get("created_at"))
    return n

async def jobicy(db):
    n=0
    async with await _client() as c:data=await _get_json(c,"https://jobicy.com/api/jobs",{"count":min(200,LIMIT)})
    for j in data.get("jobs",[])[:LIMIT]:
        n+=upsert(db,"Jobicy",j.get("id"),j.get("companyName"),j.get("jobTitle"),j.get("jobGeo") or "Remote",j.get("jobDescription"),j.get("url"),j.get("pubDate"))
    return n

async def himalayas(db):
    """Discover globally available remote roles; geography is qualified downstream.

    Do not pass a country or worldwide-only filter here. The OI eligibility and
    preference layers decide whether a listing is open to the candidate's regions.
    Himalayas locationRestrictions is an array of objects, not strings.
    """
    n = 0
    queries = [
        "product manager", "product operations", "growth", "business operations",
        "venture capital", "investment research", "policy analyst", "programme analyst",
        "product management internship", "growth internship", "research internship",
        "software engineering internship", "venture capital internship", "policy internship",
    ]
    async with await _client() as c:
        for term in queries:
            try:
                # No country/worldwide filter: return the global result set and let
                # OI's eligibility filters determine regional fit after ingestion.
                data = await _get_json(c, "https://himalayas.app/jobs/api/search", {
                    "q": term, "sort": "recent", "page": 1,
                })
                jobs = data.get("jobs", []) if isinstance(data, dict) else data if isinstance(data, list) else []
                for job in jobs[:20]:
                    restrictions = job.get("locationRestrictions") or []
                    if isinstance(restrictions, list):
                        names = []
                        for item in restrictions:
                            if isinstance(item, dict):
                                name = item.get("name") or item.get("alpha2") or item.get("slug")
                                if name:
                                    names.append(str(name))
                            elif item:
                                names.append(str(item))
                        location = ", ".join(names) if names else "Worldwide / check timezone restrictions"
                    else:
                        location = str(restrictions) if restrictions else "Worldwide / check timezone restrictions"
                    timezone_restrictions = job.get("timezoneRestrictions") or []
                    if timezone_restrictions:
                        location += " | Time zones: " + ", ".join(map(str, timezone_restrictions))
                    # Himalayas publishes pubDate as a millisecond timestamp in
                    # current API responses, but older responses may be ISO text.
                    published = job.get("pubDate") or ""
                    if isinstance(published, (int, float)):
                        try:
                            published = datetime.fromtimestamp(float(published) / 1000, timezone.utc).isoformat()
                        except (OverflowError, OSError, ValueError):
                            published = ""
                    description = job.get("description") or job.get("excerpt") or ""
                    meta = []
                    if job.get("employmentType"):
                        meta.append("Employment type: " + str(job["employmentType"]))
                    seniority = job.get("seniority") or []
                    if seniority:
                        meta.append("Seniority: " + ", ".join(map(str, seniority)) if isinstance(seniority, list) else "Seniority: " + str(seniority))
                    if meta:
                        description = "\n\n".join(meta) + "\n\n" + str(description)
                    url = job.get("applicationLink") or job.get("url")
                    n += upsert(db, "Himalayas", job.get("guid"), job.get("companyName"),
                                job.get("title"), location, description, url, published)
            except Exception as exc:
                log.warning("Himalayas query %s failed: %s", term, str(exc)[:240])
    return n


async def weworkremotely(db):
    n=0
    async with httpx.AsyncClient(timeout=TIMEOUT,headers={"User-Agent":UA},follow_redirects=True) as c:
        r=await c.get("https://weworkremotely.com/remote-jobs.rss");r.raise_for_status()
    feed=ET.fromstring(r.text)
    for item in feed.findall(".//item")[:LIMIT]:
        title=(item.findtext("title") or "").strip()
        link=(item.findtext("link") or "").strip()
        desc=BeautifulSoup(item.findtext("description") or "","html.parser").get_text(" ",strip=True)
        company=title.split(":",1)[0] if ":" in title else "Unknown"
        role=title.split(":",1)[-1].strip()
        pub=(item.findtext("pubDate") or "").strip()
        n+=upsert(db,"We Work Remotely",link,company,role,"Remote",desc,link,pub)
    return n

async def adzuna(db):
    if not settings.adzuna_app_id or not settings.adzuna_app_key:return 0
    n=0
    terms=["associate product manager","product manager","technical product","product operations",
      "growth associate","product growth","GTM associate","product marketing","business operations",
      "founder associate","venture capital analyst","investment analyst","research analyst",
      "policy analyst","programme analyst","public sector innovation","product internship","growth internship","research internship",
      "software engineering internship","business analyst internship","policy internship",
      "graduate trainee","graduate programme","fellowship"]
    async with await _client() as c:
        sem=asyncio.Semaphore(4)
        async def fetch(term):
            async with sem:
                return await c.get("https://api.adzuna.com/v1/api/jobs/ng/search/1",
                    params={"app_id":settings.adzuna_app_id,"app_key":settings.adzuna_app_key,
                            "results_per_page":50,"what":term})
        responses=await asyncio.gather(*(fetch(t) for t in terms),return_exceptions=True)
    for r in responses:
        if isinstance(r,Exception) or r.status_code!=200:continue
        for j in r.json().get("results",[]):
            n+=upsert(db,"Adzuna",j.get("id"),j.get("company",{}).get("display_name"),
                j.get("title"),j.get("location",{}).get("display_name","Nigeria"),
                j.get("description"),j.get("redirect_url"),j.get("created"))
    return n

async def greenhouse(db,tokens):
    n=0
    async with await _client() as c:
        for token in tokens:
            try:
                data=await _get_json(c,f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(token,safe='')}/jobs",{"content":"true"})
                for j in data.get("jobs",[]):
                    n+=upsert(db,"Greenhouse",j.get("id"),token,j.get("title"),
                        ", ".join(x.get("name","") for x in j.get("offices",[])),
                        j.get("content"),j.get("absolute_url"),j.get("updated_at"))
            except Exception as e:log.warning("Greenhouse board %s: %s",token,str(e)[:160])
    return n

async def ashby(db,boards):
    n=0
    async with await _client() as c:
        for board in boards:
            try:
                data=await _get_json(c,f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(board,safe='')}")
                for j in data.get("jobs",[]):
                    if j.get("isListed") is False:continue
                    n+=upsert(db,"Ashby",j.get("id"),board,j.get("title"),j.get("location"),
                        j.get("descriptionPlain") or j.get("descriptionHtml"),
                        j.get("jobUrl") or j.get("applyUrl"),j.get("publishedAt"))
            except Exception as e:log.warning("Ashby board %s: %s",board,str(e)[:160])
    return n

async def lever(db,sites):
    n=0
    async with await _client() as c:
        for site in sites:
            for region in ("global","eu"):
                try:
                    host="api.lever.co" if region=="global" else "api.eu.lever.co"
                    data=await _get_json(c,f"https://{host}/v0/postings/{urllib.parse.quote(site,safe='')}",{"mode":"json"})
                    for j in data if isinstance(data,list) else []:
                        cats=j.get("categories") or {}
                        n+=upsert(db,"Lever",j.get("id"),site,j.get("text"),
                            cats.get("location"),j.get("descriptionPlain") or j.get("description"),
                            j.get("hostedUrl"),j.get("createdAt"))
                    break
                except Exception as e:
                    if region=="eu":log.warning("Lever site %s: %s",site,str(e)[:160])
    return n

def _assert_public_https(url):
    p=urllib.parse.urlparse(url)
    if p.scheme!="https" or not p.hostname:raise ValueError("Only public HTTPS career pages are allowed.")
    if p.username or p.password or p.port not in (None,443):raise ValueError("Credentials and non-standard ports are blocked.")
    if p.hostname.lower() in {"localhost","localhost.localdomain"} or p.hostname.endswith((".local",".internal")):
        raise ValueError("Private hostnames are blocked.")
    try:
        addresses={x[4][0] for x in socket.getaddrinfo(p.hostname,None)}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ValueError("Private or non-public destinations are blocked.")
    except socket.gaierror:raise ValueError("Career-page hostname could not be resolved.")
    return p

async def robots_ok(url):
    p=_assert_public_https(url)
    try:
        async with httpx.AsyncClient(timeout=8,headers={"User-Agent":UA},follow_redirects=False) as c:
            r=await c.get(f"{p.scheme}://{p.netloc}/robots.txt")
            if r.status_code>=400:return False
            rp=urllib.robotparser.RobotFileParser();rp.parse(r.text.splitlines())
            return rp.can_fetch(UA,url)
    except Exception:return False

async def _safe_career_get(url):
    current=url
    async with httpx.AsyncClient(timeout=TIMEOUT,headers={"User-Agent":UA},follow_redirects=False) as c:
        for _ in range(6):
            _assert_public_https(current)
            response=await c.get(current)
            if response.status_code in (301,302,303,307,308) and response.headers.get("location"):
                current=urllib.parse.urljoin(current,response.headers["location"])
                continue
            response.raise_for_status()
            _assert_public_https(str(response.url))
            return response
    raise ValueError("Too many redirects while opening employer careers page.")

async def career_page(db,watch):
    if watch.last_scanned_at:
        last=watch.last_scanned_at
        last=last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
        if datetime.now(timezone.utc)-last<timedelta(hours=6):return 0
    try:_assert_public_https(watch.career_url)
    except Exception as e:
        watch.last_error=str(e);watch.last_scanned_at=datetime.now(timezone.utc);return 0
    if not await robots_ok(watch.career_url):
        watch.last_error="robots.txt disallows access or could not be checked"
        watch.last_scanned_at=datetime.now(timezone.utc);return 0
    n=0
    try:
        r=await _safe_career_get(watch.career_url)
        soup=BeautifulSoup(r.text,"html.parser")
        base=urllib.parse.urlparse(str(r.url))
        for a in soup.find_all("a",href=True):
            u=urllib.parse.urljoin(str(r.url),a["href"]);p=urllib.parse.urlparse(u)
            path=[x for x in p.path.strip("/").split("/") if x]
            if p.scheme!="https":continue
            if p.netloc=="boards.greenhouse.io" and path:n+=await greenhouse(db,[path[0]])
            elif p.netloc=="jobs.ashbyhq.com" and path:n+=await ashby(db,[path[0]])
            elif p.netloc in ("jobs.lever.co","jobs.eu.lever.co") and path:n+=await lever(db,[path[0]])
            elif p.netloc==base.netloc:
                label=a.get_text(" ",strip=True)
                if len(label)>5 and any(k in (label+" "+u).lower() for k in ["career","vacanc","job opening","apply now","open roles","job/"]):
                    n+=upsert(db,"Company career page",u,watch.name,label,"Company site",
                        "Discovered from employer careers page; open the source for full requirements.",u)
        watch.last_error=""
    except Exception as e:watch.last_error=str(e)[:500]
    watch.last_scanned_at=datetime.now(timezone.utc)
    return n

BRAVE_WEB_QUERIES = [
    '("product manager" OR "product operations" OR "growth associate" OR "GTM") (remote OR distributed) jobs internship',
    '("strategy analyst" OR "chief of staff" OR "founder associate" OR "venture capital analyst" OR "investment research") jobs fellowship',
    '("policy analyst" OR "research assistant" OR "development programme" OR "graduate trainee") opportunities',
    '(internship OR fellowship OR "graduate programme") technology research policy',
]
BRAVE_CONTEXT_QUERIES = [
    'recent official employer career pages and job postings for product, growth, strategy and go-to-market roles worldwide',
    'recent venture capital, investment research, policy and development institution analyst internships or fellowships worldwide',
    'recent internships, research assistantships, graduate programmes and early career opportunities at official employer sites worldwide',
]
BRAVE_NEWS_QUERIES = [
    '(hiring OR recruitment OR "join our team") technology internship fellowship',
    '(internship OR fellowship OR "graduate programme") employer announcement',
]


def _brave_headers():
    return {"User-Agent": UA, "X-Subscription-Token": settings.brave_search_api_key,
            "Accept": "application/json", "Accept-Encoding": "gzip"}


def _brave_error_detail(exc):
    """Include Brave's validation response body so rejected parameters are diagnosable."""
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            detail = response.text.strip()
            if detail:
                return f"HTTP {response.status_code}: {detail[:700]}"
        except Exception:
            pass
    return str(exc)[:700]


async def _brave_get_json(client, endpoint, params):
    """Call a Brave endpoint with bounded retries for transient failures only."""
    last_error = None
    for attempt in range(3):
        try:
            response = await client.get(endpoint, params=params)
            # Lightweight test doubles and compatible transports may omit
            # status_code; a successful raise_for_status() is then sufficient.
            status_code = getattr(response, "status_code", 200)
            if status_code == 429 or status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = min(8.0, max(1.0, float(retry_after))) if retry_after else 2 ** attempt
                except ValueError:
                    delay = 2 ** attempt
                last_error = httpx.HTTPStatusError(
                    f"Brave transient HTTP {status_code}: {getattr(response, 'text', '')[:400]}",
                    request=getattr(response, "request", None), response=response)
                if attempt < 2:
                    await asyncio.sleep(delay)
                    continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            if status != 429 and status < 500:
                raise
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
    if last_error:
        raise last_error
    raise RuntimeError("Brave request failed without a response")


def _brave_listing_signal(title, description, url=""):
    text = f"{title} {description} {url}".lower()
    return any(term in text for term in (
        "apply now", "apply here", "job opening", "job opportunity", "vacancy", "recruitment",
        "intern", "fellowship", "graduate programme", "graduate program", "research assistant",
        "analyst", "associate", "product manager", "growth manager", "policy officer",
        "we are hiring", "we're hiring", "join our team", "open position",
        "career opportunity", "applications are open",
    ))


async def brave_web_discovery(db):
    """Broad, human-readable Brave search for opportunity URLs and snippets."""
    if not settings.brave_search_api_key:
        return 0
    n = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=_brave_headers()) as c:
        for q in BRAVE_WEB_QUERIES:
            try:
                payload = await _brave_get_json(c, "https://api.search.brave.com/res/v1/web/search", {
                    "q": q, "count": 20, "freshness": "pm", "country": "ALL", "search_lang": "en"
                })
                for item in payload.get("web", {}).get("results", []):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    snippet = item.get("description", "")
                    if not url or not title:
                        continue
                    domain = urllib.parse.urlparse(url).netloc.lower()
                    source = "Brave web search"
                    for d, label in [
                        ("opportunitydesk.org", "Opportunity Desk"), ("wellfound.com", "Wellfound search result"),
                        ("indeed.com", "Indeed search result"), ("linkedin.com", "LinkedIn search result"),
                        ("boards.greenhouse.io", "Greenhouse search result"), ("jobs.ashbyhq.com", "Ashby search result"),
                        ("jobs.lever.co", "Lever search result")]:
                        if d in domain:
                            source = label
                            break
                    n += upsert(db, source, url, domain, title, "See original listing", snippet, url,
                                item.get("page_age", ""))
            except Exception as e:
                log.warning("Brave web query failed: %s", _brave_error_detail(e))
    return n


async def brave_llm_context_discovery(db):
    """Search and ingest Brave's pre-extracted page chunks without browser scraping."""
    if not settings.brave_search_api_key:
        return 0
    n = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=_brave_headers()) as c:
        for q in BRAVE_CONTEXT_QUERIES:
            try:
                # Request the global index. Geographic fit is intentionally not
                # decided by Brave; OI's downstream eligibility filters handle it.
                payload = await _brave_get_json(c, "https://api.search.brave.com/res/v1/llm/context", {
                    "q": q, "country": "ALL", "search_lang": "en", "freshness": "pm",
                    "count": 10, "maximum_number_of_urls": 10,
                    "maximum_number_of_tokens": 4096, "maximum_number_of_tokens_per_url": 1024,
                    "context_threshold_mode": "balanced", "enable_source_metadata": True,
                })
                for item in payload.get("grounding", {}).get("generic", []):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    snippets = item.get("snippets", [])
                    description = "\n\n".join(str(x) for x in snippets if x)[:30000]
                    if not url or not title or not description:
                        continue
                    if not _brave_listing_signal(title, description, url):
                        continue
                    parsed = urllib.parse.urlparse(url)
                    source_meta = payload.get("sources", {}).get(url, {})
                    age = source_meta.get("age", [])
                    published = age[3] if isinstance(age, list) and len(age) > 3 else ""
                    n += upsert(db, "Brave LLM context", url, source_meta.get("hostname") or parsed.netloc,
                                title, "See original listing", description, url, published)
            except Exception as e:
                log.warning("Brave LLM context query failed: %s", _brave_error_detail(e))
    return n


async def brave_news_discovery(db):
    """Experimental news-index discovery, filtered to likely recruitment announcements."""
    if not settings.brave_search_api_key:
        return 0
    n = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=_brave_headers()) as c:
        for q in BRAVE_NEWS_QUERIES:
            try:
                payload = await _brave_get_json(c, "https://api.search.brave.com/res/v1/news/search", {
                    "q": q, "count": 20, "freshness": "pw", "country": "ALL", "search_lang": "en"
                })
                for item in payload.get("results", []):
                    url = item.get("url", "")
                    title = item.get("title", "")
                    description = item.get("description", "")
                    if not url or not title or not _brave_listing_signal(title, description, url):
                        continue
                    domain = urllib.parse.urlparse(url).netloc.lower()
                    n += upsert(db, "Brave news search", url, domain, title, "See original announcement",
                                description, url, item.get("page_age") or item.get("published", ""))
            except Exception as e:
                log.warning("Brave news query failed: %s", _brave_error_detail(e))
    return n

async def discover(db,force=False):
    """Serialize scans across the web and worker services when using PostgreSQL."""
    lock_conn=None
    locked=False
    try:
        if db.bind.dialect.name=="postgresql":
            lock_conn=db.connection()
            locked=bool(lock_conn.execute(sql_text("SELECT pg_try_advisory_lock(8172634)")).scalar())
            if not locked:
                log.info("Discovery scan skipped: another service owns the advisory lock.")
                return {"skipped":"another discovery scan is already running"}
        return await _discover_locked(db,force=force)
    finally:
        if locked and lock_conn is not None:
            try:lock_conn.execute(sql_text("SELECT pg_advisory_unlock(8172634)"))
            except Exception:log.exception("Could not release discovery advisory lock")

async def _discover_locked(db,force=False):
    _PENDING_URLS.clear()
    run=DiscoveryRun(status="running");db.add(run);db.commit()
    stats={}
    history=db.query(DiscoveryRun).filter(DiscoveryRun.status=="complete").order_by(DiscoveryRun.finished_at.desc()).limit(200).all()
    def last_success_for(source):
        for prior in history:
            try:value=json.loads(prior.source_results or "{}").get(source)
            except Exception:value=None
            if isinstance(value,int) and prior.finished_at:
                stamp=prior.finished_at
                return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        return None
    def last_attempt_for(source):
        for prior in history:
            try: results_for_run=json.loads(prior.source_results or "{}")
            except Exception: results_for_run={}
            if source in results_for_run and prior.finished_at:
                stamp=prior.finished_at
                return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        return None
    def source_due(source, hours):
        # Cool down failures too, otherwise a broken credential or exhausted quota
        # would be retried on every 30-minute worker cycle.
        last=last_attempt_for(source)
        return force or not last or datetime.now(timezone.utc)-last >= timedelta(hours=hours)
    tasks=[
      ("Remote OK",remoteok(db)),
      ("Arbeitnow",arbeitnow(db) if settings.arbeitnow_enabled else asyncio.sleep(0,result=0)),
      ("Jobicy",jobicy(db) if settings.jobicy_enabled else asyncio.sleep(0,result=0)),
      ("We Work Remotely",weworkremotely(db) if settings.weworkremotely_enabled else asyncio.sleep(0,result=0)),
      ("Adzuna",adzuna(db)),
      ("Greenhouse",greenhouse(db,settings.csv(settings.greenhouse_board_tokens))),
      ("Ashby",ashby(db,settings.csv(settings.ashby_board_names))),
      ("Lever",lever(db,settings.csv(settings.lever_sites))),
    ]
    brave_hours=max(1,min(168,int(settings.brave_scan_interval_hours or 24)))
    brave_sources=[
        ("Brave web search", brave_web_discovery),
        ("Brave LLM context", brave_llm_context_discovery),
        ("Brave news search", brave_news_discovery),
    ]
    if settings.brave_search_api_key:
        for name,func in brave_sources:
            if source_due(name,brave_hours):
                tasks.append((name,func(db)))
            else:
                stats[name]=f"skipped: {brave_hours}-hour cooldown"
    else:
        for name,_ in brave_sources:
            stats[name]="skipped: API key not configured"
    remotive_last=last_success_for("Remotive")
    if not remotive_last or datetime.now(timezone.utc)-remotive_last>timedelta(hours=6):
        tasks.append(("Remotive",remotive(db)))
    else:stats["Remotive"]="skipped: six-hour rate-limit cooldown"
    himalayas_last=last_success_for("Himalayas")
    if settings.himalayas_enabled and (not himalayas_last or datetime.now(timezone.utc)-himalayas_last>timedelta(hours=24)):
        tasks.append(("Himalayas",himalayas(db)))
    elif settings.himalayas_enabled:
        stats["Himalayas"]="skipped: 24-hour refresh cooldown"
    # MyJobMag is a high-value Nigeria/Africa source. Refresh daily; the
    # collector respects robots.txt and keeps the original listing URL.
    myjobmag_last=last_attempt_for("MyJobMag")
    if source_due("MyJobMag", 24):
        tasks.append(("MyJobMag", myjobmag(db)))
    else:
        stats["MyJobMag"]="skipped: 24-hour refresh cooldown"
    results=await asyncio.gather(*(task for _,task in tasks),return_exceptions=True)
    for (name,_),result in zip(tasks,results):
        stats[name]=("error: "+str(result)[:180]) if isinstance(result,Exception) else int(result)
    for item in db.query(CompanyWatch).filter_by(enabled=True).all():
        try:stats["Company: "+item.name]=await career_page(db,item)
        except Exception as e:stats["Company: "+item.name]="error: "+str(e)[:160]
    db.commit()
    stale_before=datetime.now(timezone.utc)-timedelta(days=60)
    db.query(Job).filter(Job.active.is_(True),Job.last_seen_at < stale_before,~Job.application.has()).update({Job.active:False},synchronize_session=False)
    db.commit()
    run.finished_at=datetime.now(timezone.utc);run.source_results=json.dumps(stats,ensure_ascii=False)
    run.total_new=sum(v for v in stats.values() if isinstance(v,int))
    run.total_indexed=db.query(Job).count();run.status="complete";db.commit()
    return {"sources":stats,"new":run.total_new,"total":run.total_indexed,"run_id":run.id}

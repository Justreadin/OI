"""ATS-aware, persistent-session employer form assistant.

The assistant inspects common ATS platforms and ordinary forms, including
Google Forms. It fills only explicitly selected fields and never submits.
"""
import asyncio, os, re, socket, ipaddress, hashlib, threading
from pathlib import Path
from urllib.parse import urlparse
from app.profile import PROFILE

_PROFILE_LOCKS={}
_PROFILE_LOCKS_GUARD=threading.Lock()

ATS_RULES = [
 ("greenhouse", re.compile(r"boards\.greenhouse\.io|job-boards\.greenhouse\.io|greenhouse\.io", re.I)),
 ("lever", re.compile(r"jobs\.lever\.co|lever\.co", re.I)),
 ("ashby", re.compile(r"jobs\.ashbyhq\.com|ashbyhq\.com", re.I)),
 ("workday", re.compile(r"myworkdayjobs\.com|workday\.com", re.I)),
 ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com|smartrecruiters\.com", re.I)),
 ("icims", re.compile(r"icims\.com", re.I)),
 ("taleo", re.compile(r"taleo\.net", re.I)),
 ("successfactors", re.compile(r"successfactors\.com", re.I)),
 ("google_forms", re.compile(r"docs\.google\.com/forms|forms\.gle", re.I)),
 ("workable", re.compile(r"apply\.workable\.com|workable\.com", re.I)),
 ("recruitee", re.compile(r"recruitee\.com", re.I)),
 ("bamboohr", re.compile(r"bamboohr\.com", re.I)),
 ("jazzhr", re.compile(r"applytojob\.com|jazz\.co", re.I)),
]

def detect_ats(url, title=""):
    haystack=f"{url} {title}"
    for name,pattern in ATS_RULES:
        if pattern.search(haystack): return name
    return "generic"

def adapter_metadata(ats):
    """Expose honest adapter capability level instead of implying full ATS coverage."""
    capabilities={
      "greenhouse":{"adapter":"greenhouse_public_board","level":"public_job_board_plus_generic_form","submission_api":"employer_api_key_required"},
      "lever":{"adapter":"lever_postings","level":"public_job_board_plus_generic_form","submission_api":"posting_api_key_required"},
      "ashby":{"adapter":"ashby_public_postings","level":"public_job_board_plus_generic_form","submission_api":"employer_permission_required"},
      "google_forms":{"adapter":"google_forms_accessible_dom","level":"generic_accessible_form","submission_api":"manual_candidate_confirmation"},
      "workday":{"adapter":"workday_accessible_dom","level":"generic_accessible_form","submission_api":"manual_candidate_confirmation"},
      "generic":{"adapter":"generic_accessible_dom","level":"generic_accessible_form","submission_api":"manual_candidate_confirmation"},
    }
    return capabilities.get(ats,{"adapter":ats+"_accessible_dom","level":"generic_accessible_form","submission_api":"manual_candidate_confirmation"})

def validate_public_url(url:str):
    p=urlparse(url)
    if p.scheme!="https" or not p.hostname: raise ValueError("Only public HTTPS application URLs are accepted.")
    host=p.hostname.lower()
    if p.username or p.password or (p.port not in (None,443)):
        raise ValueError("Credentials and non-standard ports are blocked.")
    if host in {"localhost","localhost.localdomain"} or host.endswith((".local",".internal")):
        raise ValueError("Private/local hosts are blocked.")
    try:
        addresses={x[4][0] for x in socket.getaddrinfo(host,None)}
        if not addresses: raise ValueError("The application host could not be resolved.")
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("Private or non-public network destinations are blocked.")
    except socket.gaierror:
        raise ValueError("The application host could not be resolved; refusing to navigate.")
    return url

def _profile_values():
    c=PROFILE.get("contact",{}); links=PROFILE.get("links",{})
    return {"name":PROFILE.get("name","Favour Akintoye"),"email":c.get("email",""),
      "phone":c.get("phone",""),"portfolio":links.get("portfolio",""),
      "github":links.get("github",""),"location":"Nigeria","city":"Akure","country":"Nigeria"}

def _profile_dir(url):
    host=urlparse(url).hostname or "unknown"
    key=hashlib.sha256(host.encode()).hexdigest()[:20]
    base=Path(os.getenv("BROWSER_DATA_DIR","./browser_sessions"))
    base.mkdir(parents=True,exist_ok=True)
    return str(base/key)

async def _browser():
    from playwright.async_api import async_playwright
    pw=await async_playwright().start()
    endpoint=os.getenv("PLAYWRIGHT_WS_ENDPOINT","").strip()
    if endpoint:
        browser=await pw.chromium.connect_over_cdp(endpoint)
        # CDP's default context retains cookies between assistant requests.
        context=browser.contexts[0] if browser.contexts else await browser.new_context()
        return pw,browser,context,False
    return pw,None,None,True

async def _field_inventory(page):
    output=[]
    page_key=hashlib.sha256((page.url or "").encode()).hexdigest()[:10]
    frames=page.frames
    for frame_no,frame in enumerate(frames):
        try:
            items=await frame.locator("input:not([type=hidden]),textarea,select,[contenteditable=true],[role=combobox],[role=textbox],[role=radio],[role=checkbox]").evaluate_all("""els=>els.map((e,i)=>{
              const labels=e.labels&&e.labels.length?[...e.labels].map(x=>x.innerText).join(' '):'';
              const p=e.getAttribute('placeholder')||'',a=e.getAttribute('aria-label')||'';
              const par=e.closest('label')?.innerText||e.parentElement?.innerText||'';
              const type=(e.getAttribute('type')||'').toLowerCase();
              return {index:i,tag:e.tagName.toLowerCase(),type,name:e.getAttribute('name')||'',id:e.id||'',
                label:(labels||a||p||par||'').trim().replace(/\\s+/g,' ').slice(0,220),
                placeholder:p,required:!!e.required||e.getAttribute('aria-required')==='true',
                disabled:!!e.disabled,options:e.tagName==='SELECT'?[...e.options].map(o=>({label:o.text.trim(),value:o.value})).filter(o=>o.label).slice(0,60):[],
                autocomplete:e.getAttribute('autocomplete')||'',role:e.getAttribute('role')||''}
            })""")
            for item in items:
                item["frame_index"]=frame_no
                field_sig="|".join([str(item.get("label","")),str(item.get("name","")),str(item.get("id","")),str(item.get("type",""))])
                field_key=hashlib.sha256(field_sig.encode()).hexdigest()[:8]
                item["selector_key"]=f"{page_key}-{field_key}-f{frame_no}-i{item['index']}"
                output.append(item)
        except Exception: continue
    return output


async def _guard_public_requests(page):
    """Revalidate every browser navigation/request, including redirect targets."""
    async def guard(route):
        request_url=route.request.url
        parsed=urlparse(request_url)
        if parsed.scheme=="https":
            try:
                validate_public_url(request_url)
                await route.continue_()
            except Exception:
                await route.abort("blockedbyclient")
        elif parsed.scheme in ("data","blob"):
            await route.continue_()
        else:
            await route.abort("blockedbyclient")
    await page.route("**/*",guard)

async def _inspect_page(page,url=None):
    if url and page.url != url:
        await page.goto(url,wait_until="domcontentloaded",timeout=60000)
    try: await page.wait_for_load_state("networkidle",timeout=5000)
    except Exception: pass
    await page.wait_for_timeout(900)
    title=await page.title()
    fields=await _field_inventory(page)
    buttons=[]
    for frame in page.frames:
        try:
            buttons += await frame.locator("button,input[type=submit],[role=button]").evaluate_all("""els=>els.map(e=>({text:(e.innerText||e.value||e.getAttribute('aria-label')||'').trim().slice(0,120),type:e.getAttribute('type')||'',disabled:!!e.disabled})).filter(x=>x.text)""")
        except Exception: pass
    forms=[]
    for frame_no,frame in enumerate(page.frames):
        try:
            count=await frame.locator("form").count()
            for i in range(min(count,12)):
                forms.append({"frame_index":frame_no,"index":i,"action":await frame.locator("form").nth(i).get_attribute("action")})
        except Exception: pass
    ats=detect_ats(page.url,title)
    return {"url":page.url,"title":title,"ats":ats,"adapter":adapter_metadata(ats),
      "fields":fields,"buttons":buttons[:80],"forms":forms,
      "frames":[{"index":i,"url":f.url,"name":f.name} for i,f in enumerate(page.frames)],
      "page_title":title}

async def inspect_form(url):
    validate_public_url(url)
    pw,browser,remote_context,persistent=await _browser()
    context=None
    try:
        if persistent:
            context=await pw.chromium.launch_persistent_context(_profile_dir(url),headless=True,accept_downloads=True)
        else: context=remote_context
        page=await context.new_page()
        await _guard_public_requests(page)
        result=await _inspect_page(page,url)
        result["session_profile"]=urlparse(url).hostname
        result["session_persistent"]=True
        return result
    finally:
        if context and persistent: await context.close()
        # For a remote CDP browser, stop the Playwright client without closing
        # the shared browser process or its persistent context.
        await pw.stop()

async def fill_form(url,field_values,cv_path=None,cover_path=None,document_paths=None,advance_button_text=None,final_submit_button_text=None):
    validate_public_url(url)
    if advance_button_text and final_submit_button_text:
        raise ValueError("A workflow page cannot advance and submit in the same action.")
    document_paths=document_paths or {}
    pw,browser,remote_context,persistent=await _browser()
    context=None
    try:
        if persistent:
            context=await pw.chromium.launch_persistent_context(_profile_dir(url),headless=True,accept_downloads=True)
        else: context=remote_context
        page=await context.new_page()
        await _guard_public_requests(page)
        await _inspect_page(page,url)
        applied=[];unmatched=[]
        for item in field_values:
            frame_no=int(item.get("frame_index",0));idx=int(item.get("index",-1));value=str(item.get("value",""))
            if not value or idx<0: continue
            try:
                frame=page.frames[frame_no]
                locator=frame.locator("input:not([type=hidden]),textarea,select,[contenteditable=true],[role=combobox],[role=textbox],[role=radio],[role=checkbox]").nth(idx)
                typ=(await locator.get_attribute("type") or "").lower()
                tag=await locator.evaluate("(e)=>e.tagName.toLowerCase()")
                role=await locator.get_attribute("role") or ""
                if typ=="file": unmatched.append(item);continue
                if typ in ("checkbox","radio") or role in ("checkbox","radio"):
                    desired=value.strip().lower() in ("1","true","yes","checked","on")
                    if desired: await locator.check()
                    else: await locator.uncheck()
                elif tag=="select": await locator.select_option(label=value)
                elif await locator.get_attribute("contenteditable")=="true": await locator.fill(value)
                elif role=="combobox": await locator.fill(value)
                else: await locator.fill(value)
                applied.append({"index":idx,"frame_index":frame_no,"label":item.get("label","")})
            except Exception: unmatched.append(item)
        # File inputs are mapped by accessible metadata, including labels and enclosing text.
        for frame_no,frame in enumerate(page.frames):
            uploads=frame.locator('input[type="file"]')
            for i in range(await uploads.count()):
                loc=uploads.nth(i)
                try:
                    label=" ".join(filter(None,[await loc.get_attribute("aria-label"),await loc.get_attribute("name"),await loc.get_attribute("id"),await loc.get_attribute("accept")]))
                    try: label += " "+await loc.evaluate("(e)=>e.closest('label')?.innerText||e.parentElement?.innerText||''")
                    except Exception: pass
                    selected=None;kind=None
                    if re.search(r"cover|motivation letter",label,re.I):selected=cover_path;kind="cover letter"
                    elif re.search(r"resume|curriculum|\\bcv\\b",label,re.I):selected=cv_path;kind="resume"
                    else:
                        patterns={"portfolio":r"portfolio","transcript":r"transcript|academic record","writing_sample":r"writing sample|work sample","certificate":r"certificate|certification","reference":r"reference|recommendation"}
                        for category,pattern in patterns.items():
                            if re.search(pattern,label,re.I) and document_paths.get(category):
                                selected=document_paths[category];kind=category;break
                    if selected and os.path.exists(selected):
                        await loc.set_input_files(selected);applied.append({"kind":kind+" upload","frame_index":frame_no,"index":i})
                    elif re.search(r"resume|curriculum|\\bcv\\b|cover|portfolio|transcript|writing sample|certificate|reference",label,re.I):
                        unmatched.append({"kind":"required supporting upload not matched","label":label,"frame_index":frame_no,"index":i})
                except Exception: unmatched.append({"kind":"file upload","frame_index":frame_no,"index":i})
        next_page=None
        submission_result={"submission_attempted":False,"submission_confirmed":False,"submission_status":"not_requested"}
        if final_submit_button_text:
            final_label=str(final_submit_button_text).strip()
            if not re.fullmatch(r"(?i)(submit application|submit|apply|apply now|send application|finish application)",final_label):
                raise ValueError("The final control label is not on the approved submission allowlist.")
            body_text=(await page.locator("body").inner_text())[:30000]
            if re.search(r"captcha|hcaptcha|recaptcha|cloudflare turnstile|verify you are human|security challenge",body_text+" "+ " ".join(f.url for f in page.frames),re.I):
                raise ValueError("A CAPTCHA or anti-bot checkpoint is present. Complete it manually on the employer's site; automated submission is paused.")
            candidates=page.get_by_role("button",name=final_label,exact=True)
            count=await candidates.count()
            if count==0:
                candidates=page.locator('input[type="submit"],button,[role="button"]').filter(has_text=re.compile("^"+re.escape(final_label)+"$",re.I))
                count=await candidates.count()
            if count!=1: raise ValueError(f"Could not identify exactly one final '{final_label}' control.")
            if not await candidates.first.is_visible() or not await candidates.first.is_enabled():
                raise ValueError("The final submission control is not visible and enabled.")
            submission_result["submission_attempted"]=True
            submission_result["submission_status"]="clicked_unverified"
            click_error=""
            try:
                await candidates.first.click(timeout=15000)
            except Exception as e:
                click_error=str(e)[:500]
            try: await page.wait_for_load_state("domcontentloaded",timeout=20000)
            except Exception: pass
            try: await page.wait_for_load_state("networkidle",timeout=5000)
            except Exception: pass
            try:
                await page.wait_for_timeout(1200)
                confirmation_text=(await page.locator("body").inner_text())[:30000]
            except Exception:
                confirmation_text=""
            confirmed=bool(re.search(r"application (?:has been )?(?:successfully )?(?:submitted|received)|thank you for applying|thanks for applying|we(?:'|’)ve received your application|we have received your application|successfully applied",confirmation_text,re.I))
            submission_result.update({"submission_confirmed":confirmed,
                "submission_status":"confirmed" if confirmed else "clicked_unverified",
                "confirmation_text":confirmation_text[:1200],"url_after_submit":page.url,
                "click_error":click_error})
        if advance_button_text:
            label=str(advance_button_text).strip()
            if not re.fullmatch(r"(?i)(next|continue|save and continue|continue to next step)",label):
                raise ValueError("Only an explicitly selected safe Next/Continue control can be activated.")
            # Require an exact, unique visible control; never click final submission controls.
            candidates=page.get_by_role("button",name=label,exact=True)
            count=await candidates.count()
            if count==0:
                candidates=page.locator('input[type="submit"],button,[role="button"]').filter(has_text=re.compile("^"+re.escape(label)+"$",re.I))
                count=await candidates.count()
            if count!=1: raise ValueError(f"Could not identify exactly one safe '{label}' control.")
            await candidates.first.click(timeout=12000)
            try: await page.wait_for_load_state("domcontentloaded",timeout=12000)
            except Exception: pass
            try: await page.wait_for_load_state("networkidle",timeout=4000)
            except Exception: pass
            await page.wait_for_timeout(500)
            next_page=await _inspect_page(page)
        # Never click submit/apply/send or final confirmation controls.
        return {"filled":applied,"unfilled":unmatched,"url":page.url,"title":await page.title(),
                "ats":detect_ats(page.url,await page.title()),"submit_clicked":submission_result["submission_attempted"],
                "advanced_to_next_step":bool(next_page),"next_page":next_page,
                **submission_result,"session_persistent":True}
    finally:
        if context and persistent: await context.close()
        # For a remote CDP browser, stop the Playwright client without closing
        # the shared browser process or its persistent context.
        await pw.stop()

def run(coro, url=None):
    if not url:return asyncio.run(coro)
    host=urlparse(url).hostname or "unknown"
    with _PROFILE_LOCKS_GUARD:
        lock=_PROFILE_LOCKS.setdefault(host,threading.Lock())
    with lock:
        return asyncio.run(coro)

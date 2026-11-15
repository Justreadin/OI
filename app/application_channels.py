"""Evidence-based application-channel classification for discovered vacancies."""
from __future__ import annotations
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I)
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "smartrecruiters.com", "icims.com", "taleo.net", "successfactors.com", "workable.com", "recruitee.com", "bamboohr.com", "jazz.co")
EMAIL_PATTERNS = (
    r"(?:send|email|submit|forward)\s+(?:your\s+)?(?:application|cv|resume|résumé|cover\s+letter|portfolio)[^.!\n]{0,100}?\bto\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    r"(?:applications?|cv|resumes?|résumés?)\s+(?:should\s+be\s+)?(?:sent|emailed|submitted)\s+to\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
)

def classify_application_channel(description: str, url: str) -> dict:
    text = re.sub(r"\s+", " ", description or "")
    lower = text.lower()
    host = (urlparse(url or "").hostname or "").lower()
    emails = list(dict.fromkeys(x.lower() for x in EMAIL_RE.findall(text)))
    explicit_email = None
    for pattern in EMAIL_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            explicit_email = match.group(1).lower()
            break
    if explicit_email:
        return {"method":"direct_email", "confidence":"high", "recipient":explicit_email,
                "evidence":f"The listing explicitly instructs applicants to send application materials to {explicit_email}."}
    if any(host == d or host.endswith("."+d) for d in ATS_HOSTS):
        return {"method":"ats", "confidence":"high", "recipient":"",
                "evidence":f"The application URL is hosted on an identified ATS domain ({host})."}
    email_language = any(p in lower for p in ("email your application", "send your cv", "send your resume", "send your résumé", "email your cv", "email your resume", "send your application to"))
    if email_language and len(emails) == 1:
        return {"method":"direct_email", "confidence":"medium", "recipient":emails[0],
                "evidence":"The listing contains email-application language and one email address; confirm that this is the application recipient."}
    if any(p in lower for p in ("apply through our careers portal", "apply via our careers portal", "submit your application through", "apply on our website", "apply via the link")):
        return {"method":"employer_portal", "confidence":"medium", "recipient":"",
                "evidence":"The listing directs candidates to an employer website or careers portal."}
    if any(p in lower for p in ("google form", "complete this form", "application form:")):
        return {"method":"external_form", "confidence":"medium", "recipient":"",
                "evidence":"The listing refers to a separate application form; inspect the destination before proceeding."}
    if host and any(x in host for x in ("careers.", "jobs.", "career.", "recruiting.")):
        return {"method":"employer_portal", "confidence":"low", "recipient":"",
                "evidence":f"The destination appears to be an employer careers/recruiting subdomain ({host}); verify the application flow."}
    return {"method":"unknown", "confidence":"low", "recipient":"",
            "evidence":"The listing and destination do not establish a reliable application method. Inspect the employer instructions."}

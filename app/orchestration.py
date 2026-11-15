"""Application workflow orchestration and evidence-aware quality gates."""
import json, re
from datetime import datetime, timezone
from app.profile import PROFILE

STAGE_RULES = [
    ("account", r"create account|sign in|log in|register|password"),
    ("personal_details", r"personal details|contact information|first name|last name|phone number"),
    ("experience", r"work experience|employment history|professional experience"),
    ("education", r"education history|academic background|qualification"),
    ("resume", r"resume|curriculum vitae|upload cv"),
    ("screening", r"screening question|additional question|why do you want|tell us about|eligibility question"),
    ("eligibility", r"work authori[sz]ation|visa|sponsorship|right to work|location eligibility"),
    ("declarations", r"equal opportunity|disability|veteran|demographic|data protection|consent|declaration"),
    ("review", r"review (your )?application|application summary|check your answers"),
    ("submission", r"submit application|final submission|apply now|send application"),
]
SENSITIVE_OR_UNVERIFIED = re.compile(
    r"salary expectation|notice period|work authori[sz]ation|visa|sponsorship|"
    r"criminal|disability|medical|gender|race|ethnicity|religion|veteran|"
    r"date of birth|nationality|citizenship|years of experience|graduation date", re.I)

def infer_stage(title="", url="", fields=None, buttons=None):
    # Stage is inferred from page context and form fields, not merely the presence
    # of a final-submit button that may be visible in a persistent page footer.
    text = " ".join([title or "", url or ""] + [
        str(x.get("label",""))+" "+str(x.get("placeholder","")) for x in (fields or [])
    ]).lower()
    matched = [name for name, pattern in STAGE_RULES if re.search(pattern,text,re.I)]
    # Prefer the most specific stage over a generic button label.
    priority = ["submission","review","eligibility","screening","resume","education",
                "experience","personal_details","declarations","account"]
    stage = next((x for x in priority if x in matched), "application_form")
    if stage == "review" and any(re.search(r"submit|apply|send application|finish application",x.get("text",""),re.I) for x in (buttons or [])):
        stage = "submission"
    next_controls = [x for x in (buttons or []) if re.search(r"\b(next|continue|save and continue)\b",x.get("text",""),re.I)
                     and not re.search(r"submit|apply|send|finish|complete",x.get("text",""),re.I)]
    final_controls = [x for x in (buttons or []) if re.search(r"submit|apply|send application|finish application",x.get("text",""),re.I)]
    return {"stage":stage,"matched_stages":matched,"next_step_controls":next_controls,
            "final_submission_controls":final_controls,
            "human_action_required": bool(final_controls),
            "observed_at":datetime.now(timezone.utc).isoformat()}

def field_requirements(fields):
    missing=[]
    for f in fields or []:
        label=(f.get("label") or f.get("placeholder") or f.get("name") or "Unlabelled field").strip()
        typ=(f.get("type") or "").lower()
        if f.get("required") and not f.get("disabled") and typ not in ("submit","button","hidden"):
            missing.append({"label":label,"field_key":f.get("selector_key"),"reason":"Required field; value not yet confirmed."})
    return missing

def evidence_audit(job, application, fields=None, filled=None):
    evidence=[(e["name"],fact) for e in PROFILE.get("evidence",[]) for fact in e.get("facts",[])]
    application_text=(application.cv_text+" "+application.cover_letter).lower()
    verify=[f"{name}: {fact['claim']}" for name,fact in evidence
            if fact.get("status")=="verify_before_use" and fact["claim"].lower() in application_text]
    constraints=[fact["claim"] for _,fact in evidence if fact.get("status")=="constraint"]
    missing=field_requirements(fields or [])
    sensitive=[]
    for f in fields or []:
        label=f.get("label") or f.get("placeholder") or ""
        if SENSITIVE_OR_UNVERIFIED.search(label):
            sensitive.append({"label":label,"reason":"Requires an explicit candidate-provided answer; do not infer from profile."})
    text=application_text
    consistency=[]
    if "2,000" in text or "2000" in text:
        consistency.append("NexaHealth user figures are project-level and must not be attributed solely to the applicant.")
    if "production payment" in text and "layla" in text:
        consistency.append("Layla Orders was a prototype using Paystack test mode, not a production payment deployment.")
    if "solely" in text and "mylurah" in text:
        consistency.append("Avoid sole attribution of MyLurah platform-wide metrics.")
    letter = application.cover_letter.lower()
    generic_phrases = [phrase for phrase in (
        "i am excited to apply", "i am passionate about", "dynamic team",
        "fast-paced environment", "perfect fit", "i believe i would be a great",
        "leverage my skills", "i am writing to express my interest") if phrase in letter]
    named_evidence = [e.get("name", "") for e in PROFILE.get("evidence", [])
                      if e.get("name", "").lower() in letter]
    editorial_issues = []
    if letter.strip() and len(letter.split()) < 100:
        editorial_issues.append("Cover letter is too short to establish a convincing role-specific case.")
    if letter.strip() and len(letter.split()) > 400:
        editorial_issues.append("Cover letter is too long and needs tighter prioritisation.")
    if generic_phrases:
        editorial_issues.append("Generic application language detected: " + ", ".join(generic_phrases))
    if letter.strip() and not named_evidence:
        editorial_issues.append("Cover letter does not identify a concrete candidate project or experience.")
    if "\u2014" in application.cv_text or "\u2014" in application.cover_letter or "\u2013" in application.cv_text or "\u2013" in application.cover_letter:
        editorial_issues.append("Replace em dashes and en dashes with plain punctuation.")
    checks={
      "role_and_employer_present":bool(job and job.title and job.company),
      "tailored_cv_present":bool(application.cv_text.strip()),
      "cover_letter_present":bool(application.cover_letter.strip()),
      "required_fields_identified":len(missing)==0,
      "candidate_input_required":len(sensitive),
      "unverified_evidence_to_review":len(verify),
      "consistency_flags":consistency,
      "known_constraints":constraints,
      "editorial_issues":editorial_issues,
      "named_evidence_in_letter":named_evidence,
    }
    blockers=[]
    if not checks["tailored_cv_present"]: blockers.append("Tailored CV is missing.")
    if not checks["cover_letter_present"]: blockers.append("Cover letter/email draft is missing.")
    if missing: blockers.append(f"{len(missing)} required form field(s) are not confirmed.")
    if sensitive: blockers.append(f"{len(sensitive)} field(s) require direct candidate input.")
    if editorial_issues: blockers.extend(editorial_issues)
    return {"checks":checks,"blockers":blockers,"required_fields_missing":missing,
            "candidate_questions":sensitive,"verify_before_use":verify,
            "consistency_flags":consistency,
            "ready_for_human_review":not blockers,
            "submission_policy":"Final external submission is never automatic. It requires an approved package, a fresh form inspection, a completeness audit and explicit candidate authorization immediately before the final control is clicked."}

def dump(obj):
    return json.dumps(obj,ensure_ascii=False,default=str)

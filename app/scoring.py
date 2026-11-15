"""Evidence-aware opportunity classification and candidate-fit scoring."""
import re

from app.ai_classifier import classify_ambiguous_opportunity

TRACKS = {
    "Product": ["product manager", "associate product", "technical product", "product owner", "product operations", "product analyst", "product management intern", "product internship"],
    "Growth": ["growth", "plg", "product-led", "lifecycle", "acquisition", "activation", "growth intern", "growth internship"],
    "GTM": ["go-to-market", "gtm", "product marketing", "demand generation", "outbound", "commercial"],
    "Strategy": ["strategy", "business operations", "business ops", "founder's associate", "chief of staff", "operations analyst"],
    "Venture Capital": ["venture capital", "vc analyst", "investment analyst", "venture fellow", "investment associate", "portfolio analyst", "due diligence"],
    "Research & Finance": ["research analyst", "investment research", "equity research", "financial analyst", "economic research", "market research", "research intern", "research internship", "investment intern"],
    "Policy & Government": ["policy analyst", "public policy", "government affairs", "public sector", "technology policy", "regulatory research", "policy intern", "policy internship"],
    "Development & Institutions": ["programme analyst", "program analyst", "development research", "think tank", "institutional strategy", "international development", "development intern", "programme intern"],
}
TRACKS_WITH_OTHER = (*TRACKS.keys(), "Other")
OPPORTUNITY_TYPES = ["Internship", "Fellowship", "Graduate Programme", "Research Opportunity", "Early-Career Programme", "Part-Time Employment", "Full-Time Employment", "Other"]
HARD_EXCLUDE = ["us citizens only", "us citizen only", "must be a us citizen", "u.s. citizens only", "must be a u.s. citizen", "security clearance required", "active security clearance required"]
JUNIOR = ["intern", "graduate", "junior", "associate", "entry level", "early career", "analyst", "fellow", "trainee"]
SENIOR = ["senior", "lead", "principal", "director", "head of", "10+ years", "8+ years", "7+ years"]


def classify_opportunity_type(title, description="", location=""):
    """Classify from explicit language. Analyst/junior roles are not internships."""
    title_text = re.sub(r"\s+", " ", str(title or "")).lower()
    text = title_text + " " + str(description or "").lower()
    patterns = [
        ("Internship", r"\b(intern(ship)?|interning|summer analyst intern)\b"),
        ("Fellowship", r"\b(fellow(ship)?)\b"),
        ("Graduate Programme", r"\b(graduate programme|graduate program|management trainee programme|management trainee program|graduate trainee)\b"),
        ("Research Opportunity", r"\b(research opportunity|research placement|research assistantship)\b"),
        ("Early-Career Programme", r"\b(early career programme|early career program|rotational programme|rotational program|new graduate programme|new graduate program)\b"),
        ("Part-Time Employment", r"\b(part[- ]time|working student)\b"),
        ("Full-Time Employment", r"\b(full[- ]time)\b"),
    ]
    for kind, pattern in patterns:
        if re.search(pattern, title_text):
            return kind
    # Description-only evidence must describe the opportunity itself, not mention internships in passing.
    if re.search(r"\b(apply for our internship|internship opportunity|internship position|this internship)\b", text):
        return "Internship"
    # For genuinely ambiguous programme/analyst listings, reuse the cached AI
    # interpretation already requested by score_job_detailed when available.
    if len(str(description or "")) >= 250 and re.search(r"\b(programme|program|analyst|associate|research|trainee)\b", text):
        interpreted = classify_ambiguous_opportunity(title, location, description)
        if interpreted and interpreted.get("confidence", 0) >= 0.75:
            return interpreted["opportunity_type"]
    return "Other"


def _evidence(text):
    patterns = [
        ("explicit_nigeria", r"[^.!?\n]*(?:nigeria|nigerian applicants|based in nigeria)[^.!?\n]*[.!?]?"),
        ("africa_region", r"[^.!?\n]*(?:africa|african countries|sub-saharan africa)[^.!?\n]*[.!?]?"),
        ("worldwide", r"[^.!?\n]*(?:worldwide|work from anywhere|anywhere in the world|global remote)[^.!?\n]*[.!?]?"),
        ("country_restriction", r"[^.!?\n]*(?:must be based in|only applicants (?:located|based)|residents only|eligible to work in|authorized to work in|authorised to work in)[^.!?\n]*[.!?]?"),
        ("visa_sponsorship", r"[^.!?\n]*(?:visa sponsorship|sponsor(?:ship)? (?:is )?(?:available|provided)|work permit sponsorship)[^.!?\n]*[.!?]?"),
    ]
    found = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            quote = " ".join(match.group(0).split())[:350]
            if quote and quote not in [item["quote"] for item in found]:
                found.append({"type": kind, "quote": quote})
            if len(found) >= 8:
                return found
    return found


def _deterministic_track(title, location, description):
    title_text = str(title or "").lower()
    text = f"{title} {location} {description}".lower()
    title_counts = {track: sum(2 for term in terms if term in title_text) for track, terms in TRACKS.items()}
    full_counts = {track: sum(1 for term in terms if term in text) for track, terms in TRACKS.items()}
    counts = {track: title_counts[track] + full_counts[track] for track in TRACKS}
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    best_track, best_count = ordered[0]
    second_count = ordered[1][1] if len(ordered) > 1 else 0
    # A strong title match is decisive; low/no signal and close competing signals need interpretation.
    uncertain = best_count < 2 or (second_count > 0 and best_count - second_count <= 1)
    return best_track if best_count else "Other", counts, uncertain


def _eligibility(text, location):
    lower = f"{location or ''} {text or ''}".lower()
    hard = any(term in lower for term in HARD_EXCLUDE)
    if hard:
        return "ineligible"
    nigeria_location = bool(re.search(r"\bnigeria\b", str(location or "").lower()))
    nigeria_acceptance = bool(re.search(
        r"\b(applicants based in nigeria may apply|applicants in nigeria may apply|open to (?:applicants|candidates) in nigeria|nigeria is an eligible country|eligible to work in nigeria|based in nigeria)\b",
        lower,
    ))
    worldwide = bool(re.search(r"\b(worldwide|work from anywhere|anywhere in the world|global remote)\b", lower))
    explicit_non_ng_restriction = bool(re.search(
        r"(?:must be based in|must reside in|only applicants (?:located|based) in|residents of|residents only in)\s+(?:the\s+)?(?:united states|u\.s\.|us|united kingdom|u\.k\.|uk|canada|australia|south africa|kenya|ghana|european union|eu)\b",
        lower,
    ))
    if explicit_non_ng_restriction and not nigeria_acceptance:
        return "restricted"
    if nigeria_location or nigeria_acceptance or worldwide:
        return "likely"
    # Africa-wide language is not proof of Nigeria eligibility. Remote alone is not proof either.
    return "verify"


def score_job_detailed(title, location, description, preferences=None):
    preferences = preferences or {}
    title = str(title or "")
    location = str(location or "")
    description = str(description or "")
    text = f"{title} {location} {description}".lower()
    track, counts, uncertain = _deterministic_track(title, location, description)
    ai_result = classify_ambiguous_opportunity(title, location, description) if uncertain else None
    if ai_result and ai_result.get("confidence", 0) >= 0.65:
        track = ai_result["track"]
    if track not in TRACKS_WITH_OTHER:
        track = "Other"

    opportunity_type = classify_opportunity_type(title, description)
    if ai_result and ai_result.get("confidence", 0) >= 0.65 and opportunity_type == "Other":
        opportunity_type = ai_result["opportunity_type"]

    junior = any(term in text for term in JUNIOR)
    senior = any(term in title.lower() for term in SENIOR)
    remote = any(term in text for term in ["remote", "worldwide", "anywhere", "global", "distributed"])
    evidence = _evidence(text)
    eligibility = _eligibility(text, location)

    # Transparent fit score. This is a heuristic, not an AI-generated suitability verdict.
    role_signal = min(36, counts.get(track, 0) * 9)
    seniority_signal = 18 if junior else 3 if senior else 10
    work_mode_signal = 14 if remote else 0
    geography_signal = 14 if eligibility == "likely" else 3
    score = role_signal + seniority_signal + work_mode_signal + geography_signal
    selected_tracks = preferences.get("tracks")
    if isinstance(selected_tracks, (list, tuple, set)) and selected_tracks and track not in selected_tracks:
        score -= 18
    if eligibility in ("restricted", "ineligible"):
        score -= 50
    score = max(0, min(100, score))

    if ai_result:
        evidence.extend({"type": "ai_interpretation", "quote": quote} for quote in ai_result.get("evidence", []) if quote)
    evidence = evidence[:12]
    reasons = (
        f"Best-fit track: {track}. Opportunity type: {opportunity_type}. "
        f"Seniority signal: {'early-career' if junior else 'senior' if senior else 'unspecified'}. "
        f"Work mode: {'remote signal found' if remote else 'not clearly remote'}. "
        f"Geographic eligibility: {eligibility}. "
        f"{'AI-assisted interpretation used; confidence ' + str(round(ai_result['confidence'], 2)) + '. ' if ai_result else ''}"
        "Remote or Africa-wide wording alone does not confirm Nigerian eligibility. "
        "Verify the employer's exact country policy and work-authorisation requirements before applying."
    )
    return score, track, eligibility, reasons, evidence


def score_job(title, location, description, preferences=None):
    """Backward-compatible four-value scoring API."""
    score, track, eligibility, reasons, _ = score_job_detailed(title, location, description, preferences)
    return score, track, eligibility, reasons

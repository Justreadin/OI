"""Optional, cached LLM interpretation for ambiguous opportunity listings.

The model extracts structured opportunity facts. It does not decide candidate
eligibility or assign the final fit score; those remain evidence-based rules.
"""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import re

from app.config import settings

log = logging.getLogger(__name__)

TRACKS = (
    "Product", "Growth", "GTM", "Strategy", "Venture Capital",
    "Research & Finance", "Policy & Government",
    "Development & Institutions", "Other",
)
OPPORTUNITY_TYPES = (
    "Internship", "Fellowship", "Graduate Programme", "Research Opportunity",
    "Early-Career Programme", "Part-Time Employment", "Full-Time Employment", "Other",
)


def _normalise_result(raw: object) -> dict | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return None
    if not isinstance(raw, dict):
        return None
    track = raw.get("track")
    kind = raw.get("opportunity_type")
    if track not in TRACKS or kind not in OPPORTUNITY_TYPES:
        return None
    confidence = raw.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "track": track,
        "opportunity_type": kind,
        "seniority": str(raw.get("seniority", "Unclear"))[:80],
        "work_mode": str(raw.get("work_mode", "Unclear"))[:80],
        "geographic_eligibility": str(raw.get("geographic_eligibility", "Unclear"))[:100],
        "eligible_countries": [str(x)[:80] for x in raw.get("eligible_countries", [])[:30]]
            if isinstance(raw.get("eligible_countries", []), list) else [],
        "required_experience": str(raw.get("required_experience", "Not specified"))[:300],
        "key_requirements": [str(x)[:300] for x in raw.get("key_requirements", [])[:12]]
            if isinstance(raw.get("key_requirements", []), list) else [],
        "evidence": [str(x)[:500] for x in raw.get("evidence", [])[:8]]
            if isinstance(raw.get("evidence", []), list) else [],
        "confidence": confidence,
    }


@lru_cache(maxsize=2048)
def _classify_cached(title: str, location: str, description: str, model: str) -> dict | None:
    if not settings.enable_ai_classification or not settings.openai_api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key, timeout=20.0, max_retries=1)
        prompt = f"""Classify this opportunity for a candidate based in Nigeria.
Return one JSON object only, with these keys:
track (one of {list(TRACKS)}), opportunity_type (one of {list(OPPORTUNITY_TYPES)}),
seniority, work_mode, geographic_eligibility, eligible_countries (array),
required_experience, key_requirements (array), evidence (array of short exact quotes
from the supplied listing), confidence (0 to 1).

Do not infer that a remote role accepts Nigerians. Do not treat Africa as proof that
Nigeria is eligible. Do not infer internship from junior/analyst/graduate wording
unless the listing explicitly describes an internship or structured programme.
Only use facts supported by the listing. Use Other or Unclear when uncertain.

TITLE: {title}
LOCATION: {location}
DESCRIPTION: {description[:9000]}
"""
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "track": {"type": "string", "enum": list(TRACKS)},
                "opportunity_type": {"type": "string", "enum": list(OPPORTUNITY_TYPES)},
                "seniority": {"type": "string"},
                "work_mode": {"type": "string"},
                "geographic_eligibility": {"type": "string"},
                "eligible_countries": {"type": "array", "items": {"type": "string"}},
                "required_experience": {"type": "string"},
                "key_requirements": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
            "required": ["track", "opportunity_type", "seniority", "work_mode", "geographic_eligibility", "eligible_countries", "required_experience", "key_requirements", "evidence", "confidence"],
        }
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a precise opportunity classification engine. Never invent listing facts."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "opportunity_classification", "strict": True, "schema": schema}},
            max_completion_tokens=700,
            temperature=0,
            reasoning_effort="none",
        )
        content = response.choices[0].message.content
        result = _normalise_result(content)
        if not result:
            return None
        # Evidence must be copied from the source, not generated as plausible prose.
        source = " ".join((title + " " + location + " " + description).lower().split())
        result["evidence"] = [quote for quote in result["evidence"] if " ".join(quote.lower().split()) in source]
        return result
    except Exception as exc:  # API/model incompatibility must not break discovery.
        log.warning("Optional AI opportunity classification failed: %s", exc)
        return None


def classify_ambiguous_opportunity(title: str, location: str, description: str) -> dict | None:
    """Return cached structured interpretation only when explicitly enabled and configured."""
    if not settings.enable_ai_classification or not settings.openai_api_key:
        return None
    model = settings.openai_classifier_model or settings.openai_model
    return _classify_cached(
        re.sub(r"\s+", " ", str(title or "")).strip()[:500],
        re.sub(r"\s+", " ", str(location or "")).strip()[:500],
        re.sub(r"\s+", " ", str(description or "")).strip()[:9000],
        model,
    )


def clear_classifier_cache() -> None:
    """Test and operational hook for invalidating cached classifications."""
    _classify_cached.cache_clear()

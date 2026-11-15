"""Persistent, user-editable candidate intelligence profile.

Verified project/evidence records remain in profile.py. This module stores candidate
facts and preferences supplied or confirmed by the user, without inventing them.
"""
import copy, json, os
from app.profile import PROFILE
from app.config import settings
from app.database import backend

PATH = os.getenv('CANDIDATE_PROFILE_PATH', './data/candidate_profile.json')
DEFAULTS = {
    'name': PROFILE['name'], 'headline': PROFILE['headline'],
    'email': PROFILE['contact']['email'], 'phone': '',
    'location': PROFILE['location'], 'website': PROFILE['links']['portfolio'],
    'linkedin': '', 'github': PROFILE['links']['github'],
    'summary': '', 'skills': '', 'education_notes': '',
    'experience_notes': '', 'project_notes': '', 'achievements': '',
    'career_interests': '', 'languages': '', 'additional_context': ''
}

def get_candidate_profile():
    if backend == 'firestore':
        from app.firestore_database import get_workspace_document
        saved = get_workspace_document('candidates', 'primary', {})
    else:
        try:
            with open(PATH, encoding='utf-8') as f: saved = json.load(f)
        except (OSError, ValueError, TypeError): saved = {}
    data = {**DEFAULTS, **{k: str(v) for k, v in saved.items() if k in DEFAULTS}}
    profile = copy.deepcopy(PROFILE)
    profile['name'] = data['name']
    profile['headline'] = data['headline']
    profile['location'] = data['location']
    profile['contact']['email'] = data['email']
    profile['contact']['phone'] = data['phone']
    profile['contact']['website'] = data['website']
    profile['links']['portfolio'] = data['website']
    profile['links']['github'] = data['github']
    profile['links']['linkedin'] = data['linkedin']
    profile['candidate_details'] = data
    return profile

def save_candidate_profile(values):
    clean = {k: str(values.get(k, '')).strip()[:12000] for k in DEFAULTS if k in values}
    if backend == 'firestore':
        from app.firestore_database import get_workspace_document, set_workspace_document
        current = {**DEFAULTS, **get_workspace_document('candidates', 'primary', {})}
        current.update(clean); return set_workspace_document('candidates', 'primary', current)
    os.makedirs(os.path.dirname(PATH) or '.', exist_ok=True)
    current = {**DEFAULTS}
    try:
        with open(PATH, encoding='utf-8') as f: current.update(json.load(f))
    except (OSError, ValueError, TypeError): pass
    current.update(clean)
    with open(PATH, 'w', encoding='utf-8') as f: json.dump(current, f, ensure_ascii=False, indent=2)
    return current

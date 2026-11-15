"""Persistent candidate and workspace preferences."""
import json, os
from app.database import backend
DEFAULTS={
 "minimum_fit_score":65,"residence_country":"Nigeria","citizenship":"","immigration_status":"not_specified","work_authorisation_mode":"any","authorised_countries":"","sponsorship_countries":"","relocation_willingness":"open","include_visa_sponsorship":True,"include_roles_requiring_local_work_authorisation":False,
 "include_location_restricted_roles":False,"include_hybrid_onsite_outside_nigeria":False,
 "include_unverified_geography":True,"show_stale":False,"default_submit_mode":"manual",
 "display_mode":"auto","auto_shortlist":True,"notification_email":False,
 "tracks":["Product","Growth","GTM","Strategy","Venture Capital","Research & Finance","Policy & Government","Development & Institutions"]}
PATH=os.getenv("PREFERENCES_PATH","./data/preferences.json")
def get_preferences():
    if backend == 'firestore':
        from app.firestore_database import get_workspace_document
        return {**DEFAULTS, **get_workspace_document('preferences', 'primary', {})}
    try:
        with open(PATH,encoding='utf-8') as f: return {**DEFAULTS,**json.load(f)}
    except Exception:return dict(DEFAULTS)
def save_preferences(values):
    merged={**DEFAULTS,**values}
    if backend == 'firestore':
        from app.firestore_database import set_workspace_document
        return set_workspace_document('preferences', 'primary', merged)
    os.makedirs(os.path.dirname(PATH) or '.',exist_ok=True)
    with open(PATH,'w',encoding='utf-8') as f:json.dump(merged,f,indent=2)
    return merged

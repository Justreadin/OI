"""Role-aware links for application packages."""
from app.profile import PROFILE
ASSETS=[
 {"key":"portfolio_website","label":"Portfolio website","url":PROFILE["links"]["portfolio"],"type":"portfolio","tracks":["all"],"description":"Primary overview of selected work."},
 {"key":"portfolio_pdf","label":"Portfolio PDF","url":PROFILE["links"]["portfolio_pdf"],"type":"document","tracks":["all"],"description":"Downloadable supporting portfolio; attach only when useful or requested."},
 {"key":"github","label":"GitHub","url":PROFILE["links"]["github"],"type":"technical","tracks":["Product","Growth","GTM"],"description":"Technical projects and code."},
 {"key":"payla","label":"Payla","url":PROFILE["links"]["payla"],"type":"product","tracks":["Product","Growth","GTM","Strategy"],"description":"Product example for fintech, product and growth roles."},
 {"key":"research","label":"Startup Reality Check","url":PROFILE["links"]["research"],"type":"research","tracks":["Venture Capital","Research & Finance","Policy & Government","Development & Institutions","Strategy"],"description":"Independent research on African technology, capital and institutions."},
 {"key":"email","label":"Email","url":"mailto:"+PROFILE["contact"]["email"],"type":"contact","tracks":["all"],"description":"Primary application contact."}
]
def select_assets(track:str,title:str="",description:str=""):
 text=f"{track} {title} {description}".lower()
 return [a.copy() for a in ASSETS if "all" in a["tracks"] or any(t.lower() in text for t in a["tracks"])]

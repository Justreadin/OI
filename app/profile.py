"""Candidate source of truth. Facts marked verify_before_use must be checked before submission."""
PROFILE = {
 "name":"Favour Akintoye",
 "headline":"Product builder, founder and independent analyst",
 "location":"Nigeria",
 "contact":{"email":"favour@payla.vip","website":"https://favourakintoye.com"},
 "education":[{"institution":"Federal University of Technology, Akure","qualification":"Computer Engineering (undergraduate)","status":"Current student","verification":"Confirm dates, current level and expected graduation before use."}],
 "work_preferences":{"countries":["Nigeria"],"remote_regions":["Africa","International"],"must_explicitly_accept_nigeria":True,"exclude_roles_requiring_unavailable_work_authorisation":True},
 "tracks":{
  "Product":["Associate Product Manager","Product Manager","Technical Product Manager","Product Operations","Product Analyst"],
  "Growth":["Growth Associate","Growth Manager","Product Growth","PLG","Lifecycle Growth","Acquisition"],
  "GTM":["GTM Associate","Go-to-Market","Product Marketing","Commercial Strategy","Business Development"],
  "Strategy":["Business Operations","Strategy Associate","Founder's Associate","Chief of Staff","Operations Analyst"],
  "Venture Capital":["VC Analyst","Investment Analyst","Venture Fellow","Investment Associate","Portfolio Analyst","Due Diligence"],
  "Research & Finance":["Research Analyst","Investment Research","Equity Research","Financial Analyst","Economic Research","Market Research"],
  "Policy & Government":["Policy Analyst","Public Policy","Government Affairs","Public Sector Innovation","Technology Policy","Regulatory Research"],
  "Development & Institutions":["Programme Analyst","Development Research","Think Tank","Institutional Strategy","International Development","Programme Associate"]
 },
 "evidence":[
  {"id":"payla","name":"Payla","role":"Founder / Product Builder","tracks":["Product","Growth","GTM","Strategy"],"facts":[
   {"claim":"Built a payment identity and payment-link product using FastAPI, Firebase/Firestore and Paystack.","status":"user_reported","use":"technical/product roles"},
   {"claim":"Designed paylinks, branded invoices, reminders, payment tracking and subscription features.","status":"user_reported","use":"product/growth roles"},
   {"claim":"Historical user-reported traction included 50+ configured users and 15 receiving payments.","status":"verify_before_use","use":"commercial outcomes; confirm current date and definitions"}
  ]},
  {"id":"mylurah","name":"MyLurah","role":"Product Manager / PLG Advisor","tracks":["Product","Growth","Strategy","Development & Institutions"],"facts":[
   {"claim":"Worked cross-functionally on product management, product-led growth and growth initiatives for a culturally grounded women's health platform.","status":"user_reported","use":"product/growth roles"},
   {"claim":"Do not claim sole ownership of platform-wide user or engagement metrics.","status":"constraint","use":"all applications"}
  ]},
  {"id":"aortem","name":"Aortem","role":"Product Manager, Growth & GTM","tracks":["Growth","GTM","Strategy"],"facts":[
   {"claim":"Executed 94 outbound campaigns reaching 5,900+ prospects.","status":"user_reported","use":"growth/GTM roles"},
   {"claim":"Reported 29.6% average open rate.","status":"verify_before_use","use":"growth outcomes; confirm measurement basis"}
  ]},
  {"id":"src","name":"Startup Reality Check","role":"Founder / Independent Research Publisher","tracks":["Venture Capital","Research & Finance","Policy & Government","Development & Institutions","Strategy"],"facts":[
   {"claim":"Produced 30+ analyses of African technology companies, private capital, market structure, governance, valuation and liquidity.","status":"user_reported","use":"investment/research/policy roles"},
   {"claim":"Prepared a paid 10-page diligence memo for a venture investor.","status":"user_reported","use":"investment research roles"},
   {"claim":"Research method distinguishes fact, inference and thesis; prioritises evidence before conclusions.","status":"user_reported","use":"research/policy roles"}
  ]},
  {"id":"nexahealth","name":"NexaHealth","role":"Founder / Product Builder","tracks":["Product","Strategy","Development & Institutions"],"facts":[
   {"claim":"Built an AI-assisted medicine verification and pharmacy trust product prototype.","status":"user_reported","use":"product/health innovation roles"},
   {"claim":"Project-reported 2,000+ registered users and 101 DAU; these are project-level figures and must not be attributed solely to the applicant.","status":"verify_before_use","use":"impact; explain attribution"}
  ]},
  {"id":"layla","name":"Layla Orders","role":"Technical Product Builder","tracks":["Product","GTM"],"facts":[
   {"claim":"Built a WhatsApp ordering assistant prototype with Paystack test-mode payment verification.","status":"user_reported","use":"technical product roles"},
   {"claim":"Prototype and test-mode integration, not a production payment deployment.","status":"constraint","use":"all applications"}
  ]},
  {"id":"blocade","name":"Blocade","role":"Growth Campaign","tracks":["Growth","GTM"],"facts":[
   {"claim":"Campaign associated with 675,512 Instagram views over 14 days.","status":"verify_before_use","use":"growth metrics; verify personal contribution"}
  ]}
 ],
 "links":{"portfolio":"https://favourakintoye.com","portfolio_pdf":"https://drive.google.com/file/d/1hU-fzSRF9ReQOV21WkV7dbtkTmFmewrT/view?usp=drive_link","github":"https://github.com/Justreadin","payla":"https://payla.ng/@favour","research":"https://favourt.substack.com","resume_source":"https://drive.google.com/file/d/12JA1jq07qLRulzEjMY7B38DpFFYXp9af/view?usp=drive_link"},
 "location_policy":"Nigeria-based roles; Africa-wide remote roles open to Nigeria; international roles only where Nigerian applicants are explicitly eligible or eligibility can be confirmed."
}

from app.application_channels import classify_application_channel

def test_explicit_email_instruction_extracts_recipient():
    r=classify_application_channel('Please send your CV and cover letter to talent@example.com.', 'https://example.com/jobs/1')
    assert r['method']=='direct_email' and r['recipient']=='talent@example.com' and r['confidence']=='high'

def test_ats_host_is_detected():
    r=classify_application_channel('Apply now.', 'https://boards.greenhouse.io/acme/jobs/123')
    assert r['method']=='ats' and r['confidence']=='high'

def test_portal_language_is_detected():
    r=classify_application_channel('Please apply through our careers portal.', 'https://example.com/jobs')
    assert r['method']=='employer_portal'

def test_ambiguous_listing_is_not_guessed():
    r=classify_application_channel('We are hiring. Apply now.', 'https://example.com/jobs/1')
    assert r['method']=='unknown' and r['recipient']==''

def test_email_address_without_instruction_is_not_assumed_recipient():
    r=classify_application_channel('Contact talent@example.com for questions. Apply now.', 'https://example.com/jobs')
    assert r['method']=='unknown'

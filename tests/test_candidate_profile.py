import json
from app import candidate_profile

def test_candidate_profile_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / 'candidate.json'
    monkeypatch.setattr(candidate_profile, 'PATH', str(path))
    saved = candidate_profile.save_candidate_profile({'name':'Test User','skills':'Python, SQL'})
    assert saved['name'] == 'Test User'
    profile = candidate_profile.get_candidate_profile()
    assert profile['name'] == 'Test User'
    assert profile['candidate_details']['skills'] == 'Python, SQL'
    assert profile['evidence']  # static evidence remains intact

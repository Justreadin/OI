import os, json
from cryptography.fernet import Fernet
from app import gmail_service

def test_gmail_token_encryption_roundtrip(monkeypatch):
    monkeypatch.setenv('GMAIL_TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode())
    token={'access_token':'secret-token','refresh_token':'refresh-secret','email':'person@example.com'}
    encrypted=gmail_service.encrypt_token(token)
    assert 'secret-token' not in encrypted
    assert gmail_service.decrypt_token(encrypted)==token

def test_oauth_url_uses_pkce_and_send_only_scope(monkeypatch):
    config={'web':{'client_id':'client-id','client_secret':'client-secret'}}
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_CONFIG',json.dumps(config))
    url,state,verifier=gmail_service.authorization_url('https://example.com/gmail/oauth/callback')
    assert 'code_challenge_method=S256' in url
    assert 'gmail.send' in url
    assert 'gmail.readonly' not in url
    assert state and verifier and 'client-id' in url

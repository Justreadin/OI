"""Minimal Gmail OAuth/REST integration; tokens encrypted at rest."""
import base64, hashlib, json, os, secrets, urllib.parse
import httpx
from cryptography.fernet import Fernet, InvalidToken
SCOPES = "openid email https://www.googleapis.com/auth/gmail.send"
AUTH_ENDPOINT="https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT="https://oauth2.googleapis.com/token"
GMAIL_SEND_ENDPOINT="https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
USERINFO_ENDPOINT="https://openidconnect.googleapis.com/v1/userinfo"
class GmailNotConfigured(RuntimeError): pass

def _fernet():
    key=os.getenv('GMAIL_TOKEN_ENCRYPTION_KEY','').strip()
    if not key: raise GmailNotConfigured('Set GMAIL_TOKEN_ENCRYPTION_KEY before connecting Gmail.')
    try: return Fernet(key.encode())
    except Exception as e: raise GmailNotConfigured('GMAIL_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.') from e

def encrypt_token(value): return _fernet().encrypt(json.dumps(value).encode()).decode()
def decrypt_token(value):
    try: return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken,ValueError) as e: raise GmailNotConfigured('Stored Gmail credentials cannot be decrypted. Check the encryption key.') from e

def client_config():
    raw=os.getenv('GOOGLE_OAUTH_CLIENT_CONFIG','').strip(); path=os.getenv('GOOGLE_OAUTH_CLIENT_FILE','').strip()
    if raw:
        try: data=json.loads(raw)
        except Exception as e: raise GmailNotConfigured('GOOGLE_OAUTH_CLIENT_CONFIG is not valid JSON.') from e
    elif path and os.path.exists(path):
        with open(path,encoding='utf-8') as f: data=json.load(f)
    else: raise GmailNotConfigured('Configure GOOGLE_OAUTH_CLIENT_CONFIG or GOOGLE_OAUTH_CLIENT_FILE in the environment.')
    return data.get('web') or data.get('installed') or {}

def authorization_url(redirect_uri):
    config=client_config(); verifier=base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip('=')
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state=secrets.token_urlsafe(32)
    params={'client_id':config.get('client_id',''),'redirect_uri':redirect_uri,'response_type':'code','scope':SCOPES,
      'access_type':'offline','prompt':'consent','include_granted_scopes':'true','state':state,
      'code_challenge':challenge,'code_challenge_method':'S256'}
    return AUTH_ENDPOINT+'?'+urllib.parse.urlencode(params),state,verifier

def exchange_code(code,redirect_uri,verifier):
    config=client_config()
    response=httpx.post(TOKEN_ENDPOINT,data={'code':code,'client_id':config.get('client_id'),'client_secret':config.get('client_secret'),
      'redirect_uri':redirect_uri,'grant_type':'authorization_code','code_verifier':verifier},timeout=25)
    response.raise_for_status(); token=response.json()
    user=httpx.get(USERINFO_ENDPOINT,headers={'Authorization':'Bearer '+token['access_token']},timeout=20)
    user.raise_for_status(); claims=user.json()
    if not claims.get('email') or not claims.get('email_verified'): raise GmailNotConfigured('Google did not return a verified email address.')
    token['email']=claims['email']; token['expires_at']=__import__('time').time()+int(token.get('expires_in',3600))
    return token,claims['email']

def _valid_access_token(token):
    if token.get('expires_at',0)>__import__('time').time()+60: return token
    refresh=token.get('refresh_token')
    if not refresh: raise GmailNotConfigured('Gmail authorization expired. Reconnect the account.')
    config=client_config()
    response=httpx.post(TOKEN_ENDPOINT,data={'client_id':config.get('client_id'),'client_secret':config.get('client_secret'),
      'refresh_token':refresh,'grant_type':'refresh_token'},timeout=25)
    response.raise_for_status(); updated=response.json(); token.update(updated)
    token['expires_at']=__import__('time').time()+int(updated.get('expires_in',3600)); return token

def send_raw_message(token,raw_message):
    token=_valid_access_token(token)
    raw=base64.urlsafe_b64encode(raw_message).decode()
    response=httpx.post(GMAIL_SEND_ENDPOINT,headers={'Authorization':'Bearer '+token['access_token'],'Content-Type':'application/json'},
      json={'raw':raw},timeout=30)
    response.raise_for_status(); return response.json(),token

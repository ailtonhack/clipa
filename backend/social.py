"""Official OAuth and publication adapters. Provider approval is required."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlparse
import httpx
from cryptography.fernet import Fernet
from .core import DATA, db, identifier

def configured_base_url():
    explicit = os.getenv('CLIPA_BASE_URL')
    railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN')
    return (explicit or ('https://' + railway_domain if railway_domain else 'http://localhost:8000')).rstrip('/')


BASE_URL = configured_base_url()
GRAPH = 'https://graph.facebook.com/v23.0'
PROVIDERS = {
    'youtube': {'name': 'YouTube', 'prefix': 'YOUTUBE', 'auth': 'https://accounts.google.com/o/oauth2/v2/auth', 'token': 'https://oauth2.googleapis.com/token', 'scope': 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'},
    'tiktok': {'name': 'TikTok', 'prefix': 'TIKTOK', 'auth': 'https://www.tiktok.com/v2/auth/authorize/', 'token': 'https://open.tiktokapis.com/v2/oauth/token/', 'scope': 'user.info.basic,video.publish'},
    'facebook': {'name': 'Facebook + Instagram', 'prefix': 'META', 'auth': 'https://www.facebook.com/v23.0/dialog/oauth', 'token': GRAPH + '/oauth/access_token', 'scope': 'pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish'},
}


def credential_key():
    value = os.getenv('CLIPA_ENCRYPTION_KEY')
    if not value:
        path = DATA / 'credential.key'
        if not path.exists():
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'wb') as f:
                    f.write(Fernet.generate_key())
            except FileExistsError:
                pass
        value = path.read_bytes()
    return value.encode() if isinstance(value, str) else value


def cipher():
    return Fernet(credential_key())


def signing_key():
    return hashlib.sha256(base64.urlsafe_b64decode(credential_key()) + b'clipa-public-media').digest()


def check_response(response):
    if not response.is_success:
        raise ValueError(f'A plataforma recusou a solicitação (HTTP {response.status_code}). Confira as permissões, o token e os requisitos da conta.')
    value = response.json()
    if value.get('error') and (not isinstance(value['error'], dict) or value['error'].get('code') not in (None, 'ok')):
        raise ValueError('A plataforma recusou a operação. Confira a aprovação do aplicativo e as permissões da conta.')
    return value


def configuration():
    result = []
    for platform in ['youtube', 'tiktok', 'facebook', 'instagram']:
        spec = PROVIDERS['facebook' if platform == 'instagram' else platform]
        prefix = spec['prefix']
        ready = bool(os.getenv(prefix + '_CLIENT_ID') and os.getenv(prefix + '_CLIENT_SECRET'))
        if platform != 'youtube' and urlparse(BASE_URL).scheme != 'https':
            ready = False
        result.append({'platform': platform, 'configured': ready, 'name': platform.capitalize(), 'message': 'Pronto para conectar' if ready else 'Faltam credenciais oficiais e/ou endereço HTTPS do servidor'})
    return result


def authorization_url(platform):
    if platform == 'instagram':
        platform = 'facebook'
    if platform not in PROVIDERS or not next(p for p in configuration() if p['platform'] == platform)['configured']:
        raise ValueError('Configure as credenciais oficiais e a URL do servidor antes de conectar esta rede.')
    spec = PROVIDERS[platform]
    state = secrets.token_urlsafe(32)
    with db() as c:
        c.execute('DELETE FROM oauth WHERE expires < ?', (int(time.time()),))
        c.execute('INSERT INTO oauth VALUES(?,?,?)', (state, platform, int(time.time()) + 600))
    params = {'client_key' if platform == 'tiktok' else 'client_id': os.getenv(spec['prefix'] + '_CLIENT_ID'), 'redirect_uri': f'{BASE_URL}/api/oauth/{platform}/callback', 'response_type': 'code', 'scope': spec['scope'], 'state': state}
    if platform == 'youtube':
        params.update(access_type='offline', prompt='consent')
    return spec['auth'] + '?' + urlencode(params)


def save_account(platform, external_id, name, credential):
    account_id = hashlib.sha256(f'{platform}:{external_id}'.encode()).hexdigest()[:32]
    encoded = cipher().encrypt(json.dumps(credential).encode()).decode()
    with db() as c:
        c.execute('INSERT OR REPLACE INTO accounts VALUES(?,?,?,?)', (account_id, platform, name, encoded))
    return account_id


def complete_oauth(platform, state, code):
    with db() as c:
        entry = c.execute('SELECT * FROM oauth WHERE state=? AND platform=?', (state, platform)).fetchone()
        if not entry or entry['expires'] < time.time():
            raise ValueError('Esta conexão expirou. Inicie novamente pelo estúdio.')
        c.execute('DELETE FROM oauth WHERE state=?', (state,))
    spec = PROVIDERS[platform]
    prefix = spec['prefix']
    payload = {'client_key' if platform == 'tiktok' else 'client_id': os.getenv(prefix + '_CLIENT_ID'), 'client_secret': os.getenv(prefix + '_CLIENT_SECRET'), 'code': code, 'grant_type': 'authorization_code', 'redirect_uri': f'{BASE_URL}/api/oauth/{platform}/callback'}
    with httpx.Client(timeout=60) as client:
        token = check_response(client.get(spec['token'], params=payload) if platform == 'facebook' else client.post(spec['token'], data=payload))
        token['expires_at'] = time.time() + token.get('expires_in', 3600)
        access = token['access_token']
        if platform == 'facebook':
            extended = check_response(client.get(spec['token'], params={'grant_type': 'fb_exchange_token', 'client_id': os.getenv(prefix + '_CLIENT_ID'), 'client_secret': os.getenv(prefix + '_CLIENT_SECRET'), 'fb_exchange_token': access}))
            access = extended['access_token']
        if platform == 'youtube':
            channels = check_response(client.get('https://www.googleapis.com/youtube/v3/channels', params={'part': 'snippet', 'mine': 'true'}, headers={'Authorization': 'Bearer ' + access})).get('items', [])
            if not channels:
                raise ValueError('Crie um canal no YouTube antes de conectar.')
            channel = channels[0]
            save_account(platform, channel['id'], channel['snippet']['title'], token)
        elif platform == 'tiktok':
            user = check_response(client.get('https://open.tiktokapis.com/v2/user/info/', params={'fields': 'open_id,display_name'}, headers={'Authorization': 'Bearer ' + access}))['data']['user']
            save_account(platform, user['open_id'], user['display_name'], token)
        else:
            # Persist page credentials, not the user's general Facebook token.
            pages = check_response(client.get(GRAPH + '/me/accounts', params={'fields': 'id,name,access_token,instagram_business_account{id,username}', 'access_token': access}))['data']
            if not pages:
                raise ValueError('Nenhuma Página do Facebook disponível. Instagram exige conta profissional vinculada a uma Página.')
            for page in pages:
                page_token = {'access_token': page['access_token'], 'external_id': page['id']}
                save_account('facebook', page['id'], page['name'], page_token)
                ig = page.get('instagram_business_account')
                if ig:
                    save_account('instagram', ig['id'], ig.get('username', page['name']), {**page_token, 'external_id': ig['id']})


def get_account(account_id):
    with db() as c:
        row = c.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
    if not row:
        raise ValueError('A conta foi desconectada.')
    account = dict(row)
    token = json.loads(cipher().decrypt(account.pop('credential').encode()))
    platform = account['platform']
    if platform in ('youtube', 'tiktok') and token.get('expires_at', 0) < time.time() + 120:
        if not token.get('refresh_token'):
            raise ValueError('Reconecte a conta para renovar a autorização.')
        spec = PROVIDERS[platform]
        prefix = spec['prefix']
        with httpx.Client(timeout=60) as client:
            refreshed = check_response(client.post(spec['token'], data={'client_key' if platform == 'tiktok' else 'client_id': os.getenv(prefix + '_CLIENT_ID'), 'client_secret': os.getenv(prefix + '_CLIENT_SECRET'), 'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}))
        token.update(refreshed)
        token['expires_at'] = time.time() + token.get('expires_in', 3600)
        with db() as c:
            c.execute('UPDATE accounts SET credential=? WHERE id=?', (cipher().encrypt(json.dumps(token).encode()).decode(), account_id))
    return account, token


def chunks(path, size=8*1024*1024):
    with open(path, 'rb') as f:
        while data := f.read(size):
            yield data


def signed_media_url(export_id):
    if not BASE_URL.startswith('https://') or urlparse(BASE_URL).hostname in ('localhost', '127.0.0.1'):
        raise ValueError('Instagram exige um servidor HTTPS público para buscar o vídeo.')
    expiry = int(time.time()) + 3600
    signature = hmac.new(signing_key(), f'{export_id}:{expiry}'.encode(), hashlib.sha256).hexdigest()
    return f'{BASE_URL}/api/public-media/{export_id}?expires={expiry}&signature={signature}'


def valid_signature(export_id, expires, signature):
    if expires < time.time() or expires > time.time() + 3700:
        return False
    expected = hmac.new(signing_key(), f'{export_id}:{expires}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def publish(item, path):
    account, token = get_account(item['account_id'])
    access = token['access_token']
    auth = {'Authorization': 'Bearer ' + access}
    platform = account['platform']
    with httpx.Client(timeout=120) as client:
        if platform == 'youtube':
            metadata = {'snippet': {'title': item['title'][:100], 'description': item['caption'][:5000]}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
            response = client.post('https://www.googleapis.com/upload/youtube/v3/videos', params={'uploadType': 'resumable', 'part': 'snippet,status'}, headers={**auth, 'X-Upload-Content-Type': 'video/mp4', 'X-Upload-Content-Length': str(path.stat().st_size)}, json=metadata)
            if not response.is_success or 'location' not in response.headers:
                raise ValueError('YouTube não autorizou o envio. Confira a cota e a aprovação do aplicativo.')
            uploaded = check_response(client.put(response.headers['location'], headers={**auth, 'Content-Type': 'video/mp4', 'Content-Length': str(path.stat().st_size)}, content=chunks(path)))
            return {'platform_id': uploaded['id'], 'url': 'https://www.youtube.com/watch?v=' + uploaded['id']}
        if platform == 'facebook':
            with open(path, 'rb') as video:
                value = check_response(client.post(f"{GRAPH}/{token['external_id']}/videos", data={'access_token': access, 'title': item['title'], 'description': item['caption']}, files={'source': ('clip.mp4', video, 'video/mp4')}))
            return {'platform_id': value['id'], 'url': 'https://www.facebook.com/' + value['id']}
        if platform == 'instagram':
            media = check_response(client.post(f"{GRAPH}/{token['external_id']}/media", data={'access_token': access, 'media_type': 'REELS', 'video_url': signed_media_url(item['export_id']), 'caption': item['caption'], 'share_to_feed': 'true'}))
            container = media['id']
            for _ in range(60):
                state = check_response(client.get(f'{GRAPH}/{container}', params={'fields': 'status_code', 'access_token': access}))['status_code']
                if state == 'FINISHED':
                    break
                if state in ('ERROR', 'EXPIRED'):
                    raise ValueError('Instagram recusou o processamento do vídeo.')
                time.sleep(5)
            else:
                raise ValueError('Instagram ainda está processando. Confira a conta antes de reagendar.')
            value = check_response(client.post(f"{GRAPH}/{token['external_id']}/media_publish", data={'access_token': access, 'creation_id': container}))
            return {'platform_id': value['id']}
        if platform == 'tiktok':
            creator = check_response(client.post('https://open.tiktokapis.com/v2/post/publish/creator_info/query/', headers=auth, json={}))['data']
            if 'PUBLIC_TO_EVERYONE' not in creator.get('privacy_level_options', []):
                raise ValueError('TikTok não autorizou publicação pública. O aplicativo precisa de aprovação para Direct Post.')
            if item.get('consent') is not True:
                raise ValueError('Confirme as opções de publicação do TikTok no agendamento.')
            size = path.stat().st_size
            # TikTok accepts one chunk up to 64 MB, otherwise chunks between 5 and 64 MB.
            chunk_size = min(size, 10*1024*1024)
            count = max(1, size // chunk_size)
            value = check_response(client.post('https://open.tiktokapis.com/v2/post/publish/video/init/', headers=auth, json={'post_info': {'title': item['caption'][:2200], 'privacy_level': 'PUBLIC_TO_EVERYONE', 'disable_duet': True, 'disable_stitch': True, 'disable_comment': True, 'video_cover_timestamp_ms': 0}, 'source_info': {'source': 'FILE_UPLOAD', 'video_size': size, 'chunk_size': chunk_size, 'total_chunk_count': count}}))['data']
            with open(path, 'rb') as video:
                for index in range(count):
                    remaining = size - video.tell()
                    length = remaining if index == count - 1 else chunk_size
                    offset = video.tell()
                    response = client.put(value['upload_url'], content=video.read(length), headers={'Content-Type': 'video/mp4', 'Content-Length': str(length), 'Content-Range': f'bytes {offset}-{offset+length-1}/{size}'})
                    if not response.is_success:
                        raise ValueError('TikTok recusou o envio do vídeo.')
            for _ in range(60):
                result = check_response(client.post('https://open.tiktokapis.com/v2/post/publish/status/fetch/', headers=auth, json={'publish_id': value['publish_id']}))['data']
                if result['status'] == 'PUBLISH_COMPLETE':
                    return {'platform_id': value['publish_id'], 'provider_status': result['status']}
                if result['status'] == 'FAILED':
                    raise ValueError('TikTok recusou a publicação. Confira os requisitos da conta e do vídeo.')
                time.sleep(5)
            raise ValueError('TikTok ainda está processando. Confira a conta antes de reagendar.')
    raise ValueError('Rede não suportada.')

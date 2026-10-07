import importlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv('CLIPA_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('CLIPA_PASSWORD', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    from backend import core, social, app
    importlib.reload(core)
    importlib.reload(social)
    importlib.reload(app)
    with TestClient(app.app) as client:
        yield client, core, social, app


def test_supported_links_reject_untrusted_addresses():
    from backend.core import validate_link
    for url in ['https://youtu.be/test', 'https://clips.twitch.tv/TestClip', 'https://kick.com/channel?clip=clip_id']:
        assert validate_link(url) == url
    for url in ['http://youtube.com/watch?v=test', 'https://youtube.com.evil.test/a', 'https://127.0.0.1/a', 'https://youtube.com@evil.test/a', 'https://youtube.com:8080/a', 'file:///etc/passwd', 'https://youtube.com/']:
        with pytest.raises(ValueError):
            validate_link(url)


def test_clips_reject_out_of_bounds_and_nonfinite():
    from backend.core import normalize_clips
    raw = [{'start': 5, 'end': 35, 'title': 'Bom'}, {'start': -1, 'end': 4}, {'start': 0, 'end': 90}, {'start': 0, 'end': float('nan')}, {'start': 35, 'end': 10}, {'start': 5, 'end': 110}]
    assert normalize_clips(raw, 100, 30) == [{'start': 5.0, 'end': 35.0, 'title': 'Bom', 'reason': ''}]


def test_relative_subtitles_and_markup():
    from backend.core import make_srt
    segments = [{'start': 3, 'end': 8, 'text': 'Olá {\\an8}mundo'}, {'start': 9, 'end': 14, 'text': 'Segundo trecho'}, {'start': 20, 'end': 25, 'text': 'Fora do corte'}]
    value = make_srt(segments, 5, 12)
    assert '00:00:00,000 --> 00:00:03,000' in value
    assert '00:00:04,000 --> 00:00:07,000' in value
    assert 'Olá mundo' in value and 'Fora' not in value and '\\an8' not in value


def create_video(path):
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=15', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '4', '-c:v', 'libx264', '-c:a', 'aac', str(path)], check=True)


def test_upload_render_subtitles_and_audio(studio, tmp_path):
    client, core, social, app = studio
    original = tmp_path / 'test.mp4'
    create_video(original)
    with original.open('rb') as f:
        response = client.post('/api/upload', files={'file': ('test.mp4', f, 'video/mp4')})
    assert response.status_code == 200, response.text
    video = response.json()
    video_id = video['video_id']
    assert client.get(video['url']).status_code == 200
    segments = [{'start': 0, 'end': 2, 'text': 'Legenda original'}, {'start': 2, 'end': 4, 'text': 'Outra legenda'}]
    with core.db() as c:
        c.execute('UPDATE videos SET transcript=? WHERE id=?', (json.dumps(segments), video_id))
    payload = app.RenderInput(video_id=video_id, start=1, end=3, format='vertical', subtitles=True, title='Teste', segments=[{'start': 0, 'end': 2, 'text': 'Legenda revisada'}, {'start': 2, 'end': 4, 'text': 'Outra legenda'}])
    payload.segments = [part.model_dump() for part in payload.segments]
    result = app.render_job('not-a-job', payload)
    assert client.get(result['url']).status_code == 200
    captions = client.get(result['subtitles_url']).text
    assert 'Legenda revisada' in captions and '00:00:00,000 --> 00:00:01,000' in captions
    with core.db() as c:
        output = Path(c.execute('SELECT filename FROM exports WHERE id=?', (result['export_id'],)).fetchone()['filename'])
    info = json.loads(core.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output)]))
    video_stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    assert (video_stream['width'], video_stream['height']) == (540, 960)
    assert any(s['codec_type'] == 'audio' for s in info['streams'])
    assert 1.9 <= float(info['format']['duration']) <= 2.2


def test_bad_subtitle_shape_is_validation_error(studio):
    client, *_ = studio
    response = client.post('/api/render', json={'video_id': 'a'*32, 'start': 0, 'end': 2, 'subtitles': True, 'segments': [{'start': 0, 'text': 'Sem fim'}]})
    assert response.status_code == 422


def test_schedule_requires_connection_consent_future_and_cancellation(studio, tmp_path):
    client, core, social, app = studio
    path = tmp_path / 'export.mp4'
    path.write_bytes(b'test')
    with core.db() as c:
        c.execute('INSERT INTO exports VALUES(?,?,?,?)', ('export', 'video', str(path), 'Teste'))
    payload = {'export_id': 'export', 'account_id': 'missing', 'title': 'Teste', 'caption': 'Descrição', 'when': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), 'consent': True}
    assert client.post('/api/schedules', json=payload).status_code == 400
    social.save_account('youtube', 'channel', 'Meu canal', {'access_token': 'secret', 'expires_at': 9999999999})
    config = client.get('/api/config').json()
    assert 'secret' not in json.dumps(config)
    payload['account_id'] = config['accounts'][0]['id']
    payload['consent'] = False
    assert client.post('/api/schedules', json=payload).status_code == 400
    payload['consent'] = True
    payload['when'] = datetime.now(timezone.utc).isoformat()
    assert client.post('/api/schedules', json=payload).status_code == 400
    payload['when'] = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    created = client.post('/api/schedules', json=payload)
    assert created.status_code == 200
    assert client.delete('/api/schedules/'+created.json()['id']).status_code == 200
    assert client.get('/api/schedules').json()[0]['status'] == 'cancelled'


def test_oauth_rejects_missing_state_and_replay(studio):
    client, core, social, app = studio
    with pytest.raises(ValueError):
        social.complete_oauth('youtube', 'invalid', 'fake-code')
    with core.db() as c:
        c.execute('INSERT INTO oauth VALUES(?,?,?)', ('expired', 'youtube', 1))
    with pytest.raises(ValueError):
        social.complete_oauth('youtube', 'expired', 'fake-code')


def test_signed_media_and_auth(studio, monkeypatch, tmp_path):
    client, core, social, app = studio
    monkeypatch.setenv('CLIPA_PASSWORD', 'local-password')
    assert client.get('/api/config').status_code == 401
    assert client.get('/api/config', auth=('clipa', 'local-password')).status_code == 200
    path = tmp_path / 'export.mp4'
    path.write_bytes(b'mp4')
    with core.db() as c:
        c.execute('INSERT INTO exports VALUES(?,?,?,?)', ('export', 'video', str(path), 'Teste'))
    monkeypatch.setattr(social, 'BASE_URL', 'https://studio.example.com')
    url = social.signed_media_url('export')
    relative = url.replace(social.BASE_URL, '')
    assert client.get(relative).status_code == 200
    assert client.get(relative+'&signature=invalid').status_code == 403
    assert client.post('/api/import', json={'url': 'https://youtu.be/test'}, auth=('clipa', 'local-password'), headers={'Origin': 'https://evil.test'}).status_code == 403


def test_analysis_extracts_audio_and_filters_ai_suggestions(studio, tmp_path, monkeypatch):
    client, core, social, app = studio
    original = tmp_path / 'analysis.mp4'
    create_video(original)
    with original.open('rb') as f:
        video = client.post('/api/upload', files={'file': ('analysis.mp4', f, 'video/mp4')}).json()
    import httpx
    real_client = httpx.Client
    calls = []
    def respond(request):
        calls.append(request.url.path)
        assert request.headers['authorization'] == 'Bearer test-key'
        if request.url.path.endswith('transcriptions'):
            assert b'audio/wav' in request.content
            return httpx.Response(200, json={'segments': [{'start': 0, 'end': 2, 'text': 'Uma ideia.'}, {'start': 2, 'end': 4, 'text': 'Uma conclusão.'}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'clips': [{'start': 0, 'end': 3, 'title': 'Ideia completa', 'reason': 'Gancho'}, {'start': 0, 'end': 99, 'title': 'Inválido'}]})}}]})
    monkeypatch.setattr(app.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    result = app.analyze('test-job', video['video_id'], 30, 'test-key')
    assert len(result['clips']) == 1 and result['clips'][0]['end'] == 3
    assert len(result['segments']) == 2
    assert calls == ['/v1/audio/transcriptions', '/v1/chat/completions']
    with core.db() as c:
        text = c.execute('SELECT transcript FROM videos WHERE id=?', (video['video_id'],)).fetchone()['transcript']
    assert 'Uma conclusão.' in text and 'test-key' not in text


def test_restart_marks_publication_uncertain(studio):
    client, core, *_ = studio
    with core.db() as c:
        c.execute("INSERT INTO schedule VALUES('interrupted','export','account','Título','Texto',0,'publishing',NULL,NULL)")
    core.init_db()
    with core.db() as c:
        row = c.execute("SELECT status FROM schedule WHERE id='interrupted'").fetchone()
    assert row['status'] == 'uncertain'


def test_railway_domain_and_explicit_domain(monkeypatch):
    from backend.social import configured_base_url
    monkeypatch.delenv('CLIPA_BASE_URL', raising=False)
    monkeypatch.setenv('RAILWAY_PUBLIC_DOMAIN', 'clipa-test.up.railway.app')
    assert configured_base_url() == 'https://clipa-test.up.railway.app'
    monkeypatch.setenv('CLIPA_BASE_URL', 'https://studio.example.com/')
    assert configured_base_url() == 'https://studio.example.com'


def test_health_is_public_without_exposing_configuration(studio, monkeypatch):
    client, *_ = studio
    monkeypatch.setenv('CLIPA_PASSWORD', 'secret-password')
    assert client.get('/api/health').json() == {'status': 'ok'}
    assert client.get('/api/config').status_code == 401

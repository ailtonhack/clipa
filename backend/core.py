"""Local, single-user studio. No secrets are stored in jobs or API responses."""
import json
import math
import os
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('CLIPA_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'clipa.sqlite3'


def db():
    connection = sqlite3.connect(DB, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, status TEXT, progress TEXT, result TEXT, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS videos(id TEXT PRIMARY KEY, filename TEXT, duration REAL, transcript TEXT);
        CREATE TABLE IF NOT EXISTS exports(id TEXT PRIMARY KEY, video_id TEXT, filename TEXT, title TEXT);
        CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, platform TEXT, name TEXT, credential TEXT);
        CREATE TABLE IF NOT EXISTS oauth(state TEXT PRIMARY KEY, platform TEXT, expires INTEGER);
        CREATE TABLE IF NOT EXISTS schedule(id TEXT PRIMARY KEY, export_id TEXT, account_id TEXT, title TEXT, caption TEXT, due REAL, status TEXT, result TEXT, error TEXT);
        ''')
        # Interrupted work is never silently retried: publication may already exist.
        c.execute("UPDATE jobs SET status='failed', error='O servidor foi reiniciado durante o processamento.' WHERE status IN ('queued','running')")
        c.execute("UPDATE schedule SET status='uncertain', error='Servidor reiniciado durante publicação. Confira a rede antes de tentar novamente.' WHERE status='publishing'")


def identifier():
    return uuid.uuid4().hex


def run(args, timeout=1800):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Third-party output may include API query parameters; never expose it.
        raise ValueError('O processamento de mídia falhou. Verifique o formato do vídeo e a instalação do FFmpeg.')
    return result.stdout


def probe(path):
    info = json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], 30))
    duration = float(info.get('format', {}).get('duration', 0))
    if not any(s.get('codec_type') == 'video' for s in info['streams']) or not 3 <= duration <= 7200:
        raise ValueError('Envie um vídeo entre 3 segundos e 2 horas.')
    return duration


def video_path(video_id):
    if not re.fullmatch(r'[a-f0-9]{32}', video_id):
        raise ValueError('Vídeo inválido.')
    return DATA / video_id / 'source.mp4'


def validate_link(url):
    parsed = urlparse(url)
    hosts = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'twitch.tv', 'www.twitch.tv', 'clips.twitch.tv', 'kick.com', 'www.kick.com', 'clips.kick.com'}
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Use um link HTTPS público do YouTube, Twitch ou Kick.')
    if not parsed.path.strip('/'):
        raise ValueError('Cole o link de um vídeo ou clip, não a página inicial.')
    return url


def normalize_clips(raw, duration, maximum):
    result = []
    for clip in raw:
        try:
            start, end = float(clip['start']), float(clip['end'])
        except (KeyError, ValueError, TypeError):
            continue
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration and end - start <= maximum + 1):
            continue
        result.append({'start': start, 'end': end, 'title': str(clip.get('title', 'Novo corte'))[:140], 'reason': str(clip.get('reason', ''))[:800]})
    return result[:6]


def srt_time(seconds):
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, millis = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def make_srt(segments, start, end):
    lines = []
    for segment in segments:
        left, right = max(start, float(segment['start'])), min(end, float(segment['end']))
        text = re.sub(r'[\x00-\x1f]', ' ', str(segment['text'])).strip()
        # FFmpeg interprets ASS overrides in subtitles; strip them from user text.
        text = re.sub(r'\{[^}]*\}', '', text).replace('\\', '')
        if right <= left or not text:
            continue
        lines.append(f'{len(lines)+1}\n{srt_time(left-start)} --> {srt_time(right-start)}\n{text}\n')
    return '\n'.join(lines)


def render_video(video_id, start, end, format_name, subtitles, title):
    path = video_path(video_id)
    duration = probe(path)
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration and end-start <= 180):
        raise ValueError('Escolha um corte de até 180 segundos, dentro do vídeo.')
    export_id = identifier()
    folder = DATA / export_id
    folder.mkdir()
    filters = []
    if format_name == 'vertical':
        filters.append('scale=540:960:force_original_aspect_ratio=increase,crop=540:960,setsar=1')
    elif format_name == 'square':
        filters.append('scale=720:720:force_original_aspect_ratio=increase,crop=720:720,setsar=1')
    else:
        filters.append('scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1')
    with db() as c:
        video = c.execute('SELECT transcript FROM videos WHERE id=?', (video_id,)).fetchone()
    if subtitles:
        if not video or not video['transcript']:
            raise ValueError('Analise a fala antes de adicionar legendas.')
        content = make_srt(subtitles, start, end)
        if not content.strip():
            raise ValueError('Não há fala neste intervalo para legendar.')
        subtitle_path = folder / 'captions.srt'
        subtitle_path.write_text(content, encoding='utf-8')
        # Only generated IDs are used in the filter path.
        filters.append("subtitles=filename='" + str(subtitle_path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'") + "':force_style='FontName=DejaVu Sans,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00202020,BorderStyle=1,Outline=2,Alignment=2,MarginV=35'")
    output = folder / 'clip.mp4'
    run(['ffmpeg', '-nostdin', '-y', '-ss', str(start), '-i', str(path), '-t', str(end-start), '-vf', ','.join(filters), '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-movflags', '+faststart', str(output)])
    with db() as c:
        c.execute('INSERT INTO exports VALUES(?,?,?,?)', (export_id, video_id, str(output), title[:140]))
    return {'export_id': export_id, 'url': f'/api/exports/{export_id}', 'subtitles_url': f'/api/exports/{export_id}/subtitles' if subtitles else None}

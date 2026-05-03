#!/usr/bin/env python3
"""
tiktok_scanner.py — Scanner de canais TikTok com fila persistente.

Arquitetura:
  - scan_channel_to_queue: lista metadata (flat-playlist) e popula tiktok_videos
    com status='pendente' (ou 'pulado' para photo-posts). NAO baixa MP4.
  - download_pending_videos: consome a fila (oldest-first por default), baixa
    via yt-dlp e cria pasta em imports/. Nao chama flat-playlist.
  - process_all_channels: fluxo completo (scan + download) para manutencao.

O scheduler chama apenas download_pending_videos no horario agendado. Scans
completos sao disparados manualmente (dashboard) ou via scan leve.
"""

import json
import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
IMPORTS_DIR = os.path.join(PROJECT_ROOT, 'imports')

sys.path.insert(0, PROJECT_ROOT)
import db


def log(msg):
    print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}', flush=True)


def _build_tiktok_url(handle):
    handle = handle.strip()
    if handle.startswith('http'):
        return handle
    if not handle.startswith('@'):
        handle = '@' + handle
    return f'https://www.tiktok.com/{handle}'


# ---------------------------------------------------------------------------
# SCAN: popula a fila (tiktok_videos) sem baixar MP4
# ---------------------------------------------------------------------------

def scan_channel_to_queue(channel, playlist_end=5000, timeout=1200):
    """Lista metadata do canal e popula a fila.

    Retorna dict: {novos, pulados, ja_conhecidos, antes_data, total_scanned, erro}.
    """
    handle = channel['handle']
    url = _build_tiktok_url(handle)
    data_desde = channel.get('data_desde', '')

    log(f'  Scan -> fila: {handle} (desde={data_desde}, limite={playlist_end})')

    cmd = ['yt-dlp', '--flat-playlist', '-j', '--no-warnings']
    if playlist_end and playlist_end > 0:
        cmd += ['--playlist-end', str(playlist_end)]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or '')[:200]
            log(f'  yt-dlp erro: {err}')
            return {'novos': 0, 'pulados': 0, 'ja_conhecidos': 0, 'antes_data': 0,
                    'total_scanned': 0, 'erro': err}
    except subprocess.TimeoutExpired:
        log(f'  yt-dlp timeout para {handle}')
        return {'novos': 0, 'pulados': 0, 'ja_conhecidos': 0, 'antes_data': 0,
                'total_scanned': 0, 'erro': 'timeout'}

    novos = pulados = ja_conhecidos = antes_data = total = 0

    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        vid_id = info.get('id', '')
        if not vid_id:
            continue

        total += 1

        upload_date = info.get('upload_date', '')  # YYYYMMDD
        if data_desde and upload_date:
            desde_fmt = data_desde.replace('-', '')
            if upload_date < desde_fmt:
                antes_data += 1
                continue

        if db.is_tiktok_known(vid_id):
            ja_conhecidos += 1
            continue

        duration = info.get('duration') or 0
        title = info.get('title', '')
        video_url = (info.get('url', '') or info.get('webpage_url', '')
                     or f'https://www.tiktok.com/@{handle.lstrip("@")}/video/{vid_id}')

        if not duration:
            # Photo-post / slideshow: marca como pulado direto
            db.upsert_tiktok_video(vid_id, handle, title=title, url=video_url,
                                   upload_date=upload_date, duration=0,
                                   status='pulado', skip_reason='foto_post')
            pulados += 1
            continue

        db.upsert_tiktok_video(vid_id, handle, title=title, url=video_url,
                               upload_date=upload_date, duration=int(duration),
                               status='pendente')
        novos += 1

    log(f'  Scan: {total} escaneados | {novos} novos na fila | {ja_conhecidos} ja conhecidos | '
        f'{antes_data} antes de {data_desde} | {pulados} pulados (foto-post)')

    db.update_tiktok_channel(channel['id'],
        ultimo_scan=datetime.now().strftime('%Y-%m-%d %H:%M'))

    return {'novos': novos, 'pulados': pulados, 'ja_conhecidos': ja_conhecidos,
            'antes_data': antes_data, 'total_scanned': total, 'erro': ''}


# ---------------------------------------------------------------------------
# FETCH NEW: scan incremental com early-break no cutoff
# ---------------------------------------------------------------------------

def fetch_new_videos_for_channel(channel, safety_cap=5000, timeout=1200):
    """Scan incremental: pega so videos com upload_date > cutoff.

    Cutoff = MAX(upload_date) ja conhecida na fila. Fallback: data_desde.
    yt-dlp retorna newest-first; iteramos e paramos assim que ver upload_date < cutoff.
    """
    handle = channel['handle']
    url = _build_tiktok_url(handle)

    cutoff = db.get_tiktok_max_upload_date(handle)
    if not cutoff:
        cutoff = (channel.get('data_desde', '') or '').replace('-', '')

    data_desde_fmt = (channel.get('data_desde', '') or '').replace('-', '')

    log(f'  Fetch novos: {handle} (cutoff={cutoff or "sem cutoff"})')

    cmd = ['yt-dlp', '--flat-playlist', '-j', '--no-warnings',
           '--playlist-end', str(safety_cap), url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or '')[:200]
            log(f'  yt-dlp erro: {err}')
            return {'novos': 0, 'pulados': 0, 'ja_conhecidos': 0, 'antes_data': 0,
                    'parou_em_cutoff': False, 'erro': err}
    except subprocess.TimeoutExpired:
        log(f'  yt-dlp timeout para {handle}')
        return {'novos': 0, 'pulados': 0, 'ja_conhecidos': 0, 'antes_data': 0,
                'parou_em_cutoff': False, 'erro': 'timeout'}

    novos = pulados = ja_conhecidos = antes_data = 0
    parou_em_cutoff = False

    for line in result.stdout.strip().split('\n'):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            continue

        vid_id = info.get('id', '')
        if not vid_id:
            continue

        upload_date = info.get('upload_date', '')

        # Early break: yt-dlp retorna newest-first; se ja caimos no cutoff, para aqui.
        if cutoff and upload_date and upload_date < cutoff:
            parou_em_cutoff = True
            break

        # Filtro extra de data_desde (nao quebra; so nao insere)
        if data_desde_fmt and upload_date and upload_date < data_desde_fmt:
            antes_data += 1
            continue

        if db.is_tiktok_known(vid_id):
            ja_conhecidos += 1
            continue

        duration = info.get('duration') or 0
        title = info.get('title', '')
        video_url = (info.get('url', '') or info.get('webpage_url', '')
                     or f'https://www.tiktok.com/@{handle.lstrip("@")}/video/{vid_id}')

        if not duration:
            db.upsert_tiktok_video(vid_id, handle, title=title, url=video_url,
                                   upload_date=upload_date, duration=0,
                                   status='pulado', skip_reason='foto_post')
            pulados += 1
            continue

        db.upsert_tiktok_video(vid_id, handle, title=title, url=video_url,
                               upload_date=upload_date, duration=int(duration),
                               status='pendente')
        novos += 1

    log(f'  Fetch: {novos} novos na fila | {ja_conhecidos} ja conhecidos | '
        f'{pulados} pulados | {antes_data} antes de {channel.get("data_desde","")} | '
        f'{"parou no cutoff" if parou_em_cutoff else "iterou ate o fim"}')

    db.update_tiktok_channel(channel['id'],
        ultimo_scan=datetime.now().strftime('%Y-%m-%d %H:%M'))

    return {'novos': novos, 'pulados': pulados, 'ja_conhecidos': ja_conhecidos,
            'antes_data': antes_data, 'parou_em_cutoff': parou_em_cutoff, 'erro': ''}


# ---------------------------------------------------------------------------
# DOWNLOAD: consome a fila (tiktok_videos status='pendente')
# ---------------------------------------------------------------------------

def _download_single(video, folder_path):
    """Baixa um video. Retorna nome do arquivo mp4 ou None."""
    vid_id = video['tiktok_id']
    video_url = video['url']
    out_template = os.path.join(folder_path, f'{vid_id}.%(ext)s')

    try:
        result = subprocess.run(
            ['yt-dlp', '-o', out_template, '--no-warnings',
             '--format', 'best[ext=mp4]/best',
             '--merge-output-format', 'mp4',
             video_url],
            capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        log(f'  Timeout ao baixar {vid_id}')
        return None

    if result.returncode != 0:
        log(f'  Download falhou {vid_id}: {(result.stderr or "")[:200]}')
        return None

    for f in os.listdir(folder_path):
        if f.startswith(vid_id) and f.endswith('.mp4'):
            return f
    return None


def download_pending_for_channel(channel, max_por_scan=None):
    """Baixa N pendentes de um canal (oldest-first), cria manifest.

    Retorna dict: {downloaded, errors, folder, handle}.
    """
    handle = channel['handle']
    if max_por_scan is None:
        max_por_scan = int(channel.get('max_por_scan', 2) or 2)

    pending = db.get_pending_tiktok_videos(handle, limit=max_por_scan, order='oldest')
    if not pending:
        return {'handle': handle, 'downloaded': 0, 'errors': 0, 'folder': '', 'ok': True}

    handle_clean = handle.strip().lstrip('@')
    today = datetime.now().strftime('%Y%m%d')
    folder_name = f'tiktok_{handle_clean}_{today}'
    folder_path = os.path.join(IMPORTS_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    manifest_path = os.path.join(folder_path, 'manifest.json')
    existing_clips = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                raw = json.load(f)
            existing_clips = raw.get('clips', []) if isinstance(raw, dict) else raw
        except Exception:
            existing_clips = []

    downloaded_new = []
    errors = 0

    for video in pending:
        vid_id = video['tiktok_id']
        title = video.get('title') or f'tiktok_{vid_id}'

        if any(vid_id in c.get('file', '') for c in existing_clips):
            db.mark_tiktok_video_status(vid_id, 'baixado')
            continue

        log(f'  Baixando: {title[:50]} ({vid_id})')
        mp4_file = _download_single(video, folder_path)

        if not mp4_file:
            errors += 1
            db.mark_tiktok_video_status(vid_id, 'erro', skip_reason='download_falhou')
            continue

        downloaded_new.append({
            'file': mp4_file,
            'title': title,
            'description': '',
            'tags': ['tiktok', handle_clean],
        })
        db.mark_tiktok_video_status(vid_id, 'baixado')

    if downloaded_new:
        all_clips = existing_clips + downloaded_new
        manifest = {
            'titulo': f'TikTok @{handle_clean}',
            'privacy': 'public',
            'clips': all_clips
        }
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        log(f'  Manifest: {folder_name} ({len(downloaded_new)} novo(s), {len(all_clips)} total)')
    else:
        # Remove pasta vazia se foi criada agora
        try:
            if not existing_clips:
                os.rmdir(folder_path)
        except OSError:
            pass

    # Atualiza contador do canal
    stats = db.get_tiktok_channel_stats(handle)
    db.update_tiktok_channel(channel['id'], total_baixados=stats['baixado'])

    return {'handle': handle, 'downloaded': len(downloaded_new), 'errors': errors,
            'folder': folder_name, 'ok': True}


def download_pending_videos(config=None):
    """Roda download_pending_for_channel em todos os canais ativos.

    Chamado pelo scheduler no horario tiktok_horarios.
    """
    channels = db.get_tiktok_channels()
    active = [c for c in channels if c.get('ativo', 0) == 1]
    if not active:
        log('  Nenhum canal TikTok ativo')
        return []

    log(f'  Download da fila: {len(active)} canal(is) ativo(s)')
    results = []
    for channel in active:
        try:
            r = download_pending_for_channel(channel)
            results.append(r)
        except Exception as e:
            log(f'  Erro no canal {channel.get("handle")}: {e}')
            results.append({'handle': channel.get('handle'), 'downloaded': 0,
                           'errors': 1, 'ok': False, 'motivo': str(e)})

    total = sum(r.get('downloaded', 0) for r in results)
    log(f'  TikTok download concluido: {total} video(s) baixado(s)')

    if total > 0:
        try:
            import import_worker
            import_results = import_worker.process_imports(config)
            processed = [r for r in import_results if r.get('ok')]
            if processed:
                log(f'  Import worker: {len(processed)} lote(s) processado(s)')
        except Exception as e:
            log(f'  Import worker erro: {e}')

    return results


# ---------------------------------------------------------------------------
# Compat: process_all_channels (scan + download)
# ---------------------------------------------------------------------------

def process_all_channels(config=None, playlist_end=5000):
    """Fluxo completo (scan + download). Uso: scan manual + download imediato."""
    channels = db.get_tiktok_channels()
    active = [c for c in channels if c.get('ativo', 0) == 1]
    if not active:
        log('  Nenhum canal TikTok ativo')
        return []

    log(f'  Scan+download: {len(active)} canal(is) ativo(s)')
    for channel in active:
        try:
            scan_channel_to_queue(channel, playlist_end=playlist_end)
        except Exception as e:
            log(f'  Erro scan canal {channel.get("handle")}: {e}')

    return download_pending_videos(config)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'scan'
    if action == 'scan':
        # Scan completo + download imediato
        results = process_all_channels()
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif action == 'scan-only':
        # So popula fila, sem baixar
        channels = [c for c in db.get_tiktok_channels() if c.get('ativo', 0) == 1]
        out = [scan_channel_to_queue(c) for c in channels]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif action == 'download':
        # So consome fila
        results = download_pending_videos()
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif action == 'queue':
        channels = db.get_tiktok_channels()
        for c in channels:
            stats = db.get_tiktok_channel_stats(c['handle'])
            print(f'  [{c["id"]}] {c["handle"]}: pendentes={stats["pendente"]} '
                  f'baixados={stats["baixado"]} pulados={stats["pulado"]} erros={stats["erro"]}')
    elif action == 'list':
        channels = db.get_tiktok_channels()
        for c in channels:
            print(f'  [{c["id"]}] {c["handle"]} ({"ativo" if c["ativo"] else "inativo"}) '
                  f'desde={c["data_desde"]} max={c["max_por_scan"]} baixados={c["total_baixados"]}')
    elif action == 'add':
        handle = sys.argv[2] if len(sys.argv) > 2 else ''
        if not handle:
            print('Uso: tiktok_scanner.py add @handle')
            sys.exit(1)
        row_id = db.add_tiktok_channel(handle)
        print(f'Canal adicionado: {handle} (id={row_id})')
    else:
        print(f'Uso: {sys.argv[0]} scan | scan-only | download | queue | list | add @handle')

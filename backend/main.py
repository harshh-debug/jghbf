"""Read-only API over the checksummed Elexon snapshot."""
from datetime import date, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from scripts.analyze_data import ROOT, comparison, cutoff_for, deduplicate, metrics

app = FastAPI(title="Wind decision pilot")

@lru_cache(maxsize=1)
def snapshot():
    manifest = json.loads((ROOT / 'data/manifest.json').read_text())
    rows = {'WINDFOR': [], 'FUELHH': []}
    hashes = []
    for request in manifest['requests']:
        payload = (ROOT / request['path']).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != request['sha256']:
            raise ValueError(f"Checksum mismatch: {request['path']}")
        data = json.loads(payload)
        if len(data) != request['rows'] or not data:
            raise ValueError(f"Unexpected row count: {request['path']}")
        rows[data[0]['dataset']].extend(data)
        hashes.append(digest)
    return (deduplicate(rows['WINDFOR'], 'WINDFOR')[0],
            deduplicate(rows['FUELHH'], 'FUELHH')[0],
            hashlib.sha256(''.join(hashes).encode()).hexdigest()[:12], manifest)

@app.get('/api/health')
def health():
    snapshot()
    return {'status': 'ok'}

@app.get('/api/meta')
def meta():
    _, _, version, manifest = snapshot()
    return {'data_version': version, 'timezone': 'Europe/London', 'default_cutoff': '09:00',
            'sources': ['WINDFOR', 'FUELHH WIND'], 'requests': manifest['requests']}

@app.get('/api/analysis')
def analysis(decision_from: date = date(2026, 1, 1), decision_to: date = date(2026, 1, 31), cutoff: str = '09:00'):
    if not date(2026, 1, 1) <= decision_from <= decision_to <= date(2026, 1, 31):
        raise HTTPException(422, 'Decision dates must be an ordered range within January 2026.')
    if not re.fullmatch(r'\d{2}:\d{2}', cutoff):
        raise HTTPException(422, 'Cutoff must be HH:MM in Europe/London.')
    try:
        cutoff_for(decision_from, cutoff)
    except ValueError:
        raise HTTPException(422, 'Cutoff must be HH:MM in Europe/London.')
    wind, actual, version, manifest = snapshot()
    points = [p for p in comparison(wind, actual, cutoff) if str(decision_from) <= p['decision_date'] <= str(decision_to)]
    daily = []
    for offset in range((decision_to - decision_from).days + 1):
        day = decision_from + timedelta(days=offset)
        day_points = [p for p in points if p['decision_date'] == str(day)]
        daily.append({'decision_date': str(day), 'delivery_date': str(day + timedelta(days=1)),
                      'expected_hours': len(day_points), **metrics(day_points)})
    return {'decision_from': str(decision_from), 'decision_to': str(decision_to), 'cutoff_local': cutoff,
            'timezone': 'Europe/London', 'delivery_from': str(decision_from + timedelta(days=1)),
            'delivery_to': str(decision_to + timedelta(days=1)), 'data_version': version,
            'snapshot_last_retrieved_at_utc': max(r['retrieved_at_utc'] for r in manifest['requests']),
            'evaluation_mode': 'retrospective', 'summary': {'expected_hours': len(points), **metrics(points)},
            'daily': daily, 'series': points}

# One origin in Docker/Heroku; Vite proxies /api during development.
dist = ROOT / 'frontend/dist'
if (dist / 'assets').is_dir():
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
if (dist / 'index.html').is_file():
    @app.get('/')
    def index():
        return FileResponse(dist / 'index.html')

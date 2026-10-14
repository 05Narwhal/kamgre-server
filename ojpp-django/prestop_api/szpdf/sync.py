"""SŽ notices → their timetable PDFs → `<sha256>.pdf`, `<sha256>.json` and `index.json` in one directory, which
the API reads (prestop_api/sztimetables.py). Run by `manage.py szpdf_sync` from the prestop-szpdf timer.

Cheap by design: a URL is downloaded when it is new, and checked again once a day with a conditional request (ETag /
Last-Modified); a PDF is parsed when its checksum is new or the parser version changed. Files are written only when
their content changes, through a temporary file and a rename, so readers never see half a file. Files of notices
that have been gone for 7 days are deleted.
"""
import hashlib
import html
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import requests

from prestop_api import szpdf
from prestop_api.upstream import USER_AGENT

logger = logging.getLogger(__name__)

TIMEOUT = 30
MAX_BYTES = 15 * 1024 * 1024
RECHECK = timedelta(days=1)
KEEP = timedelta(days=7)
HREF = re.compile(r'''href\s*=\s*["']([^"']+?\.pdf)["']''', re.I)
RANK = {'ok': 0, 'unsure': 1, 'failed': 2}


class SyncError(Exception):
    pass


@dataclass
class Fetched:
    body: bytes | None  # None: unchanged since the last download
    etag: str | None = None
    last_modified: str | None = None


def notice_pdfs(notices: list) -> dict[str, dict]:
    """ID_ovire → {'title', 'urls'}: every link ending in .pdf, in order, for each notice that has one. A record of
    the feed can group several notices: ID_ovire[i] goes with Naslov[i], Opis[i] (as in closures.py)."""
    out = {}
    for n in notices:
        ids = n.get('ID_ovire') or []
        for i, pid in enumerate(ids):
            urls: list[str] = []
            for value in n.values():
                text = value[i] if isinstance(value, list) and len(value) == len(ids) else ''
                for href in HREF.findall(text if isinstance(text, str) else ''):
                    href = html.unescape(href).strip()
                    if href not in urls:
                        urls.append(href)
            if pid.strip() and urls:
                titles = n.get('Naslov') or []
                out[pid.strip()] = {'title': (titles[i] if i < len(titles) else '').strip(), 'urls': urls}
    return out


def download(url: str, known: dict | None) -> Fetched:
    """GET with our user agent, a 30 s timeout and a 15 MB cap; conditional when the URL was seen before."""
    headers = {'User-Agent': USER_AGENT}
    if known and known.get('etag'):
        headers['If-None-Match'] = known['etag']
    if known and known.get('lastModified'):
        headers['If-Modified-Since'] = known['lastModified']
    try:
        with requests.get(url, headers=headers, timeout=TIMEOUT, stream=True) as resp:
            if resp.status_code == 304 and known:
                return Fetched(None, known.get('etag'), known.get('lastModified'))
            if resp.status_code != 200:
                raise SyncError(f'HTTP {resp.status_code}')
            body = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise SyncError(f'larger than {MAX_BYTES // (1024 * 1024)} MB')
            if not bytes(body[:1024]).lstrip().startswith(b'%PDF'):
                raise SyncError('not a PDF')
            return Fetched(bytes(body), resp.headers.get('ETag'), resp.headers.get('Last-Modified'))
    except requests.RequestException as e:
        raise SyncError(e.__class__.__name__) from e


def fixture_fetcher(notices: list, directory: Path) -> Callable[[str, dict | None], Fetched]:
    """Reads `<ID_ovire>.pdf` for each notice's first link instead of downloading (the test snapshot)."""
    files: dict[str, Path] = {}
    for pid, notice in notice_pdfs(notices).items():
        path = Path(directory) / f'{pid}.pdf'
        if path.exists() and notice['urls'][0] not in files:
            files[notice['urls'][0]] = path

    def fetch(url: str, known: dict | None) -> Fetched:
        if url not in files:
            raise SyncError('not in the snapshot')
        return Fetched(files[url].read_bytes())
    return fetch


def write(path: Path, data: bytes):
    """Atomic: a reader sees the old file or the new one."""
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, doc: dict) -> bool:
    data = (json.dumps(doc, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    if path.exists() and path.read_bytes() == data:
        return False
    write(path, data)
    return True


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def run(directory, notices: list, fetch=download, now: datetime | None = None) -> list[dict]:
    """One sync. Returns one report row per notice that links a PDF."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now().astimezone()
    stamp = now.isoformat()
    state = read_json(directory / 'state.json') or {}
    urls, seen = state.setdefault('urls', {}), state.setdefault('seen', {})

    linked = notice_pdfs(notices)
    resolved: dict[str, str] = {}  # url → sha256
    errors: dict[str, str] = {}
    for url in dict.fromkeys(u for n in linked.values() for u in n['urls']):
        known = urls.get(url)
        if known and now - datetime.fromisoformat(known['checked']) < RECHECK and (directory / f'{known["sha256"]}.pdf').exists():
            resolved[url] = known['sha256']
            continue
        try:
            got = fetch(url, known)
        except SyncError as e:
            errors[url] = str(e)
            if known and (directory / f'{known["sha256"]}.pdf').exists():
                resolved[url] = known['sha256']  # keep using the copy we have
            if str(e) != 'not in the snapshot':
                logger.warning('SŽ timetable %s: %s', url, e)
            continue
        if got.body is None:
            digest = known['sha256']
        else:
            digest = hashlib.sha256(got.body).hexdigest()
            if not (directory / f'{digest}.pdf').exists():
                write(directory / f'{digest}.pdf', got.body)
        fetched = known['fetched'] if known and known['sha256'] == digest else stamp
        urls[url] = {'sha256': digest, 'etag': got.etag, 'lastModified': got.last_modified, 'checked': stamp,
                     'fetched': fetched}
        resolved[url] = digest

    # Each PDF's notices, and the title of the notice it is the (first) timetable of.
    by_sha: dict[str, dict] = {}
    for pid in sorted(linked, key=int):
        for i, url in enumerate(linked[pid]['urls']):
            if url in resolved:
                entry = by_sha.setdefault(resolved[url], {'notices': [], 'url': url, 'title': None})
                entry['notices'].append(pid)
                if i == 0 and entry['title'] is None:
                    entry['title'] = linked[pid]['title']
    for digest, entry in by_sha.items():
        entry['title'] = entry['title'] or linked[entry['notices'][0]]['title']

    docs = {}
    for digest, entry in by_sha.items():
        doc = _parsed(directory, digest)
        fetched = next((u['fetched'] for u in urls.values() if u['sha256'] == digest), stamp)
        doc = {'schema': doc['schema'], 'parser': doc['parser'], 'notices': entry['notices'], 'title': entry['title'],
               'url': entry['url'], 'sha256': digest, 'fetched': fetched,
               **{k: v for k, v in doc.items() if k not in ('schema', 'parser', 'notices', 'title', 'url', 'sha256', 'fetched')}}
        write_json(directory / f'{digest}.json', doc)
        docs[digest] = doc
        seen[digest] = stamp

    _prune(directory, state, set(by_sha), now)

    index = {'schema': szpdf.SCHEMA, 'updated': stamp,
             'notices': {pid: resolved[next(u for u in n['urls'] if u in resolved)]
                         for pid, n in linked.items() if any(u in resolved for u in n['urls'])},
             'files': sorted(by_sha)}
    old = read_json(directory / 'index.json')
    if not old or {k: v for k, v in old.items() if k != 'updated'} != {k: v for k, v in index.items() if k != 'updated'}:
        write_json(directory / 'index.json', index)
    write_json(directory / 'state.json', state)

    rows = []
    for pid, n in linked.items():
        files = [docs[resolved[u]] for u in dict.fromkeys(n['urls']) if u in resolved]
        rows.append({
            'id': pid, 'title': n['title'], 'files': len(files), 'missing': len(set(n['urls'])) - len(files),
            'status': max((f['status'] for f in files), key=RANK.get) if files else 'missing',
            'columns': sum(len(t['columns']) for f in files for t in f['tables']),
            'problems': sum(len(f['problems']) for f in files),
            'errors': [f'{u}: {errors[u]}' for u in n['urls'] if u in errors and u not in resolved],
        })
    return rows


def _parsed(directory: Path, digest: str) -> dict:
    """The cached parse of a PDF, parsed again when the parser (or schema) changed, or when an image was left
    unread for want of tesseract and tesseract is there now."""
    doc = read_json(directory / f'{digest}.json')
    stale = (doc is None or doc.get('parser') != szpdf.PARSER or doc.get('schema') != szpdf.SCHEMA
             or (any('tesseract is not installed' in p for p in doc.get('problems', [])) and shutil.which('tesseract')))
    if not stale:
        return doc
    try:
        doc = szpdf.parse(directory / f'{digest}.pdf')
    except Exception as e:  # noqa: BLE001 - one odd PDF must not stop the others
        logger.exception('SŽ timetable %s could not be parsed', digest)
        doc = {'schema': szpdf.SCHEMA, 'parser': szpdf.PARSER, 'status': 'failed', 'problems': [f'parser error: {e!r}'],
               'valid': None, 'footnotes': {}, 'stationNotes': [], 'stops': [], 'notes': [], 'tables': []}
    logger.info('SŽ timetable %s parsed: %s, %d problems', digest[:12], doc['status'], len(doc['problems']))
    return doc


def _prune(directory: Path, state: dict, current: set[str], now: datetime):
    for digest, last in list(state['seen'].items()):
        if digest in current or now - datetime.fromisoformat(last) <= KEEP:
            continue
        for suffix in ('.pdf', '.json'):
            (directory / f'{digest}{suffix}').unlink(missing_ok=True)
        del state['seen'][digest]
        for url in [u for u, e in state['urls'].items() if e['sha256'] == digest]:
            del state['urls'][url]
        logger.info('SŽ timetable %s pruned (notice gone since %s)', digest[:12], last)

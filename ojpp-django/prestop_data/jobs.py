import hashlib
import logging
import os
from pathlib import Path
from typing import Iterable, Optional

import requests
from django.conf import settings
from django.utils import timezone

from prestop_data.gtfs_import import FEEDS, GtfsArchive, GtfsImporter
from prestop_data.models import GtfsImport

logger = logging.getLogger(__name__)

MAX_FEED_BYTES = 512 * 1024 * 1024
TIMEOUT = (10, 120)


def gtfs_dir() -> Path:
    path = Path(settings.PRESTOP_GTFS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def feed_url(feed: str) -> str:
    return settings.PRESTOP_GTFS_MIRROR.rstrip('/') + '/' + FEEDS[feed].filename


def download_feed(feed: str, log=logger.info) -> tuple[Path, str]:
    """Download a feed from the mirror into the GTFS dir; returns (path, Last-Modified)."""
    url = feed_url(feed)
    target = gtfs_dir() / FEEDS[feed].filename
    partial = target.with_suffix('.part')
    log(f'[{feed}] downloading {url}')
    with requests.get(url, stream=True, timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        size = 0
        with open(partial, 'wb') as f:
            for chunk in resp.iter_content(1024 * 1024):
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise ValueError(f'{url} exceeds {MAX_FEED_BYTES} bytes')
                f.write(chunk)
        last_modified = resp.headers.get('Last-Modified', '')
    os.replace(partial, target)
    return target, last_modified


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def import_feed(feed: str, download: bool = True, force: bool = False, shapes: bool = True,
                log=logger.info) -> Optional[GtfsImport]:
    last_modified = ''
    if download:
        path, last_modified = download_feed(feed, log)
    else:
        path = gtfs_dir() / FEEDS[feed].filename
    digest = sha256_of(path)
    previous = GtfsImport.objects.filter(feed=feed, succeeded=True).first()
    if previous and previous.sha256 == digest and not force:
        log(f'[{feed}] unchanged since {previous.started:%Y-%m-%d %H:%M}, skipping')
        return None

    record = GtfsImport.objects.create(
        feed=feed, source_url=feed_url(feed), sha256=digest, last_modified=last_modified, started=timezone.now(),
    )
    archive = GtfsArchive(path)
    try:
        record.counts = GtfsImporter(FEEDS[feed], archive, log=log).run(with_shapes=shapes)
        record.succeeded = True
    except Exception as e:
        record.error = repr(e)
        raise
    finally:
        archive.close()
        record.finished = timezone.now()
        record.save()
    log(f'[{feed}] done: {record.counts}')
    return record


def refresh_gtfs(feeds: Iterable[str] = ('ijpp', 'lpp')):
    for feed in feeds:
        try:
            import_feed(feed)
        except Exception:
            logger.exception(f'GTFS refresh failed for {feed}')

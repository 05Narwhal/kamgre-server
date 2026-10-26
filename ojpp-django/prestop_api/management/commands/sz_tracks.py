"""Each SŽ train's usual track at each station, from the track scraper's history, into data/sz_tracks.json, or
PRESTOP_SZ_USUAL_TRACKS_FILE when set (see tracks.usual_file; the server's night window rebuilds it on Sundays).

    manage.py sz_tracks              # the last 60 days
    manage.py sz_tracks --days 120

Days the scraper has nothing for (its source was down) are skipped. The app's copy is checked in: re-run it
after a timetable change (December, or when SŽ moves trains), then commit it.
"""
import json
import os
from datetime import date, timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from prestop_api import tracks
from prestop_api.upstream import USER_AGENT, url_list


class Command(BaseCommand):
    help = "Build data/sz_tracks.json (each train's usual track per station) from the SŽ track scraper's history."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60)
        parser.add_argument('--url', default='', help='the scraper\'s train_data endpoint (default PRESTOP_SZ_TRACKS_URL)')

    def handle(self, *args, days=60, url='', **options):
        urls = [url] if url else url_list(getattr(settings, 'PRESTOP_SZ_TRACKS_URL', ''))
        if not urls:
            raise CommandError('No track scraper URL (PRESTOP_SZ_TRACKS_URL).')
        rows, used = [], []
        for back in range(days, 0, -1):
            day = (date.today() - timedelta(days=back)).isoformat()
            found = None
            for url in list(urls):  # the scraper's host names in turn; the one that answered stays first
                try:
                    resp = requests.get(url, params={'date': day}, timeout=60, headers={'User-Agent': USER_AGENT})
                    resp.raise_for_status()
                    found = [r for r in resp.json().get('trains') or [] if r.get('platform')]
                    urls.remove(url)
                    urls.insert(0, url)
                    break
                except (requests.RequestException, ValueError, AttributeError) as e:
                    self.stderr.write(f'{day} {url}: {e}')
            if found is None:
                continue
            if found:
                rows += [{**r, 'date': day} for r in found]
                used.append(day)
        if not used:
            raise CommandError('The scraper had no tracks for any of those days; the file is left as it was.')
        usual = tracks.usual_tracks(rows)
        pairs = sum(len(v) for v in usual.values())
        target = tracks.usual_file()
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(json.dumps({'from': used[0], 'to': used[-1], 'days': len(used), 'trains': usual},
                                  ensure_ascii=False, indent=0, sort_keys=True), encoding='utf-8')
        os.replace(tmp, target)
        self.stdout.write(f'{len(used)} days ({used[0]} – {used[-1]}): {len(usual)} trains, {pairs} train/station tracks.')

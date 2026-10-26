"""SŽ's live sources (sz.py): derp-si's sz-platform-scraper under two host names, then modra.ninja, tried in order with
the one that answered last first, so no single upstream takes live trains away (2026-10-26: modra.ninja died)."""
import json
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import sz, tracks
from prestop_api.upstream import Mirrors, UpstreamError, url_list

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'sz'
T0 = 1_793_042_000
SCRAPER = ['http://a.example/active_trains', 'http://b.example/active_trains', 'https://modra.example/lokacije']


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def answers(by_url: dict):
    """A get_json stand-in: each URL's answer, or the exception it raises."""
    def get(url, **kwargs):
        value = by_url[url]
        if isinstance(value, Exception):
            raise value
        return value
    return get


class ScraperRowsTests(SimpleTestCase):
    def test_todays_active_trains_are_read(self):
        """2026-10-26 20:18: 46 trains, SŽ's own field names, coordinates as the string "lon,lat"."""
        trains = sz.parse_trains(fixture('active_trains-2026-10-26.json'), T0)
        self.assertEqual(len(trains), 46)
        t = trains['1897']
        self.assertEqual((t['category'], t['next'], t['delay'], t['relation']), ('LPV', 'Divača', 0, 'Sežana-Ljubljana'))
        self.assertEqual(t['coords'], (45.7048735502, 13.8996975041))
        late = [t for t in trains.values() if t['delay']]
        self.assertTrue(late and all(t['delay'] % 60 == 0 for t in late))  # whole minutes, as SŽ reports them

    def test_the_old_feeds_names_still_work(self):
        t = sz.normalize({'st_vlaka': '2904', 'rang_vlaka': 'LPV', 'naslednja_postaja': 'Kranj', 'zamuda_min': 4}, T0)
        self.assertEqual((t['number'], t['category'], t['next'], t['delay']), ('2904', 'LPV', 'Kranj', 240))

    def test_no_trains_is_an_answer_but_another_shape_is_not(self):
        self.assertEqual(sz.parse_trains([], T0), {})  # 3 am
        self.assertEqual(sz.parse_trains({'vlaki': []}, T0), {})
        for wrong in ({'detail': 'Not Found'}, 'OK', None):
            with self.assertRaises((ValueError, TypeError)):
                sz.parse_trains(wrong, T0)


class MirrorsTests(SimpleTestCase):
    def test_url_lists_from_a_setting(self):
        self.assertEqual(url_list('http://a, http://b ,'), ['http://a', 'http://b'])
        self.assertEqual(url_list(['http://a', '']), ['http://a'])
        self.assertEqual(url_list(''), [])

    def test_the_next_url_answers_when_the_first_fails_and_stays_first(self):
        mirrors = Mirrors('PRESTOP_SZ_LIVE_URL')
        calls = []
        get = answers({SCRAPER[0]: UpstreamError('timeout'), SCRAPER[1]: [{'St_vlaka': '1'}], SCRAPER[2]: []})
        with self.settings(PRESTOP_SZ_LIVE_URL=SCRAPER), \
                mock.patch('prestop_api.upstream.get_json', side_effect=lambda url, **kw: calls.append(url) or get(url)):
            self.assertEqual(mirrors.get_json(), [{'St_vlaka': '1'}])
            self.assertEqual(mirrors.good, SCRAPER[1])
            calls.clear()
            mirrors.get_json()
        self.assertEqual(calls, [SCRAPER[1]])  # the one that answered is asked first

    def test_a_mirror_answering_something_else_counts_as_failing(self):
        mirrors = Mirrors('PRESTOP_SZ_LIVE_URL')
        with self.settings(PRESTOP_SZ_LIVE_URL=SCRAPER), \
                mock.patch('prestop_api.upstream.get_json', side_effect=answers({SCRAPER[0]: {'detail': 'x'}, SCRAPER[1]: [], SCRAPER[2]: []})):
            self.assertEqual(mirrors.get_json(check=sz.train_rows), [])
        self.assertEqual(mirrors.good, SCRAPER[1])

    def test_every_url_failing_is_an_upstream_error(self):
        with self.settings(PRESTOP_SZ_LIVE_URL=SCRAPER[:2]), \
                mock.patch('prestop_api.upstream.get_json', side_effect=UpstreamError('down')):
            with self.assertRaises(UpstreamError):
                Mirrors('PRESTOP_SZ_LIVE_URL').get_json()


class LiveFeedTests(SimpleTestCase):
    def test_a_poll_reads_the_scraper_and_reports_live(self):
        feed = sz.LiveTrains()
        rows = fixture('active_trains-2026-10-26.json')
        with self.settings(PRESTOP_SZ_LIVE_URL=SCRAPER), \
                mock.patch('prestop_api.upstream.get_json', side_effect=answers({SCRAPER[0]: rows, SCRAPER[1]: [], SCRAPER[2]: []})):
            feed._poll()
        self.assertEqual((feed.status(), feed.used, len(feed._items)), ('live', SCRAPER[0], 46))

    def test_an_empty_list_from_a_working_url_is_live_with_no_trains(self):
        feed = sz.LiveTrains()
        with self.settings(PRESTOP_SZ_LIVE_URL=SCRAPER[:1]), mock.patch('prestop_api.upstream.get_json', return_value=[]):
            feed._poll()
        self.assertEqual((feed.status(), feed._items), ('live', {}))

    def test_tracks_try_the_second_host_name(self):
        t = tracks.Tracks()
        urls = ['http://a.example/train_data', 'http://b.example/train_data']
        day = '2026-10-26'
        got = {f'{urls[0]}?date={day}': UpstreamError('dns'),
               f'{urls[1]}?date={day}': {'trains': [{'train_id': '1897', 'ijpp_id': 'IJPP:1', 'platform': '2'}]}}
        with self.settings(PRESTOP_SZ_TRACKS_URL=urls), mock.patch('prestop_api.upstream.get_json', side_effect=answers(got)):
            t._poll(day)
        self.assertEqual((t._today, t.mirrors.good), ({'1897': {'IJPP:1': '2'}}, urls[1]))


class OutageTests(SimpleTestCase):
    """F5: an SŽ source down for more than 30 min shows in /health `outages` (server:top and the watchdog print it)."""

    def source(self, id_, status, since):
        return {'id': id_, 'name': id_, 'status': status, 'updatedAt': since, 'capabilities': [], 'since': since}

    def test_only_sz_sources_down_for_over_half_an_hour(self):
        from prestop_api import mapping, views
        now = T0
        srcs = [self.source('sz:live', 'live', mapping.iso(now - 10)),
                self.source('sz:notices', 'unavailable', mapping.iso(now - 45 * 60)),
                self.source('sz:delays', 'stale', mapping.iso(now - 20 * 60)),  # not yet half an hour
                self.source('operator-site:arriva', 'unavailable', None)]
        with mock.patch.object(views, 'STARTED', now - 3600):
            got = views.outages(srcs, now)
            self.assertEqual([(o['id'], o['minutes']) for o in got], [('sz:notices', 45)])
            # never answered since this server started an hour ago
            self.assertEqual(views.outages([self.source('sz:news', 'unavailable', None)], now)[0]['minutes'], 60)
        with mock.patch.object(views, 'STARTED', now - 60):  # just restarted: not an outage yet
            self.assertEqual(views.outages([self.source('sz:news', 'unavailable', None)], now), [])

    def test_a_feed_says_when_it_last_answered(self):
        from prestop_api import views
        feed = sz.LiveTrains()
        self.assertEqual((views.sz_feed_source('sz:live', 'x', feed, [])['since'], feed.status()), (None, 'unavailable'))
        feed.last_ok = T0
        self.assertEqual(views.sz_feed_source('sz:live', 'x', feed, [])['since'], '2026-10-26T19:13:20Z')


class DelayTableTests(SimpleTestCase):
    """F2: SŽ's delay tables (`/delays`): measured or expected, at an arrival or a departure."""

    def test_todays_table_is_read(self):
        rows = sz.parse_delays(fixture('delays-2026-10-26.json'), T0)
        self.assertEqual(len(rows), 27)
        r = rows['3222']
        self.assertEqual((r['station'], r['delay'], r['kind'], r['event'], r['category']), ('Grosuplje', 2400, 'actual', 'departure', 'LP'))
        p = rows['480']  # from Croatia, not in Slovenia yet: SŽ's forecast
        self.assertEqual((p['station'], p['delay'], p['kind'], p['event']), ('Ilirska Bistrica', 900, 'predicted', None))

    def test_a_measured_row_beats_a_forecast_of_the_same_train(self):
        table = {'delays': [{'train_id': '480', 'station': 'Pivka', 'delay_minutes': 12, 'delay_type': 'actual', 'event': 'arrival'},
                            {'train_id': '480', 'station': 'Ilirska Bistrica', 'delay_minutes': 15, 'delay_type': 'predicted'}]}
        self.assertEqual(sz.parse_delays(table, T0)['480']['kind'], 'actual')
        with self.assertRaises(ValueError):
            sz.parse_delays({'detail': 'x'}, T0)

    def test_the_running_trains_list_beats_the_table_when_both_measure(self):
        trains = {'502': {'number': '502', 'next': 'Pragersko', 'delay': 600, 'coords': None, 'at': T0}}
        table = {'502': {'number': '502', 'station': 'Kidričevo', 'event': 'departure', 'delay': 660, 'kind': 'actual', 'at': T0 + 5},
                 '480': {'number': '480', 'station': 'Ilirska Bistrica', 'event': None, 'delay': 900, 'kind': 'predicted', 'at': T0}}
        got = sz.merged(trains, table)
        self.assertEqual((got['502']['feed'], got['502']['station'], got['502']['delay'], got['502']['kind']), ('live', 'Pragersko', 600, 'actual'))
        self.assertEqual((got['480']['feed'], got['480']['kind']), ('delays', 'predicted'))  # only the table has it
        # listed without a delay: the table's row, where the list says the train is
        got = sz.merged({'502': {**trains['502'], 'delay': None, 'coords': (46.4, 15.7)}}, table)
        self.assertEqual((got['502']['feed'], got['502']['delay'], got['502']['coords']), ('delays', 660, (46.4, 15.7)))


class UsualTrackFileTests(SimpleTestCase):
    """F10: the night window rebuilds each train's usual track outside the deployed code (PRESTOP_SZ_USUAL_TRACKS_FILE);
    until it has, the copy checked in with the app is read."""

    def test_the_configured_file_once_it_exists_else_the_apps_copy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'sz_tracks.json'
            t = tracks.Tracks()
            with self.settings(PRESTOP_SZ_USUAL_TRACKS_FILE=str(target)):
                self.assertEqual(tracks.usual_file(), target)
                self.assertEqual(t.usual(), json.loads(tracks.USUAL.read_text(encoding='utf-8'))['trains'])
                target.write_text(json.dumps({'trains': {'1897': {'IJPP:1': '2'}}}), encoding='utf-8')
                t._usual['checked'] = float('-inf')
                self.assertEqual(t.usual(), {'1897': {'IJPP:1': '2'}})
        self.assertEqual(tracks.usual_file(), tracks.USUAL)

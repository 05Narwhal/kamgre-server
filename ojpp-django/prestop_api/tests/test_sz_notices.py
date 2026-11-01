"""F4: SŽ's closure notices survive an outage of every notices URL and a restart (the last good ones are kept on disk),
and SŽ's own RSS keeps the app from going silent meanwhile (text alerts, no replacement buses)."""
import json
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import closures, operator_notices, sources, sztimetables
from prestop_api.szpdf import sync
from prestop_api.upstream import Snapshot, UpstreamError

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
NOTICES = json.loads((FIXTURES / 'szpdf' / 'notices-2026-10-14.json').read_text(encoding='utf-8'))
RSS = (FIXTURES / 'sz' / 'feed-2026-10-26.xml').read_bytes()
EVENING = datetime(2026, 10, 26, 20, 0, tzinfo=closures.LOCAL).timestamp()


def ids(raw):
    return [str(n) for item in raw for n in item.get('ID_ovire') or []]


class SavedNoticesTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = str(Path(self.dir.name) / 'sz-notices.json')

    def test_a_notice_is_dropped_once_its_last_day_has_passed(self):
        # one record groups three notices: until 25 Oct, until 18 Oct, until 1 Nov
        record = next(r for r in NOTICES if len(r.get('ID_ovire') or []) == 3)
        [kept] = closures.current_notices([record], date(2026, 10, 27))
        self.assertEqual((kept['ID_ovire'], kept['Cas']), ([record['ID_ovire'][2]], ['24.10.2026-01.11.2026']))
        self.assertEqual(kept['Lokacija'], record['Lokacija'])  # fields that aren't per notice stay as they were
        self.assertEqual(closures.current_notices([record], date(2026, 11, 2)), [])

    def test_saved_atomically_and_read_back(self):
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file):
            closures.save_notices(NOTICES, now=EVENING)
            saved, at = closures.saved_notices(date(2026, 10, 14))
        self.assertEqual((len(saved), at), (len(NOTICES), EVENING))
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], ['sz-notices.json'])  # no .tmp left behind
        with self.settings(PRESTOP_SZ_NOTICES_FILE=str(Path(self.dir.name) / 'none.json')):
            self.assertEqual(closures.saved_notices(), ([], None))

    def test_a_restart_while_every_notices_url_fails_keeps_yesterdays_closures(self):
        running = closures.current_notices(NOTICES, date(2026, 10, 27))
        number = next(n for n in ids(running) if n in ids(NOTICES))
        tables = sztimetables.Timetables({number: 'sha'}, {'sha': {'status': 'ok', 'notices': [number]}})
        real = closures.saved_notices
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file, PRESTOP_SZ_NOTICES_URL=['http://dead.example/ovire', 'http://gone.example/ovire']):
            closures.save_notices(NOTICES, now=EVENING)  # yesterday, while a notices URL still worked
            # the server restarts the next day: nothing in memory, every URL fails
            with mock.patch.dict(closures._notices, raw=None, since=None, saved=None), \
                    mock.patch.object(closures.points, '_snap', None), mock.patch.object(closures.points, '_retry_at', 0), \
                    mock.patch.object(closures.points, '_last_error', ''), \
                    mock.patch.object(sources.alerts_raw, '_snap', Snapshot([], time.time())), \
                    mock.patch.object(closures, 'saved_notices', lambda today=None: real(date(2026, 10, 27))), \
                    mock.patch('prestop_api.upstream.get_json', side_effect=UpstreamError('HTTP 500')), \
                    self.assertLogs('prestop_api.closures', 'WARNING'):
                with self.assertRaises(UpstreamError):
                    closures.points.get()
                self.assertEqual(ids(closures._notices['raw']), ids(running))
                snap = closures.points.peek()
                self.assertTrue(snap and snap.error and snap.age >= closures.points.ttl)  # retried, not trusted for 6 h
                health = closures.notices_source()
                self.assertEqual((health['status'], health['since']), ('stale', '2026-10-26T19:00:00Z'))
                # the notice's alert, which runs its replacement timetable's buses, is back
                alerts = closures.sz_notice_alerts(closures._notices['raw'], [], tables)
                self.assertEqual([a['id'] for a in alerts], [closures.notice_alert_id(number)])

    def test_a_working_url_is_saved_and_wins_over_the_file(self):
        with self.settings(PRESTOP_SZ_NOTICES_FILE=self.file, PRESTOP_SZ_NOTICES_URL=['http://ok.example/ovire']), \
                mock.patch.dict(closures._notices, raw=None, since=None, saved=None), \
                mock.patch('prestop_api.upstream.get_json', return_value=NOTICES[:2]):
            closures._load_points()
            self.assertEqual((ids(closures._notices['raw']), closures._notices['saved']), (ids(NOTICES[:2]), None))
        self.assertEqual(ids(json.loads(Path(self.file).read_text(encoding='utf-8'))['notices']), ids(NOTICES[:2]))


class Response:
    def __init__(self, status, body=b'', headers=None):
        self.status_code, self.headers = status, headers or {}
        self.raw = mock.Mock(read=lambda n, decode_content=True: body[:n])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SzRssTests(SimpleTestCase):
    def test_passenger_notices_become_text_alerts_for_the_days_they_name(self):
        items = operator_notices.rss_items(RSS)
        self.assertEqual(len(items), 10)
        alerts = operator_notices.sz_news_alerts(items, EVENING)
        titles = [a['title'] for a in alerts]
        self.assertTrue(any(t.startswith('Spremenjena dostopna pot do peronov') for t in titles))  # from 22 Oct, two weeks
        self.assertFalse(any('Zalaegerszeg' in t for t in titles))  # 16-22 Oct: over
        self.assertFalse(any('solidarnosti' in t for t in titles))  # news, not a passenger notice
        a = alerts[0]
        self.assertEqual((a['operatorId'], a['source'], a['routeIds']), ('IJPP:1161', 'operator-site', []))
        self.assertTrue(a['sourceUrl'].startswith('https://potniski.sz.si/') and a['id'].startswith('sz-news:'))

    def test_a_feed_with_entities_is_refused(self):
        with self.assertRaises(ValueError):
            operator_notices.rss_items(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel></channel></rss>')

    def test_unchanged_since_the_last_read_keeps_the_items(self):
        got = []

        def get(url, headers, **kwargs):
            got.append(headers)
            return Response(200, RSS, {'ETag': 'W/"1"', 'Last-Modified': 'Mon, 26 Oct 2026 13:34:59 GMT'}) if len(got) == 1 else Response(304)
        cache = operator_notices.sz_news
        with self.settings(PRESTOP_SZ_NEWS_URL=['https://sz.example/feed/']), mock.patch.object(cache, '_snap', None), \
                mock.patch.object(operator_notices, 'SZ_PAGES', 1), mock.patch.dict(operator_notices._rss, url=None, etag=None, modified=None), \
                mock.patch('prestop_api.operator_notices.session', return_value=mock.Mock(get=get)):
            first = operator_notices._load_sz_news()
            cache._snap = Snapshot(first, time.time())
            self.assertIs(operator_notices._load_sz_news(), first)
        self.assertNotIn('If-None-Match', got[0])
        self.assertEqual((got[1]['If-None-Match'], got[1]['If-Modified-Since']), ('W/"1"', 'Mon, 26 Oct 2026 13:34:59 GMT'))

    def test_every_post_in_effect_shows_whatever_else_we_have_but_not_the_same_notice_twice(self):
        items = operator_notices.rss_items(RSS)
        posts = [{'id': 'sz-news:x', 'title': 'Nadomestni prevoz'}, {'id': 'sz-news:y', 'title': 'Spremenjena dostopna pot'}]
        with mock.patch.object(operator_notices.sz_news, '_snap', Snapshot(items, time.time())), \
                mock.patch.object(operator_notices, 'sz_news_alerts', return_value=posts), \
                mock.patch.object(closures, 'notices_source', return_value={'status': 'live'}):
            self.assertEqual(operator_notices.sz_alerts([]), posts)
            known = [{'title': 'NADOMESTNI  prevoz.', 'source': 'sz'}, {'title': 'Spremenjena dostopna pot', 'source': 'otp'}]
            self.assertEqual(operator_notices.sz_alerts(known), posts[1:])

    def test_a_long_running_notice_far_down_the_feed_is_read(self):
        """The Ljubljana - Jesenice notice was posted on 7 September for works until 11 November: on page 2 by November."""
        pages = {'https://sz.example/feed/?category_name=n': Response(200, rss(post('Novo', 'Mon, 26 Oct 2026 10:00:00 +0000'))),
                 'https://sz.example/feed/?category_name=n&paged=2': Response(200, rss(post('Staro', 'Mon, 07 Sep 2026 10:00:00 +0000'))),
                 'https://sz.example/feed/?category_name=n&paged=3': Response(404)}
        asked = []

        def get(url, **kwargs):
            asked.append(url)
            return pages[url]
        with self.settings(PRESTOP_SZ_NEWS_URL=['https://sz.example/feed/?category_name=n']), mock.patch.object(operator_notices.sz_news, '_snap', None), \
                mock.patch.dict(operator_notices._rss, url=None, etag=None, modified=None), \
                mock.patch('prestop_api.operator_notices.session', return_value=mock.Mock(get=get)):
            items = operator_notices._load_sz_news()
        self.assertEqual([i['title'] for i in items], ['Novo', 'Staro'])
        self.assertEqual(len(asked), 3)  # stops at the end of the feed

    def test_a_failed_older_page_is_a_failed_read_and_is_tried_again(self):
        pages = {'https://sz.example/feed/': Response(200, rss(post('Novo', 'Mon, 26 Oct 2026 10:00:00 +0000')), {'ETag': '"1"'}),
                 'https://sz.example/feed/?paged=2': Response(503)}
        with self.settings(PRESTOP_SZ_NEWS_URL=['https://sz.example/feed/']), mock.patch.object(operator_notices.sz_news, '_snap', None), \
                mock.patch.dict(operator_notices._rss, url=None, etag=None, modified=None), \
                mock.patch('prestop_api.operator_notices.session', return_value=mock.Mock(get=lambda url, **kwargs: pages[url])):
            with self.assertRaises(UpstreamError):
                operator_notices._load_sz_news()
            self.assertIsNone(operator_notices._rss['etag'])  # or the next read's 304 would keep the old posts

    def test_a_post_lasts_for_the_days_in_its_title_not_a_date_misread_from_a_list_of_days(self):
        title = 'Nadomestni prevoz na relaciji Ljubljana – Borovnica in obratno (10., 11., 17. 10., 24. in 25. 10. ter 31. 10. in 1. 11.)'
        now = datetime(2026, 11, 2, 12, 0, tzinfo=closures.LOCAL).timestamp()
        item = {'title': title, 'link': 'https://potniski.sz.si/x/', 'date': '2026-09-24T10:00:00', 'categories': [operator_notices.SZ_CATEGORY], 'text': ''}
        self.assertEqual(operator_notices.sz_news_alerts([item], now), [])  # over on 1 Nov, not 10 Nov
        [alert] = operator_notices.sz_news_alerts([item], datetime(2026, 11, 1, 12, 0, tzinfo=closures.LOCAL).timestamp())
        self.assertTrue(alert['validFrom'].startswith('2026-10-09T22'))


def post(title: str, published: str, text: str = '', category: str = 'Obvestila za potnike') -> str:
    return (f'<item><title>{title}</title><link>https://potniski.sz.si/{published[5:7]}/</link><pubDate>{published}</pubDate><category>{category}</category>'
            f'<content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/"><![CDATA[{text}]]></content:encoded></item>')


def rss(*items: str) -> bytes:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'.encode()


JESENICE = 'Nadomestni prevoz na relaciji Ljubljana – Jesenice – Beljak / Villach (A) in obratno (26. 9. – 11. 11. 2026), velja tudi za mednarodne vlake'
PDF = 'https://potniski.sz.si/wp-content/uploads/2026/10/'
JESENICE_TEXT = (f'<p>Povezava: <a href="{PDF}do-11-10.pdf">Vozni red nadomestnega prevoza (do 11. oktobra)</a></p>'
                 f'<p>Povezava: <a href="{PDF}24-10-do-1-11.pdf">Vozni red nadomestnega prevoza (od 24. oktobra do 1. novembra)</a></p>'
                 f'<p>Povezava: <a href="{PDF}2-do-6-11.pdf">Vozni red nadomestnega prevoza (od 2. do 6. novembra)</a></p>'
                 f'<p>Povezava: <a href="{PDF}7-do-11-11.pdf">Vozni red nadomestnega prevoza (od 7. do 11. novembra)</a></p>'
                 f'<p>Povezava: <a href="{PDF}vizmarje.pdf">Vozni red nadomestnega prevoza Ljubljana &#8211; Ljubljana Vižmarje (24. in 25. oktober)</a></p>'
                 '<p><a href="https://potniski.sz.si/dobro-je-vedeti/">Več informacij</a></p>')
NOV_1 = date(2026, 11, 1)


class PostedTimetableTests(SimpleTestCase):
    """SŽ links the timetables of coming days in its post; zamudil.si lists a timetable only on its own day, so on the
    evening of 1 November nothing told the planner about 2 November's buses."""

    def records(self, *items, today=NOV_1):
        return operator_notices.sz_timetable_records(operator_notices.rss_items(rss(*items)), today)

    def jesenice(self):
        return post(JESENICE, 'Mon, 07 Sep 2026 11:59:22 +0000', JESENICE_TEXT)

    def test_each_timetable_still_in_effect_is_a_notice_for_its_own_days(self):
        found = {r['Povezava'][0].rsplit('/', 1)[1]: r for r in self.records(self.jesenice())}
        self.assertEqual(sorted(found), ['2-do-6-11.pdf', '24-10-do-1-11.pdf', '7-do-11-11.pdf'])  # the older ones are over
        record = found['2-do-6-11.pdf']
        self.assertEqual(record['Cas'], ['02.11.2026-06.11.2026'])
        self.assertEqual(record['Relacija'], ['Ljubljana – Jesenice – Beljak / Villach (A)'])
        self.assertEqual(record['Naslov'], ['Vozni red nadomestnega prevoza: Ljubljana – Jesenice – Beljak / Villach (A) (od 2. do 6. novembra)'])
        self.assertEqual(record['CasVir'], ['title'])
        self.assertNotIn('Vlaki', record)  # a post names no trains: the timetable decides
        self.assertEqual(found['24-10-do-1-11.pdf']['Cas'], ['24.10.2026-01.11.2026'])

    def test_a_link_naming_its_own_line_keeps_it(self):
        [record] = [r for r in self.records(self.jesenice(), today=date(2026, 10, 24)) if 'vizmarje' in r['Povezava'][0]]
        self.assertEqual(record['Relacija'], ['Ljubljana – Ljubljana Vižmarje'])
        self.assertEqual(record['Cas'], ['24.10.2026-24.10.2026, 25.10.2026-25.10.2026'])

    def test_a_timetable_link_without_days_takes_the_posts_and_its_pdf_decides(self):
        text = f'<a href="{PDF}a.pdf">Vozni red nadomestnega prevoza</a>'
        [record] = self.records(post('Nadomestni prevoz na relaciji Celje – Velenje in obratno (2. – 8. november)', 'Mon, 26 Oct 2026 10:00:00 +0000', text))
        self.assertEqual((record['Relacija'], record['Cas'], record['CasVir']), (['Celje – Velenje'], ['02.11.2026-08.11.2026'], ['listed']))

    def test_other_posts_and_links_make_no_notice(self):
        link = f'<a href="{PDF}a.pdf">Vozni red nadomestnega prevoza (2. november)</a>'
        self.assertEqual(self.records(post('Manjše spremembe v voznem redu (2. november)', 'Mon, 26 Oct 2026 10:00:00 +0000', link)), [])
        self.assertEqual(self.records(post('Nadomestni prevoz na relaciji A – B in obratno (2. november)', 'Mon, 26 Oct 2026 10:00:00 +0000', f'<a href="{PDF}cenik.pdf">Cenik</a>')), [])
        self.assertEqual(self.records(post('Nadomestni prevoz na relaciji A – B in obratno (2. november)', 'Mon, 26 Oct 2026 10:00:00 +0000', link, 'Novice')), [])

    def test_the_same_timetable_keeps_its_number_so_a_plan_is_not_rebuilt_for_nothing(self):
        self.assertEqual([r['ID_ovire'] for r in self.records(self.jesenice())], [r['ID_ovire'] for r in self.records(self.jesenice())])
        self.assertTrue(all(r['ID_ovire'][0].isdigit() for r in self.records(self.jesenice())))  # szpdf sorts them as numbers

    def with_posts(self, zamudil_records):
        items = operator_notices.rss_items(rss(self.jesenice()))
        with mock.patch.object(operator_notices.sz_news, '_snap', Snapshot(items, time.time())), \
                mock.patch.object(closures, 'datetime', mock.Mock(wraps=datetime, now=lambda tz=None: datetime(2026, 11, 1, 20, 0, tzinfo=closures.LOCAL))), \
                mock.patch.object(closures.zamudil, 'notice_records', return_value=zamudil_records):
            return closures.read_notices()

    def test_tomorrows_timetable_reaches_the_notices_beside_zamudils(self):
        named = {'ID_ovire': ['1'], 'Naslov': ['x'], 'Opis': [f'<p><a href="{PDF}24-10-do-1-11.pdf">Vozni red</a></p>'], 'Vlaki': [[311]]}
        raw, source = self.with_posts([named])
        self.assertEqual(source, 'zamudil')
        # zamudil's record of a PDF names its trains, so the post adds only the two timetables it lacks
        self.assertEqual(raw[0], named)
        self.assertEqual(sorted(r['Povezava'][0].rsplit('/', 1)[1] for r in raw[1:]), ['2-do-6-11.pdf', '7-do-11-11.pdf'])

    def test_the_timetable_is_found_by_the_pdf_sync(self):
        raw, _ = self.with_posts([])
        linked = sync.notice_pdfs(raw)
        self.assertEqual(sorted(u.rsplit('/', 1)[1] for n in linked.values() for u in n['urls']), ['2-do-6-11.pdf', '24-10-do-1-11.pdf', '7-do-11-11.pdf'])

    def test_a_readable_timetable_becomes_the_days_replacement_alert(self):
        raw, _ = self.with_posts([])
        record = next(r for r in raw if '2-do-6' in r['Povezava'][0])
        number = record['ID_ovire'][0]
        tables = sztimetables.Timetables({number: 'sha'}, {'sha': {'status': 'ok', 'notices': [number]}})
        [alert] = closures.sz_notice_alerts([record], [], tables)
        self.assertEqual(alert['id'], closures.notice_alert_id(number))
        self.assertEqual(alert['kind'], 'replacement')
        self.assertEqual(alert['sourceUrl'], record['Povezava'][0])
        self.assertTrue(closures.is_closure(alert))
        self.assertTrue({'20261102', '20261106'} <= closures._days(alert))
        self.assertNotIn('20261101', closures._days(alert))
        self.assertNotIn('20261107', closures._days(alert))
        self.assertIsNone(closures.trains_of(alert, '20261102'))  # no train names: the timetable's buses all run

    def test_sz_shortening_nadomestni_still_replaces_the_trains(self):
        """Its Jesenice - Vintgar / Bohinjska Bistrica notice: the timetable was read, the buses never planned."""
        title = 'Vozni red nadomest. prevoza: Jesenice - Vintgar / Bohinjska Bistrica in obratno (31. 10. - 11. 11.).'
        self.assertTrue(closures.is_closure({'title': title, 'kind': 'replacement'}))
        self.assertFalse(closures.is_closure({'title': 'DODATNO: Avtobusni prevoz za vezo', 'kind': 'replacement'}))

    def test_no_readable_timetable_makes_no_guessed_buses(self):
        raw, _ = self.with_posts([])
        tables = sztimetables.Timetables({}, {})
        self.assertEqual(closures.sz_notice_alerts(raw, [], tables), [])

"""Our own reader of potniski.sz.si (prestop_api/szsite): its parsers on saved pages, the last-good-copy store, the
Cloudflare client with a mocked solver, the schedule and the local server. Offline: nothing here reaches the network."""
import json
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from prestop_api import sz, sz_list, tracks
from prestop_api.szsite import jobs, parse
from prestop_api.szsite.client import AJAX, Backoff, Client, SiteError, clearance_from
from prestop_api.szsite.serve import Server
from prestop_api.szsite.store import Store

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'szsite'
T0 = 1_793_042_000  # 2026-10-26 20:13 local: service hours (+8 h is 04:13, before service)
PAGE = jobs.SOLVE_PAGE


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def trains() -> list:
    return json.loads(text('aktivni_vlaki.json'))


class Resp:
    """A requests.Response stand-in: status, headers, body."""

    def __init__(self, status=200, body='', headers=None):
        self.status_code, self.headers, self.encoding = status, headers or {}, 'utf-8'
        self._body = body.encode('utf-8') if isinstance(body, str) else body

    def iter_content(self, size):
        for i in range(0, len(self._body), size):
            yield self._body[i:i + size]

    def json(self):
        return json.loads(self._body)

    def close(self):
        pass


class Http:
    """A requests.Session stand-in: `answer(method, url, kwargs)` returns a Resp (or raises); every call is recorded."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.answer(method, url, kwargs)

    def site(self):
        return [c for c in self.calls if 'solver' not in c[1]]

    def commands(self):
        return [c[2]['json']['cmd'] for c in self.calls if 'solver' in c[1]]


CHALLENGE = Resp(403, '<title>Just a moment...</title>', {'cf-mitigated': 'challenge'})
SOLVED = {'status': 'ok', 'solution': {'userAgent': 'Edge/157', 'cookies': [{'name': 'cf_clearance', 'value': 'abc'}, {'name': 'wp', 'value': 'sl'}]}}


def client(answer, solver='http://solver:8191', directory=None):
    directory = directory or tempfile.mkdtemp()
    c = Client(solver, directory, http=Http(answer), clock=lambda: 0.0, sleep=lambda s: None)
    return c


class ParserTests(SimpleTestCase):
    def test_active_trains_keep_buses_and_come_back_unchanged(self):
        data = trains()
        self.assertEqual(len(data), 63)
        self.assertIs(parse.active_trains(data), data)
        self.assertTrue(any(t['Rang'] == 'BUS' for t in data))
        self.assertEqual(parse.active_trains([]), [])

    def test_active_trains_layout(self):
        for bad in ({'vlaki': []}, [1, 2], [{'St_vlaka': '1'}], [{'Koordinate': '13,46'}], 'x'):
            with self.assertRaises(SiteError) as caught:
                parse.active_trains(bad)
            self.assertEqual(caught.exception.kind, 'layout')

    def test_served_list_is_what_sz_reads(self):
        """The shape sz.parse_trains already accepts: SŽ's own rows, nothing renamed."""
        found = sz.parse_trains(parse.active_trains(trains()), T0)
        self.assertGreater(len(found), 40)
        self.assertEqual(found['601']['category'], 'RG')
        self.assertEqual(found['601']['next'], 'Grahovo')
        self.assertEqual(found['601']['delay'], 16 * 60)
        self.assertEqual(found['601']['coords'], (46.1707313984, 13.9097141648))

    def test_status_page(self):
        page = text('stanje.html')
        found = parse.status_page(page)
        self.assertGreater(len(found['notices']), 0)
        self.assertEqual(found['notices'], sz_list.parse(page))
        self.assertEqual(len(found['works']), 48)
        work = found['works'][0]
        self.assertEqual((work['from'], work['to']), ('2026-11-16', '2026-11-19'))
        self.assertEqual(work['Lokacija'], '44711')
        self.assertIn('Bohinjska Bistrica', work['Relacija'][0])
        first = found['delays'][0]
        self.assertEqual((first['station'], first['train'], first['minutes'], first['event']), ('Ljutomer', 'RG 1640', 30, 'departure'))
        self.assertTrue(first['over30'])
        self.assertEqual((len(found["delays"]), sum(d["over30"] for d in found["delays"])), (31, 2))  # 2 highlighted (over 30 min) + 29 others
        self.assertEqual(found['delays'][1]['text'], '45 min V ODHODU')

    def test_status_page_layout_changed(self):
        page = text('stanje.html')
        with self.assertRaises(SiteError) as caught:
            parse.status_page(page.replace('nadomestni-prevozi', 'x'))
        self.assertEqual(caught.exception.kind, 'layout')
        with self.assertRaises(SiteError) as caught:
            parse.status_page(page.replace('var roadworks', 'var other'))
        self.assertEqual(caught.exception.kind, 'layout')
        with self.assertRaises(SiteError) as caught:
            parse.status_page(page.replace('var roadworks = [', 'var roadworks = {'))
        self.assertEqual(caught.exception.kind, 'layout')

    def test_ljubljana_board(self):
        board = parse.departures(text('odhodi-ljubljana.html'))
        self.assertEqual((board['code'], board['name']), ('42300', 'Ljubljana'))
        out = [r for r in board['rows'] if r['kind'] == 'departure']
        into = [r for r in board['rows'] if r['kind'] == 'arrival']
        self.assertEqual((len(out), len(into)), (74, 76))
        self.assertEqual(out[0], {'train': '4531', 'track': '14', 'planned': '04:15', 'kind': 'departure', 'relation': 'Ljubljana - Kočevje', 'expected': ''})
        self.assertEqual(out[2]['track'], '10-A')
        self.assertEqual(sum(1 for r in board["rows"] if r["track"]), 139)
        self.assertEqual((into[0]['planned'], into[0]['expected'], into[0]['track']), ('01:04', '01:04', '10-A'))

    def test_board_layout_changed(self):
        page = text('odhodi-ljubljana.html')
        with self.assertRaises(SiteError) as caught:
            parse.departures(re.sub(r'Tir\s*</th>', 'Pot</th>', page))
        self.assertEqual(caught.exception.kind, 'layout')
        with self.assertRaises(SiteError):
            parse.departures('<html></html>')

    def test_train_sets(self):
        sets = parse.train_sets(text('finder-results.html'))
        self.assertEqual(sets['512'], {'set': 'SŽ 312 Siemens Desiro (tročleni)', 'slug': 'sz-312-siemens-desiro-troclenski'})
        self.assertIn('sz-510-stadler-flirt', {s['slug'] for s in sets.values()})
        self.assertEqual(sets['502']['slug'], 'emg-313-stadler-kiss-dvopodni')
        with self.assertRaises(SiteError):
            parse.train_sets('<html></html>')


class StoreTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)

    def test_keeps_and_reports(self):
        self.assertEqual(self.store.keep('works', [1, 2, 3], now=T0), (True, None))
        self.assertEqual(self.store.load('works')['data'], [1, 2, 3])
        self.assertEqual(self.store.status()['works'], {'at': T0, 'ok': True, 'error': None, 'count': 3})

    def test_refuses_a_collapsed_list(self):
        self.store.keep('works', list(range(48)), now=T0)
        for bad in ([], list(range(23))):
            self.assertEqual(self.store.keep('works', bad, now=T0 + 1), (False, 'layout'))
        self.assertEqual(len(self.store.load('works')['data']), 48)
        self.assertEqual(self.store.status()['works'], {'at': T0 + 1, 'ok': False, 'error': 'layout', 'count': 48})
        self.assertEqual(self.store.keep('works', list(range(24)), now=T0 + 2), (True, None))  # half is fine

    def test_small_lists_may_shrink(self):
        self.store.keep('delays', list(range(9)), now=T0)
        self.assertEqual(self.store.keep('delays', [], now=T0 + 1), (True, None))

    def test_live_list_may_be_empty_only_at_night(self):
        service, night = 1_793_042_000, 1_793_042_000 + 8 * 3600  # 20:13 and 04:13 local
        self.store.keep('active_trains', list(range(60)), now=service)
        self.assertEqual(self.store.keep('active_trains', [], now=service + 30), (False, 'layout'))
        self.assertEqual(self.store.keep('active_trains', [], now=night), (True, None))

    def test_layout_changed_keeps_the_last_good_notices(self):
        """A page that lost its notices section: the fetch fails, the loop notes `layout`, the copy and the file stay."""
        page = text('stanje.html')
        answers = [page, page.replace('nadomestni-prevozi', 'x')]
        fake = mock.Mock()
        fake.get.side_effect = lambda path, params=None: answers.pop(0)
        with override_settings(PRESTOP_SZ_LIST_FILE=str(Path(self.dir) / 'sz-list.json')):
            self.assertGreater(jobs.fetch_status(fake, self.store)['count'], 0)
            good = self.store.load('notices')
            with self.assertRaises(SiteError) as caught:
                jobs.fetch_status(fake, self.store)
        self.assertEqual(caught.exception.kind, 'layout')
        self.assertEqual(self.store.load('notices'), good)
        self.assertEqual(len(self.store.load('works')['data']), 48)
        self.assertEqual(len(json.loads((Path(self.dir) / 'sz-list.json').read_text(encoding='utf-8'))['notices']), good['count'])


class BackoffTests(SimpleTestCase):
    def test_ladder_never_faster_than_a_minute(self):
        b = Backoff()
        self.assertTrue(b.due(0))
        waits = [b.failed('down', 100) for _ in range(6)]
        self.assertEqual(waits, [60, 300, 900, 3600, 3600, 3600])
        self.assertFalse(b.due(100 + 3599))
        b.ok()
        self.assertEqual((b.failed('layout', 0), b.due(59), b.due(60)), (60, False, True))

    def test_a_block_waits_an_hour_at_once(self):
        self.assertEqual(Backoff().failed('blocked', 0), 3600)


class ClientTests(SimpleTestCase):
    def test_challenge_is_solved_once_and_retried_with_the_new_cookie(self):
        def answer(method, url, kwargs):
            if 'solver' in url:
                return Resp(200, json.dumps(SOLVED))
            return Resp(200, '[]') if kwargs['cookies'].get('cf_clearance') == 'abc' else CHALLENGE
        c = client(answer)
        self.assertEqual(c.ajax('aktivni_vlaki'), '[]')
        self.assertEqual(c.http.commands(), ['sessions.create', 'request.get', 'sessions.destroy'])
        first, second = c.http.site()
        self.assertEqual(first[2]['cookies'], {})
        self.assertEqual(second[2]['cookies'], {'cf_clearance': 'abc', 'wp': 'sl'})
        self.assertEqual(second[2]['headers']['User-Agent'], 'Edge/157')
        self.assertEqual(second[2]['headers']['Accept-Encoding'], 'gzip')
        self.assertEqual((second[0], second[1], second[2]['data']), ('POST', 'https://potniski.sz.si' + AJAX, {'action': 'aktivni_vlaki'}))
        solve = [x for x in c.http.calls if x[2].get('json', {}).get('cmd') == 'request.get'][0][2]['json']
        self.assertEqual((solve['maxTimeout'], solve['session'], solve['url']), (120000, 'kamgre-sz', 'https://potniski.sz.si' + PAGE))
        # a new client finds the clearance on disk
        again = Client('', str(c.path.parent), http=Http(answer))
        self.assertEqual((again.clearance['cookies']['cf_clearance'], again.clearance['userAgent']), ('abc', 'Edge/157'))

    def test_session_is_destroyed_even_when_solving_fails(self):
        def answer(method, url, kwargs):
            if 'solver' not in url:
                return CHALLENGE
            if kwargs['json']['cmd'] == 'request.get':
                return Resp(500, json.dumps({'status': 'error', 'message': 'Timeout after 120 seconds'}))
            return Resp(200, json.dumps({'status': 'ok'}))
        c = client(answer)
        with self.assertRaises(SiteError) as caught:
            c.get(PAGE)
        self.assertEqual(caught.exception.kind, 'challenge')
        self.assertIn('Timeout', caught.exception.detail)
        self.assertEqual(c.http.commands(), ['sessions.create', 'request.get', 'sessions.destroy'])
        self.assertEqual(len(c.http.site()), 1)  # no retry without a clearance

    def test_solve_without_a_cf_clearance_cookie_fails(self):
        def answer(method, url, kwargs):
            if 'solver' not in url:
                return CHALLENGE
            return Resp(200, json.dumps({'status': 'ok', 'solution': {'cookies': [{'name': 'x', 'value': 'y'}], 'userAgent': 'U'}}))
        c = client(answer)
        with self.assertRaises(SiteError) as caught:
            c.get(PAGE)
        self.assertEqual(caught.exception.kind, 'challenge')
        self.assertFalse(c.cleared)
        self.assertIn('sessions.destroy', c.http.commands())

    def test_no_solver_is_a_challenge_error(self):
        c = client(lambda *a: CHALLENGE, solver='')
        with self.assertRaises(SiteError) as caught:
            c.get(PAGE)
        self.assertEqual(caught.exception.kind, 'challenge')
        self.assertEqual(c.http.commands(), [])
        self.assertEqual(len(c.http.site()), 1)

    def test_a_second_challenge_after_solving_is_not_retried_again(self):
        c = client(lambda method, url, kwargs: Resp(200, json.dumps(SOLVED)) if 'solver' in url else CHALLENGE)
        with self.assertRaises(SiteError) as caught:
            c.get(PAGE)
        self.assertEqual(caught.exception.kind, 'challenge')
        self.assertEqual((len(c.http.site()), c.solves), (2, 1))

    def test_other_failures(self):
        def refused(status, body='', headers=None):
            return client(lambda *a: Resp(status, body, headers), solver='')
        for resp, kind in ((Resp(403, '<h1>Error 1020</h1> Access denied'), 'blocked'), (Resp(403, 'Error 1015 rate limited'), 'blocked'),
                           (Resp(429), 'blocked'), (Resp(502), 'down'), (Resp(500), 'down'), (Resp(404), 'layout')):
            with self.assertRaises(SiteError, msg=resp.status_code) as caught:
                client(lambda *a, r=resp: r, solver='').get(PAGE)
            self.assertEqual(caught.exception.kind, kind)

    def test_timeout_and_connection_errors_are_down(self):
        for error in (requests.Timeout(), requests.ConnectionError()):
            def answer(*a, e=error):
                raise e
            with self.assertRaises(SiteError) as caught:
                client(answer).get(PAGE)
            self.assertEqual(caught.exception.kind, 'down')

    def test_answers_are_size_limited(self):
        with mock.patch('prestop_api.szsite.client.LIMIT', 100):
            with self.assertRaises(SiteError) as caught:
                client(lambda *a: Resp(200, 'x' * 500)).get(PAGE)
        self.assertEqual(caught.exception.kind, 'layout')

    def test_requests_are_a_second_apart(self):
        now, slept = [10.0], []
        c = Client('', tempfile.mkdtemp(), http=Http(lambda *a: Resp(200, 'ok')), clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
        c.get('/a')
        c.get('/b')
        now[0] += 0.25
        c.get('/c')
        self.assertEqual([round(s, 2) for s in slept], [1.0, 0.75])

    def test_seed_takes_a_browser_export(self):
        c = client(lambda *a: Resp(200, 'ok'), solver='')
        c.seed({'cookies': [{'name': 'cf_clearance', 'value': 'z', 'domain': 'x'}], 'userAgent': 'Edge/1'})
        c.get(PAGE)
        sent = c.http.site()[0][2]
        self.assertEqual((sent['cookies'], sent['headers']['User-Agent']), ({'cf_clearance': 'z'}, 'Edge/1'))
        self.assertEqual(clearance_from('{"cookies": {"a": "b"}}')['cookies'], {'a': 'b'})
        with self.assertRaises(ValueError):
            clearance_from({'cookies': {}})


class JobTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = Store(self.dir)
        self.stops = [{'id': 'IJPP:1122804', 'name': 'Ljubljana', 'modes': ['rail']}, {'id': 'IJPP:1122805', 'name': 'LJUBLJANA (peron 2)', 'modes': ['rail']},
                      {'id': 'IJPP:2', 'name': 'Maribor', 'modes': ['rail']}]

    def ids(self):
        return jobs.StationIds(lambda: self.stops)

    def test_station_ids_by_name(self):
        ids = self.ids()
        self.assertEqual(ids.ids('Ljubljana'), ['IJPP:1122804', 'IJPP:1122805'])
        self.assertEqual(ids.ids('Zidani Most'), [])
        broken = jobs.StationIds(mock.Mock(side_effect=OSError('down')))
        self.assertEqual(broken.ids('Ljubljana'), [])

    def test_station_ids_are_read_once(self):
        provider = mock.Mock(return_value=self.stops)
        ids = jobs.StationIds(provider)
        ids.ids('Ljubljana'), ids.ids('Maribor'), ids.ids('Celje')
        self.assertEqual(provider.call_count, 1)

    def test_board_rows_become_tracks_rows(self):
        fake = mock.Mock()
        fake.get.return_value = text('odhodi-ljubljana.html')
        boards = jobs.Boards(self.ids())
        with mock.patch.object(jobs, 'today', return_value=mock.Mock(**{'date.return_value': __import__('datetime').date(2026, 11, 7)})):
            summary = boards(fake, self.store)
        fake.get.assert_called_once()
        self.assertEqual(fake.get.call_args[0][1], {'postaja': '42300', 'datum': '07.11.2026'})
        self.assertEqual((summary['count'], summary['ids']), (150, 2))
        rows = jobs.train_data(self.store, '2026-11-07')
        self.assertEqual(rows[0], {'train_id': '4531', 'ijpp_id': 'IJPP:1122804', 'platform': '14'})
        usable = [r for r in parse.departures(text("odhodi-ljubljana.html"))["rows"] if r["kind"] == "departure" and r["train"] and r["track"]]
        self.assertEqual(len(rows), 2 * len(usable))  # departures only, once per railway stop of the station
        self.assertEqual(jobs.train_data(self.store, '2026-11-08'), [])

    def test_a_board_of_another_station_is_a_layout_error(self):
        fake = mock.Mock()
        fake.get.return_value = text('odhodi-ljubljana.html')
        with self.assertRaises(SiteError):
            jobs.Boards(self.ids())(fake, self.store, code='43400')

    def test_loop_runs_one_task_at_a_time_and_backs_off(self):
        fake = mock.Mock()
        fake.ajax.side_effect = [json.dumps(trains()), SiteError('down', 'HTTP 502')]
        now = [1000.0]
        loop = jobs.Loop(fake, self.store, self.ids(), clock=lambda: now[0], wall=lambda: T0)
        loop.tasks = [t for t in loop.tasks if t.name == 'live']
        self.assertEqual(loop.step(), 'live')
        self.assertEqual(self.store.status()['active_trains']['count'], 63)
        self.assertIsNone(loop.step())  # not due for 30 s
        now[0] += 30
        self.assertEqual(loop.step(), 'live')
        self.assertEqual(self.store.status()['active_trains']['error'], 'down')
        now[0] += 59
        self.assertIsNone(loop.step())
        now[0] += 2
        fake.ajax.side_effect = None
        fake.ajax.return_value = json.dumps(trains())
        self.assertEqual(loop.step(), 'live')
        self.assertTrue(self.store.status()['active_trains']['ok'])

    def test_a_challenge_holds_every_task(self):
        fake = mock.Mock()
        fake.ajax.side_effect = SiteError('challenge', 'no solver configured')
        now = [1000.0]
        loop = jobs.Loop(fake, self.store, self.ids(), clock=lambda: now[0], wall=lambda: T0)
        self.assertEqual(loop.step(), 'live')
        self.assertTrue(all(not t.backoff.due(now[0] + 59) for t in loop.tasks))
        self.assertIsNone(loop.step())

    def test_live_tasks_sleep_at_night(self):
        loop = jobs.Loop(mock.Mock(), self.store, self.ids(), clock=lambda: 1000.0, wall=lambda: T0 + 8 * 3600)
        loop.tasks = [t for t in loop.tasks if t.name != 'status']
        self.assertIsNone(loop.step())


class ServeTests(SimpleTestCase):
    def setUp(self):
        self.store = Store(tempfile.mkdtemp())
        self.clock = [T0]
        self.server = Server(self.store, 0, clock=lambda: self.clock[0])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path, timeout=5) as r:
                return r.status, r.headers['Content-Type'], json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.headers['Content-Type'], json.loads(e.read())

    def test_listens_on_localhost_only(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_active_trains_are_503_when_stale(self):
        self.assertEqual(self.get('/active_trains')[0], 503)
        self.store.keep('active_trains', trains(), now=T0)
        status, kind, body = self.get('/active_trains')
        self.assertEqual((status, kind, len(body)), (200, 'application/json', 63))
        self.clock[0] = T0 + 120
        self.assertEqual(self.get('/active_trains')[0], 200)
        self.clock[0] = T0 + 121
        self.assertEqual(self.get('/active_trains')[0], 503)

    def test_train_data_is_what_tracks_polls(self):
        self.store.keep('board-42300', {'code': '42300', 'name': 'Ljubljana', 'date': '2026-11-07', 'ids': ['IJPP:1122804'],
                                        'rows': [{'train': '2606', 'track': '6-A', 'planned': '05:00', 'kind': 'departure'},
                                                 {'train': '9', 'track': '', 'planned': '05:10', 'kind': 'departure'},
                                                 {'train': '10', 'track': '3', 'planned': '05:20', 'kind': 'arrival'}]}, count=3, now=T0)
        self.assertEqual(self.get('/train_data?date=2026-11-07')[2], {'trains': [{'train_id': '2606', 'ijpp_id': 'IJPP:1122804', 'platform': '6-A'}]})
        self.assertEqual(self.get('/train_data?date=2026-11-08')[0], 503)
        self.assertEqual(self.get('/train_data')[0], 400)
        with override_settings(PRESTOP_SZ_TRACKS_URL=[self.base + '/train_data']):
            found = tracks.Tracks()
            found._poll('2026-11-07')
        self.assertEqual(found._today, {'2606': {'IJPP:1122804': '6-A'}})

    def test_works_and_status(self):
        self.assertEqual(self.get('/works')[0], 503)
        self.store.keep('works', [{'Naslov': ['x']}], now=T0)
        self.assertEqual(self.get('/works')[2], {'at': T0, 'works': [{'Naslov': ['x']}]})
        status = self.get('/status')[2]
        self.assertEqual(status['jobs']['works']['count'], 1)
        self.assertTrue(status['inService'])
        self.assertEqual(self.get('/nothing')[0], 404)

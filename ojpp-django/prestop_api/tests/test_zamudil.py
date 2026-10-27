"""zamudil.si client (spec 2026-10-27 G1): fixtures parse, a failing or changed API keeps the last copy; its notices as
SŽ's old notices feed records (G2)."""
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from prestop_api import upstream, zamudil
from prestop_api.upstream import UpstreamError

FIXTURES = Path(__file__).parent / 'fixtures' / 'sz'
DAY = date(2026, 10, 27)
NOON = datetime(2026, 10, 27, 12, 0, tzinfo=zamudil.LOCAL).timestamp()
NIGHT = datetime(2026, 10, 27, 2, 0, tzinfo=zamudil.LOCAL).timestamp()


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f'zamudil-{name}.json').read_text(encoding='utf-8'))


class ZamudilCase(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.settings_ = override_settings(PRESTOP_ZAMUDIL_URL=['https://zamudil.example/api'], PRESTOP_ZAMUDIL_DIR=self.dir.name)
        self.settings_.enable()
        self.today = mock.patch.object(zamudil, 'today', return_value=DAY)
        self.today.start()
        self.forget()

    def tearDown(self):
        self.today.stop()
        self.settings_.disable()
        self.dir.cleanup()
        self.forget()

    def forget(self):
        zamudil._copies.clear()
        zamudil._looked.clear()
        zamudil._records.update(version=None, value=None)
        zamudil.urls.good = None

    def answer(self, by_path: dict):
        """upstream.get_json answering each endpoint with by_path[path] (an exception is raised)."""
        asked = []

        def get(url, params=None, **kwargs):
            path = url.split('/api', 1)[1]
            asked.append((path, (params or {}).get('date')))
            value = by_path[path]
            if isinstance(value, Exception):
                raise value
            return value
        return mock.patch.object(upstream, 'get_json', side_effect=get), asked


class FixtureTests(ZamudilCase):
    def test_fixtures_parse(self):
        patch, asked = self.answer({'/notices': fixture('notices'), '/rollingstock/assignments': fixture('assignments'),
                                    '/map/maintenance': fixture('maintenance')})
        with patch:
            notices = zamudil.fetch(zamudil.NOTICES, DAY, NOON)
            classes = zamudil.fetch(zamudil.CLASSES, DAY, NOON)
            works = zamudil.fetch(zamudil.WORKS, None, NOON)
        self.assertEqual(len(notices['data']['notices']), 21)
        self.assertEqual(len(classes['data']['rollingStock']), 9)
        self.assertEqual(len(works['data']['works']), 7)
        self.assertEqual(asked, [('/notices', '2026-10-27'), ('/rollingstock/assignments', '2026-10-27'), ('/map/maintenance', None)])
        self.assertIsNone(notices['error'])

    def test_user_agent_names_the_app(self):
        self.assertIn('KamGre', upstream.session().headers['User-Agent'])


class KeepsTheLastCopyTests(ZamudilCase):
    def fetched(self):
        patch, _ = self.answer({'/notices': fixture('notices')})
        with patch:
            zamudil.fetch(zamudil.NOTICES, DAY, NOON)

    def test_failures_keep_the_previous_data_and_mark_it_stale(self):
        for broken in (UpstreamError('HTTP 500'), UpstreamError('returned invalid JSON'), {}, {'notices': 'x'},
                       {'notices': []}, {'notices': [{'summary': ''}]}, {'serviceDate': '2026-10-28', 'notices': []}):
            with self.subTest(broken=broken):
                self.forget()
                self.fetched()
                patch, _ = self.answer({'/notices': broken})
                with patch:
                    kept = zamudil.fetch(zamudil.NOTICES, DAY, NOON + 700)
                self.assertEqual(len(kept['data']['notices']), 21)
                self.assertTrue(kept['error'])
                self.assertEqual(kept['fetchedAt'], NOON)
                [health] = [s for s in zamudil.health(NOON + 700) if s['id'] == 'sz:zamudil-notices']
                self.assertEqual(health['status'], 'stale')
                self.assertEqual(health['since'], '2026-10-27T11:00:00Z')

    def test_a_restart_reads_the_disk_copy(self):
        self.fetched()
        self.forget()  # a new process
        found = zamudil.copy(zamudil.NOTICES, DAY, NOON + 5)
        self.assertEqual(len(found['data']['notices']), 21)
        self.assertEqual([d for d, _ in zamudil.copies(zamudil.NOTICES, NOON + 5)], [DAY])

    def test_another_process_copy_is_not_asked_again(self):
        self.fetched()
        self.forget()
        patch, asked = self.answer({'/notices': UpstreamError('must not be asked')})
        with patch:
            self.assertFalse(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + 300))
        self.assertEqual(asked, [])

    def test_first_failure_without_a_copy(self):
        patch, _ = self.answer({'/notices': UpstreamError('HTTP 500')})
        with patch:
            self.assertIsNone(zamudil.fetch(zamudil.NOTICES, DAY, NOON))
        self.assertEqual(zamudil.copies(zamudil.NOTICES, NOON), [])
        self.assertFalse(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + 60))  # retried after RETRY, not every tick
        self.assertTrue(zamudil._due(zamudil.NOTICES, DAY, 600, NOON + zamudil.RETRY))
        [health] = [s for s in zamudil.health(NOON) if s['id'] == 'sz:zamudil-notices']
        self.assertEqual(health['status'], 'unavailable')

    def test_past_dates_are_pruned(self):
        zamudil._write(Path(self.dir.name) / 'notices-2026-10-26.json', {'data': {'notices': []}, 'fetchedAt': 1, 'checkedAt': 1})
        self.fetched()
        zamudil.prune()
        self.assertEqual(sorted(p.name for p in Path(self.dir.name).glob('*.json')), ['notices-2026-10-27.json'])

    def test_off_without_urls(self):
        with override_settings(PRESTOP_ZAMUDIL_URL=[]):
            self.assertIsNone(zamudil.fetch(zamudil.NOTICES, DAY, NOON))
            self.assertEqual(zamudil.poll(NOON), 0)
            self.assertEqual(zamudil.health(NOON), [])
            self.assertIsNone(zamudil.notice_records())


class ScheduleTests(ZamudilCase):
    def test_a_day_of_polls_stays_light(self):
        """Every copy the schedule keeps, asked for whenever due, over one day: about 200 requests."""
        patch, asked = self.answer({'/notices': fixture('notices') | {'serviceDate': None}, '/rollingstock/assignments': fixture('assignments') | {'serviceDate': None},
                                    '/map/maintenance': fixture('maintenance')})
        start = datetime(2026, 10, 27, 0, 0, tzinfo=zamudil.LOCAL).timestamp()
        with patch:
            for minute in range(0, 24 * 60, 1):
                zamudil.poll(start + minute * 60)
        per = {}
        for path, _ in asked:
            per[path] = per.get(path, 0) + 1
        self.assertLessEqual(len(asked), 230, per)
        self.assertGreaterEqual(per['/notices'], 140)  # today every 10 min by day, tomorrow hourly, the others nightly
        self.assertEqual({d for p, d in asked if p == '/notices'}, {f'2026-{m}' for m in ['10-27', '10-28', '10-29', '10-30', '10-31', '11-01', '11-02',
                                                                                         '11-03', '11-04', '11-05', '11-06', '11-07', '11-08', '11-09']})

    def test_intervals(self):
        self.assertEqual(zamudil.interval(zamudil.NOTICES, DAY, DAY, NOON), 600)
        self.assertEqual(zamudil.interval(zamudil.NOTICES, DAY, DAY, NIGHT), 3600)
        self.assertEqual(zamudil.interval(zamudil.NOTICES, date(2026, 10, 28), DAY, NOON), 3600)
        self.assertIsNone(zamudil.interval(zamudil.NOTICES, date(2026, 10, 30), DAY, NOON))  # on demand by day
        self.assertIsNotNone(zamudil.interval(zamudil.NOTICES, date(2026, 10, 30), DAY, NIGHT))
        self.assertEqual(zamudil.interval(zamudil.CLASSES, DAY, DAY, NOON), 1800)
        self.assertEqual(zamudil.interval(zamudil.WORKS, None, DAY, NOON), 3600)

    def test_on_demand(self):
        later = date(2026, 11, 3)
        patch, asked = self.answer({'/notices': fixture('notices') | {'serviceDate': '2026-11-03'}})
        with patch:
            self.assertTrue(zamudil.ensure(zamudil.NOTICES, later, now=NOON))
            self.assertFalse(zamudil.ensure(zamudil.NOTICES, later, now=NOON + 3600))  # younger than 6 h
            self.assertTrue(zamudil.ensure(zamudil.NOTICES, later, now=NOON + 7 * 3600))
            self.assertFalse(zamudil.ensure(zamudil.NOTICES, date(2026, 11, 20), now=NOON))  # past the 14 days
        self.assertEqual(asked, [('/notices', '2026-11-03')] * 2)


class TitleDateTests(SimpleTestCase):
    """G2: the five ways SŽ writes a notice's days, the year from the service date it was listed on."""

    def spans(self, title, seen=DAY):
        return zamudil.title_spans(title, seen)

    def test_the_five_forms(self):
        d = date
        self.assertEqual(self.spans('Vozni red nadomestnega prevoza: Ljubljana - Jesenice / Beljak in obratno (24. 10. - 1. 11.).'),
                         [(d(2026, 10, 24), d(2026, 11, 1))])
        self.assertEqual(self.spans('Vozni red nadomestnega prevoza: B. Bistrica / Vintgar - Jesenice in obratno (26. - 30. oktober).'),
                         [(d(2026, 10, 26), d(2026, 10, 30))])
        self.assertEqual(self.spans('Vozni red nadomestnega prevoza: Grosuplje - Kočevje in obratno (26. in 27. oktober).'),
                         [(d(2026, 10, 26), d(2026, 10, 26)), (d(2026, 10, 27), d(2026, 10, 27))])
        self.assertEqual(self.spans('Vozni red nadomestnega prevoza: Ptuj / Moškanjci - Ormož in obratno (26. - 30. 10. in 3. - 6. 11.).'),
                         [(d(2026, 10, 26), d(2026, 10, 30)), (d(2026, 11, 3), d(2026, 11, 6))])
        self.assertEqual(self.spans('Avtobusni IC prevoz na relaciji Ljubljana - Celje in obratno (do 12. decembra).'),
                         [(DAY, d(2026, 12, 12))])

    def test_the_year_rolls_over(self):
        seen = date(2026, 12, 28)
        self.assertEqual(self.spans('Vozni red nadomestnega prevoza: Divača - Koper in obratno (28. 12. - 5. 1.).', seen),
                         [(seen, date(2027, 1, 5))])
        self.assertEqual(self.spans('… in obratno (do 15. januarja).', seen), [(seen, date(2027, 1, 15))])
        self.assertEqual(self.spans('… in obratno (3. - 6. 1.).', seen), [(date(2027, 1, 3), date(2027, 1, 6))])
        self.assertEqual(self.spans('… in obratno (20. 12. 2026 - 5. 1. 2027).', seen), [(date(2026, 12, 20), date(2027, 1, 5))])

    def test_unreadable(self):
        for title in ('Vozni red nadomestnega prevoza: Ljubljana - Kranj in obratno.', '… (do nadaljnjega)', '… (27. oktober, 7.00 - 15.00)',
                      '… (31. 2.)', '… (30. - 26. 10.)', 'Beljak (A) in obratno'):
            with self.subTest(title=title):
                self.assertIsNone(self.spans(title))

    def test_relation(self):
        self.assertEqual(zamudil.relation('Vozni red nadomestnega prevoza: Lesce Bled - Jesenice / Beljak (A) in obratno (24. 10. - 1. 11.).'),
                         'Lesce Bled - Jesenice / Beljak (A)')
        self.assertEqual(zamudil.relation('Avtobusni IC prevoz na relaciji Ljubljana - Celje in obratno (do 12. decembra).'), 'Ljubljana - Celje')


class RecordTests(SimpleTestCase):
    """G2: zamudil's notices as SŽ's old notices feed records (closures.py and szpdf_sync read them unchanged)."""

    def records(self, *lists):
        return zamudil.records(list(lists) or [(DAY, fixture('notices'))])

    def test_the_fixture_gives_one_record_per_replacement_notice(self):
        recs = self.records()
        lines = sorted(r['Relacija'][0] for r in recs)
        self.assertEqual(lines, ['B. Bistrica / Vintgar - Jesenice', 'Grosuplje - Kočevje', 'Lesce Bled - Jesenice / Beljak (A)', 'Ljubljana - Celje',
                                 'Ljubljana - Jesenice / Beljak', 'Ptuj / Moškanjci - Ormož'])
        pdfs = {r['ID_ovire'][0]: re.findall(r'href="([^"]+\.pdf)"', r['Opis'][0]) for r in recs}
        self.assertTrue(all(len(v) == 1 for v in pdfs.values()), pdfs)
        self.assertEqual(len({v[0] for v in pdfs.values()}), 5)  # Ljubljana - Jesenice and Lesce Bled - Jesenice share one PDF
        self.assertEqual(len({r['ID_ovire'][0] for r in recs}), 6)
        self.assertTrue(all(r['ID_ovire'][0].isdigit() for r in recs))
        by_line = {r['Relacija'][0]: r for r in recs}
        ormoz = by_line['Ptuj / Moškanjci - Ormož']
        self.assertEqual(ormoz['Cas'], ['26.10.2026-30.10.2026, 03.11.2026-06.11.2026'])
        self.assertEqual(ormoz['Vlaki'], [[640, 2501, 2503, 2519]])
        self.assertEqual(ormoz['VlakiPoDnevih'], [{'2026-10-27': [640, 2501, 2503, 2519]}])
        self.assertEqual(by_line['Ljubljana - Celje']['Vlaki'], [[36]])
        self.assertEqual(by_line['Ljubljana - Celje']['Cas'], ['27.10.2026-12.12.2026'])
        self.assertIn('Zaradi del na progi Ptuj', ormoz['Opis'][0])
        self.assertEqual(ormoz['Naslov'], ['Vozni red nadomestnega prevoza: Ptuj / Moškanjci - Ormož in obratno (26. - 30. 10. in 3. - 6. 11.).'])

    def test_the_numbers_stay_from_date_to_date(self):
        one = {r['Relacija'][0]: r['ID_ovire'][0] for r in self.records()}
        later = fixture('notices') | {'serviceDate': '2026-10-28'}
        both = self.records((DAY, fixture('notices')), (date(2026, 10, 28), later))
        self.assertEqual({r['Relacija'][0]: r['ID_ovire'][0] for r in both}, one)  # one record per notice
        ormoz = next(r for r in both if r['Relacija'][0].startswith('Ptuj'))
        self.assertEqual(sorted(ormoz['VlakiPoDnevih'][0]), ['2026-10-27', '2026-10-28'])

    def test_unreadable_dates_take_the_listed_dates(self):
        data = {'notices': [{'summary': 'Vozni red nadomestnega prevoza: Ljubljana - Kamnik in obratno.', 'trainNumbers': [1, 2]},
                            {'summary': 'Povezava: [Vozni red](https://example.si/a.pdf)', 'body': 'x', 'trainNumbers': [2, 1]}]}
        with self.assertLogs('prestop_api.zamudil', 'WARNING'):
            [rec] = zamudil.records([(DAY, data), (date(2026, 10, 28), data), (date(2026, 10, 30), data)])
        self.assertEqual((rec['Cas'], rec['CasVir']), (['27.10.2026-28.10.2026, 30.10.2026-30.10.2026'], ['listed']))

    def test_the_old_feeds_readers(self):
        from prestop_api import closures
        from prestop_api.szpdf import sync
        recs = self.records()
        self.assertEqual(len(sync.notice_pdfs(recs)), 6)
        self.assertEqual(len(closures.current_notices(recs, date(2026, 11, 2))), 2)  # Moškanjci (to 6 Nov) and IC (to 12 Dec)
        alerts = closures.sz_notice_alerts(recs, [], None)
        self.assertEqual(len(alerts), 6)
        self.assertTrue(all(closures.is_closure(a) for a in alerts), [a['title'] for a in alerts if not closures.is_closure(a)])
        ormoz = next(a for a in alerts if 'Ormož' in a['title'])
        self.assertEqual((ormoz['_trains'], ormoz['_trains_on']['20261027']), (frozenset({'640', '2501', '2503', '2519'}),) * 2)
        self.assertIn('20261103', ormoz['_dates'])
        self.assertNotIn('20261101', ormoz['_dates'])
        self.assertEqual(closures.sides(next(a for a in alerts if 'Celje' in a['title'])), [['ljubljana'], ['celje']])
        # the same notice from OTP (SŽ's own number) is one alert
        otp = [{'id': 'alert:x', 'title': ormoz['title'], 'source': 'sz', 'routeIds': []}]
        self.assertEqual(len(closures.sz_notice_alerts(recs, otp, None)), 5)


def routes(*names: str) -> dict:
    return {f'IJPP:r{n.split()[-1]}': {'gtfsId': f'IJPP:r{n.split()[-1]}', 'shortName': n, 'agencyId': 'IJPP:1161', 'mode': 'RAIL'} for n in names}


class TrainNoticeTests(ZamudilCase):
    """G4: the other notices as alerts on the trains they name, that date."""

    def setUp(self):
        super().setUp()
        from prestop_api import closures, sources
        from prestop_api.upstream import Snapshot
        zamudil._copies[(zamudil.NOTICES, DAY.isoformat())] = {'data': fixture('notices'), 'fetchedAt': NOON, 'checkedAt': NOON, 'error': None}
        zamudil._looked[(zamudil.NOTICES, DAY.isoformat())] = (1e12, None)  # no disk look
        closures._train_alerts.update(stamp=None, value=[])
        self.routes = mock.patch.object(sources.routes, 'peek', return_value=Snapshot(routes('RG 619', 'RG 631', 'RG 632', 'EC 573', 'AVT 850', 'LPV 2424'), NOON))
        self.routes.start()

    def tearDown(self):
        self.routes.stop()
        super().tearDown()

    def test_the_notices(self):
        notices = zamudil.train_notices([(DAY, fixture('notices'))])
        self.assertEqual(len(notices), 8)  # 21 items: 6 replacement pairs, the joined-trains notice and its details as one
        joined = next(n for n in notices if n['title'].startswith('OBVESTILO: Združeni'))
        self.assertEqual(joined['trains'], ['619', '631', '632'])
        self.assertIn('Garnitura vlaka RG 619 iz Maribora', joined['text'])
        siska = next(n for n in notices if n['title'].startswith('Zaradi obsežnih'))
        self.assertNotIn('](', siska['title'])  # Markdown links as their words
        self.assertIn('iskalniku voznega reda', siska['title'])
        self.assertEqual(siska['url'], 'https://potniski.sz.si/')

    def test_alerts_on_their_trains(self):
        from prestop_api import closures
        alerts = closures.train_alerts()
        oebb = next(a for a in alerts if 'tujini' in a['title'])
        self.assertTrue(oebb['title'].startswith('ÖBB: '))
        self.assertEqual((oebb['routeIds'], oebb['source']), (['IJPP:r573'], 'sz'))
        joined = next(a for a in alerts if 'Združeni' in a['title'])
        self.assertEqual(joined['routeIds'], ['IJPP:r619', 'IJPP:r631', 'IJPP:r632'])
        self.assertTrue(joined['id'].startswith('sz-zamudil:') and joined['_leg_notice'])
        self.assertEqual((joined['validFrom'], joined['validTo']), ('2026-10-26T23:00:00Z', '2026-10-28T03:00:00Z'))
        self.assertEqual(closures.train_alert_ids('IJPP:r850', NOON), [a['id'] for a in alerts if 'IJPP:r850' in a['routeIds']])
        self.assertEqual(len(closures.train_alert_ids('IJPP:r850', NOON)), 2)  # two car-train notices
        self.assertEqual(closures.train_alert_ids('IJPP:r850', NOON + 2 * 86400), [])
        self.assertIs(closures.train_alerts(), alerts)  # worked out once per copy

    def test_one_alert_when_otp_has_it_too(self):
        from prestop_api import closures
        joined = next(a for a in closures.train_alerts() if 'Združeni' in a['title'])
        otp = {'id': 'alert:otp', 'title': joined['title'], 'message': '', 'source': 'sz', 'routeIds': ['IJPP:r619'], 'stopIds': [], 'kind': 'info'}
        with mock.patch.object(closures, 'sz_notice_alerts', return_value=[]):
            out = closures.notice_alerts([otp])
        self.assertEqual([a['id'] for a in out if 'Združeni' in a['title']], ['alert:otp'])

    def test_a_leg_tells_its_trains_notice(self):
        from prestop_api import closures, leg_alerts
        joined = next(a for a in closures.train_alerts() if 'Združeni' in a['title'])
        journey = {'legs': [{'mode': 'rail', 'routeName': 'RG 619', 'alertIds': [joined['id']], 'origin': {'name': 'Celje'}, 'destination': {'name': 'Ljubljana'}}]}
        [leg] = leg_alerts.add_notices([journey], [joined], 'sl')[0]['legs']
        self.assertEqual(leg['notices'], [{'kind': joined['kind'], 'text': 'OBVESTILO: Združeni vlaki iz/do Zidanega Mosta (do nadaljnjega).'}])

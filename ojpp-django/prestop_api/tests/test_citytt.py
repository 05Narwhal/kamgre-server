"""City bus timetables from the operators' pages (prestop_api/citytt): Jesenice's Arriva PDFs into a hand-kept feed.

The fixtures are Arriva's four line PDFs as arriva.si served them on 2026-10-23 (tests/fixtures/citytt). Each golden
<name>.expected.json was checked row by row against the PDF's text layer. Regenerate a golden only after checking the
changed runs against the PDF again:

    ojpp.sh manage city_timetables --fixtures prestop_api/tests/fixtures/citytt --write-goldens
"""
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import citytt, scheduled, supplement
from prestop_api.citytt import arriva, build, poles

FIXTURES = Path(__file__).parent / 'fixtures' / 'citytt'
JESENICE = citytt.CITIES['Jesenice']
PAGE = f'<p>Vozni redi.</p><p>{JESENICE.days} (takrat se bodo prevozi izvajali).</p>'


def word(text, x0, top, width=None):
    return {'text': text, 'x0': x0, 'x1': x0 + (width or 6 * len(text)), 'top': top, 'bottom': top + 10}


class ReaderTests(SimpleTestCase):
    def test_every_fixture_matches_its_golden(self):
        pdfs = sorted(FIXTURES.glob('*.pdf'))
        self.assertEqual(len(pdfs), 4)
        for pdf in pdfs:
            with self.subTest(pdf.name):
                golden = json.loads(pdf.with_name(f'{pdf.stem}.expected.json').read_text(encoding='utf-8'))
                self.assertEqual(arriva.parse(pdf), golden)

    def test_names_wrap_and_lose_the_terminus_note(self):
        doc = json.loads((FIXTURES / 'jesenice-1a.expected.json').read_text(encoding='utf-8'))
        self.assertEqual(doc['stops'][0], 'Koroška Bela trgovina')           # "… / Začetna postaja" on the next line
        self.assertEqual(doc['stops'][7], 'Blejska Dobrava pokopališče')     # "pokopališče" wrapped
        self.assertEqual(doc['stops'][-1], 'Hrušica Belo Polje')             # page 2, no header there
        self.assertEqual([r[0] for r in doc['runs']], ['07:00', '09:15', '12:00', '14:00', '16:15'])

    def test_a_run_skipping_a_stop_leaves_its_cell_empty(self):
        header = [word('LINIJA', 50, 10), word('9:', 100, 10), word('A', 120, 10), word('–', 130, 10), word('B', 140, 10)]
        page = [header, [word('Št.', 50, 30), word('Postaja', 80, 30), word('Čas', 200, 30, 18), word('odhoda', 220, 30, 36),
                         word('Čas', 280, 30, 18), word('odhoda', 300, 30, 36)],
                [word('1', 50, 50), word('A', 80, 50), word('07:00', 215, 50, 30), word('08:00', 295, 50, 30)],
                [word('2', 50, 70), word('Mid', 80, 70), word('07:05', 215, 70, 30)],
                [word('3', 50, 90), word('B', 80, 90), word('07:10', 215, 90, 30), word('08:10', 295, 90, 30)]]
        doc = arriva.read([[sorted(line, key=lambda w: w['x0']) for line in page]])
        self.assertEqual(doc['line'], '9')
        self.assertEqual(doc['runs'], [['07:00', '07:05', '07:10'], ['08:00', None, '08:10']])

    def test_stop_numbers_out_of_order_fail(self):
        page = [[word('LINIJA', 50, 10), word('1:', 100, 10), word('X', 120, 10)],
                [word('Postaja', 80, 30), word('Čas', 200, 30)],
                [word('1', 50, 50), word('A', 80, 50), word('07:00', 195, 50, 30)],
                [word('3', 50, 70), word('B', 80, 70), word('07:05', 195, 70, 30)]]
        with self.assertRaises(arriva.ReadError):
            arriva.read([page])


def stop(sid, name, lat, lon):
    return {'id': sid, 'name': name, 'lat': lat, 'lon': lon}


class PoleTests(SimpleTestCase):
    def test_osm_poles_join_the_feed_stop_they_are(self):
        feed = [stop('IJPP:1', 'Jesenice ZD', 46.4397, 14.0444)]
        osm = [{'id': 'osm:7', 'name': 'Jesenice Zdravstveni dom', 'lat': 46.4398, 'lon': 14.0444, 'refs': {'IJPP': '1'}},
               {'id': 'osm:8', 'name': 'Jesenice ZD', 'lat': 46.43975, 'lon': 14.04441, 'refs': {}},        # 5 m, alike name
               {'id': 'osm:9', 'name': 'Straža', 'lat': 46.429, 'lon': 14.0823, 'refs': {}}]
        found, alias = poles.unify(feed, osm)
        self.assertEqual(alias, {'osm:7': 'IJPP:1', 'osm:8': 'IJPP:1', 'osm:9': 'osm:9'})
        self.assertEqual(sorted(found), ['IJPP:1', 'osm:9'])
        self.assertEqual(found['IJPP:1']['names'], ['Jesenice ZD', 'Jesenice Zdravstveni dom'])

    def test_each_direction_takes_the_pole_known_runs_use(self):
        found, _ = poles.unify([stop('IJPP:a', 'Integral', 46.437, 14.049), stop('IJPP:w', 'ZD', 46.4399, 14.0443),
                                stop('IJPP:e', 'ZD', 46.4397, 14.0444), stop('IJPP:b', 'Bolnica', 46.443, 14.035)], [])
        pairs = poles.merged(poles.adjacent([['IJPP:a', 'IJPP:w', 'IJPP:b']] * 3), poles.adjacent([['IJPP:b', 'IJPP:e', 'IJPP:a']]))
        self.assertEqual(poles.choose(['Integral', 'ZD', 'Bolnica'], found, pairs), (['IJPP:a', 'IJPP:w', 'IJPP:b'], []))
        self.assertEqual(poles.choose(['Bolnica', 'ZD', 'Integral'], found, pairs), (['IJPP:b', 'IJPP:e', 'IJPP:a'], []))
        # One OSM relation listing the other side's pole is outweighed by the runs that agree.
        noisy = poles.merged(pairs, poles.adjacent([['IJPP:a', 'IJPP:e', 'IJPP:b']]))
        self.assertEqual(poles.choose(['Integral', 'ZD', 'Bolnica'], found, noisy)[0][1], 'IJPP:w')

    def test_a_tie_or_a_missing_pole_fails_instead_of_guessing(self):
        found, _ = poles.unify([stop('IJPP:w', 'ZD', 46.4399, 14.0443), stop('IJPP:e', 'ZD', 46.4397, 14.0444)], [])
        chosen, problems = poles.choose(['ZD', 'Nowhere'], found, {})
        self.assertEqual(chosen, [None, None])
        self.assertIn('no pole named like "Nowhere"', problems[0])
        chosen, problems = poles.choose(['ZD'], found, {})
        self.assertEqual(chosen, [None])
        self.assertIn('IJPP:e, IJPP:w', problems[0])


class CalendarTests(SimpleTestCase):
    def test_monday_to_saturday_without_holidays_but_31_october_and_1_november(self):
        rows, dates = build.calendar(JESENICE)
        self.assertEqual(rows[0]['saturday'], '1')
        self.assertEqual(rows[0]['sunday'], '0')
        exceptions = {d['date']: d['exception_type'] for d in dates}
        self.assertEqual(exceptions['20261225'], '2')   # Christmas, a Friday
        self.assertEqual(exceptions['20270329'], '2')   # Easter Monday
        self.assertEqual(exceptions['20261101'], '1')   # All Saints', a Sunday: it runs
        self.assertNotIn('20261031', exceptions)        # Reformation Day, a Saturday: it runs as usual
        self.assertNotIn('20270502', exceptions)        # a Sunday holiday: no run anyway

    def test_titles(self):
        self.assertEqual(build.title_case('JESENICE BOLNICA –TOMŠIČEVA –KOROŠKA BELA (trgovina)'),
                         'Jesenice Bolnica – Tomšičeva – Koroška Bela (trgovina)')


# Line 2's stops along a street (west is lower longitude); ZD has a pole per direction, Straža is OSM's only.
LINE2 = [('Koroška Bela trgovina', 14.0988), ('Straža', 14.0823), ('Tomšičeva trgovina', 14.0772), ('Tomšičeva II', 14.0716),
         ('Tomšičeva I', 14.0660), ('OŠ Prežihov Voranc', 14.0610), ('Jesenice Gimnazija', 14.0596), ('Jesenice ŽP', 14.0549),
         ('Jesenice Integral', 14.0490), ('Jesenice ZD', 14.0443), ('Jesenice bolnica', 14.0356)]


def sources(page=PAGE):
    feed = [stop(f'IJPP:{i + 1}', name, 46.432, lon) for i, (name, lon) in enumerate(LINE2) if name != 'Straža']
    feed.append(stop('IJPP:99', 'Jesenice ZD', 46.4321, 14.0444))  # the other side
    files = [{'url': f'https://arriva.si/{n}.pdf', 'name': f'{n}.pdf', 'data': (FIXTURES / f'{n}.pdf').read_bytes()}
             for n in ('jesenice-2a', 'jesenice-2b')]
    osm = [{'id': 'osm:5', 'name': 'Straža', 'lat': 46.432, 'lon': 14.0823, 'refs': {}}]
    runs = [['IJPP:9', 'IJPP:10', 'IJPP:11'], ['IJPP:11', 'IJPP:99', 'IJPP:9']]
    return build.Sources(page, files, feed, runs, osm, [])


def straight(window):
    return [[[a['lon'], a['lat']], [b['lon'], b['lat']]] for a, b in zip(window, window[1:])]


class BuildTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        patcher = mock.patch.object(supplement, 'LOCAL_GTFS', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.today = date(2026, 10, 23)

    def test_the_timetables_become_a_feed_supplement_reads(self):
        files, status = build.build(JESENICE, sources(), self.today, route=straight)
        self.assertEqual(status['lines'], {'2A': 5, '2B': 5})
        self.assertEqual(build.write(JESENICE, files, status, self.today)[:2], ['agency.txt', 'calendar.txt'])
        feed = supplement.parse('Jesenice', supplement._local_zip(str(self.root / 'Jesenice')))
        trip = feed['trips']['Jesenice:2A-0810']
        self.assertEqual(trip['headsign'], 'Jesenice bolnica')
        self.assertEqual([s['stopId'] for s in trip['stops']][:2], ['Jesenice:1', 'Jesenice:osm5'])
        self.assertEqual(trip['stops'][9]['stopId'], 'Jesenice:10')                       # westbound ZD
        self.assertEqual(feed['trips']['Jesenice:2B-0830']['stops'][1]['stopId'], 'Jesenice:99')  # eastbound ZD
        self.assertEqual(trip['stops'][-1]['departure'], 8 * 3600 + 24 * 60)
        self.assertEqual(feed['stops']['Jesenice:3']['name'], 'Tomšičeva trgovina')       # "Tomšičeva trg." in the PDF
        self.assertEqual(feed['routes']['Jesenice:2A']['agency']['name'], 'Arriva d.o.o.')
        self.assertTrue(supplement.runs(feed, trip['serviceId'], date(2026, 10, 31)))
        self.assertFalse(supplement.runs(feed, trip['serviceId'], date(2026, 12, 25)))
        self.assertEqual(json.loads((self.root / 'Jesenice' / 'status.json').read_text(encoding='utf-8'))['built'], '2026-10-23')
        # The same build again changes nothing.
        self.assertEqual(build.write(JESENICE, files, status, date(2026, 10, 30)), [])

    def test_a_changed_days_sentence_or_an_unplaceable_stop_fails(self):
        with self.assertRaisesRegex(build.BuildError, 'running days may have changed'):
            build.build(JESENICE, sources(page='<p>Krožni liniji obratujeta vse dni.</p>'), self.today, route=straight)
        src = sources()
        src.osm_stops = []
        with self.assertRaisesRegex(build.BuildError, 'no pole named like "Straža"'):
            build.build(JESENICE, src, self.today, route=straight)

    def test_a_failed_build_keeps_the_folder_and_shows_in_health(self):
        files, status = build.build(JESENICE, sources(), self.today, route=straight)
        build.write(JESENICE, files, status, self.today)
        self.assertEqual(citytt.health(self.today)[0]['status'], 'live')
        self.assertEqual(citytt.health(date(2027, 6, 15))[0]['status'], 'stale')  # near its end
        build.fail(JESENICE, 'no Overpass server answered', date(2026, 11, 2))
        self.assertTrue((self.root / 'Jesenice' / 'trips.txt').is_file())
        row = citytt.health(date(2026, 11, 2))[0]
        self.assertEqual((row['id'], row['status'], row['updatedAt']), ('city-timetables:Jesenice', 'stale', '2026-10-23T00:00:00Z'))
        build.write(JESENICE, files, status, date(2026, 11, 3))
        self.assertEqual(citytt.health(date(2026, 11, 3))[0]['status'], 'live')

    def test_no_folder_is_unavailable(self):
        self.assertEqual(citytt.health(self.today)[0]['status'], 'unavailable')

    def test_a_stop_far_from_its_routed_shape_fails(self):
        def snapped_away(window):  # the router put Tomšičeva trgovina on a street 110 m north
            pts = [[s['lon'], s['lat'] + (0.001 if s['name'].startswith('Tomšičeva trg') else 0)] for s in window]
            return [[a, b] for a, b in zip(pts, pts[1:])]
        with mock.patch.object(build.roads, 'plausible', return_value=True):
            with self.assertRaisesRegex(build.BuildError, 'shape passes more than 50 m from Tomšičeva trgovina'):
                build.build(JESENICE, sources(), self.today, route=snapped_away)


class CityBusTests(SimpleTestCase):
    """Hand-kept city buses publish no positions: the map draws them where their timetable puts them."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        with mock.patch.object(supplement, 'LOCAL_GTFS', root):
            files, status = build.build(JESENICE, sources(), date(2026, 10, 23), route=straight)
            build.write(JESENICE, files, status, date(2026, 10, 23))
            feed = supplement.parse('Jesenice', supplement._local_zip(str(root / 'Jesenice')))
        for target, value in ((supplement, '_feeds'), (supplement, '_hand_kept')):
            patcher = mock.patch.object(target, value, return_value={'Jesenice': feed} if value == '_feeds' else {'Jesenice': str(root)})
            patcher.start()
            self.addCleanup(patcher.stop)
        self.monday = supplement.day_start(date(2026, 10, 26))

    def test_a_running_bus_is_on_its_way_by_its_times(self):
        buses = scheduled.city_buses(self.monday + 8 * 3600 + 16 * 60 + 30)  # 2A left Tomšičeva trgovina at 08:16
        self.assertEqual([b['tripId'] for b in buses], ['Jesenice:2A-0810'])
        bus = buses[0]
        self.assertEqual((bus['mode'], bus['quality'], bus['routeName'], bus['nextStop']), ('bus', 'scheduled', '2A', 'Tomšičeva II'))
        self.assertTrue(14.0716 < bus['longitude'] < 14.0772)
        self.assertEqual(bus['id'], 'Jesenice:scheduled-2A-0810')

    def test_a_bus_with_a_live_vehicle_or_on_a_sunday_is_not_drawn(self):
        at = self.monday + 8 * 3600 + 16 * 60 + 30
        self.assertEqual(scheduled.city_buses(at, skip_trips=frozenset({'Jesenice:2A-0810'})), [])
        self.assertEqual(scheduled.city_buses(at - 86400), [])  # Sunday 25 October

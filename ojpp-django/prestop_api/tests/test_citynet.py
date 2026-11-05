from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from prestop_api import citynet


class CityNetworksTests(SimpleTestCase):
    def test_table_names_every_city_feed_once(self):
        feeds, routes = citynet.read()
        for feed in ('LPP', 'MARPROM', 'CELEBUS', 'MONM', 'MONG', 'MOKoper', 'MOKranj', 'MOKrsko', 'MOMS',
                     'MOVelenje', 'Postojna', 'Ptuj', 'Brezice', 'Sevnica', 'Jesenice', 'Piran'):
            self.assertIn(feed, feeds)
        self.assertNotIn('IJPP', feeds)  # the national feed is never a city feed as a whole
        self.assertEqual(routes['IJPP:65376']['number'], '1')
        self.assertEqual({routes['IJPP:58976']['number'], routes['IJPP:55131']['number']}, {'L1', 'L2'})

    def test_national_line_gets_its_number_and_network(self):
        self.assertEqual(citynet.city('IJPP:65376', 'A6206'), {
            'town': 'Škofja Loka', 'company': 'Arriva', 'number': '1', 'label': 'Mestni promet Škofja Loka · Arriva'})

    def test_city_feed_line_keeps_its_number(self):
        self.assertEqual(citynet.city('MOKoper:9', '9')['label'], 'Mestni promet Koper · Arriva')
        self.assertEqual(citynet.city('MOKoper:9', '9')['number'], '9')

    def test_other_lines_are_not_city_lines(self):
        self.assertIsNone(citynet.city('IJPP:63286', 'N0245'))  # Celje – Štore, suburban
        self.assertIsNone(citynet.city(None, '1'))
        self.assertIsNone(citynet.city('MOKoper:9', None))

    def test_operator_names_read_in_one_style(self):
        self.assertEqual(citynet.operator_name('MOKranj:MP_Kranj'), 'Mestni promet Kranj · Arriva')
        self.assertEqual(citynet.operator_name('Brezice:0'), 'Mestni promet Brežice · Nomago')
        self.assertEqual(citynet.operator_name('Sevnica:2'), 'Mestni promet Sevnica')
        self.assertIsNone(citynet.operator_name('IJPP:1119'))

    def test_bad_rows_are_skipped(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'c.csv'
            path.write_text('# note\ntown,company,feed,route_id,number\nA,B,F,,\n,B,G,,\nC,D,IJPP,IJPP:1,\n',
                            encoding='utf-8')
            feeds, routes = citynet.read(path)
        self.assertEqual(list(feeds), ['F'])
        self.assertEqual(routes, {})


class CityFieldTests(SimpleTestCase):
    def test_payloads_spread_city_only_for_city_lines(self):
        from prestop_api import mapping
        self.assertEqual(mapping.city_of({'gtfsId': 'IJPP:58976', 'shortName': 'N6217'})['city']['number'], 'L1')
        self.assertEqual(mapping.city_of({'gtfsId': 'MOKranj:3', 'shortName': '3'})['city']['label'],
                         'Mestni promet Kranj · Arriva')
        self.assertEqual(mapping.city_of({'shortName': '1'}, 'Jesenice:1')['city']['town'], 'Jesenice')
        self.assertEqual(mapping.city_of({'gtfsId': 'IJPP:63286', 'shortName': 'N0245'}), {})

    def test_a_cross_feed_copy_of_a_city_run_is_one_bus_same_feed_twins_stay(self):
        from prestop_api import mapping
        city = {'town': 'Kranj', 'number': '1', 'company': 'Arriva', 'label': 'Mestni promet Kranj · Arriva'}
        row = lambda trip, name: {'tripId': trip, 'routeName': name, 'scheduledAt': '2026-11-05T08:00:00+01:00',
                                  'destination': 'Planina', 'mode': 'bus', 'city': city}
        runs: dict = {}
        self.assertIsNone(mapping.copy_of(row('MOKranj:a', '1'), runs))
        self.assertIsNotNone(mapping.copy_of(row('IJPP:b', 'A6999'), runs))  # the national feed's copy, named otherwise
        self.assertIsNone(mapping.copy_of(row('MOKranj:c', '1'), runs))  # its own second bus (twin-buses-are-real)

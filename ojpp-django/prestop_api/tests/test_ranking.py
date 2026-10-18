from datetime import datetime, timezone

from django.test import SimpleTestCase

from prestop_api import journeys, mapping, pricing
from prestop_api.tests.test_mapping import PLACE

ASKED = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def journey(name, arrive_min, cents, depart_min=0):
    at = lambda m: mapping.iso(ASKED.timestamp() + m * 60)
    return {'id': name, 'legs': [{'mode': 'bus'}], 'effectiveDeparture': at(depart_min), 'effectiveArrival': at(arrive_min), 'price': {'totalCents': cents}}


def req(preset, mode='departAt'):
    return {'costPreset': preset, 'dateTime': ASKED, 'timeMode': mode}


class RankTests(SimpleTestCase):
    def test_fastest_keeps_the_planners_order_exactly(self):
        js = [journey('b', 40, 150), journey('a', 30, 450), journey('c', 50, 100)]
        self.assertEqual([j['id'] for j in pricing.rank(js, req('fastest'))], ['b', 'a', 'c'])
        self.assertTrue(all('savedCents' not in j['price'] for j in js))

    def test_balanced_takes_ten_minutes_later_for_each_1_50_saved(self):
        a, b, c = journey('a', 30, 450), journey('b', 38, 150), journey('c', 50, 150)
        ranked = pricing.rank([a, b, c], req('balanced'))
        self.assertEqual([j['id'] for j in ranked], ['b', 'a', 'c'])  # b: 3 € cheaper for 8 min; c: 20 min for 3 € is not worth it
        self.assertEqual((b['price']['savedCents'], b['price']['comparedTo']), (300, 'fastest'))
        self.assertNotIn('savedCents', a['price'])

    def test_cheapest_within_45_minutes_of_the_fastest(self):
        js = [journey('fast', 30, 900), journey('cheap', 70, 300), journey('cheaper-but-late', 80, 100)]
        self.assertEqual([j['id'] for j in pricing.rank(js, req('cheapest'))], ['cheap', 'fast', 'cheaper-but-late'])

    def test_an_unknown_price_never_wins_on_price(self):
        js = [journey('known', 40, 300), journey('unknown', 30, None)]
        self.assertEqual([j['id'] for j in pricing.rank(js, req('cheapest'))], ['unknown', 'known'])  # same cost: faster first
        js = [journey('known', 40, 300), journey('dear', 35, 900), journey('unknown', 30, None)]
        self.assertEqual(pricing.rank(js, req('cheapest'))[0]['id'], 'known')

    def test_arrive_by_counts_how_early_it_leaves(self):
        js = [journey('late-start', 0, 600, depart_min=-30), journey('early-start', 0, 150, depart_min=-60)]
        self.assertEqual([j['id'] for j in pricing.rank(js, req('balanced', 'arriveBy'))], ['late-start', 'early-start'])


class ExtraSearchTests(SimpleTestCase):
    def request(self, **overrides):
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-19T08:00:00Z', 'timeMode': 'departAt',
                'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'bike', 'scooter'], 'searchScope': 'all', 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    def test_bikes_and_scooters_are_two_searches(self):
        req = self.request()
        self.assertEqual(journeys.otp_variables(req)['modes']['direct'], ['WALK', 'BICYCLE_RENTAL'])
        [(kind, variables)] = journeys.extra_searches(req)
        self.assertEqual((kind, variables['modes']['direct'], variables['modes']['transit']['access']), ('scooter', ['WALK', 'SCOOTER_RENTAL'], ['WALK', 'SCOOTER_RENTAL']))
        self.assertEqual(journeys.extra_searches(self.request(pageCursor='next')), [])

    def test_member_networks_are_searched_only_when_cheaper_rides_are_wanted(self):
        profile = {'cards': [], 'bikeMemberships': ['jcdecaux_ljubljana'], 'scooterPasses': []}
        self.assertEqual(journeys.extra_searches(self.request(modes=['walk', 'bus', 'bike'], showPrices=True, priceProfile=profile)), [])
        [(kind, variables)] = journeys.extra_searches(self.request(modes=['walk', 'bus', 'bike'], showPrices=True, costPreset='cheapest', priceProfile=profile))
        self.assertEqual((kind, variables['preferences']['street']['bicycle']['rental']), ('memberBikes', {'allowedNetworks': ['jcdecaux_ljubljana']}))
        self.assertEqual(len(journeys.extra_searches(self.request(showPrices=True, costPreset='cheapest', priceProfile=profile))), journeys.MAX_EXTRA_SEARCHES)

    def test_extra_connections_follow_otps_own_without_repeats_and_are_reused(self):
        def edge(trip):
            return {'node': {'legs': [{'mode': 'BUS', 'trip': {'gtfsId': trip}, 'start': {'scheduledTime': '08:00'}}]}}
        asked = []

        def query(q, v):
            asked.append(v)
            return {'planConnection': {'edges': [edge('a'), edge('s')]}}
        main = {'planConnection': {'edges': [edge('a')], 'pageInfo': {}}}
        journeys._extra_cache.clear()
        out = journeys.with_extras(main, self.request(dateTime='2026-10-19T09:13:00Z'), query)
        self.assertEqual([e['node']['legs'][0]['trip']['gtfsId'] for e in out['planConnection']['edges']], ['a', 's'])
        journeys.with_extras(main, self.request(dateTime='2026-10-19T09:13:00Z'), query)
        self.assertEqual(len(asked), 1)

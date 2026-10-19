from datetime import datetime, timezone
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import journeys, mapping, pricing, sources
from prestop_api.tests.test_mapping import PLACE, leg
from prestop_api.upstream import Snapshot

ASKED = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def journey(name, arrive_min, cents, depart_min=0):
    at = lambda m: mapping.iso(ASKED.timestamp() + m * 60)
    return {'id': name, 'legs': [{'mode': 'bus'}], 'effectiveDeparture': at(depart_min), 'effectiveArrival': at(arrive_min), 'price': {'totalCents': cents}}


def req(preset, mode='departAt', modes=('walk', 'bus')):
    return {'costPreset': preset, 'dateTime': ASKED, 'timeMode': mode, 'modes': set(modes)}


MEMBER = {'cards': [], 'bikeMemberships': ['jcdecaux_ljubljana'], 'scooterPasses': []}


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

    def test_member_networks_are_searched_with_bike_off_and_on_any_preset(self):
        with mock.patch.object(sources.rentals, 'peek', return_value=None):  # no station list yet: every membership counts
            [(kind, variables)] = journeys.extra_searches(self.request(modes=['walk', 'bus'], priceProfile=MEMBER))
            self.assertEqual((kind, variables['preferences']['street']['bicycle']['rental'], variables['modes']['direct']),
                             ('memberBikes', {'allowedNetworks': ['jcdecaux_ljubljana']}, ['WALK', 'BICYCLE_RENTAL']))
            self.assertEqual(variables['modes']['transit']['access'], ['WALK', 'BICYCLE_RENTAL'])
            self.assertEqual(journeys.extra_searches(self.request(modes=['walk', 'bus'])), [])  # no membership, no search
            [(kind, _)] = journeys.extra_searches(self.request(modes=['walk', 'bus', 'bike'], priceProfile=MEMBER))  # Fastest too
            self.assertEqual(kind, 'memberBikes')
            # Car on (train, bus and bike set aside): driving, no bike.
            self.assertEqual([k for k, _ in journeys.extra_searches(self.request(modes=['walk', 'car'], priceProfile=MEMBER))], ['car'])
            self.assertEqual(len(journeys.extra_searches(self.request(costPreset='cheapest', priceProfile=MEMBER))), journeys.MAX_EXTRA_SEARCHES)

    def test_a_member_network_without_a_station_near_either_end_is_not_searched(self):
        near = Snapshot([{'id': 'jcdecaux_ljubljana:19', 'providerId': 'jcdecaux_ljubljana:bike', 'latitude': 46.005, 'longitude': 14.5}], 0)  # 560 m from the start
        far = Snapshot([{'id': 'jcdecaux_ljubljana:19', 'providerId': 'jcdecaux_ljubljana:bike', 'latitude': 46.05, 'longitude': 14.5}], 0)    # 5.6 km
        with mock.patch.object(sources.rentals, 'peek', return_value=near):
            self.assertEqual([k for k, _ in journeys.extra_searches(self.request(modes=['walk', 'bus'], priceProfile=MEMBER))], ['memberBikes'])
        with mock.patch.object(sources.rentals, 'peek', return_value=far):
            self.assertEqual(journeys.extra_searches(self.request(modes=['walk', 'bus'], priceProfile=MEMBER)), [])

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


def ride(name, arrive_min, cents=0):
    j = journey(name, arrive_min, cents)
    j['legs'] = [{'mode': 'walk'}, {'mode': 'bike', 'rental': {'network': 'jcdecaux_ljubljana'}}, {'mode': 'walk'}]
    return j


class MemberRideTests(SimpleTestCase):
    """Bike off, a BicikeLJ membership: the member's rides are offered when they compete with the quickest other way."""

    def test_a_ride_stays_when_it_is_about_as_quick_or_cheaper_and_not_much_slower(self):
        bus = journey('bus', 35, 150)
        js = [bus, ride('quick', 31), ride('close', 39, cents=150), ride('free', 43), ride('slow-paid', 43, cents=150), ride('far', 50)]
        self.assertEqual([j['id'] for j in pricing.member_rides(js, req('fastest'))], ['bus', 'quick', 'close', 'free'])

    def test_with_bike_on_or_nothing_else_every_ride_stays(self):
        js = [journey('bus', 35, 150), ride('far', 50)]
        self.assertEqual(len(pricing.member_rides(js, req('fastest', modes=('walk', 'bus', 'bike')))), 2)
        self.assertEqual(len(pricing.member_rides([ride('only', 50)], req('fastest'))), 1)

    def test_arriving_by_a_time_counts_how_early_it_leaves(self):
        bus = journey('bus', 0, 150, depart_min=-35)
        early = {**ride('early', 0), 'effectiveDeparture': mapping.iso(ASKED.timestamp() - 50 * 60)}
        late = {**ride('late', 0), 'effectiveDeparture': mapping.iso(ASKED.timestamp() - 30 * 60)}
        self.assertEqual([j['id'] for j in pricing.member_rides([bus, early, late], req('fastest', 'arriveBy'))], ['bus', 'late'])


class LjubljanaMemberTests(SimpleTestCase):
    """Kongresni trg → BTC City at 08:00 with Bike off (the default): a non-member gets bus 27; a BicikeLJ member also
    gets the free ride, which arrives first."""

    def otp(self, asked):
        def walk(start, end):
            return leg('WALK', start, end, transit=False, duration=300)

        def query(_q, variables):
            asked.append(variables)
            if 'BICYCLE_RENTAL' in variables['modes']['direct']:
                bike = leg('BICYCLE', '08:05:00', '08:27:00', transit=False, duration=1320)
                bike['rentedBike'] = True
                bike['from']['vehicleRentalStation'] = {'stationId': 'jcdecaux_ljubljana:3', 'rentalNetwork': {'networkId': 'jcdecaux_ljubljana'}}
                bike['to']['vehicleRentalStation'] = {'stationId': 'jcdecaux_ljubljana:61', 'rentalNetwork': {'networkId': 'jcdecaux_ljubljana'}}
                legs = [walk('08:00:00', '08:05:00'), bike, walk('08:27:00', '08:31:00')]
            else:
                legs = [walk('08:00:00', '08:09:00'), leg('BUS', '08:09:00', '08:30:00', trip='LPP:27'), walk('08:30:00', '08:35:00')]
            return {'planConnection': {'routingErrors': [], 'pageInfo': {'searchWindowUsed': 'PT24H'}, 'edges': [{'node': {'walkTime': 600, 'legs': legs}}]}}
        return query

    def plan(self, profile):
        body = {'origin': {'name': 'Kongresni trg', 'latitude': 46.0502, 'longitude': 14.5040}, 'destination': {'name': 'BTC City', 'latitude': 46.0661, 'longitude': 14.5450},
                'via': [], 'dateTime': '2026-10-09T08:00:00+02:00', 'timeMode': 'departAt', 'minTransferSeconds': 180,
                'modes': ['walk', 'bus', 'rail'], 'riskMode': 'normal', 'priceProfile': profile}
        req = journeys.parse_request(body, insane_enabled=False)
        asked = []
        journeys._extra_cache.clear()
        with mock.patch.object(sources.rentals, 'peek', return_value=Snapshot([{'id': 'jcdecaux_ljubljana:3', 'providerId': 'jcdecaux_ljubljana:bike', 'latitude': 46.0505, 'longitude': 14.5035}], 0)):
            data = journeys.with_extras(journeys.plan(req, self.otp(asked)), req, self.otp(asked), budget=3)
        out = [pricing.price_journey(j, req['priceProfile'], 'en') for j in journeys.build_journeys(data, req, [])]
        return pricing.rank(pricing.member_rides(out, req), req), asked

    def test_a_non_member_gets_the_bus_in_one_query(self):
        out, asked = self.plan(None)
        self.assertEqual([[l['mode'] for l in j['legs']] for j in out], [['walk', 'bus', 'walk']])
        self.assertEqual(len(asked), 1)

    def test_a_member_also_gets_the_free_ride_that_arrives_first(self):
        out, asked = self.plan(MEMBER)
        self.assertEqual(len(asked), 2)
        self.assertEqual(asked[1]['preferences']['street']['bicycle']['rental'], {'allowedNetworks': ['jcdecaux_ljubljana']})
        rides = [j for j in out if any(l.get('rental') for l in j['legs'])]
        self.assertEqual(len(out), 2)
        [bike] = rides
        self.assertEqual((bike['effectiveArrival'][11:16], bike['price']['totalCents']), ('08:31', 0))
        self.assertEqual(next(l for l in bike['legs'] if l.get('rental'))['rental']['operator'], 'BicikeLJ')
